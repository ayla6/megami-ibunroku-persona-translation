r"""Build the variable-width English font used by the dialogue VWF hack.

Two editions, one face each (EDITIONS; toolpath.FONT_EDITIONS), both built on
every run:

  large  sheet.png        8x16 cells - the release
  small  small_serif.png  8x16 cells - narrower glyphs (up to 8 px wide),
                                      fewer boxes that need a fourth line

Input : each face's glyph sheet in src/mods/latin-alphabet/assets/fonts: transparent
        background, black ink, cell order from sheet-characters.tsv. The cell is anchored at
        its LEFT EDGE (ink not touching it is intentionally offset); the
        baseline is 14 px up with 2 descender rows (ink may use all 16).
Output, per edition (toolpath.font_path):
        vwf_font_<ed>.bin   - the glyphs (0x20-0x7E and the extras), 16 rows
                              x 1 byte, MSB = leftmost pixel
        vwf_width_<ed>.bin  - one byte each, pen advance in pixels (ink right
                              edge + LETTER_GAP, measured from the cell's
                              left edge, so offsets count)
        vwf_index_<ed>.bin  - one u16 each: offset from FONT.BIN start of the
                              glyph's 16 stored rows
        vwf_glyphs_<ed>.asm - armips: writes the stored rows into unused
                              FONT.BIN glyph slots
A disc carries one edition (build.py --mods='english-translation(font=small)'), so both place their glyphs in
the same free slots.
Every one-byte character printed by the translation or name-entry keyboard
gets a stored glyph. Allocation always reads the repository translation corpus,
not a temporary Japanese-only translation tree. Unused one-byte characters
share a blank slot.
Additional sheet characters are stored as narrow glyphs in reclaimed
FONT.BIN cells. Other native glyphs use their original 16 px advance.
Usage : python src/injection/fonts/make_vwf_font.py          (both editions)
        python src/injection/fonts/make_vwf_font.py verify   (the built one)
"""
from functools import lru_cache
from pathlib import Path
from typing import Final
import glob
import unicodedata
import os
import re
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
FONT_DIR = toolpath.FONT_DIR
FIRST, LAST = 0x20, 0x7E
SPACE_ADVANCE = 4
# advance = measured ink width (rightmost column + 1) + this. The engine
# composites a black shadow at +1px right / +1 down of every glyph, so one
# blank ink column clears the shadow without eating into letter spacing.
LETTER_GAP = 1

SHEET_CHARACTERS: Final = Path(FONT_DIR) / 'sheet-characters.tsv'
# Stable byte assignments shared with existing scripts and padding producers.
BUILTIN_MARKS: Final = '…❤￥'
MAX_TEXT_BYTE: Final = 0xEF
TEXT_BYTE_BIAS: Final = 0x68


def read_sheet_characters(path: Path) -> tuple[str, ...]:
    rows = path.read_text(encoding='utf-8').splitlines()
    if not rows or rows[0] != 'characters' or len(rows) < 2:
        raise ValueError(f'{path}: expected a characters header and at least one row')
    seen: set[str] = set()
    for row in rows[1:]:
        for ch in row:
            if ch == ' ':              # reserve an empty cell in this row
                continue
            if ch in seen or not ch.isprintable() or unicodedata.combining(ch):
                raise ValueError(f'{path}: invalid or duplicate sheet character {ch!r}')
            seen.add(ch)
    return tuple(rows[1:])


LAYOUT = read_sheet_characters(SHEET_CHARACTERS)
CH = 16
# Each edition's face: its sheet and its cell width. The code map, the stored
# rows and the advance rule are the same for both.
EDITIONS = {'large': ('sheet.png', 8), 'small': ('small_serif.png', 8)}
assert tuple(EDITIONS) == toolpath.FONT_EDITIONS
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
# One extra code carries an 8 px blank; no wording prints it (the row writes
# the byte directly, and choices.py pads choice columns with it), and being
# blank it costs no FONT.BIN slot.
# A private-use codepoint on purpose: U+3000 is the JP full-width space, which
# the rows and names carry; assigning it an EXTRA_CODE would change Japanese
# encoding rather than provide a separate blank glyph.
WIDE_SPACE = '\ue000'
WIDE_SPACE_ADVANCE = 8
# A BLANK ONE PIXEL WIDE. A two-column choice menu pads column 1 to the column
# 2 stop with 8 px blanks and a 4 px space; the remainder (0-3 px) is made of these, so every
# row's column 2 starts on the stop exactly (choices.py). No text prints it
# and, blank, it costs no FONT.BIN slot.
HAIR_SPACE = '\ue001'
HAIR_SPACE_ADVANCE = 1
INTERNAL_MARKS: Final = BUILTIN_MARKS + WIDE_SPACE + HAIR_SPACE


