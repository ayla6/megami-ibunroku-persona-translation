"""Item names of SLPS_005.00 (field item pick-up, menus, shops).

  python src/injection_tools/items.py dump     refresh generated TSV (keeps en)
  python src/injection_tools/items.py build    QA + build/items.asm

Layout (resident main EXE; file offset = VA - 0x80010000 + 0x800): 163
records of 0x20 bytes from 0x8004441C; the name is at record+0x10,
single-byte glyph indices (the game's own font numbering). Drawn with the
8x12 "small font" page: katakana/hiragana, UPPERCASE A-Z, 0-9 and
/ : - + x = & ! ? . ( ) , (like TIME, MONEY, LEVEL). Latin = full-width
glyph codes (A = 0xA6 ...); glyph 0 = blank cell (space).

The name field is exactly 10 bytes: a 10-glyph name has NO terminator
(byte +10 is a data byte), shorter names end with 0xFF.
`en` uses small-font glyphs. The first ten glyphs go in the record;
name_tails.py stores the remainder for the full-name copy helper. The
shared scratch holds at most MAXLEN glyphs plus FF. Empty `en` leaves
Japanese intact. Equipment records share this layout; their stats follow
the name and must not be overwritten.

Schema: docs/TEXT_ARCHITECTURE.md. TSV io + emission is toolbelt.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext      # noqa: E402
import toolbelt   # noqa: E402
from toolbelt import Patch, smallfont_char  # noqa: E402

ROOT = toolbelt.ROOT
REL = 'SLPS_005.00'
BASE = 0x80010000 - 0x800
FIRST = 0x8004442C                 # name of record 0
STRIDE = 0x20
COUNT = 382                        # 0-162 items, 163-381 equipment
FIELD = 10
MAXLEN = 20                 # head 10 + tail bank (name_tails.py); PSP-US max
ROW_PX = FIELD * 8          # the row's retail footprint: ten 8-px cells, the
                            # count column starts after them. Every surface
                            # (item menu, shops, status, fusion, facility)
                            # draws the name in this row. A name wider than
                            # the row is condensed by the least aggressive
                            # tier (smallfont_vwf.condensed_tier); only a name
                            # no tier can fit is refused, never widened.
OUT = os.path.join(ROOT, 'build', 'items.asm')
# small-font page codes (NOT the dialogue font numbering: from 0xCD on the
# pages differ, and the battle page has HP/SP icons at 0xCD+): / : - exist
# in every page; . and ' are redrawn kana cells (smallfont_lc PUNCT);
# & ! ? exist only in the field page and are refused.
EXTRA = {' ': 0, '/': 0xCA, ':': 0xCB, '-': 0xCC}
G2C = {v: k for k, v in etext.char2g.items()}


def glyph(c):
    if 'A' <= c <= 'Z':
        return etext.char2g[chr(0xFF21 + ord(c) - 0x41)]
    if '0' <= c <= '9':
        return etext.char2g[chr(0xFF10 + ord(c) - 0x30)]
    if c in EXTRA:
        return EXTRA[c]
    return smallfont_char(c)       # a-z . '


def records():
    """[(pos, ja, psp)] every name field, in source order."""
    d = open(os.path.join(ROOT, 'data', 'psx', REL), 'rb').read()
    out = []
    r = FIRST - BASE
    for k in range(COUNT):
        if k < 163 and d[r - 4:r - 2] != b'\xff\x01':
            toolbelt.fail(f'{REL}:{r:#x}: item {k} record head mismatch')
        nm = d[r:r + FIELD]
        end = nm.index(b'\xff') if b'\xff' in nm else FIELD
        ja = ''.join(G2C.get(x, '<%02X>' % x) for x in nm[:end])
        out.append((r, ja, ''))
        r += STRIDE
    return out


def dump():
    rows, _man = toolbelt.dump_scaffold(
        REL, [(hex(off), psp) for off, _ja, psp in records()])
    print(f'items: {len(rows)} rows -> {toolbelt.gen_path(REL)}')


def encode(t):
    for c in t:
        try:
            glyph(c)
        except KeyError:
            toolbelt.fail(f'{t!r}: {c!r} is not in the small font')
    return bytes(glyph(c) for c in t)


def name_px(t):
    """Un-tightened drawn width of the full name (head + tail)."""
    import smallfont_vwf
    return smallfont_vwf.codes_px(encode(t))


def name_fit(t):
    """(tier, px) for the full name in the row's footprint.

    `tier` is None when even the condensed tier cannot fit the row; `px` is
    then the un-tightened width the porter reports."""
    import smallfont_vwf
    return smallfont_vwf.condensed_tier(encode(t), ROW_PX)


def build():
    p = Patch('items', OUT)
    cut = 0
    over = []
    # One table per real file (SLPS_005.00 holds every surface's rows);
    # a builder patches ONLY the positions its own scan produces - rows of
    # other surfaces belong to their builders and are never placed here.
    own = {off for off, _ja, _psp in records()}
    for r in toolbelt.merged_rows(REL):
        if int(r['pos'], 16) not in own:
            continue
        t = r['en'].strip()
        if not t:
            continue
        b = encode(t)
        if len(b) > MAXLEN:
            toolbelt.fail(f'items: {r["id"]} {t!r} is {len(b)} glyphs, max {MAXLEN}')
        tier, px = name_fit(t)
        if tier is None:
            over.append(f'{r["id"]} {t!r} {px}px')
            continue
        if len(b) > FIELD:
            b, cut = b[:FIELD], cut + 1       # physical head; name_tails owns the rest
        elif len(b) < FIELD:
            b += b'\xff' + bytes(FIELD - len(b) - 1)
        p.org(toolbelt.file_va(REL, int(r['pos'], 16)), b, f'{r["id"]} {t}')
    if over:
        toolbelt.fail(f'{len(over)} name(s) wider than the {ROW_PX}px row '
                      '(shorten the wording; the porter drafts it, the row '
                      'never grows):\n  ' + '\n  '.join(over))
    p.write()
    print(f'items: {p.n}/{COUNT} ({cut} heads continued in tail bank) -> {OUT}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build}[sys.argv[1] if sys.argv[1:] else 'build']()
