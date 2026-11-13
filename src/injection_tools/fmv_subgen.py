"""Build the in-engine FMV subtitle blob that rides at the end of MOVIE.EXE.

Subtitles are rendered by the game itself (see docs/research/fmv-subs-in-engine.md):
MOVIE.EXE's frame loop calls the renderer at 0x80160000 after each decoded frame.
This tool turns the subtitle data plus the TrueType font into the blob (glyph
atlas + subtitle/patch tables) and packs it behind the renderer code:

  python src/injection_tools/fmv_subgen.py data   -> build/movie_subs_data.bin
                                                     build/movie_subs_open_data.bin
  python src/injection_tools/fmv_subgen.py pack   -> build/movie_subs.bin
                                                     build/movie_subs_open.bin

The `data` step runs before the armips pass that assembles the renderer
(src/asm/movie_exe/subs_code.asm -> build/movie_subs_code.bin); `pack` concatenates
them. build.py runs both around that armips pass. MOVIE.EXE gets the full
payload; OPEN.EXE gets the quote-only payload that stops below OPEN.BIN's
0x80180000 home (see docs/research/fmv-subs-in-engine.md).

Two kinds of entries share one format:

  * speech subtitles (translation/manual/fmv/subtitles.tsv) draw over the live
    frame with a fade_shift ramp - the frame is correct everywhere, only the
    text is added;
  * movies with burned-in text (the opening quote's cards, the ending poems -
    layout in fmv_layout, measurement in src/assets/fmv/) composite a PATCH first:
    the picture's own pixels where the original text sits (measured from the
    clean plate frame, so the video's baked-in text is painted over), scaled by
    the measured fade, then the English text over it as one thing.

Frame numbers are 0-based stream frames (g_movie_frame's units).
Layout of the blob (copied to 0x80160000 at startup):
  0x0000..0x2000  renderer code (assembled at 0x80160000)
  0x2000..        header, advance table, glyph atlas, per-movie entry lists,
                  per-entry blobs (patch + scale + alpha + compiled ink), text

Keep the constants here and in src/asm/movie_exe/subs_code.asm in sync.
"""
import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext  # noqa: E402
import strlib  # noqa: E402
import fmv_ink  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- shared with src/asm/movie_exe/subs_code.asm --------------------------
CODE_BASE = 0x80160000
CODE_SIZE = 0x2000
DATA_BASE = CODE_BASE + CODE_SIZE
LOAD_ADDR = 0x80080000       # PS-EXE t_addr for MOVIE.EXE and OPEN.EXE
SECTOR = 2048               # CdReadPolled rounds t_size up to whole sectors
SCRATCH = 0x80140640          # the band the renderer blends into, above the
                            # T/U ramp tables and the scaled patch palette
# The resident stages SEQ/NAME/VAB/ADV/S2D packs in 0x80118000..0x801E0000, but
# the movie scene runs LoadAndExecPsExe *first* and only preloads those packs
# after the movie returns - so the whole range is stale scratch for the entire
# playback, and the loader can drop the blob anywhere below FONT_DEST.
BLOB_END = 0x801E0000
FRAME_W = 320
SCRATCH_WINDOW = 0x80160000 - SCRATCH   # band bytes (the clear runs past the end
                            # of a row in 16-byte units, hence the +16)
FPS = 15
FADE = 3                      # frames of fade at each end (ramp FADE+1 steps)
MAXW = 312                    # widest line (px): the frame minus a 4px margin
LINE_STEP = 20
LINE_BASE = 196
POEM_PITCH = 14               # the ending poems' line pitch (12px font, as the burn)
ATTR_RIGHT = 286              # ink right edge of right-aligned lines (fmv_layout)
FONT_PX = 14
FONTS = [os.path.join(ROOT, 'src', 'video_font', 'PublicSans-Medium.ttf')]

MOVIE_COUNT = 39              # entries in the game's g_movie_frames table
GLYPH_FIRST, GLYPH_LAST = 0x20, 0x7E
GLYPH_COUNT = GLYPH_LAST - GLYPH_FIRST + 1   # glyphs per set (14px then 12px)
QUOTE_MOVIE = 0x1C            # opening movie MV1C: the Zhuangzi quote cards

HDR_MAGIC = 0x34534D46        # 'FMS4': independently placed zoom-level pointers
FMV_DIR = os.path.join(ROOT, 'src', 'assets', 'fmv')

F_PATCH = 1                   # entry flags: composite mode (patch + own text)
F_ADD = 2                     # the ink adds over the faded picture (intro)
F_SMALL = 4                   # 12px glyph set (the ending poems), else 14px
F_FULL = 8                    # the patch repaints the whole band rectangle
F_ZOOM = 0x10                 # the patch carries pre-scaled levels (the
                              # picture itself zooms under the burned text)
F_INK = 0x20                  # positioned additive spans with shared expressions
F_FLOOR = 0x40                # opening's existing floor-rounded additive blend
F_LIFT = 0x80                 # the filter is a grey layer: a u8 lift per frame
                              # follows the scale table and is added to the patch
ZOOM_STEP = 6                 # per mille between levels: 0.6% of the frame
ZOOM_VARY = 20                # per mille: a picture that changes size less
                              # than this over the entry is a still, and the
                              # one-rectangle pan patch already covers it
ZOOM_MAX_LEVELS = 10
OPEN_BLOB_END = 0x80180000    # OPEN.BIN (the title's TIM/VAB/SEQ pack) lives
                              # here and the resident loads it just before
                              # OPEN.EXE; the opening EXE's blob must stop
                              # short of it. MOVIE.EXE has no such neighbour
                              # and keeps the full data up to FONT_DEST.
OPEN_ZOOM_LEVELS = 3
ZOOM_AUX_BASE = 0x80130000    # above eight 1024-expression ink lookups
ZOOM_AUX_END = 0x8013FF00     # ink cache metadata starts here (8 x 16 bytes)
# END.EXE plays the endings' movies with its own player; its blob is read
# from the tail of END.EXE to CODE_BASE when each movie starts, and holds only
# the movies its scripts play (end_movies). END.EXE's buffers and library work
# areas stop near 0x80114700; its staging areas above are reloaded after every movie.
END_EXE = os.path.join(ROOT, 'data', 'psx', 'EXE', 'END.EXE')
END_SCRIPTS = 0x80099FF4      # Rev 0 g_end_scripts: five script pointers
END_SCRIPT_COUNT = 5
END_OP_ARGS = {0, 1, 2, 3, 4, 5, 7, 8, 11}   # opcodes followed by one u16
END_OP_MOVIE = 7
END_OP_STOP = {9, 10}


