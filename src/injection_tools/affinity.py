"""Affinity descriptions (Persona / demon status page, "ぞくせい" line) in SLPS_005.00.

  python tools/affinity.py dump     queue the affinity gaps in translation/manual/SLPS_005.00.tsv (toolbelt)
  python tools/affinity.py build    QA + generate build/affinity.asm (SLPS section); English from the canonical SLPS rows

Table at RAM 0x8004C848: 120 records of 0x19 bytes (0-62 and 96 real, the rest "リザーブ"), small-font single-byte glyphs
(the small-font engine's map, smallfont_vwf.char_code), FF-terminated unless 25 long. Index = byte +0x11 of a demon record (0x800417B1) or of a Persona record
(0x8004B0E6, stride 0x2C). Readers (ADV 0x80070100 / 0x80099008 / 0x8009FF98, same in DNG/S2D/BTLP) call the tile-row
renderer 0x80067C00 with count 0x19: ONE line of at most 25 cells, no wrap. A line longer than those 25 cells keeps its
first 25 glyphs in the record and the remainder in the small-font pool (smallfont_vwf.write_pool), which the overlay's
recorder appends when it draws the row - the slot is the line's head, never a truncation. The Japanese kana やや / ぞ etc. render as
lowercase letters since tools/smallfont_lc.py took their cells, so every used record must be translated.
The header label "ぞくせい" above it (4 cells, ADV/DNG/S2D copies in HEADER) -> build/affinity_<ovl>.asm.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import etext   # noqa: E402

ROOT = etext.ROOT
SLPS_BASE = 0x8000F800
TABLE = 0x8004C848
STRIDE = 0x19
COUNT = 120                          # records 0-119; 63-95 are unused (FREE), 97-119 'リザーブ' used by some demons
FREE = range(63, 96)                 # never indexed: holds the skill-name overflow tails (slps_005.00/skill_names.asm)
HEADER = {'ADV': 0x800B2380, 'DNG': 0x8009AE70, 'S2D': 0x8009DA00}   # "ぞくせい" label, drawn with count 4
HEADER_EN = 'Type'                   # official PSP term (Type / Subtype: the two lines under the header)
LINE_MAX = 47                        # one drawn row: SF_POOL_LINE_MAX in vwf/smallfont_defs.asm
                                     # (the recorder's FF-terminated code list, head + pool tail)
OUT = os.path.join(ROOT, 'build', 'affinity.asm')
NL = chr(10)


def records():
    d = open(os.path.join(ROOT, 'data', 'psx', 'SLPS_005.00'), 'rb').read()
    out = []
    for k in range(COUNT):
        if k in FREE:
            continue
        a = TABLE + k * STRIDE
        f = d[a - SLPS_BASE:a + STRIDE - SLPS_BASE].split(b'\xff')[0]
        out.append((k, a, ''.join(etext.glyph.get(x, '<%02X>' % x) for x in f)))
    return out


def record_en():
    """{id: en} from the canonical SLPS rows (pos = record offset, manual
    wins - toolbelt.merged_rows; the rows are ported by port_affinity.py
    and scaffolded by slps.py dump)."""
    import toolbelt
    by_off = {}
    for r in toolbelt.merged_rows('SLPS_005.00'):
        t = (r.get('en') or '').strip()
        if t:
            for _entry, off in toolbelt.pos_offsets(r['pos']):
                by_off[off] = t
    return {k: by_off.get(a - SLPS_BASE, '') for k, a, _ja in records()}


def encode(k, t):
    """The line as small-font glyph codes - one byte per character - or a
    SystemExit when the disc cannot carry it at all: every character needs a
    cell, and one drawn row (head + pool tail) holds LINE_MAX glyphs.

    The first STRIDE bytes are the affinity record's own 25-cell slot; the
    rest is the small-font pool (smallfont_vwf.write_pool carries exactly
    `encode(...)[STRIDE:]`). Callers that only need the record slice.

    The code choice is the small-font engine's own (smallfont_vwf.char_code):
    the affinity row and its pool tail are drawn by that engine, so the
    punctuation the base map lacks (',' -> the comma cell) must spell the same
    way in both halves."""
    if len(t) > LINE_MAX:
        raise SystemExit(f'affinity: {k} {t!r} is {len(t)} glyphs, max {LINE_MAX}')
    import smallfont_vwf
    codes = bytearray()
    for c in t:
        try:
            codes.append(smallfont_vwf.char_code(c))
        except SystemExit:
            raise SystemExit(f'affinity: {k} {t!r}: {c!r} is not in the small font')
    return bytes(codes)


def record_bytes(k, t):
    """The 25 bytes of the record itself: the line's head, FF-terminated and
    zero-padded only when the line is shorter than the slot. A longer line's
    remainder is tail_bytes (the small-font pool)."""
    b = encode(k, t)[:STRIDE]
    return b if len(b) == STRIDE else b + b'\xff' + bytes(STRIDE - len(b) - 1)


def tail_bytes(k, t):
    """The rest of a line longer than the record's slot (b'' when it fits)."""
    return encode(k, t)[STRIDE:]


