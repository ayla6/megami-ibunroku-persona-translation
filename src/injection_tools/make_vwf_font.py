r"""Build the variable-width English font used by the dialogue VWF hack.

Input : src/asm/font/sheet.png - the glyph sheet: transparent background,
        black ink, 8x16 cells laid out in four rows of 26 (26/26/26/10):
        A-Z / a-z / 0-9 punctuation / <>*/|\#`~= . The cell is anchored at
        its LEFT EDGE (ink not touching it is intentionally offset); the
        baseline is 14 px up with 2 descender rows (ink may use all 16).
Output: font/vwf_font.bin   - 95 glyphs (0x20-0x7E), 16 rows x 1 byte,
                              MSB = leftmost pixel
        font/vwf_width.bin  - 95 bytes, pen advance in pixels (ink right
                              edge + LETTER_GAP, measured from the cell's
                              left edge, so offsets count)
        font/vwf_index.bin  - 95 u16: offset from FONT.BIN start of each
                              glyph's 16 stored rows
        font/vwf_glyphs.asm - armips: writes the stored rows into unused
                              FONT.BIN glyph slots
Every character the translation prints gets its own stored glyph; the rest
share one blank slot (they never draw, so nothing is lost, and the free
FONT.BIN slots are finite - 1344 bytes). Anything non-ASCII falls back to
the Japanese font at 16 px. The dialogue engine draws rows 0-15 in both
formats (vwf/vwf_dialog_draw.asm).
Usage : python src/injection_tools/make_vwf_font.py
"""
import glob
import os
import re
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FONT_DIR = os.path.join(ROOT, "src", "asm", "font")
FIRST, LAST = 0x20, 0x7E
SPACE_ADVANCE = 4
# advance = measured ink width (rightmost column + 1) + this. The engine
# composites a black shadow at +1px right / +1 down of every glyph, so one
# blank ink column clears the shadow without eating into letter spacing.
LETTER_GAP = 1

# The ￥ cell sits where the fullwidth ＊ was: the sheet's asterisk is retired
# (every '*' prints the ASCII one now, make_vwf_font.SPELL folds ＊ to it), so
# the user redrew that cell as the currency mark - the ONLY cell whose art the
# font was missing. load_sheet maps by CHARACTER, so the map follows the art
# and not the other way round.
LAYOUT = ['ABCDEFGHIJKLMNOPQRSTUVWXYZ',
          'abcdefghijklmnopqrstuvwxyz',
          "0123456789:;+-&%'\".,!?(){}",
          '<>*/|\\#`~=￥…']
CW, CH = 8, 16
# THE CHARACTER MAP. ASCII prints as itself - the dialogue engine encodes
# `ord(ch) + VWF_BIAS`, so those codes are fixed and cannot move. Anything
# ELSE gets the next free code above 0x7E and lives here, which is why it
# is written after the '=': it is the character after the ASCII run.
#
# Every character used by the translation needs this font's glyph and metrics
# rather than the Japanese FONT.BIN fallback (see used_chars).
# A BLANK AS WIDE AS A CAPITAL. The STATUS page's name row is a 9-byte script
# (code, id, gap, code, id, FF 01), so its separator is ONE byte - and the
# font's own space is 4 px, which reads cramped between two names ("Kei Nanjo").
# One extra code carries an 8 px blank; no text prints it (the row writes the
# byte directly), and being blank it costs no FONT.BIN slot.
# A private-use codepoint on purpose: U+3000 is the JP full-width space, which
# the rows and names carry; assigning it an EXTRA_CODE would change Japanese
# encoding rather than provide a separate blank glyph.
WIDE_SPACE = '\ue000'
WIDE_SPACE_ADVANCE = 8
EXTRA = '…＊￥' + WIDE_SPACE
# THE SPELLING FOLD: characters the source writes typographically and this
# font cannot draw, in the spelling the sheet DOES have. The PSP-US wording
# uses the curly apostrophe ('Don\u2019t come then!'); the font's cells hold
# the ASCII one, and without a fold such a row falls through to the Japanese
# FONT.BIN at 16 px or is refused. A typographic mark and its ASCII twin are
# the same character: folding is spelling, never wording.
#
# WHERE IT IS APPLIED: nowhere in a table. translation/ keeps the source's own
# character (a curly apostrophe stays curly), and the fold happens where text
# becomes bytes or pixels - etext.spell (encode), talktl.check (the build
# gate), vwf_wrap.char_width (the pricing), toolbelt.smallfont_char and
# smallfont_vwf.char_code (the battle small font). One map, one rule, so a row
# measures and prints the same characters it shows.
SPELL = {'\u2018': "'", '\u2019': "'",   # single quotes/apostrophes
         '\u201c': '"', '\u201d': '"',   # double quotes
         '\u2013': '-', '\u2014': '-',   # en/em dash
         '\u2212': '-'}                   # minus sign
