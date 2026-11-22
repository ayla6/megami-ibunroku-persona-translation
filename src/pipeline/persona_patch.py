#!/usr/bin/env python3
"""persona-patch.py - apply the Persona translation's P1MOD layers to the
original Rev 0 disc, without a browser. One file, Python 3.9+, standard
library only; it ships in every release beside the layers.

    python persona-patch.py SOURCE.bin OUT.bin base.p1mod latin-alphabet.p1mod english-translation.p1mod [MOD.p1mod ...]
    python persona-patch.py SOURCE.bin OUT.ppf base.p1mod latin-alphabet.p1mod english-translation.p1mod [MOD.p1mod ...]
    python persona-patch.py SOURCE.bin OUT.ppf --choose 'english-translation(font=small)' ...

The layers apply in dependency order: base, alphabet, English, then mods
(a mod's layer needs the mods its manifest row requires). OUT ending in .ppf
writes a PPF 3.0 of the changes instead of a disc. --choose picks a mod's
choices as a build names them: the mod's name, its choices in parentheses
(`english-translation(font=small,subtitles=off)`); every mod is at its
defaults otherwise.

This is the Python twin of webpatcher/modpack.js (the page's applier):
every rule below mirrors it - the layer format, which parts a selection
applies, the merge, and the layout (files that grow move into freed room or
past the end, the ISO records and the game's FSECT / FSIZE.DAT follow, each
written sector gets fresh EDC/ECC). The release checks that it lays out the
same disc as src/pipeline/build_disc.py, byte for byte (tools/build_patches.py).
"""
from dataclasses import dataclass
from typing import Final

import hashlib
import lzma
import os
import re
import shutil
import struct
import sys

SECTOR = 2352
SYNC = bytes([0] + [255] * 10 + [0])
SUB_DATA = bytes([0, 0, 0x08, 0])
SUB_LAST = bytes([0, 0, 0x89, 0])      # data | EOR | EOF
POSTGAP = 150
MAGIC = b'P1MOD\t1\n'
HEADER = 'kind\tpath\tbefore\tafter'
LAYOUT_FILES = frozenset({'FNAME.DAT', 'FSECT.DAT', 'FSIZE.DAT'})
LZMA_FILTERS = [{'id': lzma.FILTER_LZMA1, 'dict_size': 1 << 26, 'lc': 3, 'lp': 0, 'pb': 2}]


# --- Form 1 EDC/ECC (src/pipeline/cdsector.py) --------------------------------
EDC = []
for _i in range(256):
    _e = _i
    for _k in range(8):
        _e = (_e >> 1) ^ (0xD8018001 if _e & 1 else 0)
    EDC.append(_e)
ECC_F = [0] * 256
ECC_B = [0] * 256
for _i in range(256):
    _j = ((_i << 1) ^ (0x11D if _i & 0x80 else 0)) & 0xFF
    ECC_F[_i] = _j
    ECC_B[_i ^ _j] = _i


