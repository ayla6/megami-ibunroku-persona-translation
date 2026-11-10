"""Verify an armips write log before its outputs are trusted.

armips' `-temp LISTING` records every emitted line as
``ADDRESS STATEMENT ; /source/file line N`` inside the surrounding
``.open``/``.create`` section.  That log is a complete account of what the
assembler wrote and where, so it can prove the properties no ad-hoc
``.error`` guard can prove for every output at once:

  * every output lives in ``build/`` (never in the retail dump or dist/);
  * no output is opened twice, and no non-zero write is silently covered by
    a later write (padding from ``.fill 0``/``.area``/``.align`` may be
    covered by the data placed inside it);
  * every write stays inside the output image's declared memory limit, and
    every byte of the built file that differs from its input is a byte the
    listing says was written;
  * a retail block that the patch moves to a new address has every retail
    reader retargeted too.  Moving data but leaving some readers on the old
    home is how a patch clobbers data that is not its own: the old home now
    holds whatever was placed there, while the leftover readers still use it.

Limits come from ``addresses.inc``: an ``X_OUTPUT`` equ pairs with
``X_IMAGE_LIMIT``.  An output without a limit may not grow past its retail
input; declaring the limit is how growth is allowed.

Usage:
    python src/injection_tools/write_guard.py check --listing build/armips-main.lst
"""
from __future__ import annotations

import argparse
import csv
import heapq
import os
import re
import struct
import sys

TOOL = 'write_guard.py'
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASM_ROOT = os.path.join(ROOT, 'src', 'asm')
ADDRESSES_INC = os.path.join(ASM_ROOT, 'common', 'addresses.inc')

_LINE = re.compile(r'^([0-9A-Fa-f]{8})\s+(.*?)\s*;\s*(.+?)\s+line\s+(\d+)\s*$')
_OPEN = re.compile(r'^\.open\s+"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*(\S+)')
_CREATE = re.compile(r'^\.create\s+"([^"]*)"\s*,\s*(\S+)')
_INCBIN = re.compile(r'^"([^"]*)"(.*)$')
_STRING = re.compile(r'^"(.*)"$')
# Compare an output with its input in chunks of this size before examining
# individual bytes. Only the chunks the builder wrote can differ, so this
# skips most of a multi-megabyte output in one C-level comparison.
_DIFF_CHUNK = 1 << 16

# Directives that move the cursor without writing bytes.
_SILENT = {
    '.org', '.area', '.endarea', '.open', '.close', '.create', '.include',
    '.psx', '.if', '.ifdef', '.ifndef', '.else', '.elseif', '.endif',
    '.endmacro', '.macro', '.loadtable', '.error', '.warning', '.global',
    '.weak', '.func', '.endfunc', '.definelabel', '.equ', '.set', '.import',
    '.export', '.extern', '.forward', '.nolist', '.list', '.sym', '.align',
}
# Byte widths for data directives that take a comma-separated value list.
_WIDTH = {'.byte': 1, '.db': 1, '.halfword': 2, '.half': 2, '.dh': 2,
          '.word': 4, '.dw': 4, '.dword': 8, '.dd': 8}


class Write:
    __slots__ = ('out', 'addr', 'size', 'zero', 'path', 'line', 'text', 'order')

    def __init__(self, out, addr, size, zero, path, line, text, order):
        self.out, self.addr, self.size = out, addr, size
        self.zero, self.path, self.line = zero, path, line
        self.text, self.order = text, order

    @property
    def end(self):
        return self.addr + self.size


class Section:
    __slots__ = ('out', 'input', 'base', 'path', 'line', 'create', 'writes')

    def __init__(self, out, input, base, path, line, create):
        self.out, self.input, self.base = out, input, base
        self.path, self.line, self.create = path, line, create
        self.writes = []


