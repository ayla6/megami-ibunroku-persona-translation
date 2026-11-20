"""Original fixed UI plus two independently editable Latin sprite fonts.

Both Latin faces are drawn into small-font cells the translated game never
prints as kana. The art therefore lives in the 84-row text band every page
copy already receives (ADVCMD/ADVCMD0/OPEN and the 2D/D0x copies), so it
survives the menu's later TIM uploads and the shorter map pages. Cells the
retail renderer still reads are never claimed: the ASCII repertoire, the
blank space cell, the lowercase extension and the punctuation fallbacks.
Battle's shorter page is deliberately not an owner of this allocation.
"""
from pathlib import Path
import re
import struct

import toolbelt

ROOT = Path(toolbelt.ROOT)
COMPACT = ROOT / 'src/mods/latin-alphabet/assets/fonts/smallfont_page_compact.png'
PAGE_COLS = 31                     # the page's 8x12 cell grid
PAGE_CODES = 215                   # codes 0..214: CellsInit's text atlas
CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-:/'"
EDIT_COLS = 14


SPACE_ADV = 4                      # the page's word space, halved per stage


def editable_codes():
    return sorted({toolbelt.smallfont_char(c) for c in CHARS})


def protected_codes():
    """Cells the retail renderer still reads: the writer's ASCII repertoire
    (fixed-cell rows bypass the kit), the blank space cell, the lowercase
    extension, and the Japanese punctuation cells the VWF falls back to."""
    import etext
    import smallfont_lc
    import smallfont_vwf
    codes = {0} | set(editable_codes()) | set(smallfont_lc.LC_CODES)
    codes |= set(smallfont_lc.PUNCT_CODES.values())
    for char in smallfont_vwf.PUNCT_FALLBACK.values():
        code = etext.char2g.get(char)
        if code is not None:
            codes.add(code)
    return {code for code in codes if code < PAGE_CODES}


def spare_codes():
    return [code for code in range(PAGE_CODES) if code not in protected_codes()]


def cell_codes():
    """The storage cells in encoder order: the regular face on the first N
    spare cells, the compact face on the next N. Both faces are independent
    copies of their own artwork, never an advance derived from the other."""
    codes = editable_codes()
    spare = spare_codes()
    if len(spare) < 2 * len(codes):
        raise SystemExit('smallfont variants: the text band has no room for both Latin faces')
    return spare[:len(codes)], spare[len(codes):2 * len(codes)]


def ranges():
    """Mechanically coalesce adjacent encoded cells for the generated selector."""
    out = []
    for code in editable_codes():
        if out and code == out[-1][1] + 1:
            out[-1] = (out[-1][0], code)
        else:
            out.append((code, code))
    return out


def slots():
    return editable_codes()


