"""Ending epilogue pages (EXE/END.BIN): the 1-bit 320x240 text pages shown after the movies.

  python tools/endtext.py      writes build/EXE/END.BIN (+ previews in build/previews/endtext/)

END.BIN is a stream of TIMs: 16bpp backgrounds / portraits and 4bpp text pages (CLUT index 0 = white ink, 1 = black).
The credits roll pages (English job titles, staff names in kanji) are redrawn from the PSP-US roll's original-staff
screens where it has them (layout 'n', credits_layout: title, names indented below). For each epilogue page the
Japanese ink is located, the page is cleared and the English text is drawn with the project's VWF font
(font/vwf_font.bin, 1-bit, proportional): centred pages stay centred on the old text, profile pages keep the left edge /
column width of the old paragraph (the portrait is on the other half of the screen).
The file keeps its size, so build_disc.py writes it in place.
"""
import csv
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import toolbelt  # noqa: E402
import tim  # noqa: E402
import vwf_wrap  # noqa: E402

ROOT = tim.ROOT
FONT = open(os.path.join(ROOT, 'src', 'asm', 'font', 'vwf_font.bin'), 'rb').read()
WIDTH = open(os.path.join(ROOT, 'src', 'asm', 'font', 'vwf_width.bin'), 'rb').read()
END_SIZE = 5058560
PITCH = 12

PAGE_MAP = os.path.join(toolbelt.SOURCE_MAPPINGS, 'endtext_map.tsv')