def _split_values(text):
    """Split a directive's comma list, keeping quoted commas intact."""
    values, start, quoted = [], 0, False
    for i, char in enumerate(text):
        if char == '"':
            quoted = not quoted
        elif char == ',' and not quoted:
            values.append(text[start:i].strip())
            start = i + 1
    tail = text[start:].strip()
    if tail:
        values.append(tail)
    return values


def _int(value):
    return int(value.strip(), 0)


def _element_size(value, width):
    """Bytes for one comma item of a data directive."""
    value = value.strip()
    if value.startswith('"'):
        match = _STRING.match(value)
        if not match:
            raise ValueError(f'unterminated string {value!r}')
        return len(match.group(1)) * width if width > 1 else len(match.group(1))
    return width


def _directive_size(token, rest, path, root=None):
    """(bytes written, all-zero?) for a directive, or None when silent."""
    if token in _SILENT:
        if token == '.align':
            return None                      # handled with the current address
        return 0, True
    if token in _WIDTH:
        values = [v for v in _split_values(rest) if v]
        if not values:
            raise ValueError(f'{token} without values')
        try:
            return sum(_element_size(v, _WIDTH[token]) for v in values), False
        except ValueError as error:
            raise ValueError(f'{token}: {error}') from None
    if token == '.fill':
        args = [v for v in _split_values(rest) if v]
        if not args:
            raise ValueError('.fill without a size')
        size = _int(args[0])
        zero = len(args) < 2 or _int(args[1]) == 0
        return size, zero
    if token == '.ascii':
        match = _STRING.match(rest.strip())
        if not match:
            raise ValueError(f'.ascii with no string: {rest!r}')
        return len(match.group(1)), False
    if token in ('.asciz', '.string'):
        match = _STRING.match(rest.strip())
        if not match:
            raise ValueError(f'{token} with no string: {rest!r}')
        return len(match.group(1)) + 1, False
    if token == '.incbin':
        match = _INCBIN.match(rest.strip())
        if not match:
            raise ValueError(f'.incbin with no filename: {rest!r}')
        name = resolve(match.group(1), root)
        if not os.path.isfile(name):
            raise ValueError(f'.incbin file not found: {match.group(1)}')
        size = os.path.getsize(name)
        args = [v for v in _split_values(match.group(2)) if v]
        offset = _int(args[0]) if len(args) > 0 else 0
        if len(args) > 1:
            size = _int(args[1])
        end = offset + size
        if end > os.path.getsize(name):
            raise ValueError(f'.incbin {match.group(1)}: range {offset:#x}+{size:#x} '
                             f'past {os.path.getsize(name):#x}')
        return size, False
    return None                              # unknown: caller reports it


def resolve(path, root=None):
    if os.path.isabs(path):
        return os.path.normpath(path)
    root = root or ROOT
    candidates = (os.path.join(root, 'src', 'asm'), root)
    for base in candidates:
        candidate = os.path.normpath(os.path.join(base, path))
        if os.path.exists(candidate):
            return candidate
    return os.path.normpath(os.path.join(candidates[0], path))


def _equ_map(path):
    """Every NAME equ EXPR in addresses.inc, evaluated to int or str.

    Expressions are the assembler's (constants, + - * / and parentheses);
    nothing here evaluates source text from outside that file."""
    try:
        with open(path, encoding='utf-8') as source:
            text = source.read()
    except OSError as error:
        raise SystemExit(f'{TOOL}: cannot read {path}: {error}')
    raw = {}
    for match in re.finditer(r'^\s*([A-Za-z_]\w*)\s+equ\s+([^;]+?)\s*(?:;.*)?$',
                             text, re.M):
        raw[match.group(1)] = match.group(2).strip()
    resolved, active = {}, set()

    def value(name):
        if name in resolved:
            return resolved[name]
        if name not in raw:
            raise KeyError(name)
        if name in active:
            raise ValueError(f'circular equ {name}')
        active.add(name)
        expr = raw[name]
        if _STRING.match(expr):
            result = _STRING.match(expr).group(1)
        else:
            def replace(match):
                token = match.group(0)
                if token in raw:
                    return str(value(token))
                raise KeyError(token)
            substituted = re.sub(r'(?<![0-9A-Za-z_])[A-Za-z_]\w*', replace, expr)
            if not re.fullmatch(r'[0-9A-Fa-fxX()+\-*/\s]+', substituted):
                raise ValueError(f'{name} = {expr!r} is not a constant expression')
            result = int(eval(substituted, {'__builtins__': {}}, {}))  # noqa: S307
        active.discard(name)
        resolved[name] = result
        return result

    for name in raw:
        try:
            value(name)
        except (KeyError, ValueError, SyntaxError):
            pass
    return resolved