def ecc_pq(buf, major_count, minor_count, major_mult, minor_inc, out_off):
    size = major_count * minor_count
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _m in range(minor_count):
            t = buf[12 + index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = ECC_F[a]
        a = ECC_B[ECC_F[a] ^ b]
        buf[out_off + major] = a
        buf[out_off + major + major_count] = a ^ b


def bcd(n):
    return ((n // 10) << 4) | (n % 10)


def msf(lba):
    t = lba + 150
    return bytes([bcd(t // 4500), bcd(t // 75 % 60), bcd(t % 75)])


def make_form1(lba, sub, user):
    buf = bytearray(SECTOR)
    buf[0:12] = SYNC
    buf[12:15] = msf(lba)
    buf[15] = 2
    buf[16:20] = sub
    buf[20:24] = sub
    buf[24:24 + 2048] = user[:2048].ljust(2048, b'\0')
    e = 0
    for p in range(16, 2072):
        e = (e >> 8) ^ EDC[(e ^ buf[p]) & 0xFF]
    struct.pack_into('<I', buf, 2072, e)
    header = bytes(buf[12:16])
    buf[12:16] = b'\0\0\0\0'                 # Mode 2: ECC ignores the header
    ecc_pq(buf, 86, 24, 2, 86, 2076)        # P
    ecc_pq(buf, 52, 43, 86, 88, 2076 + 172)  # Q
    buf[12:16] = header
    return bytes(buf)


def empty_sector(lba):
    s = bytearray(SECTOR)
    s[0:12] = SYNC
    s[12:15] = msf(lba)
    s[15] = 2
    return bytes(s)


# --- layers (src/pipeline/modpack.py, webpatcher/modpack.js) -----------------
@dataclass(frozen=True)
class EntryEdit:
    index: int
    data: bytes
    source: str


class Edit:
    def __init__(self, path, raw, before, length):
        self.path, self.raw, self.before, self.length = path, raw, before, length
        self.entries: list[EntryEdit] = []
        self.scales = []
        self.source = None
        self.spans = []                      # [(offset, bytes)]


def parse_layer(blob, name='layer'):
    """{'name', 'title', 'requires', 'choices': [token], 'parts': [(when,
    [Edit])], 'twins': [[path]]}"""
    if not blob.startswith(MAGIC):
        raise SystemExit(f'{name}: not a P1MOD 1 layer')
    dash = blob.find(b'\n--\t', len(MAGIC) - 1)
    end = blob.find(b'\n', dash + 1)
    if dash < 0 or end < 0:
        raise SystemExit(f'{name}: no -- line')
    _d, runs_size, size = blob[dash + 1:end].decode('ascii').split('\t')
    runs_size, size = int(runs_size), int(size)
    both = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=LZMA_FILTERS).decompress(
        blob[end + 1:], max_length=runs_size + size)
    if len(both) != runs_size + size:
        raise SystemExit(f'{name}: the layer is damaged (short stream)')
    lines = blob[len(MAGIC):dash].decode('utf-8').split('\n')
    if lines[0] != HEADER:
        raise SystemExit(f'{name}: unknown manifest header')
    pack = {'name': None, 'title': '', 'requires': [], 'choices': [], 'parts': [], 'twins': [], 'ranges': []}
    by_path = []
    for line in lines[1:]:
        kind, cell, before, after = line.split('\t')
        if kind == 'name':
            pack['name'] = cell
        elif kind == 'title':
            pack['title'] = cell
        elif kind == 'requires':
            pack['requires'].append(cell)
        elif kind in ('option', 'extra'):
            pack['choices'].append(cell)
        elif kind == 'range':
            pack['ranges'].append((cell, *map(int, before.split(','))))
        elif kind == 'part':
            pack['parts'].append(('' if cell == '-' else cell, []))
            by_path.append({})
        elif kind in ('file', 'raw'):
            if cell in LAYOUT_FILES:
                raise SystemExit(f'{name}: {cell} belongs to the layout')
            edit = Edit(cell, kind == 'raw', int(before), int(after))
            pack['parts'][-1][1].append(edit)
            by_path[-1][cell] = edit
        elif kind not in ('description', 'author', 'version', 'commit'):
            raise SystemExit(f'{name}: unknown row kind {kind}')
    payload = both[runs_size:]
    pos = 0
    current = None
    for line in both[:runs_size].decode('ascii').splitlines():
        kind, cell, *cells = line.split('\t')
        if kind == 'twins':
            pack['twins'].append([cell, *cells])
        elif kind == 'part':
            current = by_path[int(cell)]
        elif kind == 'check':
            current[cell].source = cells[0]
        elif kind == 'scale':
            current[cell].scales.append((int(cells[0]), cells[1], int(cells[2])))
        elif kind == 'mes-entry':
            n = int(cells[1])
            current[cell].entries.append(EntryEdit(int(cells[0]), payload[pos:pos + n], cells[2]))
            pos += n
        elif kind == 'bytes':
            n = int(cells[1])
            current[cell].spans.append((int(cells[0]), payload[pos:pos + n]))
            pos += n
    if pos != len(payload):
        raise SystemExit(f'{name}: payload bytes left over')
    return pack


def parse_mods(text):
    """`a,b(font=small,x)` -> [(a, [..]), (b, ['font=small', 'x'])]."""
    items, depth, start = [], 0, 0
    for at, char in enumerate(text + ','):
        depth += (char == '(') - (char == ')')
        if char == ',' and depth == 0:
            items.append(text[start:at])
            start = at + 1
    out = []
    for item in filter(None, (i.strip() for i in items)):
        match = re.fullmatch(r'([^(),\s]+)\s*(?:\(([^()]*)\))?', item)
        if not match:
            raise SystemExit(f'cannot read {text!r}: names joined by commas, choices in parentheses')
        out.append((match.group(1), [t.strip() for t in (match.group(2) or '').split(',') if t.strip()]))
    return out


def defaults(pack):
    first = {}
    for token in pack['choices']:
        if '=' in token:
            first.setdefault(token.split('=')[0], token)
    return set(first.values()) | {f"{r[0]}={r[4]}" for r in pack.get("ranges", [])}


def selected(packs, selection):
    """The parts that apply, in order, as (name, [Edit], twins)."""
    chosen = {pack['name']: defaults(pack) for pack in packs}
    for label, tokens in selection.items():
        if label not in chosen:
            raise SystemExit(f'--choose names {label}, which is not among the layers given')
        chosen[label] = set(tokens) | {t for t in defaults(next(p for p in packs if p['name'] == label))
                                       if t.split('=')[0] not in {x.split('=')[0] for x in tokens if '=' in x}}
    out = []
    settings = []
    for pack in packs:
        named = {t for when, _f in pack['parts'] for label, toks in parse_mods(when)
                 if label == pack['name'] for t in toks}
        values = {r[0]: r[4] for r in pack.get('ranges', [])}
        parameters = set()
        for token in chosen[pack['name']]:
            key, sep, text = token.partition('=')
            setting = next((r for r in pack.get('ranges', []) if r[0] == key), None)
            if setting and sep:
                _key, minimum, maximum, step, _default = setting
                if not text.isascii() or not text.isdecimal() or step <= 0 or not minimum <= int(text) <= maximum or (int(text) - minimum) % step:
                    raise SystemExit(f'{key}: invalid range value {text}')
                values[key] = int(text)
                parameters.add(token)
        missing = sorted(chosen[pack['name']] - defaults(pack) - named - parameters)
        if missing:
            raise SystemExit(f'{pack["title"] or pack["name"]}: this release has no {", ".join(missing)}')
        first = True
        for when, files in pack['parts']:
            if all(label in chosen and set(toks) <= chosen[label] for label, toks in parse_mods(when)):
                import copy
                files = copy.deepcopy(files)
                chosen_bytes = []
                for edit in files:
                    if not edit.scales:
                        continue
                    again = Edit(edit.path, False, 0, 0)
                    for offset, parameter, original in edit.scales:
                        percent = values[parameter]
                        value = max(1, (original * percent + 50) // 100) if percent and original else 0
                        edit.spans.append((offset, bytes([value])))
                        again.spans.append((offset, bytes([value])))
                    edit.scales = []    # resolved into spans, as modpack.selected does
                    chosen_bytes.append(again)
                out.append((pack['name'], files, pack['twins'] if first else []))
                if chosen_bytes:
                    settings.append((pack['name'] + ' settings', chosen_bytes, []))
                first = False
    # every setting again after all layers, as modpack.selected does
    return out + settings


# --- the disc ----------------------------------------------------------------------
class Disc:
    """The player's image, read-only; what the layout writes is kept aside."""

    def __init__(self, path):
        self.f = open(path, 'rb')
        self.size = os.path.getsize(path)
        self.sectors = self.size // SECTOR
        self.source_sectors = self.sectors
        self.written = {}                   # lba -> bytes(2352)
        self.pending = {}                   # lba -> (sub, data)

    def read(self, offset, length):
        self.f.seek(offset)
        return self.f.read(length)

    def raw(self, lba):
        if lba in self.pending:
            sub, data = self.pending[lba]
            return make_form1(lba, sub, data)
        if lba in self.written:
            return self.written[lba]
        if lba >= self.source_sectors:
            return bytes(SECTOR)
        return self.read(lba * SECTOR, SECTOR)

    def raw_run(self, lba, count):
        if all(lba + n not in self.pending and lba + n not in self.written
               for n in range(count)) and lba + count <= self.source_sectors:
            return self.read(lba * SECTOR, count * SECTOR)
        return b''.join(self.raw(lba + n) for n in range(count))

    def user(self, lba):
        return self.raw(lba)[24:24 + 2048]

    def user_run(self, lba, count):
        raw = self.raw_run(lba, count)
        return b''.join(raw[n * SECTOR + 24:n * SECTOR + 2072] for n in range(count))

    def write_user(self, lba, data, sub=None):
        if sub is None:
            sub = self.raw(lba)[16:20] if lba < self.sectors else SUB_DATA
        self.pending.pop(lba, None)
        self.written[lba] = make_form1(lba, sub, data)
        self.sectors = max(self.sectors, lba + 1)

    def write_raw(self, lba, data, original=None):
        for n in range(len(data) // SECTOR):
            sec = data[n * SECTOR:(n + 1) * SECTOR]
            self.pending.pop(lba + n, None)
            if (original is not None and lba + n < self.source_sectors
                    and sec[16:] == original[n * SECTOR + 16:(n + 1) * SECTOR]):
                self.written.pop(lba + n, None)
                continue
            if sec[18] & 0x20:              # Form 2: no ECC, taken as it is
                out = bytearray(SECTOR)
                out[0:12] = SYNC
                out[12:15] = msf(lba + n)
                out[15] = 2
                out[16:] = sec[16:]
                out = bytes(out)
            else:
                out = make_form1(lba + n, sec[16:20], sec[24:24 + 2048])
            self.written[lba + n] = out
        self.sectors = max(self.sectors, lba + len(data) // SECTOR)

    def write_empty(self, lba):
        self.written[lba] = empty_sector(lba)
        self.sectors = max(self.sectors, lba + 1)

    def write_file(self, lba, data):
        count = max(1, -(-len(data) // 2048))
        for n in range(count):
            self.pending[lba + n] = (SUB_LAST if n == count - 1 else SUB_DATA,
                                     data[n * 2048:(n + 1) * 2048])
        self.sectors = max(self.sectors, lba + count)
        return count

    def flush(self):
        for lba in sorted(self.pending):
            sub, data = self.pending[lba]
            user = data.ljust(2048, b'\0')
            if lba < self.source_sectors:
                orig = self.read(lba * SECTOR, SECTOR)
                if orig[16:20] == sub and orig[20:24] == sub and orig[24:2072] == user:
                    self.written.pop(lba, None)
                    continue
            self.written[lba] = make_form1(lba, sub, user)
        self.pending.clear()

    def walk(self, lba, size, prefix='', out=None):
        out = [] if out is None else out
        for n in range(-(-size // 2048)):
            sec = self.user(lba + n)
            pos = 0
            while pos < 2048:
                rec_len = sec[pos]
                if rec_len == 0:
                    break
                ext, = struct.unpack_from('<I', sec, pos + 2)
                ext_size, = struct.unpack_from('<I', sec, pos + 10)
                flags = sec[pos + 25]
                name = sec[pos + 33:pos + 33 + sec[pos + 32]]
                if not (len(name) == 1 and name[0] <= 1):
                    name = name.decode('ascii').split(';')[0]
                    if flags & 2:
                        self.walk(ext, ext_size, prefix + name + '/', out)
                    else:
                        out.append((prefix + name, ext, ext_size, lba + n, pos))
                pos += rec_len
        return out

    def set_record(self, rec_lba, rec_off, ext, size):
        sec = bytearray(self.user(rec_lba))
        struct.pack_into('<I', sec, rec_off + 2, ext)
        struct.pack_into('>I', sec, rec_off + 6, ext)
        struct.pack_into('<I', sec, rec_off + 10, size)
        struct.pack_into('>I', sec, rec_off + 14, size)
        self.write_user(rec_lba, bytes(sec))

    def entries(self):
        pvd = self.user(16)
        root, = struct.unpack_from('<I', pvd, 156 + 2)
        root_size, = struct.unpack_from('<I', pvd, 156 + 10)
        return {p.upper(): [ext, size, rl, ro] for p, ext, size, rl, ro in self.walk(root, root_size)}

    def read_file(self, entries, path, raw=False):
        ext, size = entries[path][:2]
        sectors = -(-size // 2048)
        if raw:
            return self.raw_run(ext, sectors)
        return self.user_run(ext, sectors)[:size]


def raw_body(data):
    return b''.join(data[n * SECTOR + 16:(n + 1) * SECTOR] for n in range(len(data) // SECTOR))


def sector_body(raw):
    return raw[16:2348] if raw[18] & 0x20 else raw[16:2072]


def is_raw_file(path, data):
    return path.endswith('.STR') and len(data) % SECTOR == 0


# --- merge (modpack.merge) ----------------------------------------------------------
def merge(disc, layers):
    entries = disc.entries()
    files = {}
    for name, edits, _twins in layers:
        for e in edits:
            if e.path in LAYOUT_FILES:
                raise SystemExit(f'{name}: {e.path} belongs to the layout')
            if e.path not in entries:
                raise SystemExit(f'{name}: {e.path} is not on the disc')
            data = files.get(e.path)
            if data is None:
                data = bytearray(disc.read_file(entries, e.path, e.raw))
            if e.source and hashlib.sha1(
                                       raw_body(bytes(data)) if e.raw else bytes(data)).hexdigest() != e.source:
                raise SystemExit(f'{e.path} is not the file the {name} layer was made for - this'
                                 ' is not the original Rev 0 disc, or it is damaged')
            if e.entries:
                if e.spans or e.raw or e.scales:
                    raise SystemExit('MES entries cannot share a file edit with byte edits')
                files[e.path] = bytearray(replace_mes(bytes(data), e.entries))
                continue
            # growth extends a shorter file, shrinking truncates. An in-place
            # edit whose bytes all land inside the file leaves its length (the
            # recorded size may include another mod's extension this selection
            # leaves out); one that writes past the end grows to the whole
            # recorded length, trailing zero padding included
            reach = max((offset + len(b) for offset, b in e.spans), default=0)
            minimum = (reach if e.length == e.before and not e.raw and not e.scales
                       and reach <= len(data) else e.length)
            if e.length < e.before:
                del data[e.length:]
            elif len(data) < minimum:
                data.extend(bytes(minimum - len(data)))
            for offset, b in e.spans:
                data[offset:offset + len(b)] = b
            files[e.path] = data
    return files, entries


MES_SECTOR: Final = 2048
MES_ENTRIES: Final = 256
MES_TABLE_BYTES: Final = 514

def mes_table(data: bytes) -> tuple[int, ...]:
    if len(data) < MES_TABLE_BYTES:
        raise ValueError('MES: truncated table')
    table = struct.unpack_from('<257H', data)
    if table[0] < 1 or table[-1] * MES_SECTOR > len(data) or any(a > b for a, b in zip(table, table[1:])):
        raise ValueError('MES: invalid entry extents')
    return table


def mes_entry(data: bytes, index: int) -> bytes:
    if not 0 <= index < MES_ENTRIES:
        raise ValueError('MES: entry index outside table')
    table = mes_table(data)
    return data[table[index] * MES_SECTOR:table[index + 1] * MES_SECTOR]


def replace_mes(data: bytes, edits: list[EntryEdit]) -> bytes:
    """Keep extents where payloads fit, otherwise repack once in entry order.

    Checks are per entry, so changes to another entry do not invalidate an edit.
    Padding is deterministic; table changes belong to this container operation.
    """
    table = mes_table(data)
    replacements = {}
    for edit in edits:
        index, payload, expected = edit.index, edit.data, edit.source
        if index in replacements:
            raise ValueError('MES: duplicate entry edit')
        original = mes_entry(data, index)
        if hashlib.sha1(original).hexdigest() != expected:
            raise ValueError(f'MES: source entry {index} differs')
        if len(payload) < 10 or payload[-2:] != b'\x7f\xff':
            raise ValueError('MES: prepared entry lacks header or end token')
        replacements[index] = payload
    if all(len(blob) <= (table[i + 1] - table[i]) * MES_SECTOR for i, blob in replacements.items()):
        result = bytearray(data)
        for i, blob in replacements.items():
            start, end = table[i] * MES_SECTOR, table[i + 1] * MES_SECTOR
            result[start:end] = blob + bytes(end - start - len(blob))
        return bytes(result)
    pieces = []
    starts = [table[0]]
    for index in range(MES_ENTRIES):
        blob = replacements.get(index, data[table[index] * MES_SECTOR:table[index + 1] * MES_SECTOR])
        pieces.append(blob)
        starts.append(starts[-1] + (len(blob) + MES_SECTOR - 1) // MES_SECTOR)
    if starts[-1] > 65535:
        raise ValueError('MES: sector table overflow')
    result = bytearray(data[:table[0] * MES_SECTOR])
    struct.pack_into('<257H', result, 0, *starts)
    for blob in pieces:
        result.extend(blob)
        result.extend(bytes((-len(blob)) % MES_SECTOR))
    return bytes(result)


# --- layout (build_disc.build_to) ---------------------------------------------------
def duplicates_from(groups, entries, written):
    out = []
    for group in groups:
        members = sorted((entries[p][0], p, -(-entries[p][1] // 2048))
                         for p in group if p in entries and p not in written)
        for ext, path, sectors in members[1:]:
            out.append((sectors, ext, path, members[0][1]))
    out.sort(key=lambda r: (-r[0], r[1]))
    return [(path, twin) for _s, _e, path, twin in out]


def duplicate_files(disc, entries, written):
    by_length = {}
    for path, (ext, size, *_r) in sorted(entries.items(), key=lambda e: e[1][0]):
        if size and path not in written:
            by_length.setdefault(-(-size // 2048), []).append((ext, path))
    out = []
    for sectors, group in sorted(by_length.items(), key=lambda g: -g[0]):
        exts = {}
        for ext, path in group:
            exts.setdefault(ext, path)
        if len(exts) < 2:
            continue
        firsts = {}
        for ext, path in sorted(exts.items()):
            firsts.setdefault(sector_body(disc.raw(ext)), []).append((ext, path))
        for candidates in firsts.values():
            if len(candidates) < 2:
                continue
            kept = []
            for ext, path in candidates:
                raw = disc.raw_run(ext, sectors)
                body = [sector_body(raw[n * SECTOR:(n + 1) * SECTOR]) for n in range(sectors)]
                twin = next((k for k in kept if k[2] == body), None)
                if twin is None:
                    kept.append((ext, path, body))
                else:
                    out.append((sectors, ext, path, twin[1]))
    out.sort(key=lambda r: (-r[0], r[1]))
    return [(path, twin) for _s, _e, path, twin in out]


def layout(disc, files, entries_in, groups):
    pvd = bytearray(disc.user(16))
    volume, = struct.unpack_from('<I', pvd, 80)
    entries = {p: list(e) for p, e in entries_in.items()}
    fnames = [n for n in disc.read_file(entries, 'FNAME.DAT').decode('ascii').split('\0') if n]
    fsect = bytearray(disc.read_file(entries, 'FSECT.DAT'))
    fsize = bytearray(disc.read_file(entries, 'FSIZE.DAT'))
    game_index = {n.lstrip('\\').split(';')[0].replace('\\', '/').upper(): i
                  for i, n in enumerate(fnames)}
    tables_dirty = False
    orig_end = disc.sectors
    append_at = orig_end
    work, raw_work = [], []
    for path in sorted(files):
        if path not in entries:
            continue
        data = bytes(files[path])
        ext, size, rec_lba, rec_off = entries[path]
        old_sectors = -(-size // 2048)
        if is_raw_file(path, data):
            if len(data) // SECTOR != old_sectors:
                raise SystemExit(f'{path}: {len(data) // SECTOR} raw sectors, the extent holds {old_sectors}')
            orig = disc.raw_run(ext, old_sectors)
            if raw_body(orig) != raw_body(data):
                raw_work.append([path, ext, size, data, orig])
            continue
        sectors = -(-len(data) // 2048)
        orig = disc.user_run(ext, old_sectors)
        if sectors == old_sectors and data.ljust(sectors * 2048, b'\0') == orig and len(data) == size:
            continue
        work.append({'path': path, 'ext': ext, 'old': old_sectors, 'sectors': sectors,
                     'data': data, 'size': size, 'rec_lba': rec_lba, 'rec_off': rec_off})

    written = {w['path'] for w in work} | {w[0] for w in raw_work}
    shared = {}
    for path, (ext, *_r) in entries.items():
        shared.setdefault(ext, []).append(path)
    bodies = {w[0]: raw_body(w[3]) for w in raw_work}
    for path in written:
        sharers = shared[entries[path][0]]
        if len(sharers) > 1 and not (all(p in bodies for p in sharers)
                                     and all(bodies[p] == bodies[sharers[0]] for p in sharers)):
            raise SystemExit(f'{path} shares its extent with {sharers}')
    growing = [w for w in work if w['sectors'] > w['old']]
    collapsed = {}
    first_of = {}
    for item in list(raw_work):
        path, _ext, size, data, _o = item
        k = hashlib.sha1(data).digest()
        if k in first_of and entries[first_of[k]][1] == size:
            collapsed[path] = first_of[k]
            raw_work.remove(item)
        else:
            first_of[k] = path

    def plan():
        free = sorted([w['ext'], w['ext'] + w['old']] for w in growing)
        for p in collapsed:
            free.append([entries[p][0], entries[p][0] + -(-entries[p][1] // 2048)])
        merged_free = []
        for a, b in sorted(free):
            if merged_free and a <= merged_free[-1][1]:
                merged_free[-1][1] = max(merged_free[-1][1], b)
            else:
                merged_free.append([a, b])
        free = merged_free

        def take(lo, hi):
            for k, (a, b) in enumerate(free):
                if a <= lo and hi <= b:
                    free[k:k + 1] = [x for x in ([a, lo], [hi, b]) if x[0] < x[1]]
                    return True
            return False
        target = {}
        for w in sorted(growing, key=lambda w: w['ext']):
            if take(w['ext'], w['ext'] + w['sectors']):
                target[w['path']] = w['ext']
        for w in sorted((w for w in growing if w['path'] not in target), key=lambda w: -w['sectors']):
            for a, b in [list(x) for x in free]:
                if b - a >= w['sectors'] and take(a, a + w['sectors']):
                    target[w['path']] = a
                    break
        return target

    target = plan()
    twins = None
    while any(w['path'] not in target for w in growing):
        if twins is None:
            twins = (duplicates_from(groups, entries, written) if groups
                     else duplicate_files(disc, entries, written))
        if not twins:
            break
        path, twin = twins.pop(0)
        collapsed[path] = twin
        target = plan()

    for path, twin in collapsed.items():
        _e, size, rec_lba, rec_off = entries[path]
        disc.set_record(rec_lba, rec_off, entries[twin][0], size)
        if path in game_index:
            struct.pack_into('<I', fsect, game_index[path] * 4, entries[twin][0])
            tables_dirty = True

    for w in work:
        ext = w['ext']
        if w['sectors'] <= w['old']:
            disc.write_file(ext, w['data'])
        elif w['path'] in target:
            ext = target[w['path']]
            disc.write_file(ext, w['data'])
        else:
            ext = append_at
            append_at += disc.write_file(ext, w['data'])
        disc.set_record(w['rec_lba'], w['rec_off'], ext, len(w['data']))
        if w['path'] in game_index:
            i = game_index[w['path']]
            struct.pack_into('<I', fsect, i * 4, ext)
            struct.pack_into('<I', fsize, i * 4, -(-len(w['data']) // 2048) * 2048)
            tables_dirty = True

    for _p, ext, _s, data, orig in raw_work:
        disc.write_raw(ext, data, orig)

    if tables_dirty:
        for name, table in (('FSECT.DAT', fsect), ('FSIZE.DAT', fsize)):
            ext, _s, rec_lba, rec_off = entries[name]
            disc.write_file(ext, bytes(table))
            disc.set_record(rec_lba, rec_off, ext, len(table))

    if append_at > orig_end:
        for lba in range(append_at, append_at + POSTGAP):
            disc.write_empty(lba)
        volume = append_at + POSTGAP
        struct.pack_into('<I', pvd, 80, volume)
        struct.pack_into('>I', pvd, 84, volume)
        disc.write_user(16, bytes(pvd))
    disc.flush()
    # only the sectors that differ from the source (or lie past its end)
    out = {}
    for lba in sorted(disc.written):
        sector = disc.written[lba]
        if lba < disc.source_sectors and sector == disc.read(lba * SECTOR, SECTOR):
            continue
        out[lba] = sector
    return out, disc.sectors


# --- outputs -------------------------------------------------------------------------
def write_disc(source, out, sectors, total):
    shutil.copyfile(source, out)
    with open(out, 'r+b') as f:
        for lba, sector in sectors.items():
            f.seek(lba * SECTOR)
            f.write(sector)
        f.truncate(max(total * SECTOR, os.path.getsize(source)))
    with open(os.path.splitext(out)[0] + '.cue', 'w', newline='\r\n') as cue:
        cue.write(f'FILE "{os.path.basename(out)}" BINARY\n  TRACK 01 MODE2/2352\n'
                  '    INDEX 01 00:00:00\n')


def write_ppf(disc, out, sectors, description):
    """PPF 3.0 (webpatcher/ppf.js): records of the changed bytes, short
    unchanged gaps joined in, with the source's block at 0x9320 to check."""
    block = disc.read(0x9320, 1024)
    head = bytearray(b'PPF30\x02') + description.encode('ascii', 'replace')[:50].ljust(50, b' ')
    head += bytes([0, 1, 0, 0]) + block
    records = bytearray()

    def emit(offset, data):
        for pos in range(0, len(data), 255):
            piece = data[pos:pos + 255]
            records.extend(struct.pack('<QB', offset + pos, len(piece)) + piece)
    run_start, run = -1, bytearray()
    for lba, target in sectors.items():
        base = lba * SECTOR
        source = disc.read(base, SECTOR).ljust(SECTOR, b'\0')
        i = 0
        while i < SECTOR:
            if source[i] == target[i]:
                i += 1
                continue
            j = i + 1
            while j < SECTOR and source[j] != target[j]:
                j += 1
            run_end = run_start + len(run)
            if run_start >= 0 and (base + i - run_end > 9 or run_end < base):
                emit(run_start, bytes(run))
                run_start, run = -1, bytearray()
            if run_start < 0:
                run_start = base + i
            run.extend(target[run_start + len(run) - base:j])
            i = j
    if run_start >= 0:
        emit(run_start, bytes(run))
    with open(out, 'wb') as f:
        f.write(bytes(head) + bytes(records))


def main(argv):
    args = list(argv)
    choose = {}
    while '--choose' in args:
        k = args.index('--choose')
        for label, tokens in parse_mods(args[k + 1]):
            choose[label] = tokens
        del args[k:k + 2]
    if len(args) < 3:
        print(__doc__)
        return 2
    source, out, *layer_paths = args
    packs = [parse_layer(open(p, 'rb').read(), p) for p in layer_paths]
    names = {p['name'] for p in packs}
    for pack in packs:
        for need in pack['requires']:
            if need not in names:
                raise SystemExit(f'{pack["title"] or pack["name"]} needs {need}: give its layer too')
    layers = selected(packs, choose)
    disc = Disc(source)
    print(f'persona-patch: {len(packs)} layer(s), {len(layers)} part(s); merging', flush=True)
    files, entries = merge(disc, layers)
    groups = [g for _n, _f, twins in layers for g in twins]
    print('persona-patch: laying the disc out', flush=True)
    sectors, total = layout(disc, files, entries, groups or None)
    if out.lower().endswith('.ppf'):
        if total > disc.source_sectors:
            raise SystemExit('this selection makes the disc larger, which a PPF cannot do - write a .bin')
        write_ppf(disc, out, sectors, 'Persona-TL ' + ' '.join(p['name'] for p in packs))
    else:
        write_disc(source, out, sectors, total)
    print(f'persona-patch: {len(sectors)} sector(s) changed -> {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
