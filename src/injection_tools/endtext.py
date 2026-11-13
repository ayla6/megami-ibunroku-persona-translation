"""Ending epilogue pages (EXE/END.BIN): the 1-bit 320x240 text pages shown after the movies.

  python tools/endtext.py      writes build/EXE/END.BIN (+ previews in build/previews/endtext/)

END.BIN is a stream of TIMs: 16bpp backgrounds / portraits and 4bpp text pages (CLUT index 0 = white ink, 1 = black).
The staff roll's pages (Japanese job titles, staff names in kanji) are redrawn from the PSP-US roll's original-staff
screens where it has them (layout 'n', credits_layout: the retail roll's two columns, job titles right-aligned,
names beside them). For every page the Japanese ink is located, the page is cleared to its own background and the
English text is drawn in its brightest colour with the project's VWF font
(font/vwf_font.bin, 1-bit, proportional): centred pages stay centred on the old text, profile pages keep the left edge /
column width of the old paragraph (the portrait is on the other half of the screen).
The file keeps its size, so build_disc.py writes it in place.
"""
import csv
import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import toolbelt  # noqa: E402
import tim  # noqa: E402
import vwf_wrap  # noqa: E402

ROOT = tim.ROOT
FONT = open(os.path.join(ROOT, 'src', 'asm', 'font', 'vwf_font.bin'), 'rb').read()
WIDTH = open(os.path.join(ROOT, 'src', 'asm', 'font', 'vwf_width.bin'), 'rb').read()
END_SIZE = 5058560
INK_ROWS = 15       # rows the font's ink spans: caps from row 0, descenders to row 14
MIN_PITCH = 11      # a profile paragraph never packs tighter than this
# A page is 240 rows, but the display crops its edges (NTSC overscan, and
# DuckStation's default crop): in game a line ending at row 239 is cut off and
# one ending at row 226 shows whole. Text stays inside rows 8..227.
SCREEN_TOP = 8
SCREEN_BOTTOM = 228

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
            elif row['layout'] in ('n', 'l'):
                pages[int(row['ps1_tim_offset'], 16)] = (row['layout'], lines)
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


TITLE_MARK = '■'     # the PSP credits' job-title marker: decoration, never drawn
GLYPH_ROWS = 16      # rows a glyph cell occupies (put draws 16)
# The staff roll keeps the retail roll's composition: job titles right-aligned
# in a left column, names left-aligned in a right column, a title's first name
# on its own row and further names stacked under it. The columns are the same
# on every page, so the roll does not jump as its pages fade over each other.
CREDIT_TITLE_LEFT = 8      # a title (wrapped if it must) stays inside 8..176
CREDIT_TITLE_RIGHT = 176
CREDIT_NAME_LEFT = 188     # names run from here; the widest (124 px) ends by 312
CREDIT_NAME_RIGHT = 312
CREDIT_PITCH = 20          # rows between lines of one block
CREDIT_BLOCK_GAP = 10      # extra rows between blocks: 30 per single-name
                           # block, the retail roll's step
CREDIT_WIDE_GAP = 24       # between the two name columns of a block too
                           # tall to stack (the Debug page)


def credit_blocks(lines):
    """[(title, names)] of one credits page: a line carrying the PSP's
    title marker opens a block, the lines under it are its names."""
    blocks = []
    for s in lines:
        if s.startswith(TITLE_MARK):
            title = s[len(TITLE_MARK):].strip()
            blocks.append((title, []))
        elif blocks:
            blocks[-1][1].append(s)
        else:
            blocks.append(('', [s]))
    return blocks