def output_limits(equ, root=None):
    """Map resolved output path -> (limit, equ name), from X_OUTPUT/X_IMAGE_LIMIT."""
    limits = {}
    for name, value in equ.items():
        if not name.endswith('_OUTPUT') or not isinstance(value, str):
            continue
        limit_name = name[:-len('_OUTPUT')] + '_IMAGE_LIMIT'
        if limit_name not in equ or not isinstance(equ[limit_name], int):
            continue
        limits[resolve(value, root)] = (equ[limit_name], limit_name)
    return limits


def _size(token, rest, addr, path, root=None):
    if not token:
        return 0, True
    if not token.startswith('.'):
        # A label (zero bytes) or one MIPS instruction (four bytes).
        return (0, True) if token.endswith(':') else (4, False)
    if token == '.align':
        args = [v for v in _split_values(rest) if v]
        if not args:
            raise ValueError('.align without an alignment')
        align = _int(args[0])
        if align <= 0:
            raise ValueError(f'.align {align} is not positive')
        pad = (-addr) % align
        zero = len(args) < 2 or _int(args[1]) == 0
        return pad, zero
    return _directive_size(token, rest, path, root)


def parse_listing(path, root=None):
    """Parse an armips -temp listing into its sections and write intervals.

    Relative input/output paths in the listing are resolved against `root`,
    the same tree the caller checks the outputs in (default: this repo)."""
    root = root or ROOT
    sections, current, problems = [], None, []
    order = 0
    with open(path, encoding='utf-8-sig', errors='replace') as source:
        for raw in source:
            match = _LINE.match(raw.rstrip('\r\n'))
            if not match:
                continue
            address = int(match.group(1), 16)
            text = match.group(2).strip()
            origin, line = match.group(3), int(match.group(4))
            opened = _OPEN.match(text)
            if opened:
                current = Section(resolve(opened.group(2), root),
                                  resolve(opened.group(1), root),
                                  int(opened.group(3), 0), origin, line, False)
                sections.append(current)
                continue
            created = _CREATE.match(text)
            if created:
                current = Section(resolve(created.group(1), root), None,
                                  int(created.group(2), 0), origin, line, True)
                sections.append(current)
                continue
            if text.startswith('.close'):
                current = None
                continue
            if current is None:
                continue
            token = text.split()[0] if text else ''
            rest = text[len(token):].strip()
            try:
                sized = _size(token, rest, address, origin, root)
            except ValueError as error:
                problems.append(f'{origin}:{line}: {error}')
                continue
            if sized is None:
                if token.startswith('.') and token not in _SILENT:
                    problems.append(f'{origin}:{line}: unknown directive {token}')
                elif not token.endswith(':'):
                    problems.append(f'{origin}:{line}: cannot size statement {text[:60]!r}')
                continue
            size, zero = sized
            if size < 0:
                problems.append(f'{origin}:{line}: negative write size {size}')
                continue
            if size:
                current.writes.append(Write(current.out, address, size, zero,
                                            origin, line, text, order))
                order += 1
    if not sections:
        problems.append(f'{path}: no .open/.create section found')
    return sections, problems


