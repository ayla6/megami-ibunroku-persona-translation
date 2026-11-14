"""The dialogue VWF compositor, in Python: a table line as the game draws it.

  render_line(text, measure) -> Line

The model is vwf/vwf_dialog.asm + vwf/vwf_dialog_draw.asm, step for step:
- the pen starts at 0 on each line; an English character (ASCII and the
  font's extras, make_vwf_font.EXTRA_CODE) draws its 8x16 cell from
  vwf_font.bin and advances by vwf_width.bin; any other character draws its
  16x16 FONT.BIN glyph (font_map.tsv) and advances 16;
- a glyph that would end past DLG_BOX_WIDTH_PX (240) when the pen is not at
  the line start is handed back and the ENGINE wraps the line there - the
  layout never asked for that break, so it is reported (`engine_wraps`);
- every ink pixel is ORed in as ink, and its shadow at (+DLG_SHADOW_DX, +1)
  for rows 0-14 only, both clipped at 240 (vwf_dialog_plot);
- a control code prints nothing, except an insert: the codes the measure
  prices (a name, a demon, an item) take that many pixels at the pen, drawn
  here as a hatched block because the text they print is only known in game.

Pixels are bit planes, not colours: 1 = ink, 2 = shadow, 3 = both. Each
overlay picks its own CLUT indices for them (ADV 2/1, BTLP and S2D/DNG 1/2,
vwf_dialog_cfg.asm); BTLP's index 3 is the ink colour, so ink always wins an
overlap. 4 marks an insert's block.
"""
import os
import re

import etext
import make_vwf_font
import vwf_wrap

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FONT_DIR = os.path.join(ROOT, 'src', 'asm', 'font')
ORIG_FONT = os.path.join(ROOT, 'data', 'psx', 'FONT.BIN')
BOX_PX = 240            # DLG_BOX_COLS * 16
SHADOW_DX = 1           # DLG_SHADOW_DX: 1 px everywhere
INK, SHADOW, INSERT = 1, 2, 4
TOKEN = re.compile(r'<FFFD>.|<FF(?:07|08|0F)>(?:あ|<[0-9A-F]{2}>)?|<[^>]+>')

_fonts = {'stamp': None}


def fonts():
    """(vwf rows, vwf advances, FONT.BIN) - re-read when a file changes."""
    paths = [os.path.join(FONT_DIR, 'vwf_font.bin'),
             os.path.join(FONT_DIR, 'vwf_width.bin'), ORIG_FONT]
    stamp = tuple(os.stat(p).st_mtime_ns if os.path.exists(p) else 0 for p in paths)
    if _fonts['stamp'] != stamp:
        data = [open(p, 'rb').read() if os.path.exists(p) else b'' for p in paths]
        _fonts.update(stamp=stamp, data=data)
    return _fonts['data']


def glyph(ch):
    """(rows, width, advance, missing) of one printed character: rows are
    ints with the leftmost pixel in the top bit of a `width`-bit row."""
    vwf, adv, orig = fonts()
    ch = make_vwf_font.spell(ch)
    o = ord(ch)
    if 0x20 <= o <= 0x7E or ch in make_vwf_font.EXTRA_CODE:
        k = (o if 0x20 <= o <= 0x7E else make_vwf_font.EXTRA_CODE[ch]) - 0x20
        if k * 16 + 16 <= len(vwf) and k < len(adv):
            return list(vwf[k * 16:k * 16 + 16]), 8, adv[k], False
    g = etext.char2g.get(ch)
    if g is not None and g * 32 + 32 <= len(orig):
        rows = [orig[g * 32 + r * 2] << 8 | orig[g * 32 + r * 2 + 1] for r in range(16)]
        return rows, 16, 16, False
    return [0] * 16, 16, 16, True


class Line:
    """One physical line the engine draws: its 240x16 bit planes, the text
    that went into it, and where the pen ended."""
    def __init__(self):
        self.px = [[0] * BOX_PX for _ in range(16)]
        self.text = ''
        self.pen = 0

    def plot(self, x, y, bit):
        if 0 <= x < BOX_PX and 0 <= y < 16:
            self.px[y][x] |= bit


def render_line(text, measure=vwf_wrap.text_width):
    """[Line] for one stored line: one Line, or more when the engine wraps
    a glyph that does not fit. `measure` prices the insert codes."""
    out = [Line()]
    missing = []
    at = 0
    pieces = []
    for m in TOKEN.finditer(text):
        pieces += [('c', ch) for ch in text[at:m.start()]]
        pieces.append(('t', m.group(0)))
        at = m.end()
    pieces += [('c', ch) for ch in text[at:]]
    for kind, val in pieces:
        line = out[-1]
        if kind == 't':
            w = measure(val)
            if w <= 0:
                continue
            if line.pen and line.pen + w > BOX_PX:
                line = Line()
                out.append(line)
            for x in range(line.pen, line.pen + w):
                for y in range(16):
                    if (x + y) % 4 == 0:
                        line.plot(x, y, INSERT)
            line.text += val
            line.pen += w
            continue
        rows, width, adv, lost = glyph(val)
        if lost:
            missing.append(val)
        if line.pen and line.pen + adv > BOX_PX:
            line = Line()
            out.append(line)
        top = 1 << (width - 1)
        for y, bits in enumerate(rows):
            for b in range(width):
                if bits & (top >> b):
                    line.plot(line.pen + b, y, INK)
                    if y < 15:
                        line.plot(line.pen + b + SHADOW_DX, y + 1, SHADOW)
        line.text += val
        line.pen += adv
    return out, missing