def custom_marks(layout: tuple[str, ...]) -> str:
    marks = ''.join(ch for row in layout for ch in row
                    if ord(ch) > LAST and ch not in BUILTIN_MARKS)
    if {WIDE_SPACE, HAIR_SPACE}.intersection(marks):
        raise ValueError(f'{SHEET_CHARACTERS}: private-use spacing codes are reserved')
    if LAST + len(INTERNAL_MARKS) + len(marks) + TEXT_BYTE_BIAS > MAX_TEXT_BYTE:
        raise ValueError(f'{SHEET_CHARACTERS}: too many custom glyphs for dialogue bytes EC..EF')
    return marks


RECLAIMED_KANJI: Final = Path(FONT_DIR) / 'reclaimed-kanji.tsv'
SHEET_ERROR: str | None = None
all_marks = ''.join(ch for row in LAYOUT for ch in row
                    if ord(ch) > LAST and ch not in BUILTIN_MARKS)
capacity = MAX_TEXT_BYTE - TEXT_BYTE_BIAS - LAST - len(INTERNAL_MARKS)
CUSTOM_MARKS = custom_marks((all_marks[:capacity],))
EXTRA = INTERNAL_MARKS + CUSTOM_MARKS


def reclaimed_slots(path: Path = RECLAIMED_KANJI) -> dict[str, int]:
    rows = path.read_text(encoding='utf-8').splitlines()
    if not rows or rows[0] != 'slot\tretail':
        raise ValueError(f'{path}: expected slot and retail columns')
    available = [int(row.split('\t', 1)[0], 16) for row in rows[1:]]
    if len(set(available)) != len(available) or any(
        not 0x110 <= slot < 0x7F2 or slot & 0xFF == 0xFF for slot in available
    ):
        raise ValueError(f'{path}: invalid or duplicate reclaimed slots')
    extra = all_marks[capacity:]
    if len(extra) > len(available):
        raise ValueError(f'{path}: {len(extra)} custom marks need {len(extra)} slots; {len(available)} available')
    return dict(zip(extra, available))


ATLAS_CODE = reclaimed_slots()

# The spelling fallback applies only when the sheet lacks a proportional
# character. Explicitly drawn custom marks keep their own spelling.
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
# as the ASCII '*' (src/extraction/psp_glyphs.tsv unit 0x0056), so the text
# arrives with the normal asterisk and no rule has to fold anything.


def spell(text):
    """The source's spelling in the glyphs this font has (SPELL) - applied at
    the encoder/measure layer (etext.spell is this function), never to a
    table."""
    return ''.join(c if c in CUSTOM_MARKS or c in ATLAS_CODE else SPELL.get(c, c) for c in text) if text else text
# Font slots above 0x7E: the ellipsis first (slot 0x7F = byte 0xE7), the
# heart (0x80 = 0xE8), the yen sign (0x81 = 0xE9) - all inside the
# BTLP unpacker's literal range (btlevt_unpack.asm: 88..EF characters,
# F0..FE high pair codes). Their sheet
# rows sit in the other order and load_sheet maps by character, so the
# sheet order and this order need not match. Extra sheet marks beyond
# the built-ins follow the reserved spacing codes.
EXTRA_CODE = {ch: LAST + 1 + i for i, ch in enumerate(EXTRA)}
# the top of the font's code space: ASCII plus the extra map entries
TOP = LAST + len(EXTRA)


def code_of(ch: str) -> int:
    """The font slot a printed character occupies. ASCII is itself; the
    extras take the free codes above 0x7E in map order."""
    o = ord(ch)
    return o if FIRST <= o <= LAST else EXTRA_CODE[ch] if ch in EXTRA_CODE else ATLAS_CODE[ch]


