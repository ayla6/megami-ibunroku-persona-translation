"""Location names of the overworld (S2D.BIN): the banner shown on arrival, the map, ...

  python tools/s2dnames.py dump     write/refresh translation/strings/S2DNAMES.tsv (keeps the `en` column)
  python tools/s2dnames.py build    QA + generate build/s2dnames.asm (included in the S2D section of main.asm)

47 names (御影町１丁目, 学園入口, 御影町２丁目 ...) at RAM 0x800AAE0E-0x800AB033 (file offset = RAM - 0x800643C4), FF01-terminated, in the
dialogue encoding. They are reached through pointer words (a table at 0x800A54E0, a 20-byte-stride record table at 0x800AC324,
...) and a few `lui 0x800B ; addiu` pairs; every pointer word anywhere in the file that points into a name is patched, as
are the addiu immediates (the lui stays 0x800B). The English strings are re-packed inside the zone.
`en` = plain ASCII text (no codes); the build adds FF01. The 8x1 area labels and the 15x1 arrival banner (which share the
pointers) render through the 1-row VWF path (s2d/vwf_text2.asm): proportional English via etext encoding, capped at
LABEL_LIMIT px (224 = double the old fixed 7-cell width); longer strings are refused loudly, never shortened.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext                  # noqa: E402
import strlib                  # noqa: E402
import vwf_wrap   # noqa: E402

ROOT = etext.ROOT
B = 0x800643C4
ZONE = (0x800AAE0E, 0x800AB034)
TSV = os.path.join(ROOT, 'translation', 'manual', 'strings', 'S2DNAMES.tsv')
AUTO_TSV = os.path.join(ROOT, 'translation', 'generated', 'S2D.BIN', 'S2DNAMES.tsv')
OUT = os.path.join(ROOT, 'build', 's2dnames.asm')
OUT_SLPS = os.path.join(ROOT, 'build', 's2dnames_slps.asm')   # strings spilled into the resident main EXE
LABEL_LIMIT = 224        # px: labels + banner render proportionally now (14 cells' width, double the old
                         # fixed-cell 7-glyph cap); glyphs past the limit are clipped by the 1-row VWF path
EXTRA = {'-': '－', '.': '．', '&': '＆', '/': '／', ':': '：', '!': '！', '?': '？', "'": '’', ',': '，', '+': '＋'}
# Spill space: the S2D extension past the VWF glue. The old SLPS
# "dead function" pools froze the map the moment doubled names first used them
# (they sit next to live buffers; dead-code analysis checks references, not
# buffer extents). The extension is the file's own appended bytes - safe.
# Keep the existing conservative ceiling; the compositor ring is resident.
# (vwf_text2.asm), which the banner walk needs intact through the whole frame.
SPILL = [(0x800BB8F0, 0x800BBB70)]
NL = chr(10)


def slots(t):
    """VWF text -> one byte per character (etext.vwf_byte: ASCII plus the
    font's own extras) + the b'\\xff\\x01' end marker, i.e. exactly the
    retail entry shape (raw face-value script bytes, FF 01-terminated).
    The S2D text interpreter
    (0x8009B2F4) walks these entries as BYTES - first byte FF escapes to
    the control dispatch (second byte 0x01 ends the text with flags=0),
    every other first byte is one decoder-single = one putter call - so
    u16 slot packing desyncs it (the decoder eats pairs, the FF 01 lands
    misaligned and is never seen) and over-grid walks then deadlock in
    the grid-full latch. Byte packing keeps FF 01 aligned and reachable;
    the 1-row VWF path caps pos below grid so long names still get there.
    `en` must stay one VWF byte per character (no two-byte FONT.BIN
    glyphs); anything else is refused by the LABEL_LIMIT width check at
    build time."""
    out = bytearray()
    for c in t:
        try:
            out.append(etext.vwf_byte(c))
        except ValueError:
            raise SystemExit(f's2dnames: {t!r}: {c!r} has no 1-row VWF byte')
    return bytes(out) + b'\xff\x01'


def s2d():
    return open(os.path.join(ROOT, 'data', 'psx', 'S2D.BIN'), 'rb').read()


def names(d):
    out, p = [], ZONE[0]
    while p < ZONE[1]:
        e = d.index(b'\xff\x01', p - B) + 2 + B
        out.append((p, e))
        p = e
    return out


def refs(d, msgs):
    found = {i: [] for i in range(len(msgs))}

    def which(v):
        for i, (a, e) in enumerate(msgs):
            if a <= v < e:
                return i

    for k in range(0, len(d) - 3, 4):
        v = struct.unpack_from('<I', d, k)[0]
        if ZONE[0] <= v < ZONE[1]:
            i = which(v)
            if i is not None:
                found[i].append(('ptr', B + k, v, 0))
    for k in range(0, len(d) - 36, 4):
        w = struct.unpack_from('<I', d, k)[0]
        hi = w & 0xFFFF
        if (w >> 26) == 0xF and hi in (0x800A, 0x800B):
            rt = (w >> 16) & 31
            for j in range(1, 8):
                x = struct.unpack_from('<I', d, k + 4 * j)[0]
                op, imm = x >> 26, x & 0xFFFF
                if ((x >> 21) & 31) != rt or op not in (9, 0xD):
                    continue
                v = (hi << 16) + (imm - 0x10000 if (imm & 0x8000 and op == 9) else imm)
                i = which(v)
                if i is not None:
                    found[i].append(('addiu' if op == 9 else 'ori', B + k + 4 * j, v, B + k))
    return found


def read_tsv():
    rows = {}
    if os.path.exists(TSV):
        for c in strlib.tsv_rows(TSV, required=('idx', 'en')):
            if c['idx'].isdigit():
                rows[int(c['idx'])] = c['en'] if etext.has_text(c['en']) else ''
    return rows


def auto_tsv():
    rows = {}
    if os.path.exists(AUTO_TSV):
        for c in strlib.tsv_rows(AUTO_TSV, required=('idx', 'ja', 'en')):
            if c['idx'].isdigit() and etext.has_text(c['en']):
                rows[int(c['idx'])] = (c['ja'], c['en'])
    return rows


def dump():
    d = s2d()
    msgs = names(d)
    rf = refs(d, msgs)
    old = read_tsv()
    notes = {}
    if os.path.exists(TSV):
        for c in strlib.tsv_rows(TSV, required=('idx', 'note')):
            if c['idx'].isdigit() and c['note'].strip():
                notes[int(c['idx'])] = c['note']
    auto = auto_tsv()
    os.makedirs(os.path.dirname(TSV), exist_ok=True)
    written = 0
    with open(TSV, 'w', encoding='utf-8', newline=NL) as o:
        o.write('idx\tram\tsize\trefs\tja\ten\tnote' + NL)
        for i, (a, e) in enumerate(msgs):
            ja = etext.decode(d[a - B:e - B - 2]).replace('<00>', '')
            manual = old.get(i, '')
            if i in auto and auto[i][0] == ja and not etext.has_text(manual):
                continue
            o.write(f'{i}\t{a:08X}\t{e - a}\t{len(rf[i])}\t{ja}\t'
                    f'{manual if etext.has_text(manual) else ""}\t{notes.get(i, "")}' + NL)
            written += 1
    print(f'wrote {TSV}: {written} manual rows; {len(msgs) - written} PSP-generated matches omitted')


def build():
    d = s2d()
    msgs = names(d)
    rf = refs(d, msgs)
    manual = read_tsv()
    auto = auto_tsv()
    todo = {}
    for i, (a, e) in enumerate(msgs):
        ja = etext.decode(d[a - B:e - B - 2]).replace('<00>', '')
        t = manual.get(i, '').strip()
        if not etext.has_text(t):
            port = auto.get(i)
            t = port[1] if port and port[0] == ja else ''
        if not t:
            continue
        if not rf[i]:
            raise SystemExit(f's2dnames: {i} has no reference')
        px = vwf_wrap.text_width(t)
        if px > LABEL_LIMIT:
            raise SystemExit(f's2dnames: {i} {t!r} is {px}px (> {LABEL_LIMIT}px)')
        todo[i] = slots(t)
    free = sorted(msgs[i] for i in todo)
    merged = []
    for a, e in free:
        if merged and merged[-1][1] == a:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((a, e))
    placed, addr_of = {}, {}
    spill = list(SPILL)

    def put(i, pools):
        b = todo[i]
        if b in placed:
            addr_of[i] = placed[b]
            return True
        for pool in pools:
            for k, (a, e) in enumerate(pool):
                if e - a >= len(b):
                    placed[b] = a
                    addr_of[i] = a
                    pool[k] = (a + len(b), e)
                    return True
        return False

    order = sorted(todo, key=lambda i: (not any(r[0] in ('addiu', 'ori') for r in rf[i]), -len(todo[i])))
    for i in order:
        has_code = any(r[0] in ('addiu', 'ori') for r in rf[i])
        if not put(i, [merged] if has_code else [merged, spill]):
            raise SystemExit(f's2dnames: out of space for {i} ({len(todo[i])} bytes, code refs: {has_code})')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', newline=NL) as o:
        o.write(';; generated by tools/s2dnames.py build - do not edit' + NL)
        for i in todo:
            a, e = msgs[i]
            o.write(f'.org {a:#x}{NL}.fill {e - a}, 0{NL}')
        for b, a in placed.items():
            if ZONE[0] <= a < ZONE[1]:
                o.write(f'.org {a:#x}{NL}    .byte ' + ', '.join(f'0x{x:02X}' for x in b) + NL)
        for i in todo:
            for kind, where, old, lui in rf[i]:
                new = addr_of[i]
                if kind == 'ptr':
                    o.write(f'.org {where:#x}{NL}    .word {new:#x}{NL}')
                elif kind == 'addiu':
                    o.write(f'.org {where:#x}{NL}    .halfword {(new - 0x800B0000) & 0xFFFF:#x}{NL}')
                else:                                                  # ori with lui 0x800A
                    o.write(f'.org {where:#x}{NL}    .halfword {new & 0xFFFF:#x}{NL}')
    import json
    ptrmap = {}
    content = {}
    for i in todo:
        for kind, where, old, lui in rf[i]:
            ptrmap[f'{old:#010x}'] = f'{addr_of[i]:#010x}'
        content[todo[i].hex()] = f'{addr_of[i]:#010x}'          # encoded English (+FF01) -> new address
    with open(os.path.join(ROOT, 'build', 's2dnames_map.json'), 'w') as o:
        json.dump({'ptr': ptrmap, 'content': content}, o)
    with open(OUT_SLPS, 'w', newline=NL) as o:
        o.write(';; generated by tools/s2dnames.py build - overworld names spilled into unused SLPS functions' + NL)
        for b, a in placed.items():
            if not (ZONE[0] <= a < ZONE[1]):
                o.write(f'.org {a:#x}{NL}    .byte ' + ', '.join(f'0x{x:02X}' for x in b) + NL)
    print(f's2dnames: {len(todo)}/{len(msgs)} translated, {sum(len(b) for b in placed)} of {sum(e - a for a, e in (msgs[i] for i in todo))} bytes -> {OUT}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build}[sys.argv[1] if len(sys.argv) > 1 else 'build']()