def _decode_data(text, root=None):
    """The bytes a data directive emits, or None when they are not literal.

    Used only to tell an intentional shared-suffix glyph (the next writer
    repeats the bytes it covers) from a real overwrite."""
    text = text.strip()
    token = text.split()[0] if text else ''
    rest = text[len(token):].strip()
    if token in ('.align',):
        return b''                              # size comes from the address
    if not token.startswith('.') or token.endswith(':'):
        return None                             # instruction: encoding unknown
    if token in ('.byte', '.db', '.halfword', '.half', '.dh',
                 '.word', '.dw', '.dword', '.dd'):
        width = _WIDTH[token]
        values = [v for v in _split_values(rest) if v]
        out = bytearray()
        try:
            for value in values:
                value = value.strip()
                if value.startswith('"'):
                    match = _STRING.match(value)
                    if not match:
                        return None
                    out += match.group(1).encode('latin-1') * width
                else:
                    number = _int(value)
                    out += (number & ((1 << (8 * width)) - 1)).to_bytes(width, 'little')
        except (ValueError, UnicodeEncodeError):
            return None
        return bytes(out)
    if token == '.fill':
        args = [v for v in _split_values(rest) if v]
        if not args:
            return None
        try:
            size = _int(args[0])
            value = _int(args[1]) if len(args) > 1 else 0
        except ValueError:
            return None
        return bytes([value & 0xFF]) * max(size, 0)
    if token in ('.ascii', '.asciz', '.string'):
        match = _STRING.match(rest)
        if not match:
            return None
        return match.group(1).encode('latin-1') + (b'\0' if token != '.ascii' else b'')
    if token == '.incbin':
        match = _INCBIN.match(rest)
        if not match:
            return None
        try:
            name = resolve(match.group(1), root)
            args = [v for v in _split_values(match.group(2)) if v]
            offset = _int(args[0]) if len(args) > 0 else 0
            size = _int(args[1]) if len(args) > 1 else os.path.getsize(name) - offset
            with open(name, 'rb') as source:
                source.seek(offset)
                return source.read(size)
        except (OSError, ValueError):
            return None
    return None


def _psx_exe(path):
    try:
        with open(path, 'rb') as source:
            return source.read(8) == b'PS-X EXE'
    except OSError:
        return False


# --- retail-move audit -----------------------------------------------------
# A patch may replace a retail block in place: translations do that all the
# time, and every reader keeps reading the same address. What it must not do
# is copy a retail block to a new address and retarget only some of its
# readers: the readers left behind then see whatever the patch put in the old
# home. That is the class behind the status screen's misplaced member markers:
# adv/bar.asm copied g_fm_mark_pos (0x800B209C) to a "hint" block, rebased two
# readers and left the rest on the original address while the new bar data
# overwrote its tail.
#
# The audit only judges moves. It walks each retail image's absolute-address
# readers (lui/addiu|ori pairs followed by a load, and aligned pointer words).
# When a reader's built form computes a different address, the old bytes must
# have been copied there verbatim; if they were, the old block is a moved
# block and every other reader of it must have been retargeted. A block
# rewritten in place has no retargeted reader, so it is never reported.
_RETAIL_LOADS = {0x20: 4, 0x21: 2, 0x24: 1, 0x25: 2, 0x23: 4,
                 0x28: 1, 0x29: 2, 0x31: 4, 0x39: 4}
_RETAIL_INDEX_WINDOW = 0x20      # bytes a scaled base access may reach
_RETAIL_COPY_MIN = 0x10          # a moved block copies at least this much ...
_RETAIL_COPY_CAP = 0x1000        # ... and is compared no further


def _word_table(data):
    return struct.unpack_from(f'<{len(data) // 4}I', data, 0)