def read_png(path):
    """Return size, ink and opaque-white marker queries for an 8-bit PNG."""
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
        return px[3] > 0 and px != b'\xff' * 4 if bpp == 4 else any(v < 255 for v in px)

    def white(x, y):
        return bpp == 4 and rows[y][x * 4:x * 4 + 4] == b'\xff' * 4

    return w, h, ink, white


def load_sheet(edition: str = toolpath.FONT_EDITION, *,
               advances: dict[int, int] | None = None) -> dict[int, list[int]]:
    """{code: [16 row bytes]} from an edition's glyph sheet.

    The engine composites the drop shadow only from ink rows 0-14 (at +1,+1),
    and the native FONT.BIN has no glyph with ink on row 15 - that row is for
    the shadow, not for ink. Any sheet glyph with row-15 ink is rolled up one
    row so its last ink row is the one the engine shades. Rolled glyphs must
    have a blank row 0 (descenders do); otherwise nothing is lost but the
    engine still could not shade, so fail loudly instead of silently clipping.
    """
    sheet, cw = EDITIONS[edition]
    w, h, ink, white = read_png(os.path.join(FONT_DIR, sheet))
    out = {}
    for ri, line in enumerate(LAYOUT):
        for ci, ch in enumerate(line):
            if ch == ' ' or ord(ch) > LAST and ch not in EXTRA_CODE and ch not in ATLAS_CODE:
                continue
            x0, y0 = ci * cw, ri * CH
            if x0 + cw > w or y0 + CH > h:
                raise ValueError(f'{sheet}: cell for {ch!r} falls outside the sheet')
            g = []
            for y in range(CH):
                b = 0
                for x in range(cw):
                    if x0 + x < w and y0 + y < h and ink(x0 + x, y0 + y):
                        b |= 0x80 >> x
                g.append(b)
            if (ch in CUSTOM_MARKS or ch in ATLAS_CODE) and not any(g):
                raise ValueError(f'{sheet}: cell for {ch!r} is blank')
            code = code_of(ch)
            ends = {x for x in range(cw) if any(white(x0 + x, y0 + y) for y in range(CH))}
            if ends:
                end = min(ends)
                if len(ends) != 1 or any(row & ((1 << (cw - end)) - 1) for row in g):
                    raise ValueError(f'{sheet}: {ch!r} needs one white end column after its ink')
                if advances is not None:
                    advances[code] = end + 1 + LETTER_GAP
            out[code] = g
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
    cell = out.get(code_of('\uffe5'), [])
    if any(cell) or code_of('Y') not in out:
        return
    yen = list(out[code_of('Y')])
    for r in (7, 10):
        yen[r] |= 0x7C          # cols 1-5: the two bars of ￥
    out[code_of('\uffe5')] = yen
    print('make_vwf_font: the sheet has no ￥ cell - using a PLACEHOLDER '
          '(its own Y + two bars); draw the cell and it takes over')


CODE_RE = re.compile(r'<FF[0-9A-F]{2}>|\[[0-9a-f]{4}\]|<[0-9A-F]{2,4}>')


def used_chars(edition=toolpath.FONT_EDITION):
    """Every character the translation prints in an edition (its stored-glyph
    set): the repository en column as that edition reads it
    (vwf_wrap.edition_text), plus over-limit drafts and runtime names.
    Build-mode translation overrides must not change shared source assets."""
    import vwf_wrap      # local: vwf_wrap imports this module
    # User-entered names can print any keyboard character even when every
    # translation row is empty. Derive that repertoire from the keyboard.
    import name_grid
    use = {SPELL.get(unicodedata.normalize('NFKC', c), unicodedata.normalize('NFKC', c))
           for row in name_grid.rows() for c in row}
    for base in (os.path.join(toolpath.DEFAULT_TRANSLATION, 'generated'),
                 os.path.join(toolpath.DEFAULT_TRANSLATION, 'manual')):
        for fp in glob.glob(os.path.join(base, '**', '*.tsv'), recursive=True):
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
                for c in CODE_RE.sub('', vwf_wrap.edition_text(en, edition)):
                    # A CHARACTER THAT FOLDS NEEDS NO GLYPH: ’ prints as ',
                    # – as - (SPELL). Only the folded spelling has to
                    # exist on the sheet, so ask the map the same question the
                    # encoder will.
                    use.add(spell(c))
    return {code_of(c) for c in use if c in EXTRA_CODE or FIRST <= ord(c) <= LAST}


