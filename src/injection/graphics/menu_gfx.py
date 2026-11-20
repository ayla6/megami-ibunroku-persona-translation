"""English bitmap labels of the ADV menus (ADV/ADVCMD.BIN): save/load slot screen and command labels.

  python tools/menu_gfx.py      write build/ADV/ADVCMD.BIN (same size, pixel data edited) and previews

Findings (2026-10-04, GPU dump of the save screen):
  * ADVCMD.BIN TIM 0x281D8 (4bpp 256x64, loaded to VRAM (768,416)) is the label atlas of 48x16 cells, drawn as 48x16
    sprites: u=96,v=48 "slot 1" (header of the slot screen), u=144,v=48 "slot 2", u=48,v=32 "execute",
    u=96,v=32 "settings". Its palette: indices 1..14 = light-to-dark orange ramp, 15 = black shadow.
  * ADVCMD.BIN TIM 0x38 (4bpp 256x256) is the 8x12 small-font page (loaded to VRAM (512,256) and (896,256));
    the tag after every slot row is three 8x12 sprites at u=224,232,240, v=168 ("data"). It is replaced by "DATA" drawn
    with a 5x7 pixel font on a 6 px pitch (24 px = the three cells), palette index 3 like the neighbouring labels.
The slot headers carry the same artwork as OPEN.BIN's SLOT buttons (tools/buttonlabel.py), so both screens show one
label. The remaining 48x16 cells use the dialogue VWF font (font/vwf_*.bin) like tools/name_gfx.py.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import buttonlabel  # noqa: E402
import tim  # noqa: E402
import smallfont_vwf  # noqa: E402
import strlib  # noqa: E402
import vwf_wrap  # noqa: E402

ROOT = tim.ROOT
PREVIEW = os.path.join(ROOT, 'build', 'previews', 'translation')
FONT = open(toolpath.font_path('font', 'large'), 'rb').read()
WIDTH = open(toolpath.font_path('width', 'large'), 'rb').read()

ATLAS = 0x281D8
PAGE = 0x38
# Labels with no English (the engine alone) are never drawn: their retail art stays.
SLOTS = {tuple(int(x) for x in k.split(',')): v for k, v in sorted(strlib.glossary('slot_button').items(), key=lambda kv: tuple(int(x) for x in kv[0].split(','))) if v}    # buttonlabel artwork, like OPEN.BIN's buttons
CELLS = {tuple(int(x) for x in k.split(',')): v for k, v in sorted(strlib.glossary('menu_cell').items(), key=lambda kv: tuple(int(x) for x in kv[0].split(','))) if v}    # dialogue VWF font
SLOT_TOP = 3                 # the label's ink rows 3..12 of the 16 px cell, like retail OPEN's buttons
RAMP = [13, 11, 12, 14, 8, 7, 9, 4, 10, 5, 6, 3, 2, 1]          # light -> dark (palette luminance)
OUTLINE = 15

# 5x7 glyphs for the "DATA" tag (small font cells are 8x12, orange index 3)
G57 = {
    'D': ['11110', '10001', '10001', '10001', '10001', '10001', '11110'],
    'A': ['01110', '10001', '10001', '11111', '10001', '10001', '10001'],
    'T': ['11111', '00100', '00100', '00100', '00100', '00100', '00100'],
}
# text, u, v of the first of the three 8x12 cells; None with no English
TAG = next(((text, u, v) for (u, v), text in {tuple(int(x) for x in k.split(',')): v for k, v in sorted(strlib.glossary('menu_tag').items(), key=lambda kv: tuple(int(x) for x in kv[0].split(','))) if v}.items()), None)
# Persona status page: the kanji labels 魔攻 / 魔防 are 3 bitmap cells each in the page (BG tiles 0x3CB.. / 0x3D1..,
# ADV 0x8006FA7C; same page, CLUT 0x683C). Redrawn as 4 letters of 5x7 at a 6 px pitch, colour 1 + shadow 2 like
# the kanji. Patched in every page copy whose cells still hold the kanji (label_rows / smallfont_pages.py).
G57.update({
    'M': ['10001', '11011', '10101', '10101', '10001', '10001', '10001'],
    'K': ['10001', '10010', '10100', '11000', '10100', '10010', '10001'],
    'E': ['11111', '10000', '10000', '11110', '10000', '10000', '11111'],
    'F': ['11111', '10000', '10000', '11110', '10000', '10000', '10000'],
    'H': ['10001', '10001', '10001', '11111', '10001', '10001', '10001'],
    'I': ['01110', '00100', '00100', '00100', '00100', '00100', '01110'],
    'V': ['10001', '10001', '10001', '10001', '10001', '01010', '00100'],
})
# equipment screen stat labels 攻撃 / 命中 / 防御 / 回避 are the 12 px kanji at row 156, u = 112, 136, 160, 184
LABELS_LAY = [(208, 156), (0, 168), (112, 156), (136, 156), (160, 156), (184, 156)]
# A label with no English (the engine alone, or an untranslated one) is never
# drawn: its retail art stays.
LABELS = [(text, u, v) for text, u, v in ((strlib.glossary('menu_gfx').get(f'{u},{v}', ''), u, v)
                                          for u, v in LABELS_LAY) if text]
LABEL_CELLS = 3                    # the retail label: three 8x12 cells
# The labels are drawn in the original small font: each letter is the page's
# own retail cell art (ink colour 1, shadow 2), cropped to its ink and packed
# with a 1-px gap, centred in the label's three cells. A label wider than
# its cells (MATK, MDEF) cannot grow into other page cells - the screens
# draw from page copies whose VRAM neighbours belong to other textures - so
# with the small-font kit every call that draws it writes the wording as a
# text row instead (the kit draws the original font), and its cells keep a 5x7 rendering for builds without the
# kit (build/stat_labels_<ovl>.asm, build/stat_label_strings.asm). The row
# starts at the retail cells and takes one more: left-aligned, its middle is
# within 2 px of the three-cell labels' (a centred field would centre on its
# own cells, not on the retail label's).
LABEL_Y0, LABEL_Y1 = 156, 180      # pixel rows holding the labels
PAGE_TILES = 32                    # BG tiles per page row (256 px / 8)
STAT_LABEL_OVERLAYS = ('ADV', 'DNG', 'S2D')


def text_pixels(s, adv=None):
    ink, x = set(), 0
    for i, c in enumerate(s):
        g = ord(c) - 0x20
        for r in range(16):
            bits = FONT[g * 16 + r]
            for b in range(8):
                if bits & (0x80 >> b):
                    ink.add((x + b, r))
        x += (adv or WIDTH)[i] if adv is not None else WIDTH[g]
    return ink, x - 1


def clear_cell(pix, w, u, v):
    for y in range(16):
        for x in range(48):
            pix[(v + y) * w + u + x] = 0


def draw_cell(pix, w, u, v, text, adv=None):
    clear_cell(pix, w, u, v)
    ink, tw = text_pixels(text, adv)
    ys = [y for _, y in ink]
    y0, y1 = min(ys), max(ys)
    h = y1 - y0 + 1
    ox, oy = u + (48 - tw) // 2, v + (16 - h) // 2
    body = {(x, y - y0): RAMP[(y - y0) * (len(RAMP) - 1) // max(h - 1, 1)] for x, y in ink}
    for (x, y), idx in body.items():
        pix[(oy + y) * w + ox + x] = idx
    for (x, y) in body:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                px, py = ox + x + dx, oy + y + dy
                if (x + dx, y + dy) not in body and u <= px < u + 48 and v <= py < v + 16 and pix[py * w + px] == 0:
                    pix[py * w + px] = OUTLINE
    return tw


def pack(pix):
    return bytes(pix[i] | (pix[i + 1] << 4) for i in range(0, len(pix), 2))


def unpack(d, t):
    raw = d[t['at']:t['at'] + t['w'] * 2 * t['h']]
    pix = bytearray()
    for b in raw:
        pix += bytes((b & 15, b >> 4))
    return pix


PAGE_COPIES = {'ADV/ADVCMD0.BIN': (0x240, 248), 'OPEN.BIN': (0x35AA0, 256)}   # other small-font pages: pixel offset, width
GLYPH_ROWS = smallfont_vwf.GLYPH_ROWS  # the page's whole glyph area (codes 0..214): the sheet replaces all of it
PROBE = 3 * 12                       # the kana rows every copy stores identically (proves the offset)


def tile0():
    import toolbelt
    return toolbelt.asm_equ('SF_PAGE_TILE0')


def tile_of(u, v):
    return tile0() + (v // 12) * PAGE_TILES + u // 8


def original_label(text):
    """{(x, y): colour} of `text` in the original small font, and its width
    (ink of every letter, 1-px gaps, the last letter's shadow column)."""
    import toolbelt
    retail, _pal, w = smallfont_vwf.disc_page()
    out, x = {}, 0
    for i, ch in enumerate(text):
        rows = smallfont_vwf.glyph_rows(retail, w, toolbelt.smallfont_char(ch))
        ink = [c for row in rows for c, colour in enumerate(row) if colour == 1]
        left, right = min(ink), max(ink)
        for y, row in enumerate(rows):
            for c in range(left, min(right + 2, len(row))):
                if row[c] and out.get((x + c - left, y), 0) != 1:
                    out[(x + c - left, y)] = row[c]
        x += right - left + 2
    return out, x


def label_cells(text):
    """The cells `text` takes in the original font (at least the retail 3)."""
    return max(LABEL_CELLS, -(-original_label(text)[1] // 8))


def text_labels():
    """[(text, retail first tile, cells)] of the labels drawn as text."""
    return [(text, tile_of(u, v), label_cells(text)) for text, u, v in LABELS
            if label_cells(text) > LABEL_CELLS]


def draw_labels(pix, w, y0=0):
    """Draw LABELS into 4bpp pixels of a page (w px wide) whose first row is page row y0."""
    for text, u, v in LABELS:
        for y in range(12):
            for x in range(24):
                pix[(v - y0 + y) * w + u + x] = 0
        if label_cells(text) > LABEL_CELLS:
            x0 = (24 - 6 * len(text) + 1) // 2
            main = {(x0 + 6 * i + b, 2 + r) for i, c in enumerate(text) for r, row in enumerate(G57[c])
                    for b, bit in enumerate(row) if bit == '1'}
            for x, y in main:
                pix[(v - y0 + y) * w + u + x] = 1
            for x, y in main:
                if (x + 1, y + 1) not in main and x + 1 < 24:
                    pix[(v - y0 + y + 1) * w + u + x + 1] = 2
            continue
        art, width = original_label(text)
        x0 = (24 - width) // 2
        for y in range(12):
            for x in range(24):
                if art.get((x - x0, y)):
                    pix[(v - y0 + y) * w + u + x] = art[(x - x0, y)]


TEXT_SLOT = 8                      # bytes per string: codes, 0xFF, padding, cell count last


def stat_label_strings():
    """The text labels' rows: glyph codes, 0xFF, the cell count in the last byte."""
    import toolbelt
    out = []
    for text, _tile, n in text_labels():
        codes = [toolbelt.smallfont_char(ch) for ch in text] + [0xFF]
        if len(codes) > TEXT_SLOT - 1:
            raise SystemExit(f'menu_gfx: the stat label {text!r} outgrows its {TEXT_SLOT}-byte slot')
        out.append(bytes(codes + [0xFF] * (TEXT_SLOT - 1 - len(codes)) + [n]))
    return out


def stat_label_sites():
    """{overlay: [asm lines]}: every retail call that draws a text label -
    lui a1 / ori a1,lo / ori a2,zero,base / jal / ori a3,zero,3 - calls
    stat_label_text_<ovl> with the label's index in a2."""
    import struct
    out = {}
    index = {tile: (i, n) for i, (_text, tile, n) in enumerate(text_labels())}
    # every retail label call names its writer, drawn as text or not: the
    # writer is found from all of them, and only the text labels' calls move
    retail = {tile_of(u, v) for u, v in LABELS_LAY}
    for ovl in STAT_LABEL_OVERLAYS:
        d = open(os.path.join(ROOT, 'data', 'psx', ovl + '.BIN'), 'rb').read()
        words = struct.unpack_from(f'<{len(d) // 4}I', d)
        base = 0x800643C4
        lines = [';; generated by tools/menu_gfx.py - stat labels drawn as text rows', '.if SF_VWF']
        writers = set()
        for i in range(1, len(words) - 2):
            word = words[i + 1]
            if word >> 16 != 0x3406 or word & 0xFFFF not in retail:
                continue
            if words[i] >> 16 != 0x34A5 or words[i - 1] >> 16 != 0x3C05 or \
                    words[i + 2] >> 26 != 3 or words[i + 3] != 0x34070000 | LABEL_CELLS:
                raise SystemExit(f'menu_gfx: {ovl} {base + 4 * i + 4:#x}: a label call of another shape')
            writers.add(0x80000000 | (words[i + 2] & 0x03FFFFFF) << 2)
            if word & 0xFFFF not in index:
                continue
            k, _n = index[word & 0xFFFF]
            lines += [f'.org {base + 4 * i + 4:#x}', f'    ori     a2, zero, {k}',
                      f'.org {base + 4 * i + 8:#x}', f'    jal     stat_label_text_{ovl.lower()}']
        if len(writers) != 1:
            raise SystemExit(f'menu_gfx: {ovl}: the label calls reach {len(writers)} row writers')
        # the overlay's own TileMapWriteRow, the one its label calls reach
        lines.append(f'.definelabel stat_label_writer_{ovl.lower()}, {writers.pop():#x}')
        lines.append('.endif')
        out[ovl] = lines
    return out


def write_stat_label_sites():
    for ovl, lines in stat_label_sites().items():
        with open(os.path.join(ROOT, 'build', f'stat_labels_{ovl.lower()}.asm'), 'w', newline=chr(10)) as o:
            o.write(chr(10).join(lines) + chr(10))
    with open(os.path.join(ROOT, 'build', 'stat_label_strings.asm'), 'w', newline=chr(10)) as o:
        o.write(';; generated by tools/menu_gfx.py - the text stat labels (terms.tsv, menu_gfx)' + chr(10))
        for row in stat_label_strings():
            o.write('    .byte ' + ', '.join(f'0x{x:02X}' for x in row) + chr(10))


def label_rows(b, at, bpr, ref):
    """Patch the label cells of a page copy (bytearray b, page row 0 at offset at, bpr bytes per row) in place,
    if those cells hold the same kanji as the reference page bytes `ref` (128 bytes per row). -> True if patched."""
    for text, u, v in LABELS:
        for y in range(12):
            r = (v + y)
            if b[at + r * bpr + u // 2:at + r * bpr + (u + 24) // 2] != ref[r * 128 + u // 2:r * 128 + (u + 24) // 2]:
                return False
    w = bpr * 2
    y0, y1 = LABEL_Y0, LABEL_Y1
    raw = bytes(b[at + y0 * bpr:at + y1 * bpr])
    pix = bytearray()
    for x in raw:
        pix += bytes((x & 15, x >> 4))
    draw_labels(pix, w, y0)
    b[at + y0 * bpr:at + y1 * bpr] = pack(pix)
    return True


def other_pages():
    src = open(tim.locate('ADV/ADVCMD.BIN'), 'rb').read()
    t = tim.parse(src, PAGE)
    page = src[t['at']:t['at'] + 128 * 256]
    ref = smallfont_vwf.unpack_page(page)
    pix = smallfont_vwf.page_indices()[0]           # the shipped page (the sheet)
    for name, (at, w) in PAGE_COPIES.items():
        bpr = w // 2
        d = bytearray(open(os.path.join(ROOT, 'data', 'psx', name), 'rb').read())
        for y in range(PROBE):
            assert d[at + y * bpr:at + y * bpr + bpr] == page[y * 128:y * 128 + bpr], f'{name}: glyph row {y} differs'
        old = bytes(d[at:at + bpr * GLYPH_ROWS])
        new = smallfont_vwf.page_copy(smallfont_vwf.unpack_page(old), ref, pix, w, GLYPH_ROWS)
        if name == 'OPEN.BIN':                       # armips owns build/OPEN.BIN: emit a patch for main.asm
            with open(os.path.join(ROOT, 'build', 'open_smallfont.asm'), 'w', newline=chr(10)) as o:
                o.write(';; generated by tools/menu_gfx.py - the small-font page (the sheet) in OPEN.BIN' + chr(10))
                i = 0
                while i < len(old):
                    if new[i] != old[i]:
                        j = i
                        while j < len(old) and new[j] != old[j]:
                            j += 1
                        o.write(f'.org OPEN_ADDR + {at + i:#x}' + chr(10) + '    .byte ' +
                                ', '.join(f'0x{x:02X}' for x in new[i:j]) + chr(10))
                        i = j
                    else:
                        i += 1
        else:
            d[at:at + bpr * GLYPH_ROWS] = new
            label_rows(d, at, bpr, page)
            open(os.path.join(ROOT, 'build', name), 'wb').write(bytes(d))


def main():
    from PIL import Image
    src = open(tim.locate('ADV/ADVCMD.BIN'), 'rb').read()
    out = bytearray(src)
    # label atlas
    t = tim.parse(src, ATLAS)
    w = t['px_w']
    pix = unpack(src, t)
    for (u, v), s in SLOTS.items():
        assert buttonlabel.width(s) + 1 <= 48, f'{s} is wider than its 48px cell'   # ink + shadow
        clear_cell(pix, w, u, v)
        buttonlabel.draw(pix, w, u + (48 - buttonlabel.width(s)) // 2, v + SLOT_TOP, s)
    for (u, v), s in CELLS.items():
        adv, _gap = vwf_wrap.fit_advances(FONT, s, 46)   # 48px cell, 1px margins
        tw = draw_cell(pix, w, u, v, s, adv)
    out[t['at']:t['at'] + t['w'] * 2 * t['h']] = pack(pix)
    pal = tim.palette(src, t)
    im = Image.frombytes('P', (w, t['h']), bytes(pix))
    im.putpalette([c for rgb in pal for c in rgb] + [0] * (768 - 3 * len(pal)))
    im.convert('RGB').resize((w * 3, t['h'] * 3), Image.NEAREST).save(os.path.join(PREVIEW, 'advcmd_atlas_preview.png'))
    # Retail UI page with authored glyph rows, then DATA + MATK/MDEF labels.
    t2 = tim.parse(src, PAGE)
    w2 = t2['px_w']
    pg = bytearray(smallfont_vwf.page_indices()[0])
    text, u, v = TAG or ('', 0, 0)
    for y in range(12 if TAG else 0):
        for x in range(24):
            pg[(v + y) * w2 + u + x] = 0
    for i, c in enumerate(text):
        for r, row in enumerate(G57[c]):
            for b, bit in enumerate(row):
                if bit == '1':
                    pg[(v + 2 + r) * w2 + u + 6 * i + b] = 3
    draw_labels(pg, w2)                             # the status / equipment stat labels
    write_stat_label_sites()
    out[t2['at']:t2['at'] + t2['w'] * 2 * t2['h']] = pack(pg)
    os.makedirs(os.path.join(ROOT, 'build', 'ADV'), exist_ok=True)
    open(os.path.join(ROOT, 'build', 'ADV', 'ADVCMD.BIN'), 'wb').write(bytes(out))
    other_pages()
    print('menu gfx:', ', '.join(f'{s}={buttonlabel.width(s)}px' for s in SLOTS.values()), '+',
          ', '.join(f'{s}={text_pixels(s)[1]}px' for s in CELLS.values()), '+ DATA tag; ADVCMD.BIN',
          len(out), 'bytes')


if __name__ == '__main__':
    main()
