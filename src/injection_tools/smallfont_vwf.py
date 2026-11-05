"""Variable-width data for the 8x12 small font (menus, names, the ぞくせい line).

  python src/injection_tools/smallfont_vwf.py build    write build/sf_width.bin, build/affinity_pool.bin + the recorder copies
  python src/injection_tools/smallfont_vwf.py report   pixel width of every affinity line under VWF
  python src/injection_tools/smallfont_vwf.py verify   (build.py, after armips) the kit read back from the assembled files
  python src/injection_tools/smallfont_vwf.py variants (once) create the editable compact Latin sheet
  python src/injection_tools/smallfont_vwf.py names    live stage/width report for every item/demon name

The kit renders variable-width rows with the game's own GPU path: the
overlay's writer hook RECORDS the row (src/asm/vwf/smallfont.asm - it does
NOT touch the map), and the overlay's renderer, entered from the FONT.BIN
sort gate, clears the cells of exactly the records it is about to draw and
re-emits each one as one GPU sprite per glyph at its pen offset, reading
pixels from the font page the game itself loaded into VRAM.

Outputs (consumed by the overlay wrappers in src/asm/{adv,dng,s2d}):
  sf_width.bin       256 x u8 per code, PACKED: high nibble = the glyph's
                     LEFT BEARING (where its first ink pixel sits in the
                     cell), low nibble = the pen advance (the glyph's ink
                     extent + LETTER_GAP; the shadow does not widen it). The
                     renderer draws the cell at pen - bearing, so every pair
                     of glyphs is separated by the same gap whatever their
                     bearing; blank cells are advance 1, bearing 0. ONE copy,
                     resident in SLPS.
  btl_sf_width.bin   256 x u8 battle copy of the same table where every
                     code outside the text-cell class is forced to the retail
                     8 px cell (0x08: bearing 0, advance 8). The battle bridge
                     reads it to keep numbers, icons, kana and the unanalysed
                     placeholder on the original artwork while text stays
                     proportional.
  build/sf_field_width.bin
                     256 x u8 per code for the field page: low nibble = the
                     regular advance, high nibble = the compact face's
                     independently measured advance. The word space is
                     SPACE_ADV (4) and each stage halves it (4 -> 2 -> 1).
  affinity_pool.bin  120 x u16 offsets into FF-terminated line text: the
                     remainder of an affinity line longer than its record's
                     own 25-cell slot, which carries the head (see write_pool
                     below). Entries share suffixes, so a tail that ends
                     another entry reuses its offset: ONE copy per distinct
                     ending, not per line.
  build/smallfont_<adv,dng,s2d>.asm
                     the row recorder, placed by its wrapper in a dead
                     function of each overlay.
The 8x12 glyph BITMAPS are not stored in the kit's own blocks. Three sources
feed the pages the game loads into VRAM:
  - the retail page's own art: the original fixed-cell font and UI bitmaps;
  - `smallfont_page_modified.png`: the regular proportional face, a Latin-only
    sheet in the same cell order as the compact one (thin_page_indices);
  - `smallfont_page_compact.png`: the independently editable compact face.
`page_indices` composes the field page (original text band plus both Latin
faces in spare kana cells); `thin_page_indices` is the regular face alone and
feeds the battle page and the compact starter. `menu_gfx.py` writes
ADVCMD/ADVCMD0/OPEN, `smallfont_pages.py` the 2D/D0x copies, `btlfont.py` the
battle page. When a sheet is missing, the disc page with the smallfont_lc
redraws is used and only the advances are derived. With `SF_VWF`/`SF_LATIN`
off there is no kit: `page_indices` returns the disc page untouched, so every
copy on the disc stays retail.

Widths are what the port audits must measure against: the retail writer filled
25 cells of 8 px = 200 px, and VWF packs glyphs at their own advance into that
footprint. An affinity line longer than its record is drawn as the record's
head plus the pool tail, so its bound is the map row it is drawn into (the
renderer stops the row at that row's right edge), not the record's cell count;
ROW_PX only reports the
lines that reach past the retail footprint.
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import etext   # noqa: E402
import features  # noqa: E402
import tim     # noqa: E402

ROOT = etext.ROOT
SHEET = os.path.join(ROOT, 'src', 'assets', 'fonts', 'smallfont_page_modified.png')
WIDTH_OUT = os.path.join(ROOT, 'build', 'sf_width.bin')
TEXT_BITS_OUT = os.path.join(ROOT, 'build', 'btl_text_bits.bin')
BTL_WIDTH_OUT = os.path.join(ROOT, 'build', 'btl_sf_width.bin')

GLYPH_W, GLYPH_H = 8, 12
ATLAS_COLS = 31
CODES = 256
LETTER_GAP = 1
SHADOW_IDX = 2                         # the page's drop-shadow colour (ink is 1, accents 3..9)
ROW_PX = 25 * 8                       # the retail row's footprint: 25 cells = 200 px


def PACK(bearing, advance):
    """One sf_width.bin byte: the glyph's left bearing in the high nibble and
    its pen advance in the low one. The renderer draws the cell at pen -
    bearing, so the visible gap is LETTER_GAP for every glyph, not just for
    the ones whose art happens to start at the cell's left edge. Both nibbles
    must hold the value - a wider glyph is a build error, not a silent
    truncation into its neighbour's field."""
    if not (0 <= bearing <= 0xF and 0 <= advance <= 0xF):
        raise SystemExit(
            f'smallfont_vwf: glyph does not fit the packed advance table '
            f'(bearing {bearing}, advance {advance}; a nibble holds 15)')
    return (bearing << 4) | advance


def adv(byte):
    """The pen advance out of a packed sf_width.bin byte."""
    return byte & 0x0F


