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
COMPACT = ROOT / 'src/assets/fonts/smallfont_page_compact.png'
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


def assembly():
    """Code-to-slot mapping comes from the encoder, not a second alphabet map.

    v0 = code, a0/a1 = retail UV, +2C(sp) = tier. Only at/t6/a0/a1 change.
    The slot names a cell in the text band, so the UV is that cell's own
    position - no rectangle arithmetic can drift into another screen's page.
    The regular face takes the first spare cells (scattered, so a table);
    the compact face lands on the text band's one long contiguous spare run
    and is just its base plus the slot.
    """
    regular, compact = cell_codes()
    base = compact[0]
    if compact != list(range(base, base + len(compact))):
        raise SystemExit('smallfont variants: the compact face lost its contiguous spare run')
    out = ['sf_variant_cells:']
    for start in range(0, len(regular), 16):
        values = regular[start:start + 16]
        out.append('    .byte ' + ','.join(str(value) for value in values))
    out += ['    .align 4', 'sf_variant_uv:']
    slot = 0
    for lo, hi in ranges():
        out += [f'    addiu t6,v0,-{lo}', f'    sltiu at,t6,{hi - lo + 1}',
                '    bnez at,@@mapped', f'    addiu t6,t6,{slot}']
        slot += hi - lo + 1
    out += ['    jr ra', '    nop', '@@mapped:',
            '    lw at,0x2C(sp)',
            '    nop',
            '    srl at,at,1',                # 0 for stages 1-2, 1 for stage 3
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
            '    jr ra', '    nop', 'sf_variant_uv_end:']
    return '\n'.join(out) + '\n'


RETIRED_SOURCE = ROOT / 'src/asm/qol/saves.inc'


def retired_ranges(overlay):
    """Stock code another patch replaces, read from its one declaration.

    A fixed-cell tag is a write into retail code. Tagging inside a range an
    optional patch rewrites would either be clobbered by it or clobber it, so
    those rows keep VWF. `qol/saves.inc` already owns the addresses; do not
    repeat them here."""
    pattern = (r'\.definelabel\s+QOL_%s_RETIRED_(\w+)_(START|END),\s*(0x[0-9A-Fa-f]+)'
               % re.escape(overlay))
    starts, ends = {}, {}
    for name, edge, value in re.findall(pattern, RETIRED_SOURCE.read_text()):
        (starts if edge == 'START' else ends)[name] = int(value, 16)
    return [(starts[name], ends[name]) for name in starts if name in ends]


def fixed_producers(data, overlay):
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
            # Literal short captions have a fixed 3/4/5-cell destination and
            # a statically addressed overlay string, unlike variable names.
            if words[i + 1] not in (0x34070003, 0x34070004, 0x34070005):
                continue
            registers = {0: 0}
            for ins in words[max(0, i - 8):i]:
                op, rs, rt = ins >> 26, ins >> 21 & 31, ins >> 16 & 31
                imm = ins & 65535
                if op == 15:
                    registers[rt] = imm << 16
                elif op in (9, 13):
                    value = registers.get(rs)
                    registers[rt] = None if value is None else (
                        value + (imm - 65536 if imm & 32768 else imm) if op == 9 else value | imm)
                elif op == 0 and ins & 63 in (33, 37) and (rs == 0 or rt == 0):
                    registers[ins >> 11 & 31] = registers.get(rt if rs == 0 else rs)
                elif op == 0:
                    registers[ins >> 11 & 31] = None
                elif op not in (2, 3, 4, 5, 40, 41, 43):
                    registers[rt] = None
            source = registers.get(4)
            if source is not None and base <= source < base + len(data):
                out.append((base + (i + 1) * 4, words[i + 1] | 0x4000))
            continue
        if words[i + 1] not in (0x34070008, 0x3407000A):
            raise ValueError(f'{overlay}: Char.name writer count changed at {base + i * 4:#x}')
        if any(w >> 26 == 3 for w in words[candidates[-1] + 1:i]):
            continue
        out.append((base + (i + 1) * 4, words[i + 1] | 0x4000))
    if not out:
        raise ValueError(f'{overlay}: no structurally recognised character-name producers')
    return out