def _pair_at(words, i):
    """If words[i] starts a lui/addiu|ori pair, return (addiu_index, address)."""
    if i >= len(words) or words[i] >> 26 != 0x0F:
        return None
    rt = (words[i] >> 16) & 31
    high = (words[i] & 0xFFFF) << 16
    for j in range(i + 1, min(i + 9, len(words))):
        word = words[j]
        op = word >> 26
        if op not in (0x09, 0x0D) or ((word >> 21) & 31) != rt:
            continue
        low = word & 0xFFFF
        if op == 0x09:
            address = (high + (low - 0x10000 if low & 0x8000 else low)) & 0xFFFFFFFF
        else:
            address = (high | low) & 0xFFFFFFFF
        return j, address
    return None


def _retail_readers(original, base, start=0):
    """(read_lo, read_hi, pair_index, addiu_index, kind) for retail reads."""
    words = _word_table(original)
    readers = []
    for i in range(start, len(words)):
        pair = _pair_at(words, i)
        if pair is None:
            continue
        j, address = pair
        if not base <= address < base + len(original):
            continue
        rt = (words[i] >> 16) & 31
        uses = []
        for k in range(j + 1, min(j + 9, len(words))):
            word = words[k]
            op = word >> 26
            rs = (word >> 21) & 31
            rt2 = (word >> 16) & 31
            imm = word & 0xFFFF
            offset = imm - 0x10000 if imm & 0x8000 else imm
            width = _RETAIL_LOADS.get(op)
            if width is not None and rs == rt:
                low = (address + offset) & 0xFFFFFFFF
                uses.append((low, (low + width) & 0xFFFFFFFF, 'load'))
                continue
            if op == 0x09 and rs == rt:
                for m in range(k + 1, min(k + 5, len(words))):
                    load = words[m]
                    qop = load >> 26
                    if _RETAIL_LOADS.get(qop) and ((load >> 21) & 31) == rt2:
                        qimm = load & 0xFFFF
                        qoff = qimm - 0x10000 if qimm & 0x8000 else qimm
                        low = (address + offset + qoff) & 0xFFFFFFFF
                        uses.append((low, (low + _RETAIL_LOADS[qop]) & 0xFFFFFFFF,
                                     'load'))
                        break
            elif op == 0 and (word & 63) == 0x21 and (rs == rt or rt2 == rt):
                # scaled base: the final address depends on a runtime index
                uses.append((address, (address + _RETAIL_INDEX_WINDOW) & 0xFFFFFFFF,
                             'index'))
        for low, high, kind in uses:
            readers.append((low, high, i, j, kind))
    return readers


def _retail_pointers(original, base, start=0):
    """(value, word_index) for aligned retail words that hold image addresses."""
    words = _word_table(original)
    return [(value, i) for i, value in enumerate(words)
            if i >= start and base <= value < base + len(original)]


def _copied_prefix(original, data, old, new, base):
    old_off, new_off = old - base, new - base
    if not (0 <= old_off < len(original) and 0 <= new_off < len(data)):
        return 0
    limit = min(_RETAIL_COPY_CAP, len(original) - old_off, len(data) - new_off)
    length = 0
    while length < limit and original[old_off + length] == data[new_off + length]:
        length += 1
    return length


def _remember_move(moves, original, data, old, new, base):
    if not (base <= old < base + len(original) and
            base <= new < base + len(data)):
        return
    length = _copied_prefix(original, data, old, new, base)
    if length < _RETAIL_COPY_MIN:
        return
    old_off = old - base
    source = original[old_off:old_off + length]
    if len(set(source)) < 2:                 # padding is not a moved block
        return
    if all(source[k] == data[old_off + k] for k in range(length)):
        return                               # the old home still holds it
    if length > moves.get((old, new), 0):
        moves[(old, new)] = length