def text_bits():
    """256 bits, one per small-font code: set when the code prints TEXT - a
    letter, the word space, or one of the text punctuation cells the tables
    encode (`.` `'` `/` `:` `-`). Digits, gauge marks, icons and every other
    glyph stay clear. The battle object-text VWF claims a row only when all of
    its glyphs are text cells, so numbers and non-text artwork keep the retail
    8 px path. Built from the same encoders the writers use (toolbelt's
    small-font table), never from a hand-kept code list."""
    codes = {toolbelt.smallfont_char(c) for c in
             "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .-:/'"}
    if None in codes:
        raise SystemExit('smallfont_vwf: a text character has no small-font code')
    bits = bytearray(CODES // 8)
    for c in codes:
        bits[c >> 3] |= 1 << (c & 7)
    return bytes(bits)

# ',' and '%' are drawn in the page as the Japanese punctuation that already
# sits in the atlas (、/ ％): no new glyph art, and every screen that reads the
# page shows them. The tables' whitelist is extended in skills.encode.
PUNCT_FALLBACK = {',': '、', '%': '％', '(': '（', ')': '）', '!': '！', '<': '＜'}


def disc_page():
    """The retail page exactly as ADV/ADVCMD.BIN carries it (palette + indices)."""
    src = open(tim.locate('ADV/ADVCMD.BIN'), 'rb').read()
    t = tim.parse(src, 0x38)
    w = t['px_w']
    raw = src[t['at']:t['at'] + t['w'] * 2 * t['h']]
    disc = bytearray()
    for b in raw:
        disc += bytes((b & 15, b >> 4))
    return disc, tim.palette(src, t), w


SHADOW_FIX = 0                          # cells repair_shadows() changed (build() reports it)


def repair_shadows(pix):
    """The page's drop shadow is DERIVED, never authored: a shadow pixel belongs
    one right and one down from an ink pixel of its own cell. Keep shadow
    pixels touching ink on the left or above, and cast a (+1,+1) shadow from
    every ink pixel. Return the cells changed."""
    changed = 0
    for code in range(GLYPH_CODES):
        rows = glyph_rows(pix, 256, code)
        ink = {(x, y) for y, r in enumerate(rows) for x in range(GLYPH_W)
               if r[x] and r[x] != SHADOW_IDX}
        sh = {(x, y) for y, r in enumerate(rows) for x in range(GLYPH_W)
              if r[x] == SHADOW_IDX}
        keep = {(x, y) for (x, y) in sh if (x - 1, y) in ink or (x, y - 1) in ink}
        add = {((x + 1), (y + 1)) for (x, y) in ink
               if x + 1 < GLYPH_W and y + 1 < GLYPH_H} - ink
        new = keep | add
        if new == sh:
            continue
        changed += 1
        u, v = (code % ATLAS_COLS) * GLYPH_W, (code // ATLAS_COLS) * GLYPH_H
        for y in range(GLYPH_H):
            for x in range(GLYPH_W):
                if (x, y) in new:
                    pix[(v + y) * 256 + u + x] = SHADOW_IDX
                elif (x, y) in sh:
                    pix[(v + y) * 256 + u + x] = 0
    return changed


def thin_page_indices():
    """256x256 indices: the authored regular face over the retail UI page.

    THE TWO SUBSYSTEMS, AND WHAT EACH GATE MEANS:

    SF_LATIN off   the disc's own page, untouched - the retail font, in which a
                   small-font byte is a kana and english reads as もち.
    SF_LATIN on    the retail page with the LATIN CELLS drawn over its rare
    SF_VWF off     hiragana (smallfont_lc): readable english through the retail
                   renderer. This is the pairing the two things were always
                   meant to have - the cells are not the kit.
    both on        the sheet's own thin art in the editable cells (the kit's
                   widths assume it); the retail kana cells around them stay.

    Every copy goes through here - menu_gfx, smallfont_pages, btlfont - so this
    is the one place that decides it."""
    global SHADOW_FIX
    disc, pal, w = disc_page()

    if not features.on('SF_LATIN'):
        SHADOW_FIX = 0
        return disc, pal, 'disc page (SF_LATIN off: retail font)'
    if not features.on('SF_VWF'):
        SHADOW_FIX = 0
        import smallfont_lc
        smallfont_lc.draw(disc, w)
        return disc, pal, 'disc page + smallfont_lc (SF_VWF off)'

    if not os.path.exists(SHEET):
        SHADOW_FIX = 0
        import smallfont_lc
        smallfont_lc.draw(disc, w)
        return disc, pal, 'disc page + smallfont_lc'

    import smallfont_variants
    try:
        sheet, size = smallfont_variants.sheet_pixels(SHEET, pal)
    except ValueError as exc:
        raise SystemExit(f'smallfont_vwf: {exc}') from exc
    out = bytearray(disc)
    import smallfont_lc
    smallfont_lc.draw(out, w)          # retail base for anything the sheet leaves
    if size == (w, w):
        # Legacy full-page sheet: its glyph band IS the page's text band.
        out[:GLYPH_ROWS * w] = sheet[:GLYPH_ROWS * w]
    else:
        # Latin-only sheet: every slot is drawn into its own editable cell; the
        # retail kana cells around them stay exactly as the game shipped.
        for code in smallfont_variants.editable_codes():
            u, v = smallfont_variants.cell_uv(code)
            for y in range(GLYPH_H):
                out[(v + y) * w + u:(v + y) * w + u + 8] = \
                    sheet[(v + y) * 256 + u:(v + y) * 256 + u + 8]
    SHADOW_FIX = repair_shadows(out)
    return out, pal, os.path.relpath(SHEET, ROOT)


def page_indices():
    """Field page: original fixed-cell art plus separate Latin sprite fonts."""
    regular, pal, source = thin_page_indices()
    if not (features.on('SF_VWF') and features.on('SF_LATIN')):
        return regular, pal, source
    import smallfont_variants
    retail, _, _ = disc_page()
    pix, _ = smallfont_variants.compose(retail, regular, pal, glyph_rows)
    return pix, pal, source + ' + original UI + compact Latin'


def write_sheets():
    """Park the two pages next to the artwork: the retail page (what the game
    shipped, for reverting glyphs) and the page this build actually ships (the
    composed faces with the derived shadow layer). Both are full-page RGB with
    the page's own CLUT, like the legacy form of the authored sheets."""
    from PIL import Image
    disc, pal, w = disc_page()
    pix, _pal, source = page_indices()
    def save(indices, path):
        im = Image.new('RGB', (w, w))
        im.putdata([tuple(pal[i]) for i in indices])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        im.save(path)
        print(f'wrote {os.path.relpath(path, ROOT)}')
    save(disc, os.path.join(ROOT, 'data', 'fonts', 'smallfont_page_retail.png'))
    save(pix, os.path.join(ROOT, 'build', 'previews', 'translation',
                           'smallfont_page_shipped.png'))
    print(f'shipped page: {source} (shadow layer re-derived: {SHADOW_FIX} cells)')


GLYPH_CODES = 215                       # the map's cell table defines codes 0..214 on this page
GLYPH_ROWS = ((GLYPH_CODES + ATLAS_COLS - 1) // ATLAS_COLS) * GLYPH_H   # 84 pixel rows: 7 cell rows


def unpack_page(raw):
    """4bpp TIM bytes -> one palette index per pixel (high nibble first)."""
    pix = bytearray()
    for b in raw:
        pix += bytes((b & 15, b >> 4))
    return pix


def page_copy(copy, ref, sheet, width, rows=256, prior=()):
    """The bytes a page COPY takes from the sheet: the sheet's pixel wherever
    the copy still holds a PAGE's pixel, the copy's own pixel anywhere it does
    not (a copy can own part of the page - the battle page draws icons over the
    last cell rows, ADVCMD0 has its own art in one row).

    `prior` is the page this tool wrote into that copy LAST build (see
    page_last_path): a copy in build/ is not pristine, so a pixel the previous
    sheet put there is ours too and the new sheet replaces it. Without that,
    the first sheet a copy receives would look like the copy's own art forever
    and every later edit of the sheet would stop at the copies that were
    already written (the 2D/D0x maps are rewritten only by this step, so they
    kept the older art while ADVCMD, which is rebuilt from data/psx, updated).

    `copy` is width-stride, `ref`, `sheet` and every `prior` page are
    256-stride."""
    pages = [ref, *prior]
    out = bytearray()
    for y in range(rows):
        cy = y * width
        ry = y * 256
        row = []
        for x in range(width):
            px = copy[cy + x]
            row.append(sheet[ry + x] if any(px == p[ry + x] for p in pages) else px)
        out += bytes(row[x] | (row[x + 1] << 4) for x in range(0, width, 2))
    return bytes(out)


PAGE_LAST = os.path.join(ROOT, 'build', 'smallfont_page_last.bin')


def page_prior():
    """The page the previous build wrote into the page copies: the `prior` of
    page_copy. Empty when there is none (a fresh tree, or one whose build/ was
    cleared)."""
    try:
        raw = open(PAGE_LAST, 'rb').read()
    except FileNotFoundError:
        return []
    if len(raw) != 256 * 256:
        return []
    return [raw]


def save_page_last(pix):
    """Remember the page this build wrote, so the next build can tell it apart
    from the copies' own art (see page_copy's `prior`)."""
    os.makedirs(os.path.dirname(PAGE_LAST), exist_ok=True)
    open(PAGE_LAST, 'wb').write(bytes(pix))


def glyph_rows(pix, w, code):
    u, v = (code % ATLAS_COLS) * GLYPH_W, (code // ATLAS_COLS) * GLYPH_H
    rows = []
    for y in range(GLYPH_H):
        rows.append([pix[(v + y) * w + u + x] for x in range(GLYPH_W)])
    return rows


ENGINE_TPL = os.path.join(ROOT, 'src', 'asm', 'vwf', 'smallfont.asm')


def write_engines():
    """The kit copy per overlay, split in two (build/smallfont_rec_<ovl>.asm
    and build/smallfont_hook_<ovl>.asm): armips symbols are global, so the
    labels carry the overlay suffix. The wrappers place them - the recorder
    in the overlay's HELP dead run, the renderer + thunks in the ROW dead
    run behind the registration guard. `sf_cfg` and `sf_state` are
    suffixed: the config is that overlay's own block at the head of the ROW
    dead run, and the state lives in the overlay's extension - freshly zero
    at every overlay load."""
    tpl = open(ENGINE_TPL).read()
    labels = ('sf_record_end', 'sf_thunks_end', 'sf_hook_fastbg', 'sf_hook_end',
              'sf_hook_bg', 'sf_hook', 'sf_call_fastbg', 'sf_call_bg', 'sf_record',
              'sf_state', 'sf_cfg', 'sf_name_scratch', 'sf_clip_glyph', 'sf_row_reserve',
              'item_name_copy', 'demon_name_copy', 'sf_center_row', 'sf_variant_uv')
    for ovl in ('adv', 'dng', 's2d'):
        out = tpl
        for label in labels:
            out = re.sub(rf'\b{label}\b', f'{label}_{ovl}', out)
        lines = out.split('\n')
        k = next(i for i, l in enumerate(lines) if l.startswith(f'sf_hook_bg_{ovl}:'))
        while k > 0 and lines[k - 1].lstrip().startswith(';;'):
            k -= 1                  # the renderer's comment header goes with it
        rec = '\n'.join(lines[:k]).rstrip() + '\n'
        hook = '\n'.join(lines[k:])
        # Clipping and font UV selection share the overlay's extension. This
        # keeps the bounded DNG/S2D renderer dead runs independent of font art.
        start = hook.index(f'sf_clip_glyph_{ovl}:')
        end = hook.index(f'sf_hook_end_{ovl}:')
        clip = hook[start:end]
        hook = hook[:start] + hook[end:]
        import smallfont_variants
        variant = smallfont_variants.assembly()
        for name in ('sf_variant_uv_end', 'sf_variant_uv', 'sf_variant_cells'):
            variant = re.sub(rf'\b{name}\b', f'{name}_{ovl}', variant)
        open(os.path.join(ROOT, 'build', f'smallfont_helpers_{ovl}.asm'), 'w').write(clip + variant)
        stock = open(toolbelt.bin_path(ovl.upper()), 'rb').read()
        fixed = smallfont_variants.fixed_producers(stock, ovl.upper())
        open(os.path.join(ROOT, 'build', f'smallfont_fixed_{ovl}.asm'), 'w').write(
            '\n'.join(f'.org {at:#x}\n    .word {word:#x}' for at, word in fixed) + '\n')
        for path, body in (
                (os.path.join(ROOT, 'build', f'smallfont_rec_{ovl}.asm'),
                 ';; generated by tools/smallfont_vwf.py build - do not edit\n'
                 ';; (placed by the wrapper: the tail of the overlay data block)\n' + rec),
                (os.path.join(ROOT, 'build', f'smallfont_hook_{ovl}.asm'),
                 ';; generated by tools/smallfont_vwf.py build - do not edit\n'
                 ';; (placed by the wrapper: the overlay renderer dead function)\n' + hook)):
            open(path, 'w', newline='\n').write(body)
        center = open(os.path.join(ROOT, 'src/asm/vwf/sf_center.asm')).read()
        center = re.sub(r'\bsf_center_row\b', f'sf_center_row_{ovl}', center)
        center = re.sub(r'\bsf_center_end\b', f'sf_center_end_{ovl}', center)
        open(os.path.join(ROOT, 'build', f'smallfont_center_{ovl}.asm'), 'w', newline='\n').write(center)
    print('wrote build/smallfont_{rec,hook}_{adv,dng,s2d}.asm')


def build():
    pix, _pal, source = thin_page_indices()
    import smallfont_variants
    retail, _, _ = disc_page()
    _, field_widths = smallfont_variants.compose(retail, pix, _pal, glyph_rows)
    w = 256
    widths = bytearray()
    blank = []
    for code in range(CODES):
        rows = glyph_rows(pix, w, code)
        # Advance from the glyph's INK extent, not its shadow: the shadow is
        # a 1-2 px drop copy under/right of the art and including it made
        # every glyph that much wider (M and i were the visible complaints).
        # The renderer draws the whole cell at pen - bearing, so the shadow
        # still falls where the art puts it; only the pen advance is ink.
        ink = [x for r in rows for x in range(GLYPH_W) if r[x] and r[x] != SHADOW_IDX]
        if not ink:                             # art drawn in the shadow colour alone
            ink = [x for r in rows for x in range(GLYPH_W) if r[x]]
        if not ink:
            # No art: advance only. 1 is the marker the renderer skips the
            # cell on (a drawn glyph's extent is >= 1 px, so its advance is
            # never 1).
            widths.append(PACK(0, 1 if code else LETTER_GAP + 1))
            blank.append(code)
        else:
            lo, hi = min(ink), max(ink)
            widths.append(PACK(lo, (hi - lo + 1) + LETTER_GAP))
    widths[0] = PACK(0, 4)                 # code 0: the space the tables print
    if min(adv(w) for w in widths) < 1:
        raise SystemExit('smallfont_vwf: a zero pen advance (the recorder assumes >= 1)')
    os.makedirs(os.path.dirname(WIDTH_OUT), exist_ok=True)
    open(WIDTH_OUT, 'wb').write(bytes(widths))
    open(os.path.join(ROOT, 'build', 'sf_field_width.bin'), 'wb').write(field_widths)
    text = text_bits()
    open(TEXT_BITS_OUT, 'wb').write(text)
    # THE BATTLE TABLE gives every NON-text code the retail cell's 8 px pitch:
    # the battle bridge draws a text cell from the proportional run, but a
    # number, icon, kana or the unanalysed placeholder keeps its original
    # small-font cell. 0x08 (bearing 0, advance 8) is the sentinel the
    # installed art mapper reads; no text cell has that metric, so the two
    # classes can never be confused.
    battle = bytearray(widths)
    for code in range(CODES):
        if not text[code >> 3] & (1 << (code & 7)):
            battle[code] = PACK(0, GLYPH_W)
    if any(battle[c] == PACK(0, GLYPH_W)
           for c in range(CODES) if text[c >> 3] & (1 << (c & 7))):
        raise SystemExit('smallfont_vwf: a text cell has the fixed 8 px metric')
    open(BTL_WIDTH_OUT, 'wb').write(bytes(battle))
    import battle_text_layout
    stock = open(toolbelt.bin_path('BTLP'), 'rb').read()
    headings = battle_text_layout.centred_headings(stock, widths, text)
    with open(os.path.join(ROOT, 'build', 'btl_text_centres.asm'), 'w') as out:
        out.write(battle_text_layout.assembly(headings))
    write_pool(bytes(widths))
    write_engines()
    used = [c for c in range(CODES) if c not in blank and c != 0]
    avg = sum(adv(widths[c]) for c in used) / len(used)
    print(f'glyph source: {source}')
    if SHADOW_FIX:
        print(f'shadow layer re-derived from ink: {SHADOW_FIX} cells (stale columns fixed)')
    print(f'wrote {WIDTH_OUT} ({len(widths)} bytes)')
    print(f'wrote {TEXT_BITS_OUT} ({len(text)} bytes: the battle text-cell class)')
    print(f'wrote {BTL_WIDTH_OUT} ({len(battle)} bytes: text cells proportional, '
          f'every other cell retail 8 px)')
    print(f'{len(blank)} blank cells, {len(used)} with ink; average advance {avg:.2f} px')
    print(f'affinity row budget {ROW_PX} px = about {ROW_PX / avg:.0f} average glyphs')


POOL_OUT = os.path.join(ROOT, 'build', 'affinity_pool.bin')
POOL_INDEX = 120 * 2            # u16 text offset per record, FFFF = none
RECORD_CAP = 25                 # a record's own slot (affinity.py STRIDE)
POOL_LINE_MAX = 47              # the whole drawn row: head + pool tail


def write_pool(widths):
    """build/affinity_pool.bin = 120 x u16 offsets into FF-terminated tails.

    AN AFFINITY RECORD'S 25-CELL SLOT IS THE LINE'S HEAD. affinity.py writes
    the first RECORD_CAP glyphs of the line there (the whole line when it fits,
    its first cells otherwise); this pool carries exactly the remainder,
    `affinity.encode(...)[RECORD_CAP:]`, and the overlay's recorder appends it
    when it draws the row (vwf/smallfont.asm). One entry therefore exists
    exactly for a line longer than its slot, and the slot plus the entry is the
    whole wording - the slot is never a truncation.

    A line the disc cannot carry at all - a character with no cell, or more
    than POOL_LINE_MAX glyphs, the recorder's code cap - gets no entry and
    keeps its Japanese (`dropped`; affinity.py reports it too).

    ENTRIES SHARE SUFFIXES. Each entry is `tail + FF`, and a reader stops at
    the first FF, so a tail that already ends another entry can simply point
    at that entry's last bytes. Tails are placed longest first and looked up
    as a byte substring (`tail + FF`), which folds `Fire` into `Weak: Fire`
    instead of storing both. The offsets stay u16 and the format is unchanged
    for every overlay; only the blob is smaller."""
    import toolbelt
    import affinity

    tails, dropped = {}, 0
    for r in toolbelt.merged_rows('SLPS_005.00'):
        en = (r.get('en') or '').strip()
        if not en:
            continue
        for _entry, off in toolbelt_offsets(r):
            k = (off - AFF_LO) // 0x19
            if not 0 <= k < 120:
                continue
            try:
                tail = affinity.tail_bytes(k, en)   # the SAME split affinity.py writes
            except SystemExit:
                dropped += 1
                break
            if tail:
                tails[k] = tail
            break
    text = bytearray()
    offset = {}
    for k in sorted(tails, key=lambda k: (-len(tails[k]), k)):
        entry = tails[k] + b'\xff'
        pos = text.find(entry)
        if pos < 0:
            pos = len(text)
            text += entry
        offset[k] = pos
    index = [offset.get(k, 0xFFFF) for k in range(120)]
    n = len(tails)
    out = b''.join(struct.pack('<H', o) for o in index) + bytes(text)
    # THE POOL HAS A STATED ROOM, and it is not the end of memory: each
    # fixed-layout overlay's item-name block starts at <OVL>_ITEM_DATA_ADDR, right after
    # the kit's data. A pool that grows into it is not a warning - armips
    # assembles overlapping .org claims silently, so the pool must fit fully
    # before the next block. ADV instead guards its packed extension as a whole.
    import toolbelt
    st_end = toolbelt.asm_equ('SF_ST_END',
                              os.path.join(ROOT, 'src', 'asm', 'vwf', 'smallfont_defs.asm'))
    room = None
    for ovl in ('DNG', 'S2D'):
        start = toolbelt.asm_equ(f'{ovl}_SF_DATA_ADDR') + st_end + len(widths)
        left = toolbelt.asm_equ(f'{ovl}_ITEM_DATA_ADDR') - start
        room = left if room is None else min(room, left)
    # BTLP's copy sits between the trait buffer code and the first BTLP
    # variable the battle runtime writes (0x800F85B0, a heap pointer); the
    # text must end before that word, never merely before the next .org.
    btlp_room = (toolbelt.asm_equ('BTLP_TRAIT_POOL_END')
                 - toolbelt.asm_equ('BTLP_TRAIT_POOL_ADDR'))
    room = btlp_room if room is None else min(room, btlp_room)
    if len(out) > room:
        raise SystemExit(
            f'smallfont_vwf: the affinity pool is {len(out)} bytes but only '
            f'{room} fit before the next owned block or live BTLP word - '
            f'raise the owned data window in addresses.inc')
    open(POOL_OUT, 'wb').write(out)
    print(f'wrote {POOL_OUT} ({len(out)} bytes: {POOL_INDEX} index + {len(text)} text, '
          f'{n} line tails the record cannot hold, {dropped} rows the record cannot carry)')


def toolbelt_offsets(r):
    import toolbelt
    return toolbelt.pos_offsets(r['pos'])


def char_code(c):
    """small-font code for one character (the tables' encoding + , and %)."""
    c = etext.spell(c)                 # '’' is the ASCII apostrophe's cell
    if c in PUNCT_FALLBACK:
        return etext.char2g[PUNCT_FALLBACK[c]]
    import skills
    return skills.glyph(c)


def require_viewport_clamp(words, context):
    """Verify the assembled emitter loads and enforces the viewport right edge."""
    load_right = 0x8FB20038       # lw s2,0x38(sp): viewport right
    compare = 0x0152702A          # slt t6,t2,s2: glyph left < viewport right
    if load_right not in words or not any(
            words[i] == compare and words[i + 1] & 0xFFFF0000 == 0x11C00000
            for i in range(len(words) - 1)):  # beqz t6,...
        raise SystemExit(f'smallfont_vwf: verify: {context} lost the viewport-right '
                         'load or glyph-edge branch. See vwf/smallfont.asm.')


def require_retained_geometry(codes, widths, *, columns, column, scroll, viewport):
    """Reject unsupported retained-name geometry; callers must supply real map data.

    This is a QA probe, not evidence that every live consumer has been audited.
    A successful result proves one copy's complete nonblank glyph quads fit the
    view under the current bounded single-copy renderer. It checks exactly the
    earlier/current/next copy candidates and fails closed if the view is wider
    than the ring or more distant copies could reach it.
    """
    if columns <= 0 or not 0 <= column < columns or viewport <= 0:
        raise ValueError('invalid retained-name geometry')
    period = columns * GLYPH_W
    if viewport > period:
        raise ValueError('unsupported retained-name geometry: viewport wider than ring')
    pen = column * GLYPH_W - (scroll % period)
    boxes = []
    for code in codes:
        if not 0 <= code < len(widths):
            raise ValueError('invalid retained-name glyph')
        metric = widths[code]
        advance = adv(metric)
        if not advance:
            raise ValueError('invalid retained-name advance')
        if advance != 1:
            left = pen - (metric >> 4)
            boxes.append((left, left + GLYPH_W))
        pen += advance
    if not boxes:
        raise ValueError('empty retained-name geometry')
    import toolbelt
    defs = os.path.join(ROOT, 'src', 'asm', 'vwf', 'smallfont_defs.asm')
    cap = toolbelt.asm_equ('SF_ROW_REC', defs) - toolbelt.asm_equ('SF_REC_CODES', defs) - 1
    if len(codes) > cap:
        raise ValueError('unsupported retained-name geometry: record too long')
    # Find every potentially visible ring copy, including tails longer than a
    # period; the record and viewport bounds make this enumeration finite.
    lo = (-max(right for _, right in boxes)) // period - 1
    hi = (viewport - min(left for left, _ in boxes)) // period + 1
    visible = []
    for copy in range(lo, hi + 1):
        shift = copy * period
        if any(left + shift < viewport and right + shift > 0 for left, right in boxes):
            visible.append(shift)
    if len(visible) != 1 or visible[0] not in (0, period):
        raise ValueError('unsupported retained-name geometry: multiple or earlier ring copy')
    shift = visible[0]
    if any(left + shift < 0 or right + shift > viewport for left, right in boxes):
        raise ValueError('unsupported retained-name geometry: retained tail is clipped')
    return shift


def _widths():
    if not os.path.exists(WIDTH_OUT):
        build()
    with open(WIDTH_OUT, 'rb') as f:
        return f.read()


def codes_px(codes):
    """Drawn width of small-font glyph codes (the page's own numbering)."""
    widths = _widths()
    return sum(adv(widths[c]) for c in codes)


def line_px(t):
    return codes_px(char_code(c) for c in t)


def field_line_px(t):
    """Drawn width of a row the field kit renders.

    The field page's table is not sf_width.bin: its Latin cells use the
    regular atlas advances and its non-Latin cells keep the retail 8 px
    pitch. A field row is measured with that table, exactly as the recorder
    and emitter read it."""
    widths = _field_widths()
    return sum(tier_adv(widths[char_code(c)], char_code(c), 0) for c in t)


# ---- the condensed tier for fixed name rows ----
#
# An item/demon name row is the caller's own ten 8-px cells: the row cannot
# grow and the wording is never shortened.  The renderer can instead tighten
# the row by the least aggressive step that makes the whole name fit:
#
#   tier 0  the page's own advances
#   tier 1  the word space advances 2 px instead of 4
#   tier 2  the separately authored compact face, 1-px letter gaps, 1-px spaces
#
# The recorder measures the row against the caller's footprint (8 px per
# cell), stores the chosen tier in the record's pad word, and the emitter
# applies these advances while drawing.  This module's measurement is the
# same rule, so the porter accepts exactly what the screen can show.  The
# renderer implements it in asm/vwf/smallfont_defs.asm (`sf_field_metric`);
# keep the two in lockstep.
SPACE_CODE = 0
MIN_ADV = 1                 # a pen step is never zero
CONDENSED = (0, 1, 2)


def tier_adv(metric, code, tier):
    """The pen advance at `tier` for one packed field-width byte.

    Derives everything from the byte so the porter, the report and the
    assembled renderer cannot disagree: the low nibble is the normal advance,
    the high nibble the independently measured compact advance, and a word
    space halves per stage (4 -> 2 -> 1 px)."""
    a = adv(metric)
    if code == SPACE_CODE:
        return max(a >> tier, MIN_ADV)
    if tier < 2:
        return a
    return max(metric >> 4, MIN_ADV)


_FIELD_CACHE = None


def _field_widths():
    global _FIELD_CACHE
    import smallfont_variants
    def stamp(path):
        try:
            return os.stat(path).st_mtime_ns
        except OSError:
            return 0
    key = (stamp(SHEET), stamp(smallfont_variants.COMPACT))
    if _FIELD_CACHE is not None and _FIELD_CACHE[0] == key:
        return _FIELD_CACHE[1]
    regular, pal, _ = thin_page_indices()
    retail, _, _ = disc_page()
    _, metrics = smallfont_variants.compose(retail, regular, pal, glyph_rows)
    _FIELD_CACHE = key, metrics
    return metrics


def prepare_variants():
    import smallfont_variants
    regular, palette, _ = thin_page_indices()
    smallfont_variants.prepare(regular, palette, glyph_rows)
    path = os.path.join(ROOT, 'build', 'smallfont_compact_cells.tsv')
    reverse = {toolbelt.smallfont_char(c): c for c in smallfont_variants.CHARS}
    regular_cells, compact_cells = smallfont_variants.cell_codes()
    cols = smallfont_variants.EDIT_COLS
    with open(path, 'w') as output:
        output.write('character\tcode\tx\ty\tregular_cell\tregular_x\tregular_y'
                     '\tcompact_cell\tcompact_x\tcompact_y\n')
        for slot, code in enumerate(smallfont_variants.editable_codes()):
            regular_cell, compact_cell = regular_cells[slot], compact_cells[slot]
            rx, ry = smallfont_variants.cell_uv(regular_cell)
            cx, cy = smallfont_variants.cell_uv(compact_cell)
            output.write(f'{reverse[code]}\t{code:#x}\t{slot % cols * 8}\t{slot // cols * 12}'
                         f'\t{regular_cell:#x}\t{rx}\t{ry}'
                         f'\t{compact_cell:#x}\t{cx}\t{cy}\n')
    print(f'cell index: {path}')


def names_report():
    """Live artwork measurements, not cached build widths or drafted wording."""
    import argparse
    import csv
    import name_tails
    parser = argparse.ArgumentParser(description='Name stages: 1 normal, 2 narrow spaces, 3 compact font. '
                                    'Widths include the trailing 1px letter gap (80px field = 79px ink).')
    parser.add_argument('--over', action='store_true', help='only names wider than the normal field')
    parser.add_argument('--items-only', action='store_true')
    parser.add_argument('--tsv', action='store_true', help='tab-separated output (also the default)')
    args = parser.parse_args(sys.argv[2:])
    metrics = _field_widths()
    writer = csv.writer(sys.stdout, delimiter='\t', lineterminator='\n')
    writer.writerow(('family', 'id', 'name', 'stage', 'normal_px', 'spaces_px', 'compact_px',
                     'normal_spare', 'spaces_spare', 'compact_spare', 'selected_ink_px'))
    families = [('items', name_tails.item_rows())]
    if not args.items_only:
        families.append(('demons', name_tails.demon_rows()))
    for family, rows in families:
        for ident, text in rows:
            codes = tuple(char_code(c) for c in text)
            # Same rule as the renderer: spaces halve per stage, glyphs
            # switch nibble at stage 3 (asm/vwf/smallfont_defs.asm).
            widths = tuple(sum(tier_adv(metrics[c], c, tier) for c in codes)
                           for tier in CONDENSED)
            if args.over and widths[0] <= 80:
                continue
            stage = next((i for i, width in enumerate(widths, 1) if width <= 80), None)
            writer.writerow((family, ident, text, stage or 'OVER', *widths,
                             *(80 - width for width in widths),
                             widths[stage - 1] - 1 if stage else 'OVER'))


def condensed_tier(codes, budget, widths=None):
    """(tier, px): the least aggressive tier whose drawn width fits `budget`.

    `tier` is None when even tier 2 does not fit; `px` is then the
    un-tightened width, the number a porter reports as over the row.
    `widths` is the packed field table; tests pass the built file so their
    expectations cannot race a sheet edit."""
    codes = tuple(codes)
    widths = _field_widths() if widths is None else widths
    natural = sum(adv(widths[c]) for c in codes)
    if natural <= budget:
        return 0, natural
    for tier in CONDENSED[1:]:
        px = sum(tier_adv(widths[c], c, tier) for c in codes)
        if px <= budget:
            return tier, px
    return None, natural


AFF_LO = 0x8004C848 - 0x8000F800          # affinity record offsets in the SLPS row store
AFF_HI = AFF_LO + 120 * 0x19


def _aff_rows():
    import toolbelt
    for rel, read in (('generated', toolbelt.read_generated), ('manual', toolbelt.read_manual)):
        for r in read('SLPS_005.00'):
            for _entry, off in toolbelt.pos_offsets(r['pos']):
                if AFF_LO <= off < AFF_HI:
                    yield rel, r
                    break


def report():
    if not os.path.exists(WIDTH_OUT):
        build()
    widths = open(WIDTH_OUT, 'rb').read()
    over, fit = [], []
    for _rel, r in _aff_rows():
        en = (r.get('en') or '').strip()
        if not en:
            continue
        px = field_line_px(en)
        (fit if px <= ROW_PX else over).append((px, en))
    en_avg = [adv(widths[char_code(c)]) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .-/:'"]
    print(f'English glyph advance: min {min(en_avg)} avg {sum(en_avg)/len(en_avg):.2f} max {max(en_avg)} px')
    print(f'affinity lines: {len(fit) + len(over)}  fit under {ROW_PX} px: {len(fit)}  still over: {len(over)}')
    for px, en in sorted(fit)[:10]:
        print(f'  {px:3d}px  {en[:70]}')
    print('  ...')
    for px, en in sorted(over, reverse=True)[:5]:
        print(f'  {px:3d}px  {en[:70]}')


def _j_word(target):
    return 0x08000000 | ((target >> 2) & 0x3FFFFFF)


def _verify_sort_stub(words, at, cell, gate, magic, name):
    """Require the registration load, gate jump, and its safe delay slot."""
    want = (0x3C080000 | ((cell >> 16) & 0xFFFF),
            0x8D080000 | (cell & 0xFFFF),
            _j_word(gate), 0x340C0000 | magic, 0)
    if tuple(words) != want:
        raise SystemExit(
            f'smallfont_vwf: verify: the {name} stub at {at:#x} does not read '
            f'lui/lw t0, {cell:#x} / j {gate:#x} / ori t4, magic / nop '
            f'({tuple(hex(x) for x in words)}). See vwf/sf_stubs.asm.')


def _verify_sort_gate(words, at, replay, name):
    """Require the guard load delay, exact replay branch, and jump delays."""
    if len(words) != 6 or (words[0], words[1], words[2] >> 16,
                           words[3], words[4], words[5]) != (
            0x8D0BFFFC, 0, 0x156C, 0, 0x01000008, 0):
        raise SystemExit(
            f'smallfont_vwf: verify: the {name} gate at {at:#x} lost its '
            f'guard load / nop / bne / nop / jr t0 / nop '
            f'({tuple(hex(x) for x in words)}). See vwf/sf_font.asm.')
    displacement = words[2] & 0xFFFF
    if displacement & 0x8000:
        displacement -= 0x10000
    branch_to = at + 12 + displacement * 4  # branch word 2, relative to PC+4
    if branch_to != replay:
        raise SystemExit(
            f'smallfont_vwf: verify: the {name} gate branches to {branch_to:#x}, '
            f'want the replay at {replay:#x}. See vwf/sf_font.asm.')


def verify():
    """After armips: require the kit back from the assembled files.
    armips assembles overlapping .org claims in silence (last write
    wins). Checked here: SLPS carries no appended bytes and its
    sorter stubs jump into FONT.BIN; FONT.BIN's gate, replays and
    registration cells read back exactly; each overlay's config, guard,
    recorder, renderer, own tables and full-name block are in place.
    build.py runs this after the armips pass."""
    import struct
    import smallfont_variants
    widths = open(WIDTH_OUT, 'rb').read()
    field_widths = open(os.path.join(ROOT, 'build', 'sf_field_width.bin'), 'rb').read()
    if field_widths[0] != 0x14:
        raise SystemExit(
            'smallfont_vwf: verify: the packed word space is not 4 px normal / '
            '1 px compact; the recorder\'s tier-1 saving and tier-2 nibble '
            'assume it. See smallfont_variants.SPACE_ADV.')
    pool = open(POOL_OUT, 'rb').read()
    defs = os.path.join(ROOT, 'src', 'asm', 'vwf', 'smallfont_defs.asm')
    magic = toolbelt.asm_equ('SF_ENG_MAGIC', defs)
    reg_magic = toolbelt.asm_equ('SF_REG_MAGIC', defs)
    cfg_end = toolbelt.asm_equ('SF_CFG_END', defs)
    st_end = toolbelt.asm_equ('SF_ST_END', defs)
    table_size = toolbelt.asm_equ('SF_ROWS', defs) * toolbelt.asm_equ('SF_ROW_REC', defs)
    buf_size = toolbelt.asm_equ('SF_BUF_SIZE', defs)
    bufs = toolbelt.asm_equ('SF_BUFS', defs)
    gsort_bg = toolbelt.asm_equ('GSORT_BG_ADDR')
    gsort_fast = toolbelt.asm_equ('GSORT_FASTBG_ADDR')
    slot_addr = toolbelt.asm_equ('OVERLAY_SLOT_ADDR')

    sym = {}
    for line in open(os.path.join(ROOT, 'build', 'persona.sym')):
        m = re.match(r'^([0-9A-Fa-f]{8})\s+(\S+)', line)
        if m:
            sym[m.group(2)] = int(m.group(1), 16)

    # --- SLPS: retail-sized, retail header, stubs into FONT.BIN ---
    slps = open(os.path.join(ROOT, 'build', 'SLPS_005.00'), 'rb').read()
    orig_slps = open(os.path.join(ROOT, 'data', 'psx', 'SLPS_005.00'), 'rb').read()
    SLPS_BASE = 0x80010000 - 0x800
    if len(slps) != len(orig_slps):
        raise SystemExit(
            f'smallfont_vwf: verify: build/SLPS_005.00 is {len(slps)} bytes, retail is '
            f'{len(orig_slps)} - the image GREW. The game wipes its BSS above the image '
            f'at boot and the BIOS dies past ~0x5C000: NOTHING may be appended to '
            f'SLPS_005.00 (see addresses.inc).')
    tsize, = struct.unpack_from('<I', slps, 0x1C)
    if tsize != 0x46000:
        raise SystemExit(
            f'smallfont_vwf: verify: the SLPS header t_size is {tsize:#x}, retail is '
            f'0x46000 - the image grew through the header word. See addresses.inc.')
    for name, at, gate, cell in (
            ('GsSortBg', gsort_bg, 'SF_FONT_GATE_BG', 'SF_FONT_CELL_BG'),
            ('GsSortFastBg', gsort_fast, 'SF_FONT_GATE_FAST', 'SF_FONT_CELL_FAST')):
        w = struct.unpack_from('<5I', slps, at - SLPS_BASE)
        _verify_sort_stub(w, at, toolbelt.asm_equ(cell),
                          toolbelt.asm_equ(gate), reg_magic, name)
    print('smallfont_vwf: verify: SLPS: retail-sized, stubs jump into FONT.BIN')

    # --- affinity lines: record head + pool tail read back as the wording ---
    # The split is the only thing the recorder relies on (vwf/smallfont.asm
    # continues a row at SF_ROW_BYTES), so verify both halves from the disc:
    # the record carries the line's head and the pool carries exactly the rest.
    import affinity
    pool_index = struct.unpack_from(f'<{120}H', pool)
    checked = 0
    for r in toolbelt.merged_rows('SLPS_005.00'):
        en = (r.get('en') or '').strip()
        if not en:
            continue
        for _entry, off in toolbelt_offsets(r):
            k = (off - AFF_LO) // 0x19
            if not 0 <= k < 120:
                continue
            try:
                head = affinity.record_bytes(k, en)
                tail = affinity.tail_bytes(k, en)
            except SystemExit:
                break               # the record stays Japanese
            got = slps[off:off + len(head)]
            if got != head:
                raise SystemExit(
                    f'smallfont_vwf: verify: affinity record {k} at {off:#x} reads '
                    f'{got.hex()}, want {head.hex()} - the record is not the line\'s '
                    f'head. See affinity.py record_bytes().')
            if tail:
                o = pool_index[k]
                if o == 0xFFFF:
                    raise SystemExit(
                        f'smallfont_vwf: verify: affinity record {k} needs the pool tail '
                        f'{tail!r} but build/affinity_pool.bin has no entry for it.')
                got = pool[POOL_INDEX + o:POOL_INDEX + o + len(tail) + 1]
                if got != tail + b'\xff':
                    raise SystemExit(
                        f'smallfont_vwf: verify: affinity record {k} pool entry reads '
                        f'{got.hex()}, want {tail.hex()}ff - the pool is stale. '
                        f'See smallfont_vwf.py write_pool().')
            elif pool_index[k] != 0xFFFF:
                raise SystemExit(
                    f'smallfont_vwf: verify: affinity record {k} holds its whole line '
                    f'but build/affinity_pool.bin carries a tail for it.')
            checked += 1
            break
    print(f'smallfont_vwf: verify: SLPS: {checked} affinity lines read back as '
          f'their record head + pool tail')

    import battle_text_layout
    stock = open(toolbelt.bin_path('BTLP'), 'rb').read()
    headings = battle_text_layout.centred_headings(
        stock, open(WIDTH_OUT, 'rb').read(), open(TEXT_BITS_OUT, 'rb').read())
    battle_text_layout.verify(
        open(os.path.join(ROOT, 'build', 'BTLP.BIN'), 'rb').read(), headings)

    # --- FONT.BIN: the anchor read back from the assembled font ---
    font = open(os.path.join(ROOT, 'build', 'FONT.BIN'), 'rb').read()
    FB = 0x801E0000
    def font_off(ram):
        return ram - FB
    cell_bg, cell_fast = struct.unpack_from('<2I', font,
                                            font_off(toolbelt.asm_equ('SF_FONT_CELL_BG')))
    if cell_bg != toolbelt.asm_equ('SF_FONT_REPLAY_BG') or \
            cell_fast != toolbelt.asm_equ('SF_FONT_REPLAY_FAST'):
        raise SystemExit(
            f'smallfont_vwf: verify: the FONT.BIN registration cells pre-install is '
            f'{cell_bg:#x}/{cell_fast:#x}, want the retail replays '
            f'{toolbelt.asm_equ("SF_FONT_REPLAY_BG"):#x}/{toolbelt.asm_equ("SF_FONT_REPLAY_FAST"):#x}.')
    for name, gate_addr, cell, replay, gsort in (
            ('bg', 'SF_FONT_GATE_BG', 'SF_FONT_CELL_BG', 'SF_FONT_REPLAY_BG', gsort_bg),
            ('fastbg', 'SF_FONT_GATE_FAST', 'SF_FONT_CELL_FAST', 'SF_FONT_REPLAY_FAST', gsort_fast)):
        g = toolbelt.asm_equ(gate_addr)
        w = struct.unpack_from('<6I', font, font_off(g))
        _verify_sort_gate(w, g, toolbelt.asm_equ(replay), name)
        # the replay: magic at entry-4, then [5 prologue words][j body][last word]
        r = toolbelt.asm_equ(replay)
        rw = struct.unpack_from('<7I', font, font_off(r))
        orig = struct.unpack_from('<6I', orig_slps, gsort - SLPS_BASE)
        if struct.unpack_from('<I', font, font_off(r) - 4)[0] != reg_magic:
            raise SystemExit(
                f'smallfont_vwf: verify: the {name} replay at {r:#x} lost its guard word '
                f'(entry-4). See vwf/sf_font.asm.')
        if rw[0:5] != orig[0:5] or rw[6] != orig[5]:
            raise SystemExit(
                f'smallfont_vwf: verify: the {name} replay at {r:#x} is not the retail '
                f'prologue ({[hex(x) for x in rw[1:8]]}). See vwf/sf_font.asm.')
        want_j = 0x08000000 | (((gsort + 0x18) >> 2) & 0x3FFFFFF)
        if rw[5] != want_j:
            raise SystemExit(
                f'smallfont_vwf: verify: the {name} replay at {r:#x} jumps to '
                f'{((rw[6] & 0x3FFFFFF) << 2) | 0x80000000:#x}, want {gsort + 0x18:#x}.')
    print('smallfont_vwf: verify: FONT.BIN: cells pre-name the replays, gates and '
          'replays intact')

    # --- overlays: config, guard, recorder, renderer, own tables, full names ---
    BASE = slot_addr
    center_reference = None
    for fname, ovl in (('ADV.BIN', 'ADV'), ('DNG.BIN', 'DNG'), ('S2D.BIN', 'S2D')):
        low = ovl.lower()
        map_base = toolbelt.asm_equ(f'{ovl}_SF_MAP_BASE')
        hook = toolbelt.asm_equ(f'{ovl}_SF_HOOK_ADDR')
        if ovl == 'ADV':
            row_addr = sym['sf_cfg_adv']
            help_addr = sym['sf_record_adv']
            row_size = help_addr - row_addr
            help_size = sym['sf_record_end_adv'] - help_addr
        else:
            row_addr = toolbelt.asm_equ(f'{ovl}_SF_ROW_ADDR')
            row_size = toolbelt.asm_equ(f'{ovl}_SF_ROW_SIZE')
            help_addr = toolbelt.asm_equ(f'{ovl}_SF_HELP_ADDR')
            help_size = toolbelt.asm_equ(f'{ovl}_SF_HELP_SIZE')
        cfg_addr = row_addr                 # the config is the run's first 0x20 bytes
        bufs_addr = toolbelt.asm_equ(f'{ovl}_SF_BUFS_ADDR')
        bufs_limit = toolbelt.asm_equ(f'{ovl}_SF_BUFS_LIMIT')
        data_addr = toolbelt.asm_equ(f'{ovl}_SF_DATA_ADDR')
        item_addr = ((sym['sf_data_end_adv'] + 3) & ~3) if ovl == 'ADV' else toolbelt.asm_equ(f'{ovl}_ITEM_DATA_ADDR')
        item_end = toolbelt.asm_equ('ADV_SF_EXTENSION_END' if ovl == 'ADV' else f'{ovl}_ITEM_DATA_END')
        table_addr = sym[f'sf_table_{low}']
        d = open(os.path.join(ROOT, 'build', fname), 'rb').read()

        import cfgtext
        original = open(os.path.join(ROOT, 'data', 'psx', fname), 'rb').read()
        for at, expected in cfgtext.centered_producers(original, ovl):
            actual, = struct.unpack_from('<I', d, at - BASE)
            if actual != expected:
                raise SystemExit(f'smallfont_vwf: verify: {ovl} centered producer at {at:#x} was clobbered')

        # The fixed-cell tags are written straight into retail call sites. A
        # later .org in the same overlay assembles in silence and would win,
        # so read every tagged word back from the assembled file.
        fixed_asm = os.path.join(ROOT, 'build', f'smallfont_fixed_{low}.asm')
        for match in re.finditer(r'\.org (0x[0-9A-Fa-f]+)\s*\n\s*\.word (0x[0-9A-Fa-f]+)',
                                 open(fixed_asm).read()):
            at, expected = int(match[1], 16), int(match[2], 16)
            actual, = struct.unpack_from('<I', d, at - BASE)
            if actual != expected:
                raise SystemExit(
                    f'smallfont_vwf: verify: {ovl} fixed-cell producer at {at:#x} '
                    f'reads {actual:#x}, want {expected:#x} - a later .org clobbered it')

        center = sym[f'sf_center_row_{low}']
        center_end = sym[f'sf_center_end_{low}']
        center_code = d[center - BASE:center_end - BASE]
        if (len(center_code) != 108 or
                struct.unpack_from('<I', center_code)[0] != 0x91AC0007):
            raise SystemExit(f'smallfont_vwf: verify: {ovl} centering helper at {center:#x} was clobbered')
        if ovl == 'ADV' and (center != toolbelt.asm_equ('ADV_SF_CENTER_ADDR') or
                             center_end > toolbelt.asm_equ('ADV_SF_CENTER_END')):
            raise SystemExit('smallfont_vwf: verify: ADV centering helper escapes its allocated run')
        if center_reference is not None and center_code != center_reference:
            raise SystemExit(f'smallfont_vwf: verify: {ovl} centering helper differs from ADV')
        center_reference = center_code

        st = sym[f'sf_state_{low}']
        wi = sym[f'sf_widths_{low}']
        po = sym[f'sf_pool_{low}']
        de = sym[f'sf_data_end_{low}']
        cfg = struct.unpack_from('<8I', d, cfg_addr - BASE)
        want_cfg = (magic, map_base, table_addr, 0, bufs_addr, wi, po, hook + 0x0C)
        if cfg != want_cfg:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} config at {cfg_addr:#x} reads '
                f'{tuple(hex(w) for w in cfg)}, want {tuple(hex(w) for w in want_cfg)}. '
                f'The .org was clobbered or never placed.')
        guard = struct.unpack_from('<I', d, cfg_addr + cfg_end - BASE)[0]
        if guard != reg_magic:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer guard word at '
                f'{cfg_addr + cfg_end:#x} reads {guard:#x}, want {reg_magic:#x}.')
        if bufs_addr + bufs * buf_size > bufs_limit:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} packet buffers at {bufs_addr:#x} '
                f'overrun {bufs_limit:#x}.')

        # the per-overlay tables: state + advance table + affinity pool
        if st != data_addr:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} state is at {st:#x}, '
                f'{ovl}_SF_DATA_ADDR says {data_addr:#x}.')
        if wi != st + st_end:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} advance table is at {wi:#x}, '
                f'want {st + st_end:#x} (state + SF_ST_END).')
        if po != wi + len(widths):
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} affinity pool is at {po:#x}, '
                f'want {wi + len(widths):#x}.')
        data_end = po + len(pool) if ovl == 'ADV' else sym[f'sf_variant_uv_end_{low}']
        if de != data_end:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} kit data ends at {de:#x}, '
                f'want {data_end:#x}.')
        if d[st - BASE:st - BASE + st_end] != bytes(st_end):
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} state at {st:#x} is not zero at build.')
        if d[wi - BASE:wi - BASE + len(field_widths)] != field_widths:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} advance table at {wi:#x} does not read '
                f'back as build/sf_field_width.bin.')
        if d[po - BASE:po - BASE + len(pool)] != pool:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} affinity pool at {po:#x} does not read '
                f'back as build/affinity_pool.bin.')

        # the writer hook: la t0, cfg ; j <recorder> ; nop - or, while the kit
        # hooks are disabled, the untouched retail words
        orig = open(os.path.join(ROOT, 'data', 'psx', fname), 'rb').read()
        armips_hi = (cfg_addr + 0x8000) >> 16
        la0 = (0x3C08 << 16) | armips_hi
        la1 = (0x2508 << 16) | (cfg_addr & 0xFFFF)
        hw = struct.unpack_from('<3I', d, hook - BASE)
        retail_hw = struct.unpack_from('<3I', orig, hook - BASE)
        jtarget = ((hw[2] & 0x3FFFFFF) << 2) | 0x80000000
        rec = sym[f'sf_record_{low}']
        hooked = ((hw[0], hw[1]) == (la0, la1) and hw[2] >> 26 == 2
                  and jtarget == rec)
        if not hooked and tuple(hw) != tuple(retail_hw):
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} writer hook at {hook:#x} is neither '
                f'la t0, {cfg_addr:#x} / j {rec:#x} nor retail (words {hw[0]:08x} {hw[1]:08x} '
                f'{hw[2]:08x}). Clobbered or never placed.')

        # the recorder at HELP, the renderer + thunks after the config
        if rec != help_addr:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} recorder is at {rec:#x}, '
                f'HELP says {help_addr:#x}.')
        rec_end = sym[f'sf_record_end_{low}']
        if rec_end - rec > help_size:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} recorder is {rec_end - rec} bytes, '
                f'its HELP run is {help_size}.')
        first = struct.unpack_from('<I', d, rec - BASE)[0]
        if first != 0x27BDFFD0:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} recorder at {rec:#x} does not start with the '
                f'template prologue ({first:08x}). The HELP run was clobbered or the copy was '
                f'not placed.')
        # the recorder's hard-won invariants: the walk cap, the code-list
        # terminator, the glyph-count blanking and the retail fallback's
        # displaced t0. Search the whole recorder for each word pair.
        rec_words = struct.unpack_from(f'<{(rec_end - rec) // 4}I', d, rec - BASE)
        def has_pair(a, b, what):
            if not any(rec_words[i] == a and rec_words[i + 1] == b
                       for i in range(len(rec_words) - 1)):
                raise SystemExit(
                    f'smallfont_vwf: verify: the {ovl} recorder at {rec:#x} lost {what} '
                    f'({a:08x} {b:08x}). See vwf/smallfont.asm.')
        has_pair(0x2F0B0030, 0x15600002, 'the SF_REC_CODE_MAX cap clamp branch')
        if 0x3418002F not in rec_words:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} recorder at {rec:#x} lost the '
                f'SF_REC_CODE_MAX value (0x3418002F). See vwf/smallfont.asm.')
        if 0x340300FF not in rec_words or 0xA0E30000 not in rec_words:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} recorder at {rec:#x} lost the 0xFF '
                f'code-list terminator (li v1 / sb v1). See vwf/smallfont.asm.')
        # the blanking extent: one cell per glyph walked (the retail row),
        # clamped to the caller's own run for the pooled line whose cap is
        # its own. Blanking the pixel extent instead left the retail glyphs
        # past the VWF text on screen.
        has_pair(0x026F502B, 0x11400002,
                 'the glyph-count blanking extent (sltu t2,s3,t7 / beqz t2)')
        has_pair(0x01E05021, 0x02605021,
                 'the caller-run clamp (the delay-slot cell count, then s3)')
        has_pair(0x8D09001C, 0x340800FF, 'the fallback t0 = 0xFF restore')
        # Full wording is recorded without a nominal caller-width gate.
        if 0xA0E20000 not in rec_words or 0x0145582B in rec_words:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} recorder does not retain '
                f'complete glyph codes independently of the caller pixel budget.')
        # the CLUT banks: the record keeps the GLYPH (so the width table is
        # indexed by it) and the row's bank, and the walk divides once per
        # row - li t3,SF_GLYPHS / divu v0,t3 / multu bank,SF_GLYPHS /
        # sltiu glyph,SF_GLYPHS for every later glyph.
        for word, what in ((0x340B00D7, 'li t3,SF_GLYPHS (the bank width)'),
                           (0x004B001B, 'divu v0,t3 (the row bank)'),
                           (0x018B0019, 'multu bank,SF_GLYPHS (the bank base)'),
                           (0x2C4B00D7, 'sltiu glyph,SF_GLYPHS (same bank)')):
            if word not in rec_words:
                raise SystemExit(
                    f'smallfont_vwf: verify: the {ovl} recorder at {rec:#x} lost '
                    f'{what}. A row drawn from another CLUT bank would read the '
                    f'wrong cba. See vwf/smallfont.asm.')
        # the registration: the FONT.BIN cell writes (sw into the cells)
        cell_lo = toolbelt.asm_equ('SF_FONT_CELL_BG') & 0xFFFF
        ok = any(rec_words[i] == (0x3C0A0000 | (toolbelt.asm_equ('SF_FONT_CELL_BG') >> 16))
                 and rec_words[i + 1] == (0x254A0000 | cell_lo)
                 for i in range(len(rec_words) - 1))
        if not ok:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} recorder at {rec:#x} lost the FONT.BIN '
                f'registration-cell load. See vwf/smallfont.asm.')
        hb = sym[f'sf_hook_bg_{low}']
        if hb != cfg_addr + cfg_end + 4:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer is at {hb:#x}, '
                f'want {cfg_addr + cfg_end + 4:#x} (config + SF_CFG_END + the guard).')
        # Every registered entry owns the guard checked by the resident gate.
        hf = sym[f'sf_hook_fastbg_{low}']
        thunks_end = sym[f'sf_thunks_end_{low}']
        if not hb < hf < thunks_end:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} fastbg entry is at {hf:#x}, outside '
                f'the renderer run {hb:#x}..{thunks_end:#x}.')
        fguard = struct.unpack_from('<I', d, hf - 4 - BASE)[0]
        if fguard != reg_magic:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} fastbg entry at {hf:#x} has no guard '
                f'word at entry-4 ({fguard:#x}, want {reg_magic:#x}): the resident gate '
                f'rejects it and every GsSortFastBg call stays retail.')
        if struct.unpack_from('<I', d, hf - BASE)[0] >> 16 != 0x3C19:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} fastbg entry at {hf:#x} does not start '
                f'with la t9, state. See vwf/smallfont.asm.')
        hfirst = struct.unpack_from('<I', d, hb - BASE)[0]
        if hfirst >> 16 != 0x3C19:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer at {hb:#x} does not start with '
                f'la t9, state ({hfirst:08x}). The dead run was clobbered or the copy was not '
                f'placed.')
        # the sprite packet's SPRT word must be code<<24 | b<<16 | g<<8 | r:
        # the GPU command lives in the high byte, the low 24 bits are the
        # layer's own text colour, so the row fades with the background. A bare
        # 0x64 is a NOP with a dark-blue colour and the row never draws.
        thunks_end = sym[f'sf_thunks_end_{low}']
        rwords = struct.unpack_from(f'<{(thunks_end - hb) // 4}I', d, hb - BASE)
        for word, what in ((0x340EFFFF, 'retail empty-cell marker'),
                           (0xA48E0000, 'temporary map suppression'),
                           (0xA4830000, 'logical map restoration')):
            if word not in rwords:
                raise SystemExit(f'smallfont_vwf: verify: the {ovl} renderer lost {what}.')
        # Both pre-pass and emitter call the same bounded copy-selection helper.
        reserve = sym[f'sf_row_reserve_{low}']
        rec_end = sym[f'sf_record_end_{low}']
        rec_start = sym[f'sf_record_{low}']
        if not rec_start < reserve < rec_end:
            raise SystemExit(f'smallfont_vwf: verify: {ovl} row reservation helper is outside its owned recorder region.')
        hwords = struct.unpack_from(f'<{(rec_end - reserve) // 4}I', d, reserve - BASE)
        call = 0x0C000000 | ((reserve >> 2) & 0x03FFFFFF)
        if 0x2C4E002F not in hwords or rwords.count(call) != 2:
            raise SystemExit(f'smallfont_vwf: verify: {ovl} lost bounded pre-pass/emitter row reservation.')
        # the call-through: the pre-pass spends a0-a2 as scratch, so the hook
        # must hand the sorter the arguments it was given before jumping into
        # the thunk. Without the restore the sorter reads a map cell as its
        # GsBG and a code pointer as its GsOT - a wild packet chain, then an
        # exception (black screen / unknown GPU word).
        jr_t1 = [i for i, w in enumerate(rwords) if w == 0x01200008]
        if not any(i >= 4 and rwords[i - 4] == 0x02002021 and rwords[i - 3] == 0x02202821
                   and rwords[i - 2] >> 16 == 0x3C1F and i + 1 < len(rwords)
                   and rwords[i + 1] == 0x02403021 for i in jr_t1):
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer at {hb:#x} enters the sorter '
                f'with the pre-pass\'s scratch in a0-a2 (lost the move a0,s0 / a1,s1 / '
                f'a2,s2 restore). See vwf/smallfont.asm.')
        # the row claim: bit 15 of SF_REC_COUNT. `lui` with a 16-bit constant
        # loads bit 31 instead, and the `sh` right after drops it - so the
        # pre-pass claimed nothing, the emit drew nothing and every recorded
        # row stayed blank (the game had already cleared its cells).
        own = toolbelt.asm_equ('SF_REC_OWNED', defs)
        if not any(rwords[i] == (0x34000000 | (12 << 16) | own)
                   and rwords[i + 1] == 0x014C5025
                   for i in range(len(rwords) - 1)):
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer at {hb:#x} does not set '
                f'SF_REC_OWNED ({own:#x}) with ori t4,zero (lost the row claim). '
                f'See vwf/smallfont.asm.')
        # the OT entry: org + (pri + ot->offset), exactly what GsSortBg indexes
        # with (0x80032a14). `pri` alone is the same while offset is 0, but the
        # offset is the sorter's, not ours to assume.
        if 0x8E2C0008 not in rwords:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer at {hb:#x} lost the '
                f'ot->offset load for its OT entry (lw t4,8(s1)). See vwf/smallfont.asm.')
        ok = any(rwords[i] == 0xAE6E0008 and 0x3C0A6400 in rwords[max(0, i - 8):i]
                 for i in range(len(rwords)))
        if not ok:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer at {hb:#x} lost the SPRT '
                f'colour/command word (the 0x64000000 | b<<16 | g<<8 | r store). '
                f'See vwf/smallfont.asm.')
        ok = any(rwords[i] == 0xAD8B0000 and 0x3C0C0500 in rwords[max(0, i - 6):i]
                 for i in range(len(rwords)))
        if not ok:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer at {hb:#x} lost the last '
                f'chunk length (0x05000000) when linking to the OT head. '
                f'See vwf/smallfont.asm.')
        blank_ok = False
        for i, word in enumerate(rwords):
            if word & 0xFFFF0000 != 0x118D0000:      # beq t4, t5, ...
                continue
            off = word & 0xFFFF
            if off & 0x8000:
                off -= 0x10000
            tgt = i + 1 + off
            if (0 <= tgt < len(rwords) - 1 and rwords[tgt] >> 16 == 0x1000
                    and rwords[tgt + 1] == 0x340C0001):
                jump = rwords[tgt] & 65535
                tgt += 1 + (jump - 65536 if jump & 32768 else jump)
            if 0 <= tgt < len(rwords) and rwords[tgt] == 0x012C4821:  # addu t1,t1,t4
                blank_ok = True
        if not blank_ok:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer at {hb:#x} lets a blank '
                f'cell skip the pen advance (blank marker must become advance 1). '
                f'See vwf/smallfont.asm.')
        # Field cells are left-normalised; select the normal or compact
        # advance nibble and the matching atlas artwork for this row.
        variant = sym[f'sf_variant_uv_{low}']
        if not all(word in rwords for word in (0x002C6006, 0x318C000F,
                         0x0C000000 | ((variant >> 2) & 0x3FFFFFF))):
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer at {hb:#x} does not unpack '
                f'the field advance/font selector. See vwf/smallfont.asm.')
        # The selector names a cell in each page copy; read the mapping back
        # from the assembled overlay so a stale or clobbered table cannot
        # silently point a glyph at another screen's artwork.
        cells_at = sym[f'sf_variant_cells_{low}']
        regular_cells, compact_cells = smallfont_variants.cell_codes()
        want_cells = bytes(regular_cells)
        got_cells = d[cells_at - BASE:cells_at - BASE + len(want_cells)]
        if got_cells != want_cells:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} Latin cell table at {cells_at:#x} '
                f'reads {got_cells.hex()}, want {want_cells.hex()}.')
        compact_base = compact_cells[0]
        selector_end = sym[f'sf_variant_uv_end_{low}']
        vwords = struct.unpack_from(f'<{(selector_end - cells_at) // 4}I', d, cells_at - BASE)
        if (0x25CE0000 | compact_base) not in vwords:   # addiu t6,t6,<compact base>
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} Latin selector at {variant:#x} lost '
                f'the stage-3 compact run base ({compact_base:#x}). See smallfont_variants.assembly.')
        if not all(w in rwords for w in (0x8FAE0040, 0x01205021, 0xAE6E000C,
                                         0x8FAA0044, 0x8FAE0048, 0xAE6E0014)):
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer at {hb:#x} lost the '
                f'viewport-cropped XY/UV/WH packet fields. See vwf/smallfont.asm.')
        # the CLUT banks: the pre-pass rebuilds the row's first cell from the
        # record's bank (multu bank,SF_GLYPHS) and compares the map cell's
        # glyph, and the emit walks that bank's cells (addu v1,v1,t8).
        for word, what in ((0x012C0019, 'multu bank,SF_GLYPHS (pre-pass base)'),
                           (0x01C97023, 'subu cell,base (the map cell glyph)'),
                           (0x91AB0007, 'lbu bank,SF_REC_PAD+1'),
                           (0x00781821, 'addu v1,v1,t8 (the banked cell)')):
            if word not in rwords:
                raise SystemExit(
                    f'smallfont_vwf: verify: the {ovl} renderer at {hb:#x} lost '
                    f'{what}. A row drawn from another CLUT bank would mix '
                    f'colours or read bank 0. See vwf/smallfont.asm.')
        # Retained names can cross the physical map edge. The emitter loads
        # the viewport right edge and branches out before drawing beyond it.
        require_viewport_clamp(rwords, f'{ovl} renderer at {hb:#x}')
        if not (0x860B0006 in rwords and 0x860C000E in rwords):
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer at {hb:#x} does not read '
                f'bg->y/bg->scrolly with lh (0x860B0006 / 0x860C000E). '
                f'See vwf/smallfont.asm.')
        if 0x8E0B0006 in rwords or 0x8E0C000E in rwords:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer at {hb:#x} loads bg->y or '
                f'bg->scrolly with an unaligned lw - an address error on the R3000A. '
                f'See vwf/smallfont.asm.')
        if thunks_end - hb > row_size - cfg_end - 4:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} renderer + thunks are {thunks_end - hb} bytes, '
                f'the ROW run after the config and its guard is {row_size - cfg_end - 4}.')
        # the full-name block: tails, bitmaps, copy helpers - this overlay's own
        tail = sym[f'item_tail_bank_{low}']
        if tail != item_addr:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} full-name block is at {tail:#x}, '
                f'{ovl}_ITEM_DATA_ADDR says {item_addr:#x}.')
        iend = sym[f'sf_item_end_{low}']
        if iend > item_end:
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} full-name block ends at {iend:#x}, '
                f'past {item_end:#x}.')
        if iend - BASE > len(d):
            raise SystemExit(
                f'smallfont_vwf: verify: the {ovl} full-name block ends at {iend:#x} but the '
                f'built file ends at {BASE + len(d):#x}: the extension was not written.')
        table_end = sym[f'sf_table_end_{low}']
        scratch = sym[f'sf_name_scratch_{low}']
        extension_end = sym[f'sf_extension_end_{low}']
        name_bytes = toolbelt.asm_equ('SF_NAME_BYTES', defs)
        owner_end = sym['sf_variant_uv_end_adv'] if ovl == 'ADV' else iend
        if table_addr != ((owner_end + 3) & ~3) or table_end != table_addr + table_size:
            raise SystemExit(f'smallfont_vwf: verify: {ovl} row table is outside its owned extension order')
        if scratch != table_end or extension_end != scratch + name_bytes:
            raise SystemExit(f'smallfont_vwf: verify: {ovl} name scratch overlaps the row table or extension end')
        if d[table_addr - BASE:extension_end - BASE] != bytes(table_size + name_bytes):
            raise SystemExit(f'smallfont_vwf: verify: {ovl} row table/name scratch is not zero-filled in its file')
        if ovl == 'ADV' and (cfg_addr != ((iend + 3) & ~3) or help_addr != thunks_end):
            raise SystemExit('smallfont_vwf: verify: packed ADV name/code regions are not adjacent')
        work_start = 0x800E0000 if ovl == 'S2D' else 0x800C0000
        loaded_end = BASE + ((len(d) + 0x7FF) & ~0x7FF)
        if extension_end > item_end or loaded_end > work_start:
            raise SystemExit(f'smallfont_vwf: verify: {ovl} extension/sector-rounded load reaches the work area')
        clip = sym[f'sf_clip_glyph_{low}']
        call_clip = 0x0C000000 | ((clip >> 2) & 0x3FFFFFF)
        if call_clip not in rwords or 0x860C0008 not in rwords or 0x860D000A not in rwords:
            raise SystemExit(f'smallfont_vwf: verify: {ovl} renderer lost viewport geometry/crop call')
        print(f'smallfont_vwf: verify: {fname}: config at {cfg_addr:#x} (guard '
              f'{cfg_addr + cfg_end:#x}), recorder at {rec:#x}, renderer at {hb:#x}, '
              f'data {st:#x}..{de:#x}, full names {tail:#x}..{iend:#x}, '
              f'buffers at {bufs_addr:#x}')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'build'
    {'build': build, 'report': report, 'verify': verify,
     'sheet': write_sheets, 'variants': prepare_variants, 'names': names_report}[cmd]()