def load_pages():
    """Render specs: each page's text plus the page map's layout. The text
    is cut from the transcription of the PSP-US ending images
    (translation/manual/ending/ENDALL.tsv) by the page map (endtext_map.tsv:
    first_line/end_line of an image; several rows for one page join in
    order). A page the PSP lacks (a map row with no image) takes its text from
    translation/manual/ending/pages.tsv; filled text there also replaces a
    PSP page. Literal \\n = line breaks. A page without text keeps its
    Japanese picture."""
    import strlib
    NLIT = chr(92) + 'n'
    man = os.path.join(ROOT, 'translation', 'manual', 'ending')
    image = {r['offset']: r['text'].split(NLIT)
             for r in strlib.tsv_rows(os.path.join(man, 'ENDALL.tsv'),
                                      required=('entry', 'offset', 'text'))}
    texts = {}
    with open(PAGE_MAP, encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            src = row['entry_offset']
            if not src:
                continue
            if src not in image:
                toolbelt.fail(f'endtext: image {src} is not in manual/ending/ENDALL.tsv')
            cut = image[src][int(row['first_line']):int(row['end_line'])]
            if not cut:
                toolbelt.fail(f'endtext: image {src}: empty slice '
                              f"{row['first_line']}:{row['end_line']}")
            texts.setdefault(hex(int(row['ps1_tim_offset'], 16)), []).extend(cut)
    pages_tsv = os.path.join(man, 'pages.tsv')
    if os.path.exists(pages_tsv):
        for r in strlib.tsv_rows(pages_tsv, required=('page', 'text')):
            if (r.get('text') or '').strip():
                texts[r['page'].lower()] = r['text'].strip().split(NLIT)
    pages = {}
    with open(PAGE_MAP, encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            lines = texts.get(hex(int(row['ps1_tim_offset'], 16)))
            if not lines:
                continue          # untranslated page: JA art ships as-is
            if row['layout'] == 'p':
                pages[int(row['ps1_tim_offset'], 16)] = ('p', lines[0], ' '.join(lines[1:]))
            elif row['layout'] == 'c':
                pages[int(row['ps1_tim_offset'], 16)] = ('c', lines)
            elif row['layout'] == 'n':
                pages[int(row['ps1_tim_offset'], 16)] = ('n', lines)
            else:
                raise ValueError(f"unknown layout {row['layout']!r}")
    return pages


def text_width(s):
    return sum(WIDTH[ord(c) - 0x20] for c in s) - 1 if s else 0


def wrap(text, width):
    """Reflow one run of credits text into its column. Same flow engine as
    every textbox (vwf_wrap.flow_lines), measured at this font's metrics:
    the page/line slicing in endtext_map.tsv is deliberate and never touched,
    only a run wider than its column wraps (tail 0: this art has no pen-240
    room)."""
    return vwf_wrap.wrap_line(' '.join(text.split()), width, text_width,
                              tail=0)


def put(pix, w, x, y, s, ink=0):
    for c in s:
        g = ord(c) - 0x20
        for r in range(16):
            bits = FONT[g * 16 + r]
            for b in range(8):
                if bits & (0x80 >> b) and 0 <= y + r < 240 and 0 <= x + b < w:
                    pix[(y + r) * w + x + b] = ink
        x += WIDTH[g]


def bbox(pix, w, h):
    rows = [y for y in range(h) if 0 in pix[y * w:(y + 1) * w]]
    cols = [x for x in range(w) if any(pix[y * w + x] == 0 for y in rows)]
    return rows, cols


TITLE_MARK = '■'     # the PSP credits' job-title marker (drawn as a square)
NAME_INDENT = 12     # a name line sits under its title, indented
BLOCK_GAP = 8        # extra space before each job title after the first
CREDIT_PITCH = 18    # the credits roll's line pitch: 16-row cells, two rows between
GLYPH_ROWS = 16      # rows a glyph cell occupies (put draws 16)


def credits_layout(pix, w, h, lines):
    """A credits page, laid out the way the PSP-US roll lays it out: each job
    title (its line carries the PSP's marker) with its names indented below,
    every word the PSP's. The block starts where the page's old ink did, so
    the page keeps its place in the roll; a block taller than the room below
    that point moves up just enough to fit. Returns [(x, y, text)] and
    [(x, y)] marker squares; raises ValueError when it cannot fit at all."""
    rows, cols = bbox(pix, w, h)
    left = cols[0]
    titles = sum(1 for s in lines if s.startswith(TITLE_MARK))
    height = (len(lines) - 1) * CREDIT_PITCH + max(titles - 1, 0) * BLOCK_GAP + GLYPH_ROWS
    if height > h:
        raise ValueError(f'{len(lines)} credit lines need {height}px')
    top = min(rows[0], h - height)
    out, marks, y = [], [], top
    for i, s in enumerate(lines):
        if s.startswith(TITLE_MARK):
            if i:
                y += BLOCK_GAP
            text = s[len(TITLE_MARK):].strip()
            marks.append((left, y + 6))
            out.append((left + 8, y, text))
        else:
            out.append((left + NAME_INDENT, y, s))
        y += CREDIT_PITCH
    for x, yy, s in out:
        if x + text_width(s) > w or yy + GLYPH_ROWS > h:
            raise ValueError(f'{s!r} leaves the page')
    return out, marks


def layout(pix, w, h, spec):
    rows, cols = bbox(pix, w, h)
    top, left, right = rows[0], cols[0], cols[-1]
    out = []                               # (x, y, text)
    if spec[0] == 'c':
        cx = (left + right) // 2
        lines = []
        for segment in spec[1]:
            lines.extend(wrap(segment, right - left + 1))
        for i, s in enumerate(lines):
            out.append((cx - text_width(s) // 2, top + i * 14, s))
        return out
    _, head, body = spec
    gap = next(y for y in rows[1:] if y > rows[0] + 1 and (y - 1) not in rows)   # first empty row after the name
    body_top = next(y for y in rows if y > gap)
    col_w = right - left + 1
    out.append((left, top, head))
    lines = wrap(body, col_w)
    pitch = PITCH if body_top + len(lines) * PITCH <= 236 else 11
    for i, s in enumerate(lines):
        out.append((left, body_top + i * pitch, s))
    return out


def main():
    from PIL import Image
    pages = load_pages()
    source = os.path.join(ROOT, 'data', 'psx', 'EXE', 'END.BIN')
    d = bytearray(open(source, 'rb').read())
    assert len(d) == END_SIZE, (source, len(d))
    prev = os.path.join(ROOT, 'build', 'previews', 'endtext')
    os.makedirs(prev, exist_ok=True)
    for off, spec in pages.items():
        t = tim.parse(d, off)
        assert t['bpp'] == 4 and t['px_w'] == 320 and t['h'] == 240, hex(off)
        w, h = 320, 240
        raw = d[t['at']:t['at'] + t['w'] * 2 * h]
        pix = bytearray()
        for b in raw:
            pix += bytes((b & 15, b >> 4))
        marks = []
        if spec[0] == 'n':
            try:
                items, marks = credits_layout(pix, w, h, spec[1])
            except ValueError as ex:
                toolbelt.fail(f'endtext: credits page {off:#x}: {ex}')
        else:
            items = layout(pix, w, h, spec)
        for i in range(len(pix)):
            pix[i] = 1
        for mx, my in marks:              # the title marker: a 4x4 square
            for yy in range(my - 2, my + 2):
                for xx in range(mx, mx + 4):
                    pix[yy * w + xx] = 0
        for x, y, s in items:
            assert text_width(s) + x <= w and x >= 0, (hex(off), s)
            put(pix, w, x, y, s)
        last = max(y for _, y, _ in items) + 12
        assert last <= 240, (hex(off), last)
        packed = bytes(pix[i] | (pix[i + 1] << 4) for i in range(0, len(pix), 2))
        d[t['at']:t['at'] + len(packed)] = packed
        im = Image.frombytes('P', (w, h), bytes(pix))
        im.putpalette([255, 255, 255, 0, 0, 0] + [0] * 762)
        im.save(os.path.join(prev, f'end_{off:X}.png'))
        print(f'{off:#x}: {len(items)} lines, bottom y {last}')
    os.makedirs(os.path.join(ROOT, 'build', 'EXE'), exist_ok=True)
    open(os.path.join(ROOT, 'build', 'EXE', 'END.BIN'), 'wb').write(bytes(d))


if __name__ == '__main__':
    main()