def credits_layout(pix, w, h, lines):
    """A credits page in the roll's two columns, every word the source's. The
    block starts where the page's old ink did, so the page keeps its place in
    the roll; a block taller than the room below that point moves up just
    enough. A title with no names under it is a heading, centred on the
    page. When the page cannot fit the visible rows that way, its blocks with
    the most names (the retail Debug page's shape) put the title centred and
    the names in two columns under it, read across, until it fits. Returns
    [(x, y, text)]; raises ValueError when it cannot fit."""
    rows, _cols = bbox(pix, w, h)
    blocks = credit_blocks(lines)
    wide = [False] * len(blocks)

    def titles_of(k):
        # a heading or a wide block's title is centred on the page; any
        # other title wraps inside its column
        title, names = blocks[k]
        if not title:
            return []
        width = (w - 2 * CREDIT_TITLE_LEFT if not names or wide[k]
                 else CREDIT_TITLE_RIGHT - CREDIT_TITLE_LEFT)
        return wrap(title, width)

    def rows_of(k):
        titles, names = titles_of(k), blocks[k][1]
        if not names:
            return len(titles)
        if wide[k]:
            return len(titles) + (len(names) + 1) // 2
        return max(len(titles), len(names))

    def height():
        return (sum(rows_of(k) for k in range(len(blocks))) * CREDIT_PITCH
                + (len(blocks) - 1) * CREDIT_BLOCK_GAP - (CREDIT_PITCH - GLYPH_ROWS))

    order = sorted(range(len(blocks)), key=lambda k: -len(blocks[k][1]))
    for k in order:
        if height() <= SCREEN_BOTTOM - SCREEN_TOP or len(blocks[k][1]) < 2:
            break
        wide[k] = True
    if height() > SCREEN_BOTTOM - SCREEN_TOP:
        raise ValueError(f'{len(lines)} credit lines need {height()}px')
    y = max(SCREEN_TOP, min(rows[0], SCREEN_BOTTOM - height()))
    out = []
    for k, (_title, names) in enumerate(blocks):
        titles = titles_of(k)
        if not names or wide[k]:
            for i, s in enumerate(titles):
                out.append(((w - text_width(s)) // 2, y + i * CREDIT_PITCH, s))
            if names:
                left, right = names[0::2], names[1::2]
                lw = max(text_width(s) for s in left)
                rw = max((text_width(s) for s in right), default=0)
                x0 = (w - (lw + CREDIT_WIDE_GAP + rw)) // 2
                x1 = x0 + lw + CREDIT_WIDE_GAP
                if x0 < CREDIT_TITLE_LEFT or x1 + rw > CREDIT_NAME_RIGHT:
                    raise ValueError(f'{titles!r}: two name columns do not fit')
                top = y + len(titles) * CREDIT_PITCH
                for i, s in enumerate(names):
                    out.append((x0 if i % 2 == 0 else x1, top + (i // 2) * CREDIT_PITCH, s))
        else:
            for i, s in enumerate(titles):
                x = CREDIT_TITLE_RIGHT - text_width(s)
                if x < CREDIT_TITLE_LEFT:
                    raise ValueError(f'{s!r} is wider than the title column')
                out.append((x, y + i * CREDIT_PITCH, s))
            for i, s in enumerate(names):
                if CREDIT_NAME_LEFT + text_width(s) > CREDIT_NAME_RIGHT:
                    raise ValueError(f'{s!r} is wider than the name column')
                out.append((CREDIT_NAME_LEFT, y + i * CREDIT_PITCH, s))
        y += rows_of(k) * CREDIT_PITCH + CREDIT_BLOCK_GAP
    return out


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
    lines = wrap(body, col_w)
    # The paragraph takes the largest pitch up to INK_ROWS + 1 (lines that
    # never touch) that fits the page; the name and paragraph move up
    # together, keeping their gap, before the pitch shrinks below that.
    lead = body_top - top
    room = SCREEN_BOTTOM - min(top, SCREEN_TOP)
    for pitch in range(INK_ROWS + 1, MIN_PITCH - 1, -1):
        height = lead + (len(lines) - 1) * pitch + INK_ROWS
        if height <= room:
            break
    else:
        raise ValueError(f'{len(lines)} profile lines do not fit')
    top = min(top, SCREEN_BOTTOM - height)
    out.append((left, top, head))
    for i, s in enumerate(lines):
        out.append((left, top + lead + i * pitch, s))
    return out


# Pages the retail roll does not have (the PSP-US U.S. localization staff) are
# appended to END.BIN, each a copy of the roll's last page's slot redrawn, and
# shown by four new steps in each ending's roll (end_roll_asm). Their map
# offsets are END_SIZE + k * slot + 4, in order.
END_SECTORS = 0x80099698       # Rev 0 g_end_sectors: u16 sectors into END.BIN
END_SECTOR_COUNT = 86          # the last entry is END.BIN's end
END_SCRIPTS = 0x80099FF4       # Rev 0 g_end_scripts: five script pointers
ROLL_TEMPLATE = 0x44           # the roll's last page: the new pages' slot and palette
ROLL_BEFORE_LOGO = 0x48        # opcode 8's "Presented By" card: new pages go before it
END_OP_ARGS = {0, 1, 2, 3, 4, 5, 7, 8, 11}
# one page, as every retail roll page: load to the text layer, wait, fade it
# in, hold, fade it out
ROLL_PAGE_OPS = (2, None, 5, 0x2D, 3, 4, 5, 0x96, 4, 4)
END_ROLL_HOME = 0x80120000     # free RAM above END.EXE's buffers and its
                               # libraries' work areas (the highest address its
                               # code names is 0x801146D0; SsInit clears up to
                               # there) and below the subtitle renderer's
                               # lookups (0x80128000)


def end_exe():
    return open(END_EXE, 'rb').read()


def exe_u(image, addr, fmt):
    return struct.unpack_from(fmt, image, addr - 0x80080000 + 0x800)[0]


def end_sectors(image):
    return [exe_u(image, END_SECTORS + 2 * i, '<H') for i in range(END_SECTOR_COUNT)]


def end_script(image, k):
    """Ending k's retail script as u16 words, its stop opcode included."""
    at, out = exe_u(image, END_SCRIPTS + 4 * k, '<I'), []
    while True:
        op = exe_u(image, at, '<H')
        out.append(op)
        at += 2
        if op in (9, 10):
            return out
        if op in END_OP_ARGS:
            out.append(exe_u(image, at, '<H'))
            at += 2


def roll_asm(new_pages):
    """build/end_roll.asm: the image table with the new pages' entries and the
    scripts whose roll shows them, assembled for END_ROLL_HOME (equ's) and
    placed by end_exe/roll.asm. Scripts without the roll keep their retail
    copy."""
    image = end_exe()
    sectors = end_sectors(image)
    slot = sectors[ROLL_TEMPLATE + 1] - sectors[ROLL_TEMPLATE]
    # END.BIN runs two sectors past the table's last entry; the new pages
    # start at the file's real end, as images END_SECTOR_COUNT and on
    base = END_SIZE // 0x800
    table = sectors + [base + slot * k for k in range(len(new_pages) + 1)]
    first = END_SECTOR_COUNT
    words = list(table)
    if len(words) & 1:
        words.append(0)
    out = [';; generated by src/injection_tools/endtext.py - do not edit',
           f'END_ROLL_HOME equ {END_ROLL_HOME:#x}',
           f'END_ROLL_TABLE equ {END_ROLL_HOME:#x}']
    body = ['.halfword ' + ', '.join(f'{v:#x}' for v in words)]
    at = END_ROLL_HOME + 2 * len(words)
    for k in range(5):
        script = end_script(image, k)
        ops, i = [], 0
        while i < len(script):
            op = script[i]
            ops.append((i, op))
            i += 2 if op in END_OP_ARGS else 1
        cut = next((i for i, op in ops if op == 8 and script[i + 1] == ROLL_BEFORE_LOGO), None)
        if cut is None:
            continue
        add = []
        for n in range(len(new_pages)):
            add += [first + n if v is None else v for v in ROLL_PAGE_OPS]
        new = script[:cut] + add + script[cut:]
        if len(new) & 1:
            new.append(0)
        out.append(f'END_ROLL_SCRIPT{k} equ {at:#x}')
        out.append(f'END_ROLL_SCRIPT{k}_CUT equ {cut}')
        body.append('.halfword ' + ', '.join(f'{v:#x}' for v in new))
        at += 2 * len(new)
    out.append(f'END_ROLL_SIZE equ {at - END_ROLL_HOME:#x}')
    out.append(f'END_ROLL_PAGES equ {len(new_pages)}')
    out.append('end_roll_data:')
    out += body
    out.append('end_roll_data_end:')
    return '\n'.join(out) + '\n', slot


# The roll's logo sheet (END.BIN's frame image, g_end_sectors[0x45]): END.EXE
# shows rectangles of it with opcode 8, cut by its g_end_logo_u/v/w/h tables.
END_EXE = os.path.join(ROOT, 'data', 'psx', 'EXE', 'END.EXE')
END_LOGO_TABLES = 0x8009A08C   # Rev 0: u[8], v[8], w[8], h[8] bytes


def logo_crops():
    """[(u, v, w, h)] of the logo sheet, in END.EXE's table order."""
    image = open(END_EXE, 'rb').read()
    at = END_LOGO_TABLES - 0x80080000 + 0x800
    u, v, w, h = (image[at + 8 * k:at + 8 * k + 8] for k in range(4))
    return [(u[i], v[i], w[i], h[i]) for i in range(8) if w[i] and h[i]]


def logo_layout(pix, w, lines, blank):
    """The logo sheet: each line is the name under one crop's title, in the
    table's order (the first crops are Direction and Art Direction, the PSP
    original staff's #84). A crop's name is its lower ink row: that row is
    cleared and the line drawn centred under the title, from the row's top.
    Returns [(x, y, text)] and the [(x0, y0, x1, y1)] rectangles cleared."""
    out, clear = [], []
    for (u, v, cw, ch), s in zip(logo_crops(), lines):
        rows = [y for y in range(v, v + ch)
                if any(pix[y * w + x] != blank for x in range(u, u + cw))]
        runs = []
        for y in rows:
            if runs and y == runs[-1][1] + 1:
                runs[-1][1] = y
            else:
                runs.append([y, y])
        if len(runs) < 2:
            raise ValueError(f'logo crop {u},{v} has no title and name rows')
        (t0, t1), (n0, n1) = runs[0], runs[-1]
        title = [x for x in range(u, u + cw)
                 if any(pix[y * w + x] != blank for y in range(t0, t1 + 1))]
        cx = (title[0] + title[-1] + 1) // 2
        x = cx - text_width(s) // 2
        if x < u or x + text_width(s) > u + cw or n0 + INK_ROWS > v + ch:
            raise ValueError(f'{s!r} does not fit logo crop {u},{v}')
        clear.append((u, n0, u + cw, n1 + 1))
        out.append((x, n0, s))
    return out, clear


def main():
    from PIL import Image
    pages = load_pages()
    source = os.path.join(ROOT, 'data', 'psx', 'EXE', 'END.BIN')
    d = bytearray(open(source, 'rb').read())
    assert len(d) == END_SIZE, (source, len(d))
    prev = os.path.join(ROOT, 'build', 'previews', 'endtext')
    os.makedirs(prev, exist_ok=True)
    # pages past the retail file: copies of the roll's last page's slot
    sectors = end_sectors(end_exe())
    slot = sectors[ROLL_TEMPLATE + 1] - sectors[ROLL_TEMPLATE]
    template = bytes(d[sectors[ROLL_TEMPLATE] * 0x800:sectors[ROLL_TEMPLATE + 1] * 0x800])
    new_pages = sorted(off for off in pages if off >= END_SIZE)
    for k, off in enumerate(new_pages):
        want = END_SIZE + k * slot * 0x800 + 4
        if off != want:
            toolbelt.fail(f'endtext: new page {off:#x} should be at {want:#x}')
        d += template
    for off, spec in pages.items():
        t = tim.parse(d, off)
        assert t['bpp'] == 4, hex(off)
        assert spec[0] == 'l' or (t['px_w'] == 320 and t['h'] == 240), hex(off)
        w, h = t['px_w'], t['h']
        raw = d[t['at']:t['at'] + t['w'] * 2 * h]
        pix = bytearray()
        for b in raw:
            pix += bytes((b & 15, b >> 4))
        # The page's own colours: its background is its most common index
        # and its ink the brightest CLUT entry. The epilogue pages are 1-bit
        # (0 white, 1 black); the roll's pages are a 16-step grey ramp whose
        # black sits at 12, 13 or 15, so a fixed index would paint them grey.
        blank = Counter(pix).most_common(1)[0][0]
        clut = struct.unpack_from('<16H', d, t['clut']['at'])
        ink = max(range(16), key=lambda i: sum((clut[i] >> s) & 31 for s in (0, 5, 10)))
        if spec[0] == 'l':
            try:
                items, clear = logo_layout(pix, w, spec[1], blank)
            except ValueError as ex:
                toolbelt.fail(f'endtext: logo sheet {off:#x}: {ex}')
            for x0, y0, x1, y1 in clear:   # only the name rows; the sheet stays
                for yy in range(y0, y1):
                    pix[yy * w + x0:yy * w + x1] = bytes((blank,)) * (x1 - x0)
        else:
            if spec[0] == 'n':
                try:
                    items = credits_layout(pix, w, h, spec[1])
                except ValueError as ex:
                    toolbelt.fail(f'endtext: credits page {off:#x}: {ex}')
            else:
                items = layout(pix, w, h, spec)
            for i in range(len(pix)):
                pix[i] = blank
        for x, y, s in items:
            assert text_width(s) + x <= w and x >= 0, (hex(off), s)
            put(pix, w, x, y, s, ink)
        last = max(y for _, y, _ in items) + 12
        assert last <= 240, (hex(off), last)
        packed = bytes(pix[i] | (pix[i + 1] << 4) for i in range(0, len(pix), 2))
        d[t['at']:t['at'] + len(packed)] = packed
        im = Image.frombytes('P', (w, h), bytes(pix))
        im.putpalette([v for c in clut for v in
                       (((c & 31) * 255) // 31, ((c >> 5 & 31) * 255) // 31,
                        ((c >> 10 & 31) * 255) // 31)] + [0] * 720)
        im.save(os.path.join(prev, f'end_{off:X}.png'))
        print(f'{off:#x}: {len(items)} lines, bottom y {last}')
    os.makedirs(os.path.join(ROOT, 'build', 'EXE'), exist_ok=True)
    open(os.path.join(ROOT, 'build', 'EXE', 'END.BIN'), 'wb').write(bytes(d))
    asm, _slot = roll_asm(new_pages)
    open(os.path.join(ROOT, 'build', 'end_roll.asm'), 'w').write(asm)


if __name__ == '__main__':
    main()