def retail_move_failures(section, data, original, exe=False, limit=6):
    """Fail a half-done move: copied retail block, readers left behind."""
    if not original or not data or section.base == 0:
        return [], 0
    start = 0x200 if exe else 0
    words = _word_table(original)
    built_words = _word_table(data)
    readers = _retail_readers(original, section.base, start)
    pointers = _retail_pointers(original, section.base, start)

    moves = {}
    for _, _, i, _, _ in readers:
        pair = _pair_at(words, i)
        built = _pair_at(built_words, i) if i < len(built_words) else None
        if pair is None or built is None or pair[1] == built[1]:
            continue
        _remember_move(moves, original, data, pair[1], built[1], section.base)
    for value, i in pointers:
        if (i + 1) * 4 > len(data):
            continue
        new = built_words[i]
        if new != value:
            _remember_move(moves, original, data, value, new, section.base)

    name = os.path.basename(section.out)
    failures = []
    for (old, new), length in sorted(moves.items()):
        low, high = old, old + length
        still, moved = set(), set()
        for low_read, high_read, i, _, _ in readers:
            if high_read <= low or low_read >= high:
                continue
            built = _pair_at(built_words, i) if i < len(built_words) else None
            site = section.base + i * 4
            if built is not None and (built[1] == old or low <= built[1] < high):
                still.add(site)
            else:
                moved.add(site)
        for value, i in pointers:
            if not low <= value < high:
                continue
            site = section.base + i * 4
            if (i + 1) * 4 <= len(data) and built_words[i] == value:
                still.add(site)
            else:
                moved.add(site)
        if still and moved:
            examples = ', '.join(f'{site:#x}' for site in sorted(still)[:limit])
            failures.append(
                f'{section.path}:{section.line}: {name} moved {low:#x}..{high:#x} '
                f'to {new:#x}, but {len(still)} retail reader(s) still read the '
                f'old home (e.g. {examples}); retarget every reader or replace '
                f'the block in place')
    return failures, len(moves)


