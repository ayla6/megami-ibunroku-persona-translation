"""Demon names (master table in SLPS_005.00) and race names (one copy per field overlay).

  python tools/demons.py dump     queue the demon-name gaps in translation/manual/SLPS_005.00.tsv (toolbelt)
  python tools/demons.py build    QA + generate build/demons.asm (SLPS section) and build/races_<ovl>.asm

Demons: 194 records of 0x38 bytes; record of id k (1-based) = 0x800417A0 + k*0x38 (the game indexes from
0x800417A0; record 0 is the first real entry's predecessor and is not touched). The name is a 10-byte field at +0
(small-font single-byte glyphs, tools/skills.py encoding), FF-terminated unless 10 long; +0xB is the race (1-based
into the race table). Readers copy at most 10 glyphs: battle message variable (BTLP 0x8007A920 type 5 ->
0x8007A86C, 10 chars), fusion / card screens (ADV/DNG/S2D 0x8008F730-style sprite rows and 0x80067C00 tile rows,
count 10). The record holds only the head; name_tails.py stores the rest
for full-name helpers using the shared 21-byte scratch.
Races: 26 fields of 6 bytes, padded with 0x00 (small-font blank), no terminator; copies in ADV 0x800B23C0,
DNG 0x8009AEB0, S2D 0x8009DA40 (all read with count 6). English comes from the PSP-US BOOT race table
(src/extraction_tools/psp/boot_tables.py races, positional: PSP 0-based order == PSX 1-based order, verified
via the demon records' race bytes); every PSP race name fits in 6 cells, so the manual worklist only keeps
human overrides. BTLP's separate 27-slot race tags live in tools/btlui.py.
Demon English: official names of the 2009 PSP release; race English is the
PSP-US BOOT race table verbatim (positional, see above).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import etext   # noqa: E402
import skills  # noqa: E402
import items   # noqa: E402

ROOT = etext.ROOT
SLPS_BASE = 0x8000F800
OVL_BASE = 0x800643C4
REC0 = 0x800417A0
STRIDE = 0x38
COUNT = 194
FIELD = 10
MAXLEN = items.MAXLEN       # shared 21-byte scratch: 20 glyphs + terminator
ROW_PX = items.ROW_PX       # the same ten 8-px cells as an item name row,
                            # condensed by the same tier when it overflows
RACE_COUNT = 26
RACE_LEN = 6
RACE_TABLES = {'ADV': 0x800B23C0, 'DNG': 0x8009AEB0, 'S2D': 0x8009DA40}
OUT = os.path.join(ROOT, 'build', 'demons.asm')
NL = chr(10)


def text(b):
    return ''.join(etext.glyph.get(x, '<%02X>' % x) for x in b)


def records():
    d = open(os.path.join(ROOT, 'data', 'psx', 'SLPS_005.00'), 'rb').read()
    out = []
    for k in range(1, COUNT + 1):
        a = REC0 + k * STRIDE
        f = d[a - SLPS_BASE:a + FIELD - SLPS_BASE]
        out.append((k, a, text(f.split(b'\xff')[0])))
    return out


def races():
    tabs = {}
    for ovl, a in RACE_TABLES.items():
        d = open(os.path.join(ROOT, 'data', 'psx', ovl + '.BIN'), 'rb').read()
        tabs[ovl] = d[a - OVL_BASE:a - OVL_BASE + RACE_COUNT * RACE_LEN]
    first = next(iter(tabs.values()))
    for ovl, t in tabs.items():
        assert t == first, f'race table copy in {ovl} differs'
    return [(i, text(first[i * RACE_LEN:(i + 1) * RACE_LEN].rstrip(b'\0'))) for i in range(RACE_COUNT)]


def record_en():
    """{record id: en} from the canonical SLPS rows (pos = record offset,
    manual wins - toolbelt.merged_rows). The one source for demon names;
    the rows are scaffolded by slps.py dump and ported by boot_tables."""
    import toolbelt
    by_off = {}
    for r in toolbelt.merged_rows('SLPS_005.00'):
        t = (r.get('en') or '').strip()
        if t:
            for _entry, off in toolbelt.pos_offsets(r['pos']):
                by_off[off] = t
    return {k: by_off.get(a - SLPS_BASE, '') for k, a, _ja in records()}


def race_en():
    """{index(1-based): en} from the canonical race rows (every overlay
    holds an identical copy of the 26-name table; manual wins)."""
    import toolbelt
    out = {}
    for rel in ('ADV', 'DNG', 'S2D'):
        for r in toolbelt.merged_rows(rel):
            base = RACE_TABLES[rel] - OVL_BASE
            for _entry, pos in toolbelt.pos_offsets(r['pos']):
                if base <= pos < base + RACE_COUNT * RACE_LEN:
                    idx = (pos - base) // RACE_LEN + 1
                    if (r.get('en') or '').strip():
                        out[idx] = r['en'].strip()
    return out


def dump():
    """Queue the family's positions in the canonical manual worklist (the
    rows themselves are scaffolded by slps.py dump)."""
    import toolbelt
    toolbelt.route_gaps('SLPS_005.00',
                        [hex(a - SLPS_BASE) for _k, a, _ja in records()])
    print('demons: worklist queued in', toolbelt.man_path('SLPS_005.00'))


def name_px(t):
    """Un-tightened drawn width of the full name (head + tail)."""
    import smallfont_vwf
    return smallfont_vwf.codes_px(skills.encode_glyphs(0, t))


def name_fit(t):
    """(tier, px) for the full name in the row's footprint.

    `tier` is None when even the condensed tier cannot fit the row; `px` is
    then the un-tightened width the porter reports."""
    import smallfont_vwf
    return smallfont_vwf.condensed_tier(skills.encode_glyphs(0, t), ROW_PX)


def build():
    en = record_en()
    n = cut = 0
    over = []
    with open(OUT, 'w', newline=NL) as o:
        o.write(';; generated by tools/demons.py build - do not edit' + NL)
        for k, a, ja in records():
            t = en.get(k, '').strip()
            if not t:
                continue
            b = skills.encode_glyphs(k, t)
            if len(b) > MAXLEN:
                raise SystemExit(f'demons: {k} {t!r} is {len(b)} glyphs, max {MAXLEN}')
            tier, px = name_fit(t)
            if tier is None:
                over.append(f'{k} {t!r} {px}px')
                continue
            if len(b) > FIELD:
                cut += 1
                b = b[:FIELD]
            head = b if len(b) == FIELD else b + b'\xff' + bytes(FIELD - len(b) - 1)
            o.write(f'; {k} {t}{NL}.org {a:#x}{NL}    .byte ' + ', '.join(f'0x{c:02X}' for c in head) + NL)
            n += 1
    if over:
        toolbelt.fail(f'{len(over)} name(s) wider than the {ROW_PX}px row '
                      '(shorten the wording; the porter drafts it, the row '
                      'never grows):\n  ' + '\n  '.join(over))
    ren = race_en()
    body = ''
    nr = 0
    for i, ja in races():
        t = ren.get(i + 1, '')
        if not t:
            continue
        if len(t) > RACE_LEN:
            raise SystemExit(f'demons: race {i + 1} {t!r} is {len(t)} chars, max {RACE_LEN}')
        b = skills.encode(i, t)
        b += bytes(RACE_LEN - len(b))
        body += f'; {i + 1} {t}{NL}.org TABLE + {i * RACE_LEN:#x}{NL}    .byte ' + ', '.join(f'0x{c:02X}' for c in b) + NL
        nr += 1
    for ovl, a in RACE_TABLES.items():
        with open(os.path.join(ROOT, 'build', f'races_{ovl.lower()}.asm'), 'w', newline=NL) as o:
            o.write(';; generated by tools/demons.py build - do not edit' + NL)
            o.write(body.replace('TABLE', f'{a:#x}'))
    print(f'demons: {n}/{COUNT} translated ({cut} heads continued in tail bank), races: {nr}/{RACE_COUNT} -> {OUT}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build}[sys.argv[1] if len(sys.argv) > 1 else 'build']()