def dump():
    """Queue the family's positions in the canonical manual worklist (the
    rows themselves are scaffolded by slps.py dump; over-cap PSP wording
    is routed there by port_affinity.py)."""
    import toolbelt
    toolbelt.route_gaps('SLPS_005.00',
                        [hex(a - SLPS_BASE) for _k, a, _ja in records()])
    print('affinity: worklist queued in', toolbelt.man_path('SLPS_005.00'))


def build():
    import features
    en = record_en()
    kit = features.on('SF_VWF')          # only the kit can draw a line's pool tail
    n = 0
    skipped = []
    with open(OUT, 'w', newline=NL) as o:
        o.write(';; generated by tools/affinity.py build - do not edit' + NL)
        for k, a, ja in records():
            t = en.get(k, '').strip()
            if not t:
                continue
            try:
                codes = encode(k, t)    # unencodable / over the row cap: the row stays
            except SystemExit as e:     # Japanese in game and is reported here
                skipped.append(str(e))
                continue
            if len(codes) > STRIDE and not kit:
                # No recorder to append the tail: the retail 25-cell writer
                # would cut the line, so the whole record stays Japanese until
                # a gated build can take it (build/affinity_gated.tsv renames it).
                continue
            b = record_bytes(k, t)
            o.write(f'; {k} {t}{NL}.org {a:#x}{NL}    .byte ' + ', '.join(f'0x{c:02X}' for c in b) + NL)
            n += 1
    ja = bytes.fromhex('38080e02')                   # ぞくせい
    for ovl, a in HEADER.items():
        d = open(os.path.join(ROOT, 'data', 'psx', ovl + '.BIN'), 'rb').read()
        assert d[a - 0x800643C4:a - 0x800643C4 + 4] == ja, f'affinity header not at {a:#x} in {ovl}'
        with open(os.path.join(ROOT, 'build', f'affinity_{ovl.lower()}.asm'), 'w', newline=NL) as o:
            o.write(';; generated by tools/affinity.py build - do not edit' + NL)
            o.write(f'.org {a:#x}{NL}    .byte ' + ', '.join(f'0x{c:02X}' for c in encode('header', HEADER_EN)) + NL)
    # A LINE LONGER THAN ITS SLOT IS NOT MISSING: the record keeps its head and
    # the overlay's small-font VWF engine draws the rest from the pool
    # (src/asm/vwf/smallfont.asm, config +0x18; smallfont_vwf.write_pool emits
    # exactly `encode(...)[STRIDE:]` for these records). The pool belongs to the
    # SF_VWF kit, so with the gate off those rows are not written and keep their
    # Japanese; name them so verify_disc reports the trade-off instead of a
    # mystery miss (build/affinity_gated.tsv).
    gated = []
    for k, _a, _ja in records():
        t = en.get(k, '').strip()
        if not t:
            continue
        try:
            codes = encode(k, t)
        except SystemExit:
            continue                     # the row stays Japanese (reported below)
        if len(codes) > STRIDE:
            gated.append((k, hex(TABLE + k * STRIDE - SLPS_BASE), t))
    with open(os.path.join(ROOT, 'build', 'affinity_gated.tsv'), 'w', newline=NL) as o:
        o.write('slot\tpos\ten\n')
        for k, pos, t in gated:
            o.write(f'{k}\t{pos}\t{t}\n')
    for s in skipped:
        print('affinity: skipped', s)
    carried = (f'{len(gated)} completed by the small-font pool'
               if kit else
               f'{len(gated)} needing the small-font pool (SF_VWF off: Japanese kept)')
    print(f'affinity: {n}/{COUNT} written to their own {STRIDE}-glyph slot, '
          f'{carried}, {len(skipped)} fitting neither (staying Japanese), '
          f'header {HEADER_EN!r} x{len(HEADER)} -> {OUT}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build}[sys.argv[1] if len(sys.argv) > 1 else 'build']()