def write_if_changed(path: str, data: bytes) -> None:
    """Preserve generated assets and their timestamps when their bytes match."""
    target = Path(path)
    if not target.exists() or target.read_bytes() != data:
        target.write_bytes(data)


def build(edition=toolpath.FONT_EDITION):
    advances: dict[int, int] = {}
    glyphs = load_sheet(edition, advances=advances)
    used = used_chars(edition) | {code_of(ch) for ch in CUSTOM_MARKS}
    data, widths, store = bytearray(), bytearray(), {}
    for c in range(FIRST, TOP + 1):
        rows = glyphs.get(c, [0] * CH)
        cols = [x for r in rows for x in range(8) if r & (0x80 >> x)]
        if c in advances:
            widths.append(advances[c])
        elif not cols:
            # nothing in the cell: space gets its blank advance, every other
            # blank glyph (any character the translation never prints, and
            # every unused slot) gets a 1 px advance. Zeros make the pen
            # stick: a run of them looks like overrun text, and a 1 is all
            # a blank ever needs to move the pen past itself. WIDE_SPACE is
            # the exception: its blank IS its advance.
            widths.append(WIDE_SPACE_ADVANCE if c == code_of(WIDE_SPACE)
                          else HAIR_SPACE_ADVANCE if c == code_of(HAIR_SPACE)
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
        addresses_path = os.path.join(ROOT, 'src', 'mods', 'base', 'asm', 'common', 'addresses.inc')
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
    # resident state cells: one whole atlas cell each, owned by the patch
    # that keeps run-time state there (FONT_STATE_*, never wiped)
    states = [name for name in declarations if name.startswith('FONT_STATE_')]
    try:
        values.update({name: int(declarations[name].strip(), 0) for name in states})
    except ValueError as ex:
        raise SystemExit('VWF font: invalid atlas ownership address') from ex
    reserved = []
    for name, address in values.items():
        if name.startswith('SF_FONT_CELL_'):
            lo, hi = address - base, address - base + 4
        elif name.startswith('SF_FONT_REPLAY_'):
            lo, hi = address - base - 4, address - base - 4 + 32
        else:                               # gates and state cells
            lo, hi = address - base, address - base + 32
        if name in states and address & 31:
            raise SystemExit(f'VWF font: {name} is not a whole atlas cell')
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


def shared_rows(previous: bytes, rows: bytes) -> int:
    return next((count for count in range(len(rows) - 1, 0, -1)
                 if previous[-count:] == rows[:count]), 0)


def place(store):
    """One shared blank slot + the stored glyphs, packed into the slot runs;
    return (index_by_char, asm)."""
    per = len(STORED_ROWS)
    runs = [list(run) for run in font_free_runs()]
    capacity = sum((b - a) // per for a, b in runs) * per
    index, asm = [None] * (TOP - FIRST + 1), [";; generated by tools/make_vwf_font.py - do not edit"]
    run, previous = 0, None
    slots = [(0, bytes(per))] + sorted(store.items())   # 0 = the shared blank
    # A custom sheet needs more atlas room. Pack matching rows together
    # before reclaiming any more native glyphs. Ties keep code order.
    if any(code > LAST + len(INTERNAL_MARKS) for code in store):
        ordered = [slots.pop(0)]
        while slots:
            end = ordered[-1][1]
            best = max(range(len(slots)), key=lambda i: shared_rows(end, slots[i][1]))
            ordered.append(slots.pop(best))
        slots = ordered
    for code, rows in slots:
        # Rows are read as bytes, so two adjacent glyphs can share an EXACT
        # suffix/prefix without changing either image. Never cross a reserved
        # fragment; on moving to another fragment no predecessor is shared.
        while run < len(runs):
            overlap = shared_rows(previous, rows) if previous is not None else 0
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


def atlas_payload(rows: list[int], advance: int | None = None) -> bytes:
    # The retail wide glyphs have a zero byte at the bottom right. Marker
    # A5 tags a custom narrow cell, with its advance in the last byte.
    ink = [x for row in rows for x in range(8) if row & (0x80 >> x)]
    if advance is None:
        advance = max(ink) + 1 + LETTER_GAP
    return bytes(rows) + bytes(14) + bytes((0xA5, advance))


def atlas_glyphs(edition: str) -> dict[int, bytes]:
    sheet = Path(FONT_DIR) / EDITIONS[edition][0]
    return _atlas_glyphs(edition, sheet.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _atlas_glyphs(edition: str, _stamp: int) -> dict[int, bytes]:
    if not ATLAS_CODE:
        return {}
    advances: dict[int, int] = {}
    glyphs = load_sheet(edition, advances=advances)
    return {slot: atlas_payload(glyphs[slot], advances.get(slot)) for slot in ATLAS_CODE.values()}


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


def verify(edition=toolpath.FONT_EDITION):
    """Fail if any later assembler writer overwrote the built edition's font
    art or its lookup tables."""
    glyphs, _used, store, widths = build(edition)
    extended = atlas_glyphs(edition)
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
        if cell in extended:
            if atlas[cell*32:cell*32+32] != extended[cell]:
                raise SystemExit(f'custom atlas glyph {cell:#x} overwritten')
        elif not any(lo <= cell <= hi for lo, hi in FONT_SLOT_RUNS):
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
    print(f'VWF font verify ({edition}): {len(store)} stored glyphs and runtime index/width tables intact')


if __name__ == "__main__":
    if sys.argv[1:] == ['verify']:
        verify()
        sys.exit(0)
    if sys.argv[1:]:
        raise SystemExit('usage: make_vwf_font.py [verify]')
    if SHEET_ERROR:
        print(SHEET_ERROR, file=sys.stderr)
    sample = ("Me and my great friend ABCDEFGHIJKLMNOPQRSTUVWXYZ. "
              "She said \"abcdefghijklmnopqrstuvwxyz!\" "
              "Quick brown fox jumps over 1,234 lazy dogs.")
    lines = []
    for word in sample.split(" "):
        if lines and len(lines[-1]) + 1 + len(word) <= 36:
            lines[-1] += " " + word
        else:
            lines.append(word)
    for edition in EDITIONS:
        glyphs, used, store, widths = build(edition)
        data = bytearray()
        for c in range(FIRST, TOP + 1):
            data += bytes(glyphs.get(c, [0] * CH))
        write_if_changed(toolpath.font_path('font', edition), bytes(data))
        write_if_changed(toolpath.font_path('width', edition), widths)
        index, asm = place(store)
        for slot, payload in atlas_glyphs(edition).items():
            asm += f'.org FONT_GLYPHS_ADDR + {slot * 32:#06x}\n'
            asm += '    .byte ' + ', '.join(f'{value:#04x}' for value in payload) + '\n'
        write_if_changed(toolpath.font_path('index', edition), b"".join(o.to_bytes(2, "little") for o in index))
        write_if_changed(toolpath.font_path('glyphs', edition), asm.encode('utf-8'))
        preview(data, lines, widths, toolpath.font_path('preview', edition))
        unprint = [chr(c) for c in sorted(set(glyphs) - used) if not any(glyphs[c])]
        print(f"{edition}: {len(widths)} one-byte glyphs, {len(ATLAS_CODE)} reclaimed kanji cells, {len(store)} stored ({len(used)} required including "
              f"runtime names), avg advance {sum(widths) / len(widths):.2f}px")
        if unprint:
            print(f"{edition}: blank entries (unused characters): " + ''.join(unprint))
        missing = [chr(c) for c in sorted(used) if c != 0x20 and not any(glyphs.get(c, [0] * CH))]
        if missing:
            print(f"{edition}: USED BUT UNDRAWN (blank until drawn): " + ''.join(missing))
        tail = [chr(c) for c in sorted(glyphs) if glyphs[c][15] != 0]
        if tail:
            print(f"{edition}: UNSHADED TAIL (ink reaches row 15: the shadow pass never lands "
                  "there, redraw these 1px shorter): " + ''.join(tail))