def cell_uv(code):
    return (code % PAGE_COLS) * 8, (code // PAGE_COLS) * 12


def uv(slot, compact=False):
    return cell_uv(cell_codes()[compact][slot])


SHEET_COLS = EDIT_COLS            # both authored sheets share the cell order
SHEET_SIZE = (EDIT_COLS * 8, ((len(CHARS) + EDIT_COLS - 1) // EDIT_COLS) * 12)
BAND_ROWS = -(-PAGE_CODES // PAGE_COLS) * 12    # the page's 84 text-band rows


def _sheet_pixels(path, palette):
    """An authored Latin sheet as page indices: slot i of the sheet is drawn
    into editable code i's own cell. The legacy full-page form (256x256) is
    still read - its glyph band IS the page's first 84 rows."""
    from PIL import Image
    with Image.open(path) as image:
        image = image.convert('RGB')
        if image.size not in ((256, 256), SHEET_SIZE):
            raise ValueError(f'{path} is {image.size}, want {SHEET_SIZE} (Latin only) or legacy 256x256')
        colours = {}
        for i, rgb in enumerate(palette):
            colours.setdefault(tuple(rgb), i)
        px = image.load()
        try:
            if image.size == (256, 256):
                out = bytearray(256 * 256)
                for y in range(BAND_ROWS):     # only the glyph band is the sheet's
                    for x in range(256):
                        out[y * 256 + x] = colours[px[x, y]]
                return bytes(out), image.size
            out = bytearray(256 * 256)
            for slot, code in enumerate(editable_codes()):
                sx, sy = slot % SHEET_COLS * 8, slot // SHEET_COLS * 12
                dx, dy = cell_uv(code)
                for y in range(12):
                    out[(dy + y) * 256 + dx:(dy + y) * 256 + dx + 8] = \
                        bytes(colours[px[sx + x, sy + y]] for x in range(8))
            return bytes(out), image.size
        except KeyError as exc:
            raise ValueError(f'{path}: pixel colour {exc} is not in the page CLUT') from exc


def sheet_pixels(path, palette):
    """An authored sheet as page indices, read fresh like every other art
    source (disc_page reads its TIM every call too) - no stamp cache to go
    stale between edits."""
    path = Path(path)
    if not path.exists():
        raise SystemExit(f'missing smallfont sheet: {path}')
    return _sheet_pixels(str(path), palette)


def compact_pixels(palette):
    return sheet_pixels(COMPACT, palette)[0]


def normalise(rows):
    """Keep the ink, left-align it, and derive its shadow; never squeeze gaps."""
    ink = {(x, y): colour for y, row in enumerate(rows) for x, colour in enumerate(row)
           if colour and colour != 2}
    out = [[0] * 8 for _ in range(12)]
    if not ink:
        return out, 1
    left, right = min(x for x, _ in ink), max(x for x, _ in ink)
    for (x, y), colour in ink.items():
        out[y][x - left] = colour
    for (x, y) in ink:
        if x - left + 1 < 8 and y + 1 < 12 and not out[y + 1][x - left + 1]:
            out[y + 1][x - left + 1] = 2
    return out, right - left + 2


def original_metrics(retail, glyph_rows):
    """The original fixed font, spaced proportionally: one byte per code,
    left bearing << 4 | advance, measured on the page's own cells (retail
    capitals and numerals, the lowercase extension). The renderer draws the
    retail cell at pen - bearing, so the ink starts at the pen; the advance
    is the ink plus the 1-px letter gap, as `normalise` measures the faces.
    Codes without Latin art keep the cell's 8-px pitch, and so do the
    digits: numbers stay tabular. The word space is SPACE_ADV, halved by
    the narrow-space stage like the regular face."""
    import smallfont_lc
    page = bytearray(retail)
    smallfont_lc.draw(page, 256)
    metrics = bytearray([0x08] * 256)
    for code in slots():
        ink = [x for row in glyph_rows(page, 256, code)
               for x, colour in enumerate(row) if colour and colour != 2]
        if not ink:
            raise ValueError(f'original face: missing ink in code {code:#x}')
        left, right = min(ink), max(ink)
        metrics[code] = left << 4 | (right - left + 2)
    for digit in '0123456789':
        metrics[toolbelt.smallfont_char(digit)] = 0x08
    metrics[0] = SPACE_ADV
    return bytes(metrics)


def compose(retail, regular, palette, glyph_rows):
    import smallfont_lc
    compact = compact_pixels(palette)
    cells = cell_codes()
    out = bytearray(retail)
    smallfont_lc.draw(out, 256)           # retail capitals/numerals; existing lowercase extension
    metrics = bytearray([0x88] * 256)     # other cells retain their original 8px geometry
    for slot, code in enumerate(slots()):
        advances = []
        for variant, source in enumerate((regular, compact)):
            rows, advance = normalise(glyph_rows(source, 256, code))
            if advance == 1:
                raise ValueError(f'smallfont variant {variant}: missing ink in code {code:#x}')
            u, v = cell_uv(cells[variant][slot])
            for y, row in enumerate(rows):
                out[(v + y) * 256 + u:(v + y) * 256 + u + 8] = bytes(row)
            advances.append(advance)
        metrics[code] = advances[0] | advances[1] << 4
    # The page's word space is SPACE_ADV; each stage halves it (4 -> 2 -> 1),
    # so the compact nibble must be SPACE_ADV >> 2. The renderer derives the
    # advance from the low nibble and the recorder reads this high nibble, so
    # both stay in lockstep with tier_adv().
    metrics[0] = (SPACE_ADV >> 2) << 4 | SPACE_ADV
    return out, bytes(metrics)


def prepare(regular, palette, glyph_rows):
    """One-time mechanical starter, never overwrite the user's compact art."""
    from PIL import Image
    if COMPACT.exists():
        print(f'kept existing compact artwork: {COMPACT}')
        return
    codes = editable_codes()
    width, height = EDIT_COLS * 8, ((len(codes) + EDIT_COLS - 1) // EDIT_COLS) * 12
    atlas = [tuple(palette[0])] * (width * height)
    for slot, code in enumerate(codes):
        for y, row in enumerate(glyph_rows(regular, 256, code)):
            at = (slot // EDIT_COLS * 12 + y) * width + slot % EDIT_COLS * 8
            atlas[at:at + 8] = [tuple(palette[i]) for i in row]
    image = Image.new('RGB', (width, height))
    image.putdata(atlas)
    image.save(COMPACT)
    print(f'created intact regular-glyph template (compact art must be drawn): {COMPACT}')


# The persona bar's sprite-cell writer (dng/bar.asm, s2d/bar.asm) draws the
# original font from the retail cells. A cell has no x offset, only the
# advance the slot renderer adds after it, so the left bearing moves into
# the advances: cell i advances adv(i) + bearing(i) - bearing(i + 1), which
# puts every glyph's ink where the kit's rows put it (the first glyph's own
# bearing, at most 2 px, stays). In: v0 = code, t8 = advance table,
# t9 = the next code, a3 = cells left, t4 = 0xFF. Out: t1 = the byte the
# writer reads its advance from. Clobbers t6/t7. A Persona name (page bit 6)
# keeps the regular face: the selector's cell and the advance table's entry.
BAR_ORIGINAL = [
    'sf_bar_orig:',
    '    andi t7,a2,0x40',                 # bit 6 of the page: a Persona name,
    '    bnez t7,@@regular',               # drawn in the regular face
    '    nop',
    '    lbu t7,0(t9)',
    '    addu t1,t8,v0',
    '    lbu t6,SF_ORIG_TABLE(t1)',
    '    beqz a3,@@last',
    '    nop',
    '    beq t7,t4,@@last',
    '    addu t7,t8,t7',
    '    lbu t7,SF_ORIG_TABLE(t7)',
    '    nop',
    '    b @@sum',
    '    srl t7,t7,4',
    '@@last:',
    '    move t7,zero',
    '@@sum:',
    '    andi t1,t6,0x0F',
    '    srl t6,t6,4',
    '    addu t1,t1,t6',
    '    subu t1,t1,t7',
    '    la t6,sf_bar_adv',
    '    sb t1,0(t6)',
    '    jr ra',
    '    move t1,t6',
    '@@regular:',
    '    j sf_variant_uv_v1',              # the regular cell; returns to the writer
    '    addu t1,t8,v0',                   # its advance entry (the writer reads t1)
    'sf_bar_adv:',
    '    .byte 0',
    '    .align 4',
]


def letter_ranges():
    """The Latin letters' codes, coalesced into ranges (from the encoder)."""
    import toolbelt
    out = []
    for code in sorted({toolbelt.smallfont_char(c) for c in
                        'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'}):
        if out and code == out[-1][1] + 1:
            out[-1] = (out[-1][0], code)
        else:
            out.append((code, code))
    return out


def has_letter():
    """sf_has_letter(a0 = codes, 0xFF ends) -> v0 = 1 when one is a Latin
    letter. A row without one (numbers, kana, icons) draws exactly as retail
    in the original font. Only a0/a1/at/v0 change."""
    out = ['sf_has_letter:', '    lbu a1,0(a0)', '    addiu a0,a0,1',
           '    xori at,a1,0xFF', '    beqz at,@@none', '    nop']
    for lo, hi in letter_ranges():
        out += [f'    addiu at,a1,-{lo}', f'    sltiu at,at,{hi - lo + 1}',
                '    bnez at,@@yes', '    nop']
    out += ['    b sf_has_letter', '    nop',
            '@@yes:', '    jr ra', '    ori v0,zero,1',
            '@@none:', '    jr ra', '    move v0,zero']
    return out


def assembly(original=False):
    """Code-to-slot mapping comes from the encoder, not a second alphabet map.

    v0 = code, a0/a1 = retail UV, t7 = tier. Only at/t6/a0/a1 change (the
    v1 entry also pins t7). The renderer sets t7 immediately before the
    call, so the selector never reads the caller's frame; the sprite-cell
    writer enters at sf_variant_uv_v1 because it has no text tier and wants
    the regular face.
    The slot names a cell in the text band, so the UV is that cell's own
    position - no rectangle arithmetic can drift into another screen's page.
    The regular face takes the first spare cells (scattered, so a table);
    the compact face lands on the text band's one long contiguous spare run
    and is just its base plus the slot. With `original` (the overlay builds
    SF_ORIG_FACE) a tier carrying SF_TIER_ORIG keeps the retail cell: the
    original font is the page's own art.
    """
    regular, compact = cell_codes()
    base = compact[0]
    if compact != list(range(base, base + len(compact))):
        raise SystemExit('smallfont variants: the compact face lost its contiguous spare run')
    out = ['sf_variant_cells:']
    for start in range(0, len(regular), 16):
        values = regular[start:start + 16]
        out.append('    .byte ' + ','.join(str(value) for value in values))
    # The writer (adv/cells_row.asm, dng/bar.asm) draws the bar with the
    # regular face at any text tier, so it enters one instruction earlier
    # and pins the tier the selector reads.
    out += ['    .align 4', 'sf_variant_uv_v1:', '    move t7,zero',
            'sf_variant_uv:']
    if original:
        # the emitter loads t7 in the call's delay slot: the first
        # instruction here is still that load's delay slot
        out += ['    nop', '    andi at,t7,SF_TIER_ORIG', '    bnez at,@@retail', '    nop']
    slot = 0
    for lo, hi in ranges():
        out += [f'    addiu t6,v0,-{lo}', f'    sltiu at,t6,{hi - lo + 1}',
                '    bnez at,@@mapped', f'    addiu t6,t6,{slot}']
        slot += hi - lo + 1
    out += ['    jr ra', '    nop', '@@mapped:',
            '    srl at,t7,1',                # 0 for tiers 0-1, 1 for tiers 2-3
            '    beqz at,@@regular',
            '    nop',
            f'    addiu t6,t6,{base}',        # stage 3: the contiguous run
            '    b @@cell',
            '    nop',
            '@@regular:',
            '    la at,sf_variant_cells',
            '    addu at,at,t6',
            '    lbu t6,0(at)',
            '@@cell:',
            f'    li at,{PAGE_COLS}',
            '    divu t6,at', '    nop', '    nop', '    mfhi a0', '    mflo a1',
            '    sll a0,a0,3',
            '    sll at,a1,3', '    sll a1,a1,2', '    addu a1,a1,at',
            '    jr ra', '    nop']
    if original:
        out += ['@@retail:', '    jr ra', '    nop']
        out += BAR_ORIGINAL
        out += has_letter()
    out += ['sf_variant_uv_end:']
    return '\n'.join(out) + '\n'


# file -> label prefix of the ranges it declares (%s = the overlay)
RETIRED_SOURCES = {ROOT / 'src/mods/unified-save-menu/saves.inc': 'MOD_%s_RETIRED_',
                   ROOT / 'src/mods/skip-the-agastya-tree-menu/agastya.inc': 'MOD_AGASTYA_RETIRED_'}
RETIRED_OVERLAYS = {ROOT / 'src/mods/skip-the-agastya-tree-menu/agastya.inc': ('ADV',)}


def retired_ranges(overlay):
    """Stock code another patch replaces, read from its one declaration.

    A fixed-cell tag is a write into retail code. Tagging inside a range an
    optional patch rewrites would either be clobbered by it or clobber it, so
    those rows keep VWF. `mods/unified-save-menu/saves.inc` and `mods/skip-the-agastya-tree-menu/agastya.inc` already own
    the addresses; do not repeat them here."""
    out = []
    for source, prefix in RETIRED_SOURCES.items():
        if overlay not in RETIRED_OVERLAYS.get(source, (overlay,)):
            continue
        if '%s' in prefix:
            prefix = prefix % re.escape(overlay)
        pattern = r'\.definelabel\s+' + prefix + r'(\w+)_(START|END),\s*(0x[0-9A-Fa-f]+)'
        starts, ends = {}, {}
        for name, edge, value in re.findall(pattern, source.read_text()):
            (starts if edge == 'START' else ends)[name] = int(value, 16)
        out += [(starts[name], ends[name]) for name in starts if name in ends]
    return out


def retail_latin(cells):
    """True when retail tile cells already spell English: every cell is a
    blank or one of the page's fixed Latin letters, digits or dash, and at
    least one is not blank. The codes come from the encoder."""
    import items
    latin = {items.glyph(c) for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'}
    blank = items.glyph(' ')
    return (any(c != blank for c in cells)
            and all(c == blank or c in latin for c in cells))


CALLER_SAVED = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 24, 25, 31}


def branch_targets(words, base):
    """Word indices other code can branch or jump to (path merges).

    A conditional branch counts only within one function's reach (1024
    instructions); farther "branches" are data words that decode as one."""
    out = set()
    for k, ins in enumerate(words):
        op = ins >> 26
        if op in (1, 4, 5, 6, 7, 20, 21, 22, 23):
            imm = ins & 65535
            offset = imm - 65536 if imm & 32768 else imm
            if abs(offset) <= 1024:
                out.add(k + 1 + offset)
        elif op in (2, 3):
            target = (base & 0xF0000000) | (ins & 0x3FFFFFF) << 2
            out.add((target - base) >> 2)
    return out


def caption_source(words, call, merges, window=16):
    """a0 at the writer call `words[call]`, from the straight-line block
    before it, or None. A branch target restarts the walk (another path may
    enter there); a call keeps only the callee-saved registers once its
    delay slot has run."""
    registers = {0: 0}
    returned = None                 # index where an earlier call has returned
    for k in range(max(0, call - window), call):
        if k in merges:
            registers = {0: 0}
        if k == returned:
            registers = {r: v for r, v in registers.items() if r not in CALLER_SAVED}
        ins = words[k]
        op, rs, rt = ins >> 26, ins >> 21 & 31, ins >> 16 & 31
        imm = ins & 65535
        if op == 3 or (op == 0 and ins & 63 == 9):
            returned = k + 2
            if op == 0:
                registers[ins >> 11 & 31] = None
        elif op == 15:
            registers[rt] = imm << 16
        elif op in (9, 13):
            value = registers.get(rs)
            registers[rt] = None if value is None else (
                value + (imm - 65536 if imm & 32768 else imm) if op == 9 else value | imm)
        elif op == 0 and ins & 63 in (33, 37) and (rs == 0 or rt == 0):
            registers[ins >> 11 & 31] = registers.get(rt if rs == 0 else rs)
        elif op == 0:
            registers[ins >> 11 & 31] = None
        elif op not in (2, 4, 5, 40, 41, 43):
            registers[rt] = None
    if call == returned or call in merges:
        return None
    return registers.get(4)


def _producers(data, overlay):
    """Char.name producers, recognised by their struct field and writer ABI.

    Do not classify by English wording, name length or screen position. The
    reference Char layout owns name at +0x3F; these callers use its 8/10-cell
    row. Exclude the retail functions replaced by the font kit itself and the
    ranges an optional patch rewrites.
    """
    base = 0x800643C4
    writer = toolbelt.asm_equ(f'{overlay}_SF_HOOK_ADDR')
    words = struct.unpack_from(f'<{len(data) // 4}I', data)
    call = 0x0C000000 | ((writer >> 2) & 0x3FFFFFF)
    retired = retired_ranges(overlay)
    import cfgtext
    centered = {at for at, _word in cfgtext.centered_producers(data, overlay)}
    merges = branch_targets(words, base)
    if overlay != 'ADV':
        for kind in ('HELP', 'ROW'):
            start = toolbelt.asm_equ(f'{overlay}_SF_{kind}_ADDR')
            retired.append((start, start + toolbelt.asm_equ(f'{overlay}_SF_{kind}_SIZE')))
    out = []
    for i, word in enumerate(words[:-1]):
        if word != call or any(lo <= base + i * 4 < hi for lo, hi in retired):
            continue
        # addiu a0,record,offsetof(Char,name), with no intervening call or
        # replacement of a0. These exact short call sites are shared by the
        # party HUD, equipment, status and facility member rows.
        candidates = [j for j in range(max(0, i - 5), i)
                      if words[j] >> 26 == 9 and words[j] >> 16 & 31 == 4
                      and words[j] & 65535 == 0x3F]
        if not candidates:
            # Literal captions have a constant cell count and a statically
            # addressed overlay string, unlike variable names. Short ones
            # (3/4/5 cells) keep retail cells; so does any caption the
            # Japanese release already spells in the page's Latin cells
            # (DELETE, BUTTON, ...): nothing translates it, and the retail
            # layout was drawn around those 8-px cells.
            if words[i + 1] >> 16 != 0x3407:
                continue
            source = caption_source(words, i, merges)
            if base + (i + 1) * 4 in centered:
                continue                # the centring rule owns this row
            cells = words[i + 1] & 0xFFFF
            if source is None or not base <= source <= base + len(data) - cells:
                continue
            if cells in (3, 4, 5) or retail_latin(data[source - base:source - base + cells]):
                out.append((base + (i + 1) * 4, words[i + 1] | 0x4000, 'caption'))
            continue
        if words[i + 1] not in (0x34070008, 0x3407000A):
            raise ValueError(f'{overlay}: Char.name writer count changed at {base + i * 4:#x}')
        if any(w >> 26 == 3 for w in words[candidates[-1] + 1:i]):
            continue
        out.append((base + (i + 1) * 4, words[i + 1] | 0x4000, 'name'))
    if not out:
        raise ValueError(f'{overlay}: no structurally recognised character-name producers')
    return out


def fixed_producers(data, overlay):
    """(address, tagged count word) for every fixed-cell producer."""
    return [(at, word) for at, word, _kind in _producers(data, overlay)]


def producer_tags(data, overlay, original):
    """The count-word tags an overlay assembles.

    Without the original-font tiers both kinds keep the retail fixed cells
    (bit 14). With them the original font is the kit's own face: a
    character name becomes an ordinary row in it, and a caption keeps its
    retail field's midpoint (bit 15, the centring rule)."""
    out = []
    for at, word, kind in _producers(data, overlay):
        if not original:
            out.append((at, word))
        elif kind == 'caption':
            out.append((at, word & ~0x4000 | 0x8000))
    return out