# The fullwidth asterisk is NOT here: the PSP's glyph table spells that unit
# as the ASCII '*' (src/extraction_tools/psp_glyphs.tsv unit 0x0056), so the text
# arrives with the normal asterisk and no rule has to fold anything.


def spell(text):
    """The source's spelling in the glyphs this font has (SPELL) - applied at
    the encoder/measure layer (etext.spell is this function), never to a
    table."""
    return ''.join(SPELL.get(c, c) for c in text) if text else text
# Font slots above 0x7E: the ellipsis first (slot 0x7F = byte 0xE7), the
# fullsize ＊ (0x80 = 0xE8), the yen sign (0x81 = 0xE9) - all inside the
# BTLP unpacker's literal range (btlevt_unpack.asm: 88..E9 characters,
# EA..FE pair codes; the literal range grew by one for ￥). Their sheet
# rows sit in the other order and load_sheet maps by character, so the
# sheet order and this order need not match. The curly quotes are NOT
# glyphs - units 0x0025-0x0028 are plain ' and " in the mapping, and the
# full-width ASCII forms map to their plain equivalents there too: the
# table is the output shape, nothing in code replaces anything.
EXTRA_CODE = {ch: LAST + 1 + i for i, ch in enumerate(EXTRA)}
# the top of the font's code space: ASCII plus the extra map entries
TOP = LAST + len(EXTRA)


def code_of(ch):
    """The font slot a printed character occupies. ASCII is itself; the
    extras take the free codes above 0x7E in map order."""
    o = ord(ch)
    return o if FIRST <= o <= LAST else EXTRA_CODE[ch]