def _intervals(writes):
    """Merge write intervals, returning sorted disjoint (start, end) pairs."""
    spans = sorted((w.addr, w.end) for w in writes if w.size > 0)
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def check_sections(sections, problems, equ=None, root=None):
    """Apply every guard rule to parsed sections; return (failures, stats)."""
    root = root or ROOT
    limits = output_limits(equ if equ is not None else _equ_map(
        os.path.join(root, 'src', 'asm', 'common', 'addresses.inc')), root)
    build_root = os.path.normpath(os.path.join(root, 'build'))
    seen, failures = {}, []
    lost = checked = moves = 0
    manifest = os.path.join(root, 'src', 'injection_tools', 'runtime-memory-map.tsv')
    regions = []
    if not os.path.exists(manifest) and os.path.abspath(root) == os.path.abspath(ROOT):
        failures.append(f'{manifest}: runtime memory map is missing')
    if os.path.exists(manifest):
        try:
            with open(manifest, encoding='utf-8', newline='') as source:
                reader = csv.DictReader(source, delimiter='\t')
                required = {'image', 'space', 'start', 'end', 'owner', 'protection', 'evidence'}
                if set(reader.fieldnames or ()) != required:
                    raise ValueError('unexpected TSV columns')
                mapping = list(reader)
            if not mapping:
                raise ValueError('no protected regions')
            for region in mapping:
                if region['space'] != 'cpu-ram' or region['protection'] != 'no-assembly-writes':
                    raise ValueError('unsupported memory space or protection')
                start, end = int(region['start'], 0), int(region['end'], 0)
                if start >= end or not region['owner'] or not region['evidence']:
                    raise ValueError('invalid protected region')
                regions.append((region['image'], start, end, region['owner']))
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append(f'{manifest}: invalid runtime memory map: {error}')

    for section in sections:
        out = section.out
        if not (out == build_root or out.startswith(build_root + os.sep)):
            failures.append(f'{section.path}:{section.line}: output {out} is outside '
                            f'{build_root}')
        if out in seen:
            first = seen[out]
            failures.append(f'{section.path}:{section.line}: {out} opened again '
                            f'(first at {first})')
        else:
            seen[out] = f'{section.path}:{section.line}'

        info = limits.get(out)
        if info:
            limit, limit_name = info
        elif section.input and os.path.exists(section.input):
            limit, limit_name = section.base + os.path.getsize(section.input), \
                'retail file size'
        else:
            failures.append(f'{section.path}:{section.line}: {out} has no '
                            f'X_IMAGE_LIMIT in addresses.inc and no retail input')
            continue

        retail_size = os.path.getsize(section.input) if section.input and \
            os.path.exists(section.input) else 0
        if section.input and os.path.exists(section.input):
            if section.base + retail_size > limit:
                failures.append(f'{section.path}:{section.line}: {limit_name} '
                                f'{limit:#x} is below the retail end '
                                f'{section.base + retail_size:#x}')
                continue

        max_end = section.base
        for write in section.writes:
            checked += 1
            for image, start, end, owner in regions:
                if os.path.basename(out) == image and write.size and write.addr < end and start < write.end:
                    failures.append(f'{write.path}:{write.line}: write '
                                    f'{write.addr:#x}..{write.end:#x} overlaps '
                                    f'live {owner} {start:#x}..{end:#x}')
            if write.addr < section.base:
                failures.append(f'{write.path}:{write.line}: write {write.addr:#x} '
                                f'is below {out} base {section.base:#x}')
            if write.end > limit:
                failures.append(f'{write.path}:{write.line}: write ends '
                                f'{write.end:#x}, past {limit_name} {limit:#x}')
            max_end = max(max_end, write.end)

        # Overlapping writes are only safe when the write that happens FIRST
        # in the listing is padding: a later statement may then place data in
        # that space.  If the earlier statement carried data, the overlap
        # erased it - wherever the two addresses sit.
        ordered = sorted((w for w in section.writes if w.size > 0),
                         key=lambda w: (w.addr, w.order))
        encoded, id_index = {}, {id(write): i for i, write in enumerate(ordered)}

        def data_of(index):
            if index not in encoded:
                encoded[index] = _decode_data(ordered[index].text, root)
            return encoded[index]

        active, heap = set(), []
        for index, write in enumerate(ordered):
            while heap and heap[0][0] <= write.addr:
                _, done = heapq.heappop(heap)
                active.discard(done)
            for other_index in active:
                other = ordered[other_index]
                first, second = ((other, write) if other.order < write.order
                                 else (write, other))
                if first.zero:
                    continue
                # a shared suffix/prefix (the VWF atlas packs glyphs that way)
                # repeats the covered bytes verbatim; anything else is loss
                first_bytes, second_bytes = data_of(id_index[id(first)]), \
                    data_of(id_index[id(second)])
                start = max(first.addr, second.addr)
                end = min(first.end, second.end)
                if first_bytes is not None and second_bytes is not None and \
                        first_bytes[start - first.addr:end - first.addr] == \
                        second_bytes[start - second.addr:end - second.addr]:
                    continue
                lost += 1
                failures.append(
                    f'{write.path}:{write.line}: write {write.addr:#x}..{write.end:#x} '
                    f'overlaps {other.path}:{other.line} '
                    f'({other.addr:#x}..{other.end:#x}, {other.text[:60]!r}); '
                    f'the earlier write is not padding and its bytes are lost')
            active.add(index)
            heapq.heappush(heap, (write.end, index))

        if not os.path.exists(out):
            failures.append(f'{section.path}:{section.line}: output {out} was not written')
            continue
        with open(out, 'rb') as source:
            data = source.read()
        if section.base + len(data) > limit:
            failures.append(f'{section.path}:{section.line}: output ends '
                            f'{section.base + len(data):#x}, past '
                            f'{limit_name} {limit:#x}')
        if max_end - section.base > len(data):
            failures.append(f'{section.path}:{section.line}: listing writes reach '
                            f'{max_end:#x} but {out} is only {len(data):#x} bytes')
        exe = False
        if not section.create and section.input and os.path.exists(section.input):
            with open(section.input, 'rb') as source:
                original = source.read()
            if len(data) < len(original):
                failures.append(f'{section.path}:{section.line}: {out} is {len(data)} '
                                f'bytes, shorter than its {len(original)}-byte input')
            exe = _psx_exe(section.input)
            if exe:
                payload = int.from_bytes(data[0x1C:0x20], 'little')
                if payload != len(data) - 0x800:
                    failures.append(f'{section.path}:{section.line}: {out} t_size '
                                    f'{payload:#x} != file size - 0x800 '
                                    f'({len(data) - 0x800:#x})')
        else:
            original = b''

        # every byte that differs from the input (or is non-zero in a fresh
        # .create output) must be named by a write line
        covered = _intervals(section.writes)
        cursor = 0
        unaccounted = []
        total = max(len(data), len(original))
        # `.create` outputs have no input to compare against: every non-zero
        # byte is a byte the listing must name.
        zero = bytes(_DIFF_CHUNK)
        for start in range(0, total, _DIFF_CHUNK):
            end = min(start + _DIFF_CHUNK, total)
            current = data[start:end].ljust(end - start, b'\0')
            if original:
                reference = original[start:end].ljust(end - start, b'\0')
                differs = current != reference
            else:
                reference = zero[:end - start]
                differs = current != reference
            if not differs:
                continue
            for offset in range(start, end):
                byte = current[offset - start]
                source = reference[offset - start]
                expected = byte != source if original else byte != 0
                if exe and 0x1C <= offset < 0x20:
                    expected = False         # armips owns t_size; checked above
                if not expected:
                    continue
                address = section.base + offset
                while cursor < len(covered) and covered[cursor][1] <= address:
                    cursor += 1
                if not (cursor < len(covered) and covered[cursor][0] <= address <
                        covered[cursor][1]):
                    unaccounted.append((offset, byte))
        if unaccounted:
            first = ', '.join(f'{section.base + o:#x}={b:#04x}'
                              for o, b in unaccounted[:6])
            failures.append(f'{section.path}:{section.line}: {len(unaccounted)} byte(s) '
                            f'of {out} changed outside the write log ({first})')

        if original and data != original:
            move_failures, moved = retail_move_failures(section, data, original, exe)
            failures.extend(move_failures)
            moves += moved

    return failures, {'sections': len(sections), 'writes': checked, 'lost': lost,
                      'moves': moves}


