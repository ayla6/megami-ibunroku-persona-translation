"""The SLOT 1 / SLOT 2 button label, drawn once for every atlas that carries it.

OPEN.BIN TIM 0x474C0 (4bpp 256x32, VRAM 704,256) is the retail label atlas: row 0
holds "OK? YES NO LOAD CONTINUE", row 1 the kana labels the buttons replace. The
English label is composed from the letters of that same atlas (S from "YES", L
from "LOAD", O from "OK?", T from "CONTINUE", the digits from the kana row),
painted with the retail per-row gradient and shadowed the way retail draws it:
the label in black, one pixel right and one pixel down.

The retail cells store that shadow as palette index 15 next to the ink, so a
cell's ink is indices 1..14 only; index 15 is the shadow, never a letter. The
label is therefore cut from ink alone and the shadow is derived from the
finished label.

OPEN.BIN's atlas and ADV/ADVCMD.BIN's label atlas (0x281D8) carry the identical
15-colour ramp, so the same pixel indices render the same label in both. Each
writer makes index 15 opaque black (0x8000): index zero stays transparent.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tim  # noqa: E402

ATLAS = 0x474C0
INK = range(1, 15)                 # glyph colours; 0 is transparent, 15 the shadow
SHADOW = 15
SPACE = 4                          # px a space advances
GAP = 1                            # px between two letters
KANA_ROWS = (19, 29)               # the kana row's ink rows, the label's gradient
# retail cells of the letters the label is composed from: letter -> (x0, x1, y0, y1)
SOURCE = {
    'O': (11, 16, 3, 13),          # "OK?"
    'S': (78, 83, 3, 13),          # "YES"
    'L': (153, 158, 3, 13),        # "LOAD"
    'T': (211, 216, 3, 13),        # "CONTINUE"
    '1': (40, 43, 19, 29),         # kana row
    '2': (86, 92, 19, 29),         # kana row
}
_cache = {}


def _trim(mask):
    """Cut a mask to its ink extent."""
    ys = [y for y, row in enumerate(mask) if any(row)]
    xs = [x for x in range(len(mask[0])) if any(row[x] for row in mask)]
    return [[mask[y][x] for x in range(min(xs), max(xs) + 1)] for y in range(min(ys), max(ys) + 1)]


def _atlas():
    """-> ({letter: ink mask}, per-row ink colour). Read once per process."""
    if 'glyphs' not in _cache:
        d = open(tim.locate('OPEN.BIN'), 'rb').read()
        t = tim.parse(d, ATLAS)
        w = t['px_w']
        pix = []
        for b in d[t['at']:t['at'] + t['w'] * 2 * t['h']]:
            pix += [b & 15, b >> 4]
        ramp = []
        for y in range(*KANA_ROWS):
            vals = [pix[y * w + x] for x in range(w) if pix[y * w + x] in INK]
            ramp.append(collections.Counter(vals).most_common(1)[0][0])
        glyphs = {c: _trim([[pix[y * w + x] in INK for x in range(x0, x1 + 1)]
                            for y in range(y0, y1 + 1)])
                  for c, (x0, x1, y0, y1) in SOURCE.items()}
        _cache['glyphs'], _cache['ramp'] = glyphs, ramp
    return _cache['glyphs'], _cache['ramp']


def width(text):
    """Pixel width of the label's ink."""
    glyphs = _atlas()[0]
    x = 0
    for c in text:
        x += SPACE if c == ' ' else len(glyphs[c][0]) + GAP
    return x - GAP


def draw(pix, w, x0, y0, text):
    """Draw `text` into a w-wide 4bpp page, ink starting at (x0, y0). -> the column one past the ink"""
    glyphs, ramp = _atlas()
    ink = {}
    x = x0
    for c in text:
        if c == ' ':
            x += SPACE
            continue
        g = glyphs[c]
        for r, row in enumerate(g):
            for k, on in enumerate(row):
                if on:
                    ink[(x + k, y0 + r)] = ramp[r]
        x += len(g[0]) + GAP
    for (px, py), idx in ink.items():
        pix[py * w + px] = idx
    for px, py in ink:                        # the shadow: the label in black, one pixel down-right
        if pix[(py + 1) * w + px + 1] == 0:
            pix[(py + 1) * w + px + 1] = SHADOW
    return x - GAP
