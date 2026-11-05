"""Verify an armips write log before its outputs are trusted.

armips' `-temp LISTING` records every emitted line as
``ADDRESS STATEMENT ; /source/file line N`` inside the surrounding
``.open``/``.create`` section.  That log is a complete account of what the
assembler wrote and where, so it can prove the three properties no ad-hoc
``.error`` guard can prove for every output at once:

  * every output lives in ``build/`` (never in the retail dump or dist/);
  * no output is opened twice, and no non-zero write is silently covered by
    a later write (padding from ``.fill 0``/``.area``/``.align`` may be
    covered by the data placed inside it);
  * every write stays inside the output image's declared memory limit, and
    every byte of the built file that differs from its input is a byte the
    listing says was written.

Limits come from ``addresses.inc``: an ``X_OUTPUT`` equ pairs with
``X_IMAGE_LIMIT``.  An output without a limit may not grow past its retail
input; declaring the limit is how growth is allowed.

Usage:
    python src/injection_tools/write_guard.py check --listing build/armips-main.lst
"""
from __future__ import annotations

import argparse
import heapq
import os
import re
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


def _directive_size(token, rest, path):
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
        name = resolve(match.group(1))
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


def _size(token, rest, addr, path):
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
    return _directive_size(token, rest, path)


def parse_listing(path):
    """Parse an armips -temp listing into its sections and write intervals."""
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
                current = Section(resolve(opened.group(2)), resolve(opened.group(1)),
                                  int(opened.group(3), 0), origin, line, False)
                sections.append(current)
                continue
            created = _CREATE.match(text)
            if created:
                current = Section(resolve(created.group(1)), None,
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
                sized = _size(token, rest, address, origin)
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


def _decode_data(text):
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
            name = resolve(match.group(1))
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
    lost = checked = 0

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
                encoded[index] = _decode_data(ordered[index].text)
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

    return failures, {'sections': len(sections), 'writes': checked, 'lost': lost}


def check_listing(path, root=None):
    root = root or ROOT
    sections, problems = parse_listing(path)
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
              f'{stats["lost"]} lost, {len(failures)} failure(s)')
        return 1
    if not args.quiet:
        print(f'{TOOL}: {stats["sections"]} output(s), {stats["writes"]} write(s), '
              f'no lost writes, every changed byte accounted for')
    return 0


if __name__ == '__main__':
    sys.exit(main())