def font():
    for f in FONTS:
        if os.path.exists(f):
            return f
    raise SystemExit('fmv_subgen: no usable TrueType font')


def load_rows():
    """[(movie_no, start_frame, end_frame, [line, ...]), ...] from the TSV.

    Frame windows: int(round(s*FPS)) extended by FADE frames on each side
    (the subtitles.tsv seconds are the source of truth); the renderer fades
    with the same FADE+1 ramp.
    """
    path = os.path.join(ROOT, 'translation', 'manual', 'fmv', 'subtitles.tsv')
    out = []
    for r in strlib.tsv_rows(path, required=('movie', 'start_s', 'end_s', 'text')):
        if not etext.has_text(r['text']):
            continue
        mv = r['movie']
        if not (len(mv) == 4 and mv[:2] == 'MV'):
            raise SystemExit(f'fmv_subgen: bad movie id {mv!r}')
        no = int(mv[2:], 16)
        if not 0 <= no < MOVIE_COUNT:
            raise SystemExit(f'fmv_subgen: movie id {mv!r} out of range')
        text = r['text'].replace('\\n', '\n')
        for line in text.split('\n'):
            bad = [c for c in line if not GLYPH_FIRST <= ord(c) <= GLYPH_LAST]
            if bad:
                raise SystemExit(f'fmv_subgen: unsupported glyph(s) {bad!r} in {line!r}')
        a = int(round(float(r['start_s']) * FPS)) - FADE
        b = int(round(float(r['end_s']) * FPS)) + FADE
        out.append((no, a, b, text.split('\n')))
    out.sort(key=lambda e: (e[0], e[1]))
    return out


def render_atlas():
    """(cw, ch, adv[], cells, ext[]) - the burned subs' look exactly: white text
    over a dilated black outline (stroke_width 4 at 3x, LANCZOS downscale),
    composited over the video with the same masks.

    cells is one (gray, cov) grid per glyph; the packer turns each into row
    spans so the renderer only ever touches ink pixels (the cell is mostly
    air). ext is each glyph's
    ink box (x0, x1, y0, y1 inclusive) inside its cell - ink overhangs its
    advance (the outline), so placement and band geometry use the ink box,
    not the advance box."""
    f3 = ImageFont.truetype(font(), FONT_PX * 3)
    f1 = ImageFont.truetype(font(), FONT_PX)
    chars = [chr(c) for c in range(GLYPH_FIRST, GLYPH_LAST + 1)]
    w3 = max(int(f3.getlength(c)) for c in chars) + 24
    cw, ch = w3 // 3, (FONT_PX * 3 + 30) // 3
    adv = [max(1, round(f1.getlength(c))) for c in chars]
    cells, ext = [], []
    for c in chars:
        im = Image.new('L', (w3, FONT_PX * 3 + 30), 0)
        ImageDraw.Draw(im).text((12, 8), c, 255, font=f3)
        dark = Image.new('L', im.size, 0)
        ImageDraw.Draw(dark).text((12, 8), c, 255, font=f3, stroke_width=4, stroke_fill=255)
        fg = im.resize((cw, ch), Image.LANCZOS)
        bg = dark.resize((cw, ch), Image.LANCZOS)
        grid = []
        for y in range(ch):
            row = []
            for x in range(cw):
                ft, fb = fg.getpixel((x, y)), bg.getpixel((x, y))
                cov = ft + fb - (ft * fb) // 255      # 1 - (1-ft)(1-fb)
                gray = (255 * ft) // cov if cov else 0
                row.append((gray, cov))
            grid.append(row)
        cells.append(grid)
        ink = [(x, y) for y in range(ch) for x in range(cw) if grid[y][x][1]]
        ext.append(None if not ink else
                   (min(x for x, _ in ink), max(x for x, _ in ink),
                    min(y for _, y in ink), max(y for _, y in ink)))
    return (cw, ch), adv, cells, ext


def pack_spans(cells, cw, ch, off_ptrs, off_spans, used=None):
    """Per glyph, per ink row: y, run count, then per run (x, len, pixels).
    A y of 0xFF ends a glyph. Pointers are absolute. Runs are split at the
    coverage-255 boundary; bit 7 of the length marks an opaque run (the cell
    is 21 px wide, so the real length is 7 bits).

    `used` limits the payload to the characters a build actually draws (the
    opening quote uses 34 of the 95); unused pointers share one terminator.
    The atlas is still indexed by char - GLYPH_FIRST, so this is pure size,
    never a change to any drawn glyph."""
    ptrs = [None] * len(cells)
    spans = bytearray()
    for gi, grid in enumerate(cells):
        if used is not None and chr(GLYPH_FIRST + gi) not in used:
            continue
        ptrs[gi] = DATA_BASE + off_spans + len(spans)
        for y in range(ch):
            runs, x = [], 0
            while x < cw:
                if grid[y][x][1]:
                    x0 = x
                    while x < cw and grid[y][x][1]:
                        x += 1
                    runs.append((x0, x - x0))
                else:
                    x += 1
            if not runs:
                continue
            # Split at the coverage-255 boundary so the renderer can take
            # its solid-run path over the ink's opaque core. Bit 7 of the
            # length marks such a run (the cell is 21 px wide).
            segs = []
            for x0, ln in runs:
                x = x0
                while x < x0 + ln:
                    solid = grid[y][x][1] == 255
                    j = x + 1
                    while j < x0 + ln and (grid[y][j][1] == 255) == solid:
                        j += 1
                    segs.append((x, j - x, solid))
                    x = j
            spans += bytes((y, len(segs)))
            for x0, ln, solid in segs:
                spans += bytes((x0, ln | (0x80 if solid else 0)))
                for x in range(x0, x0 + ln):
                    spans += bytes(grid[y][x])             # (gray, cov)
        spans += b'\xff'
    if used is not None:
        empty_at = len(spans)
        spans += b'\xff'
        for gi, ptr in enumerate(ptrs):
            if ptr is None:
                ptrs[gi] = DATA_BASE + off_spans + empty_at
    assert all(p is not None for p in ptrs)
    assert len(ptrs) * 4 == off_spans - off_ptrs
    return b''.join(struct.pack('<I', p) for p in ptrs), bytes(spans)


def _walk(text, adv, ext):
    """(char, pen_x, ink box or None) per character."""
    pen = 0
    for c in text:
        yield c, pen, ext[ord(c) - GLYPH_FIRST]
        pen += adv[ord(c) - GLYPH_FIRST]