def read_png(path):
    """(w, h, ink) from an 8-bit RGB/RGBA PNG (ink = non-transparent/non-white)."""
    data = open(path, 'rb').read()
    pos, idat = 8, b''
    w = h = depth = ctype = None
    while pos < len(data):
        ln, typ = struct.unpack('>I4s', data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b'IHDR':
            w, h, depth, ctype, *_ = struct.unpack('>IIBBBBB', chunk)
        elif typ == b'IDAT':
            idat += chunk
        pos += 12 + ln
    if depth != 8 or ctype not in (2, 6):
        raise SystemExit(f'make_vwf_font: {path}: need an 8-bit RGB/RGBA PNG')
    raw = zlib.decompress(idat)
    bpp = 3 if ctype == 2 else 4
    stride = w * bpp
    rows, prev, i = [], bytearray(stride), 0
    for _y in range(h):
        f = raw[i]; i += 1
        line = bytearray(raw[i:i + stride]); i += stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 0xFF
            elif f == 2:
                line[x] = (line[x] + b) & 0xFF
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 0xFF
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        rows.append(line)
        prev = line

    def ink(x, y):
        px = rows[y][x * bpp:(x + 1) * bpp]
        return px[3] > 0 if bpp == 4 else any(v < 255 for v in px)
    return w, h, ink


def load_sheet():
    """{code: [16 row bytes]} from the glyph sheet.

    The engine composites the drop shadow only from ink rows 0-14 (at +1,+1),
    and the native FONT.BIN has no glyph with ink on row 15 - that row is for
    the shadow, not for ink. Any sheet glyph with row-15 ink is rolled up one
    row so its last ink row is the one the engine shades. Rolled glyphs must
    have a blank row 0 (descenders do); otherwise nothing is lost but the
    engine still could not shade, so fail loudly instead of silently clipping.
    """
    w, h, ink = read_png(os.path.join(FONT_DIR, "sheet.png"))
    out = {}
    for ri, line in enumerate(LAYOUT):
        for ci, ch in enumerate(line):
            x0, y0 = ci * CW, ri * CH
            g = []
            for y in range(CH):
                b = 0
                for x in range(CW):
                    if x0 + x < w and y0 + y < h and ink(x0 + x, y0 + y):
                        b |= 0x80 >> x
                g.append(b)
            out[code_of(ch)] = g
    derive_glyphs(out)
    return out


# Glyphs DERIVED from the sheet's own letters, for marks the sheet has no cell
# for but the wording prints. Not invented art: the mark is composed from a
# cell the user drew, and the derivation is written down.
# Each row of the mark is one of: a sheet row to copy, or (bitmask) a set of
# columns to fill - the columns a yen sign's bars cross.
def derive_glyphs(out):
    """Fill a glyph cell the sheet leaves empty although the wording prints it.

    An empty ￥ cell uses the sheet's Y with two bars. A cell with authored
    ink is left unchanged.
    """
    cell = out[code_of('\uffe5')]
    if any(cell):
        return
    yen = list(out[code_of('Y')])
    for r in (7, 10):
        yen[r] |= 0x7C          # cols 1-5: the two bars of ￥
    out[code_of('\uffe5')] = yen
    print('make_vwf_font: the sheet has no ￥ cell - using a PLACEHOLDER '
          '(its own Y + two bars); draw the cell and it takes over')


CODE_RE = re.compile(r'<FF[0-9A-F]{2}>|\[[0-9a-f]{4}\]|<[0-9A-F]{2,4}>')


def used_chars():
    """Every character the translation prints (the stored-glyph set): the en
    column, plus over-limit drafts (they are the shipping text once placed)."""
    use = set()
    for base in ('translation/generated', 'translation/manual'):
        for fp in glob.glob(os.path.join(ROOT, base, '**', '*.tsv'), recursive=True):
            lines = open(fp, encoding='utf-8').read().splitlines()
            if not lines:
                continue
            head = lines[0].split('\t')
            if 'en' not in head:
                continue
            i_en, i_note = head.index('en'), head.index('note') if 'note' in head else None
            for line in lines[1:]:
                f = line.split('\t')
                en = f[i_en] if i_en < len(f) else ''
                if not en.strip() and i_note is not None and i_note < len(f):
                    note = f[i_note]
                    if note.startswith('over limit') and '; ' in note:
                        en = note.split('; ', 1)[1]
                for c in CODE_RE.sub('', en):
                    # A CHARACTER THAT FOLDS NEEDS NO GLYPH: ＊ prints as '*',
                    # ’ as ', – as - (SPELL). Only the folded spelling has to
                    # exist on the sheet, so ask the map the same question the
                    # encoder will.
                    use.add(SPELL.get(c, c))
    return {code_of(c) for c in use if c in EXTRA_CODE or FIRST <= ord(c) <= LAST}


def asm_code_space():
    """VWF_GLYPHS as the renderers declare it (src/asm/vwf/vwf_dialog.asm).

    The engine prints a byte only while `byte - 0x88 < VWF_GLYPHS`; anything
    above falls through to a space. So that number IS the printable code
    space and must equal what this file generates (TOP - FIRST + 1), or a
    character the encoder emits disappears on screen without a word of
    complaint - the ellipsis and ＊sigh＊ did exactly that until 2026-10-25.
    """
    path = os.path.join(ROOT, 'src', 'asm', 'vwf', 'vwf_dialog.asm')
    m = re.search(r'^VWF_GLYPHS\s+equ\s+(\d+)', open(path, encoding='utf-8').read(), re.M)
    if not m:
        raise SystemExit(f'make_vwf_font: {path}: no VWF_GLYPHS equ line')
    return int(m.group(1))


def build():
    glyphs = load_sheet()
    used = used_chars()
    data, widths, store = bytearray(), bytearray(), {}
    for c in range(FIRST, TOP + 1):
        rows = glyphs.get(c, [0] * CH)
        cols = [x for r in rows for x in range(CW) if r & (0x80 >> x)]
        if not cols:
            # nothing in the cell: space gets its blank advance, every other
            # blank glyph (any character the translation never prints, and
            # every unused slot) gets a 1 px advance. Zeros make the pen
            # stick: a run of them looks like overrun text, and a 1 is all
            # a blank ever needs to move the pen past itself. WIDE_SPACE is
            # the exception: its blank IS its advance.
            widths.append(WIDE_SPACE_ADVANCE if c == code_of(WIDE_SPACE)
                          else SPACE_ADVANCE if c == 0x20 else 1)
        elif c == 0x20:
            widths.append(SPACE_ADVANCE)
        else:
            # ink width from the cell's left edge = rightmost column + 1
            # ('A' is ink 0-6 = 7 px wide, not 6 - count the edge pixel)
            widths.append((max(cols) + 1) + LETTER_GAP)
        if cols and c in used:
            store[c] = bytes(rows)
    return glyphs, used, store, bytes(widths)


# Unused FONT.BIN glyph slots (filler "*" or blank glyphs that no text uses),
# as contiguous runs [first, last]. Stored glyphs are packed back to back.
FONT_SLOT_RUNS = [(0x0F7, 0x10F), (0x7F2, 0x7FF), (0x64E, 0x64E), (0x65F, 0x65F),
                  (0x662, 0x662), (0x0A0, 0x0A0), (0x0D2, 0x0D2),
                  (0x667, 0x667), (0x6DD, 0x6DD)]
STORED_ROWS = range(0, 16)   # the sheet's baseline is 14 up / 2 down: all 16
# The small-font anchor shares the atlas. Its address declarations own the
# reservations; never infer spare space from how many glyphs happened to fit.


def font_reservations(addresses_path=None):
    """Protected FONT-relative byte ranges, derived from addresses.inc.

    Gates own one atlas cell; replay entries have a preceding guard word and
    own one cell including that guard. Registration cells own one word each.
    Parse the address declarations fail-closed: these owners currently use
    literal addresses, and an unsupported/missing declaration is not free RAM.
    """
    if addresses_path is None:
        addresses_path = os.path.join(ROOT, 'src', 'asm', 'common', 'addresses.inc')
    with open(addresses_path, encoding='utf-8') as source:
        declarations = dict(re.findall(r'^\s*(\w+)\s+equ\s+([^;\n]+)',
                                       source.read(), re.M))
    prefixes = ('SF_FONT_GATE_', 'SF_FONT_REPLAY_', 'SF_FONT_CELL_')
    names = [name for name in declarations if name.startswith(prefixes)]
    groups = [{name[len(prefix):] for name in names if name.startswith(prefix)}
              for prefix in prefixes]
    if not groups[0] or not all(group == groups[0] for group in groups[1:]):
        raise SystemExit('VWF font: missing or unpaired small-font ownership declarations')
    try:
        base = int(declarations['FONT_GLYPHS_ADDR'].strip(), 0)
        values = {name: int(declarations[name].strip(), 0) for name in names}
    except (KeyError, ValueError) as ex:
        raise SystemExit('VWF font: invalid atlas ownership address') from ex
    reserved = []
    for name, address in values.items():
        if name.startswith('SF_FONT_CELL_'):
            lo, hi = address - base, address - base + 4
        elif name.startswith('SF_FONT_REPLAY_'):
            lo, hi = address - base - 4, address - base - 4 + 32
        else:
            lo, hi = address - base, address - base + 32
        if not 0 <= lo < hi <= 0x10000:
            raise SystemExit(f'VWF font: {name} is outside FONT.BIN')
        reserved.append((lo, hi))
    return sorted(reserved)


def font_free_runs():
    """Subtract all protected bytes, preserving the candidate allocation order."""
    reserved = font_reservations()
    free = []
    for first, last in FONT_SLOT_RUNS:
        fragments = [(first * 32, (last + 1) * 32)]
        for lo, hi in reserved:
            remaining = []
            for a, b in fragments:
                if b <= lo or hi <= a:
                    remaining.append((a, b))
                else:
                    if a < lo:
                        remaining.append((a, lo))
                    if hi < b:
                        remaining.append((hi, b))
            fragments = remaining
        free.extend(fragments)
    return free


def place(store):
    """One shared blank slot + the stored glyphs, packed into the slot runs;
    return (index_by_char, asm)."""
    per = len(STORED_ROWS)
    runs = [list(run) for run in font_free_runs()]
    capacity = sum((b - a) // per for a, b in runs) * per
    index, asm = [None] * (TOP - FIRST + 1), [";; generated by tools/make_vwf_font.py - do not edit"]
    run, previous = 0, None
    slots = [(0, bytes(per))] + sorted(store.items())   # 0 = the shared blank
    for code, rows in slots:
        # Rows are read as bytes, so two adjacent glyphs can share an EXACT
        # suffix/prefix without changing either image. Never cross a reserved
        # fragment; on moving to another fragment no predecessor is shared.
        while run < len(runs):
            overlap = next((n for n in range(per - 1, 0, -1)
                            if previous is not None and previous[-n:] == rows[:n]), 0)
            off = runs[run][0] - overlap
            if off + per <= runs[run][1]:
                break
            run += 1
            previous = None
        if run == len(runs):
            raise SystemExit(
                f"VWF font does not fit in the free FONT.BIN slots: "
                f"{len(slots) * per} bytes needed, {capacity} available before sharing")
        runs[run][0] = off + per
        previous = rows
        if code == 0:
            blank = off
        else:
            index[code - FIRST] = off
            asm.append(f".org FONT_GLYPHS_ADDR + 0x{off:04X}  ; {chr(code)!r}")
            asm.append("    .byte " + ", ".join(f"0x{rows[r]:02X}" for r in STORED_ROWS))
    index = [blank if o is None else o for o in index]
    return index, "\n".join(asm) + "\n"


def preview(data, lines, widths, path):
    """Render (advance-accurate) sample lines with the shadow the engine draws:
    white ink, black copy at +1,+1 - the same offset the sheet is spaced for."""
    try:
        from PIL import Image
    except ImportError:
        return
    pal = {0: (32, 96, 48), 1: (240, 240, 240), 2: (0, 0, 0)}
    W = max((sum(widths[code_of(c) - FIRST] for c in line) for line in lines), default=0)
    img = Image.new("RGB", (W + 8, 17 * len(lines) + 8), pal[0])
    px = img.load()
    for li, line in enumerate(lines):
        buf = [[0] * (W + 6) for _ in range(17)]
        x = 0
        for c in line:
            g = data[(code_of(c) - FIRST) * 16:(code_of(c) - FIRST + 1) * 16]
            if len(g) == 16:
                for r in range(16):
                    for b in range(8):
                        if g[r] & (0x80 >> b) and x + b < W + 6:
                            buf[r][x + b] |= 1
                            # black shadow at +1,+1, like the engine draws it;
                            # it lands one row past 16-px descender ink too,
                            # so the buffer keeps a 17th row for it
                            if x + b + 1 < W + 6:
                                buf[r + 1][x + b + 1] |= 2
            x += widths[code_of(c) - FIRST]
        for r in range(17):
            for cx in range(W + 6):
                v = buf[r][cx]
                if v:
                    px[4 + cx, 4 + li * 17 + r] = pal[1 if v & 1 else 2]
    img = img.resize((img.width * 3, img.height * 3), Image.NEAREST)
    img.save(path)


def verify():
    """Fail if any later assembler writer overwrote font art or its lookup tables."""
    _glyphs, _used, store, widths = build()
    index, _asm = place(store)
    with open(os.path.join(ROOT, 'build', 'FONT.BIN'), 'rb') as source:
        atlas = source.read()
    with open(os.path.join(ROOT, 'data', 'psx', 'FONT.BIN'), 'rb') as source:
        retail = source.read()
    if len(atlas) != len(retail):
        raise SystemExit('VWF font verify: atlas size changed')
    # Only declared spare cells may be modified, including executable gates.
    # Check every other retail cell so a gate address typo cannot silently
    # replace a real Japanese glyph even when no English glyph overlaps it.
    for cell in range(len(retail) // 32):
        if not any(lo <= cell <= hi for lo, hi in FONT_SLOT_RUNS):
            start = cell * 32
            if atlas[start:start + 32] != retail[start:start + 32]:
                raise SystemExit(f'VWF font verify: retail atlas cell {cell:#x} overwritten')
    for code, rows in store.items():
        offset = index[code - FIRST]
        if atlas[offset:offset + len(rows)] != rows:
            raise SystemExit(f'VWF font verify: glyph {code:#x} overwritten at FONT.BIN+{offset:#x}')
    blank = next((index[code - FIRST] for code in range(FIRST, TOP + 1)
                  if code not in store), None)
    if blank is not None and atlas[blank:blank + len(STORED_ROWS)] != bytes(len(STORED_ROWS)):
        raise SystemExit(f'VWF font verify: shared blank glyph overwritten at FONT.BIN+{blank:#x}')
    with open(os.path.join(ROOT, 'build', 'persona.sym'), encoding='utf-8') as source:
        symbols = {m.group(2): int(m.group(1), 16) for line in source
                   if (m := re.match(r'^([0-9A-Fa-f]{8})\s+(\S+)', line))}
    with open(os.path.join(ROOT, 'build', 'SLPS_005.00'), 'rb') as source:
        exe = source.read()
    base, size = struct.unpack_from('<II', exe, 0x18)
    for name, expected in (('vwf_font_index', b''.join(v.to_bytes(2, 'little') for v in index)),
                           ('vwf_font_width', widths)):
        address = symbols[name]
        if not base <= address or address + len(expected) > base + size:
            raise SystemExit(f'VWF font verify: {name} is outside the loaded executable')
        offset = 0x800 + address - base
        if exe[offset:offset + len(expected)] != expected:
            raise SystemExit(f'VWF font verify: runtime {name} table overwritten')
    print(f'VWF font verify: {len(store)} stored glyphs and runtime index/width tables intact')


if __name__ == "__main__":
    if sys.argv[1:] == ['verify']:
        verify()
        sys.exit(0)
    if sys.argv[1:]:
        raise SystemExit('usage: make_vwf_font.py [verify]')
    if asm_code_space() != TOP - FIRST + 1:
        raise SystemExit(
            f"make_vwf_font: src/asm/vwf/vwf_dialog.asm declares VWF_GLYPHS "
            f"{asm_code_space()} but the font's code space is {TOP - FIRST + 1} "
            f"(0x{FIRST:02X}-0x{TOP:02X}); a byte above the renderer's limit "
            f"prints as a space, so every generated glyph must be inside it")
    glyphs, used, store, widths = build()
    data = bytearray()
    for c in range(FIRST, TOP + 1):
        data += bytes(glyphs.get(c, [0] * CH))
    open(os.path.join(FONT_DIR, "vwf_font.bin"), "wb").write(bytes(data))
    open(os.path.join(FONT_DIR, "vwf_width.bin"), "wb").write(widths)
    index, asm = place(store)
    open(os.path.join(FONT_DIR, "vwf_index.bin"), "wb").write(b"".join(o.to_bytes(2, "little") for o in index))
    open(os.path.join(FONT_DIR, "vwf_glyphs.asm"), "w", newline="\n").write(asm)
    sample = ("Mark: \"Persona-sama\"? Like that's gonna show you your future! "
              "If it were that easy, nobody would ever worry. "
              "Quick brown fox jumps over 1,234 lazy dogs.")
    lines = []
    for word in sample.split(" "):
        if lines and len(lines[-1]) + 1 + len(word) <= 36:
            lines[-1] += " " + word
        else:
            lines.append(word)
    preview(data, lines, widths, os.path.join(FONT_DIR, "vwf_preview.png"))
    unprint = [chr(c) for c in sorted(set(glyphs) - used) if not any(glyphs[c])]
    print(f"{len(widths)} glyphs, {len(store)} stored ({len(used)} used by the "
          f"translation), avg advance {sum(widths) / len(widths):.2f}px")
    if unprint:
        print("blank entries (unused characters): " + ''.join(unprint))
    missing = [chr(c) for c in sorted(used) if c != 0x20 and not any(glyphs.get(c, [0] * CH))]
    if missing:
        print("USED BUT UNDRAWN (blank until drawn): " + ''.join(missing))
    tail = [chr(c) for c in sorted(glyphs) if glyphs[c][15] != 0]
    if tail:
        print("UNSHADED TAIL (ink reaches row 15: the shadow pass never lands "
              "there, redraw these 1px shorter): " + ''.join(tail))