def check_listing(path, root=None):
    root = root or ROOT
    sections, problems = parse_listing(path, root)
    equ = _equ_map(os.path.join(root, 'src', 'asm', 'common', 'addresses.inc')) \
        if os.path.isfile(os.path.join(root, 'src', 'asm', 'common', 'addresses.inc')) else {}
    failures, stats = check_sections(sections, problems, equ, root)
    return [p for p in problems], failures, stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('check', help='verify one armips -temp listing')
    check.add_argument('--listing', required=True)
    check.add_argument('--root', default=ROOT)
    check.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)
    problems, failures, stats = check_listing(args.listing, args.root)
    for problem in problems:
        print(f'{TOOL}: cannot read listing: {problem}')
    for failure in failures:
        print(f'{TOOL}: FAIL {failure}')
    if problems or failures:
        print(f'{TOOL}: {stats["sections"]} output(s), {stats["writes"]} write(s), '
              f'{stats["lost"]} lost, {stats["moves"]} move(s), '
              f'{len(failures)} failure(s)')
        return 1
    if not args.quiet:
        print(f'{TOOL}: {stats["sections"]} output(s), {stats["writes"]} write(s), '
              f'no lost writes, {stats["moves"]} move(s), every changed byte '
              f'accounted for')
    return 0


if __name__ == '__main__':
    sys.exit(main())