def ink_width(text, adv, ext):
    """Width of the line's ink box - the cells' ink boxes at each pen
    position, which overhang the advance sum (the outline)."""
    pts = [(pen, e) for _c, pen, e in _walk(text, adv, ext) if e]
    return (pts[-1][0] + pts[-1][1][1] + 1) - (pts[0][0] + pts[0][1][0])


def ink_box(text, adv, ext, x, y_top):
    """(x0, y0, x1, y1) exclusive bounds of the line's ink."""
    box = None
    for _c, pen, e in _walk(text, adv, ext):
        if e:
            gx0, gx1, gy0, gy1 = e
            b = (x + pen + gx0, y_top + gy0, x + pen + gx1 + 1, y_top + gy1 + 1)
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                         max(box[2], b[2]), max(box[3], b[3]))
    return box


def place_line(text, adv, ext, right, y_top):
    """(x, y_top, text), positioned on the INK box: centered at 160, or the
    ink's right edge at ATTR_RIGHT (fmv_layout's rule). y_top is where the
    glyph cell starts. The ink box must stay inside the frame's 4px margin:
    ink overhangs the advance, so the advance sum alone cannot tell."""
    pts = [(pen, e) for _c, pen, e in _walk(text, adv, ext) if e]
    left = pts[0][0] + pts[0][1][0]
    right_edge = pts[-1][0] + pts[-1][1][1] + 1
    inkw = right_edge - left
    if inkw > MAXW:
        raise SystemExit(f'fmv_subgen: {text!r} is {inkw}px of ink wide (max {MAXW})')
    x = (ATTR_RIGHT - right_edge) if right else (160 - inkw // 2 - left)
    x0, _y0, x1, _y1 = ink_box(text, adv, ext, x, y_top)
    if x0 < 4 or x1 > 316:
        raise SystemExit(f'fmv_subgen: {text!r} ink box {x0}..{x1} leaves the frame')
    return (x, y_top, text)


def fade_shift(span, want):
    """Fade ramp of 2**shift frames, clamped so a short subtitle still reaches
    full opacity (half the span at most)."""
    import math
    return max(2, min(want, int(math.log2(max(4, span // 2)))))


# ---- the burned-in-text movies (layout in fmv_layout, data in src/assets/fmv/) --

def load_cards():
    """The opening quote cards (movie 0x1C): bands and pin rules ('>N' pins a
    line to band N, a leading '>' is the right-aligned attribution), wording
    from translation/generated/fmv/opening.tsv.
    Returns [(first, last, [(text, right, y_top, band_index)], bands)]."""
    import re
    import fmv_layout
    out, base = [], 0
    for first, last, bands, lines in fmv_layout.quote_cards():
        recs = []
        for k, ln in enumerate(lines):
            m = re.search(r'>(\d+)$', ln)
            slot = int(m.group(1)) if m else k
            if m:
                ln = ln[:m.start()]
            # the attribution's head mark is one construct and the builds
            # stack their spellings ('>' the layout's, '＾' the PSP's, '＞'
            # the PSX's): the mark is decoration, never wording, so the
            # whole run of them goes and the attribution stays flagged
            right = ln[:1] in ('>', '＾', '＞')
            ln = re.sub(r'^[>＾＞]+', '', ln)
            y0, y1 = bands[slot]
            recs.append((ln, right, (y0 + y1) // 2 - 13, base + slot))
        out.append((first, last, recs, [(base + i, y0, y1) for i, (y0, y1) in enumerate(bands)]))
        base += len(bands)
    return out


def load_poems(adv, ext):
    """The ending poems: one block each, wording verbatim from
    translation/manual/fmv/poems.tsv, re-flowed to fit this font's width.
    Returns [(movie, first, last, [(text, right, y_top, band_index)], bands)]."""
    import fmv_layout
    out = []
    for mv, (first, last, rect, top, lines) in fmv_layout.poem_cards().items():
        x0, y0, x1, y1 = rect
        flat = wrap(' '.join(lines), adv, ext, MAXW)
        recs = [(t, False, top + k * LINE_STEP, 0) for k, t in enumerate(flat)]
        out.append((mv, first, last, recs, [(0, y0, y1)], (x0, x1)))
    return out


def load_timing(mv):
    """{frame: (scale 0..255 of the picture, [text alpha per band], lift)} -
    lift is what a grey filter layer adds to every channel (0 for a black
    filter, whose timing has no lift column)."""
    lines = open(os.path.join(FMV_DIR, mv + '.timing.tsv')).read().strip().split('\n')
    head = lines[0].split('\t')
    texts = [i for i, name in enumerate(head) if name.startswith('text')]
    at = head.index('lift') if 'lift' in head else None
    out = {}
    for line in lines[1:]:
        r = line.split('\t')
        out[int(r[0])] = (int(r[1]), [int(r[i]) for i in texts],
                          int(r[at]) if at is not None else 0)
    return out


def load_pan(mv):
    """{frame: vertical pan vs the plate in 1/8 px} - measured from the
    frames; unreadable (dark) frames are absent."""
    path = os.path.join(FMV_DIR, mv + '.pan.tsv')
    out = {}
    if os.path.exists(path):
        for line in open(path).read().strip().split('\n')[1:]:
            p = line.split('\t')
            if len(p) == 2 and p[1]:
                out[int(p[0])] = int(p[1])
    return out


def load_zoom(mv):
    """{frame: picture scale vs the plate, in 1/1000} - a similarity fit of
    every frame the fade leaves bright enough; unreadable frames are absent."""
    path = os.path.join(FMV_DIR, mv + '.zoom.tsv')
    out = {}
    if os.path.exists(path):
        for line in open(path).read().strip().split('\n')[1:]:
            p = line.split('\t')
            if len(p) == 2 and p[1]:
                out[int(p[0])] = int(p[1])
    return out


def word_cols(x0, w):
    """(x0, w) of a full-band patch: w a multiple of 4 so every 24bpp band
    row (w*3 bytes) starts word-aligned and the patch pass stores whole
    words; x0 even so the GPU rect is halfword aligned. Grows the band
    rightwards, or leftwards at the frame edge, never cutting a column."""
    w = min(FRAME_W, (w + (x0 & 1) + 3) & ~3)
    x0 &= ~1
    if x0 + w > FRAME_W:
        x0 = FRAME_W - w
    return x0, w


def zoom_levels(pts, scale, f0, f1, max_levels=ZOOM_MAX_LEVELS):
    """([level zoom per mille, ...], [level per frame, ...]) - or None when
    the picture holds the plate's size.

    The opening quote's picture zooms under the burned text (the moon card
    shrinks ~3% as it brightens), so one plate rectangle cannot line up with
    every frame. A still - the ending poems - changes less than ZOOM_VARY and
    stays on the pan's path.

    Each frame's measurement is a fit on a 2 per mille grid with a few per
    mille of noise, and the movie's zoom itself is a steady ramp: the frames
    follow one least-squares line weighted by the picture's brightness, held
    at the measured window's ends. Following the raw points instead flips a
    frame between two levels and back, which shows as the band popping.

    `max_levels` limits the ladder to the driver's storage budget (OPEN keeps
    three). The levels cover the fitted range: no frame is further from its
    level than a uniform ladder's half step, and within that bound they sit
    where the brightness-weighted worst mismatch is smallest - a rectangle
    edge shows in proportion to the picture under it, so the bright frames
    get the close levels. The level nearest the plate's own size moves to
    exactly 1000 whenever that keeps every frame inside the bound: a 1:1
    crop is the sharpest picture and needs no resampling."""
    raw = [pts.get(f) for f in range(f0, f1 + 1)]
    seen = [i for i, v in enumerate(raw) if v is not None]
    if not seen:
        return None
    vis = [raw[i] for i in seen if scale[i] > 0]
    if not vis or max(vis) - min(vis) < ZOOM_VARY:
        return None
    w = [max(1, scale[i]) for i in seen]
    sw = sum(w)
    mx = sum(wi * i for wi, i in zip(w, seen)) / sw
    my = sum(wi * raw[i] for wi, i in zip(w, seen)) / sw
    den = sum(wi * (i - mx) ** 2 for wi, i in zip(w, seen))
    slope = (sum(wi * (i - mx) * (raw[i] - my) for wi, i in zip(w, seen)) / den
             if den else 0.0)
    z = [my + slope * (min(max(i, seen[0]), seen[-1]) - mx) for i in range(len(raw))]
    lit = [i for i in range(len(z)) if scale[i] > 0]
    lo, hi = min(z[i] for i in lit), max(z[i] for i in lit)
    n = max(2, min(max_levels, int(-(-(hi - lo) // ZOOM_STEP)) + 1))
    cap = (hi - lo) / (2 * (n - 1))
    weight = {i: min(256, scale[i]) / 256.0 for i in lit}

    def place(err):
        """Levels for a weighted error bound, or None: interval stabbing,
        each level centred in its frames' common window."""
        iv = sorted(((z[i] - min(cap, err / weight[i]), z[i] + min(cap, err / weight[i]))
                     for i in lit), key=lambda r: r[1])
        out, k = [], 0
        while k < len(iv):
            left, right = iv[k]
            k += 1
            while k < len(iv) and iv[k][0] <= right:
                left = max(left, iv[k][0])
                k += 1
            out.append(1000.0 if left <= 1000 <= right else (left + right) / 2)
            if len(out) > n:
                return None
        return out

    lev = place(cap + 1e-9)
    a, b = 0.0, cap
    for _ in range(40):
        m = (a + b) / 2
        got = place(m)
        if got is None:
            a = m
        else:
            b, lev = m, got
    lev.sort()
    if lo <= 1000 <= hi:
        near = min(range(len(lev)), key=lambda k: abs(lev[k] - 1000))
        snapped = lev[:near] + [1000.0] + lev[near + 1:]
        if all(min(abs(l - z[i]) for l in snapped) <= cap + 1e-9 for i in lit):
            lev = snapped
    tab = bytes(min(range(len(lev)), key=lambda k: abs(lev[k] - v)) for v in z)
    return lev, tab


def pan_line(pts, f0, f1):
    """Least-squares pan over the frames the picture could be measured in.

    Returns (pan0 at f0 in 1/8 px, slope in 1/256 px per frame, lo, hi,
    margin rows), lo/hi being the measured window as offsets from f0. The
    pan is only knowable where the picture is visible; outside that window
    the renderer holds the nearest measured value instead of running the
    line off into the black. The margin is the largest shift the clamped
    line can produce."""
    fr = [f for f in range(f0, f1 + 1) if f in pts]
    if len(fr) < 4 or max(fr) == min(fr):
        return 0, 0, 0, 0, 1

    n = len(fr)
    xs = [f - f0 for f in fr]
    ys = [pts[f] for f in fr]
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    b8 = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    pan0 = round(my - b8 * mx)
    slope = round(b8 * 32)              # 1/8 px/frame -> 1/256 px/frame
    if abs(pan0) > 127 or abs(slope) > 127:
        return 0, 0, 0, 0, 1
    lo, hi = xs[0], xs[-1]
    vals = [(pan0 * 32 + slope * min(max(x, lo), hi) + 128) >> 8
            for x in range(f1 - f0 + 1)]
    return pan0, slope, lo, hi, max(1, min(8, max(abs(v) for v in vals) + 1))


def load_patch(mv):
    """[[(y, [(x0, len), ...]), ...], ...] per band - the pixels each band's
    burned-in text touches (band-tagged: the quote's cards share rows)."""
    b = open(os.path.join(FMV_DIR, mv + '.patch.bin'), 'rb').read()
    nb, i = b[0], 1
    out = []
    for _ in range(nb):
        rows = []
        while i < len(b) and b[i] != 0xFF:
            y, n = b[i], b[i + 1]
            i += 2
            runs = []
            for _ in range(n):
                runs.append((int.from_bytes(b[i:i + 2], 'little'),
                             int.from_bytes(b[i + 2:i + 4], 'little')))
                i += 4
            rows.append((y, runs))
        i += 1
        out.append(rows)
    return out


def wrap(text, adv, ext, maxw):
    """Greedy word wrap over the ink-width measure - the wording is verbatim,
    only the line breaks are ours (the burn layout's font is narrower)."""
    words = text.split()
    lines, cur = [], ''
    for w in words:
        cand = (cur + ' ' + w).strip()
        if cur and ink_width(cand, adv, ext) > maxw:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def collect(adv, ext, open_only=False):
    """{movie_no: [entry, ...]} with entry = (f0, f1, flags, band, patch, scale,
    alphas, shift, [(x, y, alpha_idx, text)], pan, zoom_table).

    `open_only` builds the OPEN.EXE payload: the opening quote (movie 0x1C)
    is the only movie that executable plays, and it has only the 128 KB
    below OPEN.BIN's 0x80180000 home to do it in. No speech rows, no poems,
    and the picture's zoom gets three levels, two staged in the auxiliary
    bank below the renderer instead of occupying the primary blob.

    alphas/scale are the measured curves, normalised so the plate's own frame
    is a straight copy (256). The quote's ink alpha is capped at the picture's scale so
    the additive blend can never wrap past white. zoom_table is one byte per
    frame when the picture itself zooms (the patch holds a pre-scaled copy of
    the band per level), else None."""
    entries = {}
    if not open_only:
        for no, a, b, lines in load_rows():
            n = len(lines)
            if n > 4:
                raise SystemExit(f'fmv_subgen: {n} lines in one subtitle (max 4): {lines!r}')
            gl = [place_line(t, adv, ext, False, LINE_BASE + (k + (2 - n)) * LINE_STEP - 12)
                  for k, t in enumerate(lines)]
            boxes = [ink_box(t, adv, ext, x, y) for x, y, t in gl]
            band = (min(b[1] for b in boxes), max(b[3] for b in boxes) - min(b[1] for b in boxes),
                    0, 320)
            entries.setdefault(no, []).append(
                (a, b, 0, band, None, None, None, fade_shift(b - a, 2),
                 [(x, y, k, t) for k, (x, y, t) in enumerate(gl)], (0, 0, 0, 0), None, None))

    def patch_head(plate, level, band):
        """The patch's 6-byte header: the strip just outside the band and the
        level the colours are baked at.

        The strip is a text-free slice of the plate and its mean, so the
        renderer can measure the live frame's fade instead of trusting the
        stream frame index (the decoder runs a few frames ahead of the screen,
        which showed as a rectangle around the text). 8 rows clear of the
        band: the burned text's compression halo reaches a couple of rows past
        its ink box, and the strip must be pure picture to give the fade. The
        plate is baked at this level and the scale table is normalised to it,
        so the measured fade takes the same normalisation."""
        band_y0, band_rows, band_x0, band_w = band
        if band_y0 >= 8:
            sy = band_y0 - 8
        elif band_y0 + band_rows + 8 <= 240:
            sy = band_y0 + band_rows
        else:
            sy = -1
        p16 = 0
        if sy >= 0:
            px = [plate.getpixel((x, y)) for y in range(sy, sy + 4)
                  for x in range(band_x0, band_x0 + band_w)]
            p16 = int(round(sum(sum(c) for c in px) / (3 * len(px)) * 16))
            if p16 <= 0:
                sy = -1
        return (bytes((sy & 0xFF, 0 if sy < 0 else 4)) +
                int(p16).to_bytes(2, 'little') +
                int(round(level * 256)).to_bytes(2, 'little'))

    def movie_patch(mv, level, band, runs_by_row):
        """This entry's replace patch: the burned text's runs, nothing else.

        Only the ink (widened to cover the mpeg halo and the pan) is painted
        from the plate. Every other pixel of the band stays the live frame,
        so the band keeps the movie's own grain and block noise instead of
        turning into a clean rectangle pasted over the picture. 8bpp
        palette: the pixels sit under text, so palette banding is invisible.
        """
        band_y0, band_rows, band_x0, band_w = band
        plate = Image.open(os.path.join(FMV_DIR, mv + '.png')).convert('RGB')
        cols = [tuple(round(c * level) for c in plate.getpixel((x, y)))
                for y, runs in runs_by_row
                for x0, ln in runs for x in range(x0, x0 + ln)]
        pal_img = Image.new('RGB', (len(cols), 1))
        pal_img.putdata(cols)
        q = pal_img.quantize(colors=256)
        pal = q.getpalette()[:768]
        idxs = q.tobytes()
        patch = bytearray()
        # 8-bit RGB palette: RGB555 costs ~2.3 levels of mean error on a
        # smooth picture, and the band is a picture - the fade makes any
        # systematic offset show as a rectangle around the text
        patch += bytes(pal[:768])
        patch += patch_head(plate, level, band)
        patch += bytes((max(pal), 0))
        k = 0
        for y, runs in runs_by_row:
            patch += bytes((y, len(runs)))
            for x0, ln in runs:
                patch += int(x0).to_bytes(2, 'little') + int(ln).to_bytes(2, 'little')
                while len(patch) & 3:
                    patch.append(0)
                patch += idxs[k:k + ln]
                k += ln
                while len(patch) & 3:
                    patch.append(0)
        patch += b'\xff'
        return bytes(patch)

    def zoom_patch(mv, level, band, levels):
        """One pre-scaled copy of the band per measured zoom level.

        The opening quote's picture is not the plate's size while it fades:
        the moon card shrinks ~3% as it brightens, so a single plate rectangle
        sits a couple of pixels off along the band's edges. Each level is the
        plate scaled about the frame centre (the fit finds no rotation or
        shift), cropped to the band; the renderer copies the level nearest the
        frame's measured zoom, so the console never resamples a pixel. One
        palette, quantised over every level at once.
        """
        band_y0, band_rows, band_x0, band_w = band
        plate = Image.open(os.path.join(FMV_DIR, mv + '.png')).convert('RGB')
        stack = Image.new('RGB', (band_w, band_rows * len(levels)))
        for k, s in enumerate(levels):
            inv = 1000.0 / s
            warp = plate.transform(
                plate.size, Image.AFFINE,
                (inv, 0, 160.0 * (1.0 - inv), 0, inv, 120.0 * (1.0 - inv)),
                resample=Image.BILINEAR)
            crop = warp.crop((band_x0, band_y0,
                              band_x0 + band_w, band_y0 + band_rows))
            if level != 1.0:
                lut = [min(255, int(round(v * level))) for v in range(256)]
                crop = crop.point(lut * 3)      # one band table per channel
            stack.paste(crop, (0, k * band_rows))
        q = stack.quantize(colors=256)
        idxs = q.tobytes()
        patch = bytearray(bytes(q.getpalette()[:768]))
        patch += patch_head(plate, level, band)
        patch += bytes((max(q.getpalette()[:768]), 0))
        for k in range(len(levels)):
            for i in range(band_rows):
                patch += bytes((band_y0 + i, 1))
                patch += int(band_x0).to_bytes(2, 'little')
                patch += int(band_w).to_bytes(2, 'little')
                while len(patch) & 3:
                    patch.append(0)
                at = (k * band_rows + i) * band_w
                patch += idxs[at:at + band_w]
                while len(patch) & 3:
                    patch.append(0)
            patch += b'\xff'
            while len(patch) & 3:
                patch.append(0)
        return bytes(patch)

    def composite(mv, first, last, recs, bands, flags, clip=(0, 320)):
        import fmv_layout
        timing = load_timing(mv)
        f0, f1 = first, last
        # the entry lives on a plateau - its most common non-zero picture
        # level. Store the plate pre-darkened to it and normalise that level
        # to exactly 256. The CPU expands this frame's scaled RGB palette.
        vals = [timing[f][0] for f in range(f0, f1 + 1)]
        nz = [v for v in vals if v]
        level = (max(set(nz), key=lambda v: (nz.count(v), v)) / 256.0) if nz else 1.0
        scale = [min(0xFFFF, round(v / level)) for v in vals]
        sections = load_patch(mv)
        sel = [sections[i] for i, _y0, _y1 in bands]
        # the measured mask also catches static picture elements that do not
        # fade with the plate (the movie's black border, for one); the text
        # itself lives inside the layout's text column
        runs_by_row = []
        for rows in sel:
            for y, runs in rows:
                cut = []
                for x0, ln in runs:
                    a, b = max(x0, clip[0]), min(x0 + ln, clip[1])
                    if b > a:
                        cut.append((a, b - a))
                if cut:
                    runs_by_row.append((y, cut))
        alphas = []
        for _t, _r, _y, bi in recs:
            tab = [timing[f][1][bi] for f in range(f0, f1 + 1)]
            if flags & F_ADD:
                # the additive ink may never wrap past white: plate*s/256 +
                # ink*eff/256 stays <= 255 when alpha <= 255 - s
                tab = [min(v, max(0, 255 - s)) for v, s in zip(tab, scale)]
            alphas.append(tab)
        gl, boxes = [], []
        for k, (t, right, y, _bi) in enumerate(recs):
            x, y, _t = place_line(t, adv, ext, right, y)
            gl.append((x, y, k, t))
            boxes.append(ink_box(t, adv, ext, x, y))
        # the picture is black at scale 0, so there the band is simply
        # cleared - no patch bytes needed for a whole black card
        pan0, slope, lo, hi, margin = pan_line(load_pan(mv), f0, f1)
        pan = (pan0, slope, lo, hi)
        # the band hugs what is painted: the patch runs and the text ink boxes.
        # x0/w even so the 24bpp GPU rect is halfword aligned.
        xs = [b[0] for b in boxes] + [b[2] for b in boxes] + \
             [x for _y, runs in runs_by_row for x0, ln in runs for x in (x0, x0 + ln)]
        ys = [b[1] for b in boxes] + [b[3] for b in boxes] + \
             [y for y, _r in runs_by_row] + [y + 1 for y, _r in runs_by_row]
        band_y0 = min(ys)
        band_x0 = min(xs) & ~1
        band_x0, band_w = word_cols(band_x0, max(xs) - band_x0)
        band = (band_y0, max(ys) - band_y0, band_x0, band_w)
        # the picture may itself zoom under the burned text; then each level
        # is a pre-scaled copy of the band and the renderer picks this
        # frame's. Its rows are the band's own and the drift is baked in, so
        # there is no pan left to apply.
        zpts = load_zoom(mv)
        zl = zoom_levels(zpts, scale, f0, f1,
                         max_levels=OPEN_ZOOM_LEVELS if open_only else ZOOM_MAX_LEVELS) if max(scale) else None
        ztab = None
        if zl is not None:
            levels, ztab = zl
            if open_only:
                # Cover the largest residual of the actual per-frame level,
                # not the full zoom drift of one frozen median-sized plate.
                errors = [abs(zpts[f] - levels[ztab[f - f0]]) for f in range(f0, f1 + 1)
                          if f in zpts and scale[f - f0]]
                delta = (max(errors) / 1000.0) if errors else 0.0
                y0, rows, x0, w = band
                import math
                padx = int(math.ceil(max(abs(x0 - 160), abs(x0 + w - 1 - 160)) * delta)) + 1
                pady = int(math.ceil(max(abs(y0 - 120), abs(y0 + rows - 1 - 120)) * delta)) + 1
                nx0 = max(0, (x0 - padx) & ~1)
                nx1 = min(FRAME_W, x0 + w + padx)
                ny0 = max(0, y0 - pady)
                ny1 = min(240, y0 + rows + pady)
                nx0, nw = word_cols(nx0, nx1 - nx0)
                band = (ny0, ny1 - ny0, nx0, nw)
            patch = zoom_patch(mv, level, band, levels)
            pan = (0, 0, 0, 0)
            flags |= F_ZOOM
        else:
            # the patch repaints the whole band (the burned text's mpeg halo
            # reaches past its strokes, so a stencil leaves a ghost of every
            # line), plus the rows the pan can slide the picture to
            plo = max(0, band_y0 - margin)
            phi = min(239, band_y0 + band[1] - 1 + margin)
            painted = [(y, [(band_x0, band_w)]) for y in range(plo, phi + 1)]
            patch = None if max(scale) == 0 else movie_patch(mv, level, band, painted)
        flags |= F_FULL
        if flags & F_ADD:
            flags |= F_INK
            if open_only:
                flags |= F_FLOOR
        lift = [timing[f][2] for f in range(f0, f1 + 1)]
        if any(lift):
            flags |= F_LIFT
        else:
            lift = None
        return (f0, f1, flags | F_PATCH, band, patch, scale, alphas, 0, gl, pan, ztab, lift)

    for first, last, recs, bands in load_cards():
        entries.setdefault(QUOTE_MOVIE, []).append(
            composite('MV1C', first, last, recs, bands, F_ADD))
    if not open_only:
        for mv, first, last, recs, bands, clip in load_poems(adv, ext):
            entries.setdefault(int(mv[2:], 16), []).append(
                composite(mv, first, last, recs, bands, 0, clip))
    for lst in entries.values():
        lst.sort(key=lambda e: e[0])
    return entries


def blend_table():
    """Paste T[eff*256 + v] = v*eff >> 8; also supplies glyph coverage ramps.

    Compiled additive ink evaluates each distinct expression once and needs
    no 64K additive table.
    """
    t = bytearray(256 * 256)
    for eff in range(256):
        row = eff * 256
        for v in range(256):
            t[row + v] = (v * eff) >> 8
    return bytes(t)


def end_movies():
    """The movies END.EXE's five ending scripts play (their opcode-7
    arguments), read from the retail executable."""
    image = open(END_EXE, 'rb').read()

    def u(addr, fmt):
        return struct.unpack_from(fmt, image, addr - 0x80080000 + 0x800)[0]
    movies = set()
    for k in range(END_SCRIPT_COUNT):
        at = u(END_SCRIPTS + 4 * k, '<I')
        while True:
            op = u(at, '<H')
            at += 2
            if op in END_OP_STOP:
                break
            if op not in END_OP_ARGS and op != 6:
                raise SystemExit(f'fmv_subgen: END.EXE script {k}: unknown opcode {op:#x}')
            if op in END_OP_ARGS:
                if op == END_OP_MOVIE:
                    movies.add(u(at, '<H'))
                at += 2
    return movies


def build_data(open_only=False, movies=None, suffix=None):
    """One payload. `open_only`: OPEN.EXE's opening quote; `movies`: only
    these movies' entries (END.EXE's endings), written under `suffix`."""
    (cw, ch), adv, cells, ext = render_atlas()
    entries = collect(adv, ext, open_only=open_only)
    if movies is not None:
        entries = {no: lst for no, lst in entries.items() if no in movies}

    for lst in entries.values():
        for e in lst:
            y0, rows, x0, w = e[3]
            if rows * w * 3 + 16 > SCRATCH_WINDOW or y0 < 0 or y0 + rows > 240:
                raise SystemExit(f'fmv_subgen: band {w}x{rows}+{y0} does not fit the scratch window')

    # text ids in first-seen order
    texts, text_ids = [], {}

    def tid_of(s):
        i = text_ids.setdefault(s, len(texts))
        if i == len(texts):
            texts.append(s)
        return i

    for lst in entries.values():
        for e in lst:
            for _x, _y, _bi, t in e[8]:
                tid_of(t)

    text_blob = bytearray()
    text_off = []
    for s in texts:
        text_off.append(len(text_blob))
        text_blob += s.encode('ascii') + b'\x00'

    # ---- lay out: header | adv | span pointers | spans | lists | pool | text
    hdr_size = 0x18 + 4 * MOVIE_COUNT + 12   # clamp + paste + additive pointers
    off_adv = hdr_size
    off_ptrs = (off_adv + len(adv) + 3) & ~3
    off_spans = off_ptrs + len(cells) * 4
    used = None
    if open_only:
        used = set()          # every opening line uses compiled additive ink
    ptrs, spans = pack_spans(cells, cw, ch, off_ptrs, off_spans, used=used)
    off_lists = (off_spans + len(spans) + 3) & ~3

    def rec_size(e):
        return 32 + 8 * len(e[8])

    list_size = sum(rec_size(e) for lst in entries.values() for e in lst) + 40 * len(entries)
    off_pool = (off_lists + list_size + 3) & ~3

    pool = bytearray()
    zoom_aux = bytearray()

    if 0x80128000 + 8 * fmv_ink.MAX_RECIPES * 4 > ZOOM_AUX_BASE:
        raise SystemExit('fmv_subgen: compiled-ink lookups overlap auxiliary zoom bank')

    def pool_add(data):
        # Every object in the pool is 4-byte aligned: the renderer reads a
        # scale as lhu and the entry's tex_ptr with lw-sized moves, and the
        # R3000 traps on unaligned loads.
        while len(pool) & 3:
            pool.append(0)
        at = len(pool)
        pool.extend(data)
        return at

    ink_at = {}
    for lst in entries.values():
        for e in lst:
            if e[2] & F_INK:
                if len(e[8]) > 8:
                    raise SystemExit('fmv_subgen: compiled ink exceeds eight line lookups')
                for x, y, _bi, text in e[8]:
                    key = (x, y, text)
                    if key not in ink_at:
                        ink_at[key] = pool_add(fmv_ink.compile_line(text, x, y, cells, adv))

    tex_pool = bytearray()
    patch_at = {}
    list_bytes = bytearray()
    list_ptr = [0] * MOVIE_COUNT
    for no in sorted(entries):
        list_ptr[no] = DATA_BASE + off_lists + len(list_bytes)
        for e in entries[no]:
            f0, f1, flags, band, patch, scale, alphas, shift, gl, pan, ztab, lift = e
            (band_y0, band_rows, band_x0, band_w) = band
            patch_ptr = scale_ptr = alpha_ptr = 0
            tex_ptr = zoom_ptr = 0
            # Patches are palette-expanded on the CPU. The old raw texture
            # uploads are unreachable and their RAM window is decoder-owned;
            # do not stage unused copies over the compiled-ink lookup window.
            if patch is not None:
                # one patch per movie, shared by its entries
                if id(patch) not in patch_at:
                    if flags & F_ZOOM:
                        count = max(ztab) + 1
                        stride = (((band_w + 3) & ~3) + 8) * band_rows + 4
                        if len(patch) != 776 + count * stride:
                            raise SystemExit('fmv_subgen: zoom patch geometry does not match its levels')
                        pointers = []
                        for index in range(count):
                            pixels = patch[776 + index * stride:776 + (index + 1) * stride]
                            if open_only and len(zoom_aux) + len(pixels) <= ZOOM_AUX_END - ZOOM_AUX_BASE:
                                pointers.append(ZOOM_AUX_BASE + len(zoom_aux))
                                zoom_aux.extend(pixels)
                            else:
                                pointers.append(DATA_BASE + off_pool + pool_add(pixels))
                        head = patch[:776] + struct.pack('<HH', count, 0)
                        head += struct.pack('<' + 'I' * count, *pointers)
                        patch_at[id(patch)] = pool_add(head)
                    else:
                        patch_at[id(patch)] = pool_add(patch)
                patch_ptr = DATA_BASE + off_pool + patch_at[id(patch)]
            if ztab is not None:
                zoom_ptr = DATA_BASE + off_pool + pool_add(ztab)
            if scale is not None:
                # a lifted entry's u8 lift per frame follows its scale table
                at = pool_add(b''.join(int(sc).to_bytes(2, 'little') for sc in scale)
                              + (bytes(lift) if lift else b''))
                scale_ptr = DATA_BASE + off_pool + at
            if alphas:
                alpha_ptr = DATA_BASE + off_pool + pool_add(b''.join(bytes(t) for t in alphas))
            rec = bytearray(rec_size(e))
            struct.pack_into('<HHBBBB', rec, 0, f0 & 0xFFFF, f1 & 0xFFFF,
                             len(gl), flags, band_y0 & 0xFF, band_rows & 0xFF)
            struct.pack_into('<III', rec, 8, patch_ptr, scale_ptr, alpha_ptr)
            rec[20] = shift
            rec[21] = pan[0] & 0xFF     # pan at f0, 1/8 px
            rec[24] = pan[2] & 0xFF     # measured window, frames after f0
            rec[25] = pan[3] & 0xFF
            struct.pack_into('<H', rec, 22, band_x0 & 0xFFFF)
            struct.pack_into('<H', rec, 26, band_w & 0xFFFF)
            # +28 is 4-byte aligned: the R3000 traps on an unaligned lw. A
            # zoomed entry puts its per-frame level table there; the pan
            # slope shares the top byte, and a zoomed entry has no pan.
            if flags & F_ZOOM:
                struct.pack_into('<I', rec, 28, zoom_ptr)
            else:
                struct.pack_into('<I', rec, 28, tex_ptr)
                rec[31] = pan[1] & 0xFF     # slope of the pan, 1/256 px per frame
            painted_ink = set()
            for slot, (x, y, bi, t) in enumerate(gl):
                overlap = 0
                if flags & F_INK:
                    pixels = set(fmv_ink.line_pixels(t, x, y, cells, adv))
                    overlap = int(bool(painted_ink & pixels))
                    painted_ink.update(pixels)
                struct.pack_into('<IBBBB', rec, 32 + slot * 8, 0, x & 0xFF, y & 0xFF, bi & 0xFF, overlap)
            list_bytes += rec
        list_bytes += struct.pack('<HH', 0xFFFF, 0) + bytes(36)   # end of list

    # the additive blend's saturate table: v -> min(v, 255) for v in 0..510
    clamp_at = pool_add(bytes(min(v, 255) for v in range(512)))

    # text pointers (off_text is known only now)
    off_text = off_pool + len(pool)
    pos = 0
    for no in sorted(entries):
        for e in entries[no]:
            for slot, (_x, _y, _bi, t) in enumerate(e[8]):
                pointer = (DATA_BASE + off_pool + ink_at[(_x, _y, t)] if e[2] & F_INK
                           else DATA_BASE + off_text + text_off[tid_of(t)])
                struct.pack_into('<I', list_bytes, pos + 32 + slot * 8, pointer)
            pos += rec_size(e)
        pos += 40

    blob = bytearray(off_text + len(text_blob))
    struct.pack_into('<IHHHH', blob, 0, HDR_MAGIC, cw, ch, len(adv), cw * 2)
    struct.pack_into('<I', blob, 0x18 + 4 * MOVIE_COUNT, DATA_BASE + off_pool + clamp_at)
    struct.pack_into('<I', blob, 0x0C, DATA_BASE + off_adv)
    struct.pack_into('<I', blob, 0x10, DATA_BASE + off_spans)
    struct.pack_into('<I', blob, 0x14, DATA_BASE + off_ptrs)
    for i, p in enumerate(list_ptr):
        struct.pack_into('<I', blob, 0x18 + i * 4, p)
    blob[off_adv:off_adv + len(adv)] = bytes(adv)
    blob[off_ptrs:off_ptrs + len(ptrs)] = ptrs
    blob[off_spans:off_spans + len(spans)] = spans
    blob[off_lists:off_lists + len(list_bytes)] = list_bytes
    blob[off_pool:off_pool + len(pool)] = pool
    blob[off_text:off_text + len(text_blob)] = text_blob

    # The paste table rides after the text. OPEN uses only compiled additive
    # lines, so carries neither a glyph atlas nor a blend table.
    while len(blob) & 3:
        blob.append(0)
    t_tab = blend_table()
    tab_at = len(blob)
    # Compiled additive ink evaluates its small expression dictionary exactly
    # with integer arithmetic. Only live-frame/paste text needs the 64K table.
    if not open_only:
        blob += t_tab
    struct.pack_into('<I', blob, 0x18 + 4 * MOVIE_COUNT + 4, DATA_BASE + tab_at)
    struct.pack_into('<I', blob, 0x18 + 4 * MOVIE_COUNT + 8, 0)  # reserved

    if suffix is None:
        suffix = '_open' if open_only else ''
    open(os.path.join(ROOT, 'build', f'movie_subs{suffix}_tex.bin'), 'wb').write(bytes(tex_pool))
    open(os.path.join(ROOT, 'build', f'movie_subs{suffix}_zoom.bin'), 'wb').write(bytes(zoom_aux))
    total = CODE_SIZE + len(blob)
    _patch = sum(len(e[4]) for lst in entries.values() for e in lst if e[4])
    _atlas = len(spans) + len(ptrs) + len(text_blob)
    limit = OPEN_BLOB_END if open_only else BLOB_END
    if SCRATCH + SCRATCH_WINDOW > CODE_BASE or DATA_BASE + len(blob) > limit:
        print(f'fmv_subgen: blob {total:#x} (patch {_patch:#x}, atlas/text {_atlas:#x}, '
              f'lists {list_size:#x}) window {limit - CODE_BASE:#x}')
        raise SystemExit(f'fmv_subgen: blob/scratch do not fit 0x80140000..{limit:#x} '
                         f'(scratch ends {SCRATCH + SCRATCH_WINDOW:#x}, blob ends {DATA_BASE + len(blob):#x})')
    if open_only:
        # CdReadPolled() asks the BIOS for whole sectors, so the loader writes
        # past t_size up to the next 2048-byte boundary. Check the rounded
        # image too: the title pack starts at OPEN_BLOB_END.
        read_end = LOAD_ADDR + ((CODE_BASE - LOAD_ADDR + total + SECTOR - 1)
                                & ~(SECTOR - 1))
        if read_end > OPEN_BLOB_END:
            raise SystemExit(f'fmv_subgen: OPEN.EXE sector-rounded load ends at '
                             f'{read_end:#x}, past OPEN.BIN at {OPEN_BLOB_END:#x}')
    if open_only and tex_pool:
        raise SystemExit(f'fmv_subgen: opening blob needs {len(tex_pool):#x} bytes of plate '
                         f'texture, but OPEN.EXE has no free window for it')
    print(f'fmv_subgen: {suffix or "_full"} {sum(len(v) for v in entries.values())} entries, '
          f'atlas {cw}x{ch}, blob {total:#x} bytes ({total / 2048:.1f} sectors)')
    return bytes(blob)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'data'
    build = os.path.join(ROOT, 'build')
    os.makedirs(build, exist_ok=True)
    if mode == 'data':
        open(os.path.join(build, 'movie_subs_data.bin'), 'wb').write(build_data())
        open(os.path.join(build, 'movie_subs_open_data.bin'), 'wb').write(build_data(open_only=True))
        open(os.path.join(build, 'movie_subs_end_data.bin'), 'wb').write(
            build_data(movies=end_movies(), suffix='_end'))
    elif mode == 'pack':
        code = open(os.path.join(build, 'movie_subs_code.bin'), 'rb').read()
        if len(code) > CODE_SIZE:
            raise SystemExit(f'fmv_subgen: renderer code is {len(code):#x} bytes (max {CODE_SIZE:#x})')
        for data_name, out_name in (('movie_subs_data.bin', 'movie_subs.bin'),
                                    ('movie_subs_open_data.bin', 'movie_subs_open.bin'),
                                    ('movie_subs_end_data.bin', 'movie_subs_end.bin')):
            data = open(os.path.join(build, data_name), 'rb').read()
            out = code.ljust(CODE_SIZE, b'\x00') + data
            open(os.path.join(build, out_name), 'wb').write(out)
            print(f'fmv_subgen: packed {out_name} ({len(out):#x} bytes)')


if __name__ == '__main__':
    main()
