"""Dialogue choice options of SLPS_005.00 (the text drawn after <FF0E><n> in event boxes).

  python src/injection/resident/choices.py dump     write/refresh sparse manual CHOICES.tsv work
  python src/injection/resident/choices.py build    QA + generate build/choices.asm
  python src/injection/resident/choices.py sync-boot
    regenerate the PSX choices port from PSP BOOT extraction

Layout (RAM, resident main EXE; file offset = addr - 0x80010000 + 0x800):
  0x8004D760: 32 entries x 8 bytes: u32 pointer to the option string, then 4 bytes
              [rows, cols, width_chars, 0]   (the <FF0E> handler is at 0x800672AC)
  strings:    0x8004D430-0x8004D75D, options separated by <FF03>, ended by <FF01>.
The English build rebuilds the table at NEW_TABLE with an entry for every id
BOOT_MAP names (the PSP's choice 35 is past the PSX's 32) once such an id has
English to place (otherwise the table stays where it is): it grows down into
the tail of the string pool and still ends at 0x8004D860, and every reader
in ADV/DNG/S2D (rebase_sites) gets the new low half (build/choices_<file>.asm).
An id the PSX table lacks has its row at pos ADDED_POS + idx.
The strings are drawn by the dialogue text interpreter, so English goes through the dialogue VWF
(variable width, ASCII + 0x68). The option grid is fixed: column 2 of a 2-column menu starts at
(width_chars + 1) * 16 px, the cursor underline is width_chars * 16 px long.

CHOICES.tsv `en` syntax: rows joined by <FF03>; cells of a 2-column row joined by `|`
(e.g. `Start Game|Quit<FF03>Check Coins|Rules`). Column 1 is padded to the column 2 pixel start exactly:
8 px blanks (make_vwf_font.WIDE_SPACE), at most one 4 px space, then 1 px blanks (HAIR_SPACE) for the rest. Single-column menus: the underline width byte is raised if an option is wider
than width_chars * 16 px. Empty `en` = left Japanese.
The box shows three 16 px rows and the prompt's arming line is the first, so the list may use two;
four options must therefore stay a 2x2 grid. Wording that fits no 2-column width is routed to manual
as an over-limit draft (full PSP wording in the note) instead of falling back to a taller list that
would scroll its first option out of view.
The strings are repacked into the freed original slots and unreferenced SLPS functions (pointer table is
rewritten), so English may be longer than the Japanese.

Provenance: every row comes from the PSP-US BOOT.BIN option table
(extracted_text/psp_us/EBOOT.tsv - the single per-file extract).
BOOT_MAP below gives, per PS1 row, the US option indices in PS1 cell order
(row-major); the few 2x2 rows whose PSP order differs are matched semantically,
verified against the JP EBOOT table:
  idx3  PS1 [start, quit, coins, explanation] -> US [87,90,88,89]
  idx12 PS1 [fuse, never-mind, summon, story] -> US [63,66,64,65]
        (Create Persona, Leave, Take on Persona, Talk)
  idx24 PS1 [start, quit, cards, explanation] -> US [27,30,28,29]
All other rows are positional slices. `sync-boot` writes the generated PSX-target
choice table; it does not duplicate auto wording in the manual TSV.
"""
import os
import struct
import sys

# PS1 row -> US BOOT option indices in PS1 cell order (row-major).
BOOT_MAP = {
    0: [95, 96], 1: [93, 94], 2: [91, 92], 3: [87, 90, 88, 89],
    4: [85, 86], 5: [81, 82, 83, 84], 6: [77, 78, 79, 80],
    7: [75, 76], 8: [73, 74], 9: [71, 72], 10: [69, 70],
    11: [67, 68], 12: [63, 66, 64, 65], 13: [59, 60, 61, 62],
    14: [55, 56, 57, 58], 15: [53, 54], 16: [51, 52], 17: [49, 50],
    18: [47, 48], 19: [45, 46], 20: [41, 42, 43, 44],
    21: [37, 38, 39, 40], 22: [35, 36], 23: [31, 32, 33, 34],
    24: [27, 30, 28, 29], 25: [25, 26], 26: [23, 24], 27: [21, 22],
    28: [19, 20], 29: [17, 18], 30: [15, 16], 31: [13, 14],
    # PSP-only menus, which head the BOOT list in reverse id order (35, 34,
    # 33, 32, then PS1 idx 31 down to 0). A ported box asks 35 (E0/118's
    # retry, escript); 32-34 are menus no PSX script reaches.
    35: [0, 1],
}

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import toolbelt  # noqa: E402
import etext                  # noqa: E402
import strlib                  # noqa: E402
import vwf_wrap   # noqa: E402
import make_vwf_font  # noqa: E402

ROOT = etext.ROOT
TABLE = 0x8004D760
COUNT = 32
BASE = 0x80010000 - 0x800
# The English table carries every choice id BOOT_MAP names. It grows down
# into the tail of the Japanese string pool (the strings it covers are all
# repacked - build checks), so it still ends where the retail one does and
# every reader only needs its low half moved (rebase_sites).
SIZE = max(BOOT_MAP) + 1
NEW_TABLE = TABLE - 8 * (SIZE - COUNT)
# The row pos of an id the PSX table does not have: past every SLPS offset.
ADDED_POS = 0x1000000
# The overlays that index the table: `lui at, 0x8005` / `addiu at, at,
# lo(TABLE + field)` pairs, found by scanning the retail files.
READERS = ('ADV', 'DNG', 'S2D')
# The box the choice list is drawn into. roomsetup.c sets
# g_bg_layers[4].h = 0x30 (three 16 px rows), and the prompt's arming line is
# the first of them, so the list itself may occupy at most two rows. A 2x2
# grid is therefore the only shape that carries four options; a taller
# single-column list scrolls the first option out of the box.
BOX_ROWS = 3
OPTION_ROWS = BOX_ROWS - 1
BOX_PX = 239          # a line may use 239 so the engine's own wrap never skips


class OverLimit(Exception):
    """PSP wording that cannot be drawn whole in the box the engine owns."""


# Unreferenced SLPS functions (tools/deadfuncs.py), not used by the VWF (0x80015510 is vwf_name_map). NOT the SLPS_FREE_START..END
# area of common/addresses.inc: that one holds runtime variables (e.g. the CD flag at 0x80055C34).
# (0x80011FBC, 0x800120A4) now holds skill_name_copy (common/addresses.inc SKILL_CODE_ADDR)
# (0x800316DC, 0x80031770) now holds name_col_ring (common/addresses.inc NAME_RING_STUB_ADDR)
def _free():
    """The spill pool. The head of the 0x8002BC84 run is the Persona name
    bank (addresses.inc PERSONA_HDR_BUF..PERSONA_HDR_BUF_END, runtime-written
    48 bytes), so the pool gets only its tail - read, never restated: a
    window two owners write was the 2026-10-29 crash."""
    lo = toolbelt.asm_equ('PERSONA_HDR_BUF')
    hi = toolbelt.asm_equ('PERSONA_HDR_BUF_END')
    limit = toolbelt.asm_equ('PERSONA_HDR_LIMIT')
    assert hi <= limit, 'Persona name bank escapes its dead run'
    tab_end = toolbelt.asm_equ('SF_TAB_HELPER_END')
    return [(0x8002E698, 0x8002E744), (hi, limit), (tab_end, 0x80011D0C),
            (0x80011AC0, 0x80011B88), (0x8001FF24, 0x8001FFB4)]


FREE = _free()
TSV = os.path.join(toolpath.TRANSLATION, 'manual', 'strings', 'CHOICES.tsv')
OUT = os.path.join(ROOT, 'build', 'choices.asm')
NL = chr(10)
TAB = chr(9)


def original():
    d = open(os.path.join(ROOT, 'data', 'psx', 'SLPS_005.00'), 'rb').read()
    rows = []
    for k in range(COUNT):
        at = TABLE + 8 * k - BASE
        ptr, = struct.unpack_from('<I', d, at)
        params = d[at + 4:at + 8]
        s = ptr - BASE
        e = d.index(b'\xff\x01', s) + 2
        rows.append(dict(idx=k, ptr=ptr, params=params, ja=etext.decode(d[s:e]), size=e - s))
    return rows


def added():
    """Rows for the ids past the PSX table (BOOT_MAP): no Japanese, and a
    shape from their option count - one column while it fits the box's
    option rows, else the 2x2 grid."""
    out = []
    for k in range(COUNT, SIZE):
        n = len(BOOT_MAP.get(k, ()))
        if not n:
            continue
        shape = (n, 1) if n <= OPTION_ROWS else (2, 2)
        out.append(dict(idx=k, ptr=None, params=bytes([shape[0], shape[1], 0, 0]),
                        ja='', size=0, pos=ADDED_POS + k))
    return out


def pos_idx():
    """{row pos offset: idx}: a PSX id's original string offset, an added
    id's ADDED_POS + idx."""
    out = {r['ptr'] - BASE: r['idx'] for r in original()}
    out.update({r['pos']: r['idx'] for r in added()})
    return out


def rebase_sites():
    """{overlay: [(va of the addiu, the table field it adds)]}: every
    adjacent `lui at, 0x8005` / `addiu at, at, lo(TABLE + 0..7)` pair."""
    out = {}
    for name in READERS:
        d = open(os.path.join(ROOT, 'data', 'psx', f'{name}.BIN'), 'rb').read()
        sites = []
        for o in range(0, len(d) - 7, 4):
            lui, addiu = struct.unpack_from('<II', d, o)
            field = (addiu & 0xFFFF) - (TABLE & 0xFFFF)
            if lui == 0x3C018005 and addiu >> 16 == 0x2421 and 0 <= field < 8:
                sites.append((toolbelt.file_va(name, o + 4), field))
        out[name] = sites
    return out


def read_tsv():
    """{idx: en} merged over the canonical table (manual wins, toolbelt)."""
    import toolbelt
    orig = pos_idx()
    out = {}
    for r in toolbelt.merged_rows('SLPS_005.00'):
        i = orig.get(int(r['pos'], 16))
        if i is not None and (r['en'] or '').strip():
            out[i] = r['en']
    return [dict(idx=i, en=en) for i, en in sorted(out.items())]


def _read_tsv_legacy():
    rows = []
    if os.path.exists(TSV):
        for r in strlib.tsv_rows(TSV, required=('idx', 'ptr', 'params', 'ja', 'en')):
            rows.append(r)
    return rows


def dump():
    old = {int(r["idx"]): r["en"] for r in read_tsv() if r["idx"].isdigit()}
    auto = auto_en()
    os.makedirs(os.path.dirname(TSV), exist_ok=True)
    kept = []
    for r in original():
        en = old.get(r['idx'], '')
        if r['idx'] in auto and not etext.has_text(en):
            continue
        kept.append(f"{r['idx']}\t{r['ptr']:08X}\t{r['params'].hex()}\t{r['ja']}\t"
                    f"{en if etext.has_text(en) else ''}")
    if not kept:
        if os.path.exists(TSV):
            os.remove(TSV)
        print(f'wrote {TSV}: fully auto-covered, worklist removed')
        return
    with open(TSV, 'w', encoding='utf-8', newline=NL) as o:
        o.write('idx\tptr\tparams\tja\ten' + NL)
        o.write(NL.join(kept) + NL)
    print('wrote', TSV)


def layout(r, en):
    """-> (english string with padding and codes, rows, cols, width byte).

    Column geometry (width byte, and in one case rows/cols) lives in our
    patched table, so verbatim PSP wording is fitted geometrically, never
    reworded. A 2-column entry whose wording fits no width can fall back to a
    single-column list only while that list still fits the two option rows
    the box has (BOX_ROWS minus the prompt's arming line). A four-option block
    has no such fallback: the only shape that shows all four at once is the
    2x2 grid, so wording that cannot fit it raises OverLimit and its PSP draft
    goes to manual (toolbelt.route_over), Japanese staying on disc.
    """
    rows_p, cols_p, width_p, _ = r['params']
    lines = en.split('<FF03>')
    assert len(lines) == rows_p, f"{r['idx']}: {len(lines)} rows, expected {rows_p}"
    cells = [c for ln in lines for c in ln.split('|')]
    assert len(cells) == rows_p * cols_p, f"{r['idx']}: {len(cells)} cells, expected {rows_p * cols_p}"
    if cols_p == 2:
        # Column 2 starts at (width+1)*16 px; pick the nearest width fitting
        # *verbatim* PSP wording: every row needs col1 + 4 px before col2,
        # and the whole row must stay inside the box (engine wraps at 240,
        # cf. vwf).
        widths = []
        for ln in lines:
            c1, c2 = ln.split('|')
            widths.append((vwf_wrap.text_width(c1), vwf_wrap.text_width(c2)))
        # The padding reaches the stop exactly, in the fewest bytes (the
        # strings share one fixed pool): 8 px blanks (WIDE_SPACE), at most one
        # 4 px space, then the 0-3 px left as 1 px blanks (HAIR_SPACE), so
        # column 2 of every row starts on the same pixel in every face.
        def padding(w1, x2):
            wide, rest = divmod(x2 - w1, make_vwf_font.WIDE_SPACE_ADVANCE)
            space, rest = divmod(rest, make_vwf_font.SPACE_ADVANCE)
            return (make_vwf_font.WIDE_SPACE * wide + ' ' * space
                    + make_vwf_font.HAIR_SPACE * rest)

        cands = sorted(range(0, 15), key=lambda w: (abs(w - width_p), w))
        for w in cands:
            x2 = (w + 1) * 16
            if all(x2 >= w1 + 4 and x2 + w2 <= BOX_PX for w1, w2 in widths):
                width_new = w
                break
        else:
            width_new = None
        if width_new is not None:
            out = []
            for (w1, w2), ln in zip(widths, lines):
                c1, c2 = ln.split('|')
                out.append(c1 + padding(w1, (width_new + 1) * 16) + c2)
            assert width_new <= 14
            return '<FF03>'.join(out), rows_p, cols_p, width_new
        # No 2-column width fits. The nearest legal column starts are the
        # 16 px stops after col1 + 4 px; report the narrowest line the grid
        # would need so the manual note says why it cannot ship.
        rows_n = rows_p * cols_p
        if rows_n > OPTION_ROWS:
            need = max(-(-(w1 + 4) // 16) * 16 + w2 for w1, w2 in widths)
            raise OverLimit(toolbelt.note_over(need, BOX_PX, 'px'))
        # A short 1x2 grid can still become a two-row single column.
    if cols_p == 2:
        rows_n, cols_n = rows_p * cols_p, 1
    else:
        rows_n, cols_n = rows_p, cols_p
    out = list(cells)
    width_new = width_p
    for c in cells:
        width_new = max(width_new, -(-vwf_wrap.text_width(c) // 16))
    assert width_new <= 14, f"{r['idx']}: needs {width_new} cells"
    assert rows_n <= OPTION_ROWS, (
        f"{r['idx']}: {rows_n} option rows do not fit the "
        f"{OPTION_ROWS}-row option block")
    return '<FF03>'.join(out), rows_n, cols_n, width_new


def auto_en():
    """{idx: en} from the canonical table (pos = original string address)."""
    import toolbelt
    orig = pos_idx()
    out = {}
    for r in toolbelt.merged_rows('SLPS_005.00'):
        i = orig.get(int(r['pos'], 16))
        if i is not None and (r['en'] or '').strip():
            out[i] = r['en']
    return out


def build():
    orig = original()
    extra = added()
    tsv = {int(r["idx"]): r["en"] for r in read_tsv()}
    auto = auto_en()
    for idx, text in auto.items():
        if etext.is_todo(tsv.get(idx, '')):
            tsv[idx] = text
    placed = {}                                   # idx -> (bytes, rows, cols, width)
    free = list(FREE)
    for r in orig + extra:
        en = tsv.get(r['idx'], '').strip()
        if not etext.has_text(en):
            continue
        try:
            text, rn, cn, w = layout(r, en)
        except OverLimit as e:
            raise SystemExit(
                f"choices: {r['idx']}: {e} - shorten the "
                f"choice wording; the box cannot show all its options")
        placed[r['idx']] = (etext.encode(text), rn, cn, w)
        if r['ptr'] is not None:
            free.append((r['ptr'], slot_end(r)))  # its Japanese slot becomes free
    # The table moves only to carry an id past the PSX's own with English to
    # place (a build without those rows, the engine-only tree among them,
    # keeps the retail table and its readers). Its growth comes out of the
    # pool, and no string it covers may still be in use.
    table = NEW_TABLE if any(r['idx'] in placed for r in extra) else TABLE
    for r in orig:
        if r['idx'] not in placed and r['ptr'] < TABLE and r['ptr'] + r['size'] > table:
            raise SystemExit(f"choices: {r['idx']} is untranslated and its Japanese sits where "
                             f"the table grows ({table:#x}..{TABLE:#x})")
    cut = []
    for a, b in free:
        for lo, hi in ((a, min(b, table)), (max(a, TABLE), b)):
            if hi > lo:
                cut.append((lo, hi))
    free = cut
    # first-fit decreasing into the free list (merge touching slots first)
    free.sort()
    merged = []
    for a, b in free:
        if merged and merged[-1][1] == a:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    addr = {}
    for idx in sorted(placed, key=lambda i: -len(placed[i][0])):
        n = len(placed[idx][0])
        for k, (a, b) in enumerate(merged):
            if b - a >= n:
                addr[idx] = a
                merged[k] = (a + n, b)
                break
        else:
            raise SystemExit(f'choices: out of space for entry {idx} ({n} bytes)')
    # every id of the table: an English entry, the retail one, or (an id no
    # PSX script asks and no row fills) a copy of entry 0
    entries = {}
    for r in orig:
        p = r['params']
        entries[r['idx']] = (r['ptr'], p[0], p[1], p[2])
    for idx, (b, rn, cn, w) in placed.items():
        entries[idx] = (addr[idx], rn, cn, w)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', newline=NL) as o:
        o.write(';; generated by tools/choices.py build - do not edit' + NL)
        o.write(f';; English dialogue choices: strings repacked, the table rebuilt at {table:#x} '
                f'for ids 0-{(TABLE - table) // 8 + COUNT - 1}' + NL)
        for r in orig:
            if r['idx'] in placed:
                o.write(f".org {r['ptr']:#x}{NL}.fill {r['size']}, 0{NL}")
        for idx in sorted(placed):
            b = placed[idx][0]
            o.write(f'; choice {idx}{NL}.org {addr[idx]:#x}{NL}')
            for i in range(0, len(b), 16):
                o.write('.byte ' + ', '.join(f'0x{x:02X}' for x in b[i:i + 16]) + NL)
        o.write(f'.org {table:#x}{NL}')
        for idx in range((TABLE - table) // 8 + COUNT):
            ptr, rn, cn, w = entries.get(idx, entries[0])
            o.write(f'.word {ptr:#x}{NL}.byte {rn}, {cn}, {w}, 0   ; choice {idx}{NL}')
    for name, sites in rebase_sites().items():
        with open(overlay_out(name), 'w', newline=NL) as o:
            o.write(f';; generated by tools/choices.py build - do not edit{NL}'
                    f';; the choice table readers of {name}.BIN, at {table:#x}{NL}')
            for va, field in sites if table != TABLE else ():
                o.write(f'.org {va:#x}{NL}    addiu   at, at, {(table + field) & 0xFFFF:#x} - 0x10000'
                        f'   ; lo(choice table + {field}){NL}')
    used = sum(len(placed[i][0]) for i in placed)
    print(f'choices: {len(placed)}/{len(orig) + len(extra)} translated, {used} bytes placed, '
          f'table at {table:#x} -> {OUT}')


def slot_end(r):
    """Where a Japanese string's slot ends: past its zero alignment padding
    (the strings start on 4-byte boundaries, and the pad belongs to nobody)."""
    end = r['ptr'] + r['size']
    pad = (-end) % 4
    with open(os.path.join(ROOT, 'data', 'psx', 'SLPS_005.00'), 'rb') as f:
        f.seek(end - BASE)
        tail = f.read(pad)
    return end + pad if not any(tail) else end


def overlay_out(name):
    return os.path.join(ROOT, 'build', f'choices_{name.lower()}.asm')


def sync_boot():
    """Rebuild the PSX target choices.tsv from the BOOT extractor output.

    Run after `python src/extraction/psp/boot.py extract`. Every row becomes source
    `us-boot`; rows whose map is incomplete stay TODO (Japanese in build).
    A row whose verbatim PSP wording cannot be drawn whole (no 2-column width
    fits and the list would need more option rows than the box has) is not
    written to generated: its full draft goes to manual through
    toolbelt.route_over, exactly like every other over-limit porter, and the
    Japanese ships until a human shortens it. Manual rows are never touched
    beyond that: the build merges generated text with manual overrides.
    """
    import toolbelt
    opts = {}
    packed = toolbelt.read_be(0x2C06EC, 0x2C1094)
    # THE PSP'S OWN SLIPS AND OVER-WIDE WORDINGS, fixed at the source
    # (translation/psp_errata.tsv): a row names the extract line that holds
    # this table, and its find must occur once in the whole table
    ext = toolbelt.read_extracted('psp_us', 'EBOOT')
    line = max((r['pos'] for r in ext if int(r['pos'], 16) <= 0x2C06EC),
               key=lambda pos: int(pos, 16))
    if any(loc == toolbelt.psp_loc(line) for loc, _f, _r in toolbelt.psp_errata('EBOOT')):
        sep = '\ue000'
        fixed = toolbelt.errata_text('EBOOT', line, sep.join(u for _p, u in packed))
        packed = [(p, u) for (p, _u), u in zip(packed, fixed.split(sep))]
    for _p, unit in packed:
        for i, text in enumerate(unit.split('<FF03>')):
            if text.strip():
                # a cell's edge blanks are the PSP list's spacing (' Game
                # rules' opens its group), never wording: column 1 is padded
                # to column 2 by layout, nothing else
                opts[len(opts)] = text.strip()
    orig = {r['idx']: r for r in original() + added()}
    rows = {}
    over = {}
    for idx in sorted(orig):
        cells = []
        for oi in BOOT_MAP.get(idx, []):
            if oi not in opts:
                break
            cells.append(opts[oi])
        else:
            rows_p, cols_p = orig[idx]['params'][0], orig[idx]['params'][1]
            if len(cells) == rows_p * cols_p and cells:
                text = '<FF03>'.join('|'.join(cells[r * cols_p:(r + 1) * cols_p])
                                     for r in range(rows_p))
                # Lay the row out now, at its only write: a wording that does
                # not fit the box is a manual draft, never a broken generated
                # row the build would have to notice later.
                try:
                    layout(orig[idx], text)
                except OverLimit as e:
                    over[idx] = (text, str(e))
                    continue
                rows[idx] = text
                continue
        rows[idx] = ''
    def pos(idx):
        r = orig[idx]
        return hex(r['ptr'] - BASE if r['ptr'] is not None else r['pos'])
    auto = [{'pos': pos(idx), 'en': text, 'psp': 'EBOOT:2c06ec'}
            for idx, text in rows.items() if text]
    n = toolbelt.upsert_generated('SLPS_005.00', auto)
    routed = []
    for idx, (text, reason) in over.items():
        if toolbelt.route_over('SLPS_005.00', pos(idx), 'EBOOT:2c06ec', text, reason):
            routed.append(idx)
    print(f'choices: {n} rows -> {toolbelt.gen_path("SLPS_005.00")}')
    if routed:
        print(f'choices: {len(routed)} over limit -> manual: '
              + ', '.join(f'idx{i}' for i in sorted(routed)))
    n = sum(1 for v in rows.values() if v)
    print(f'choices: {n}/{len(orig)} rows from the BOOT table')


def purge_unverified():
    """Keep only choice wording with disc provenance (source `us-boot`/`handmade`).

    Old `ai-reviewed` labels are not provenance: those rows return to TODO,
    and their CHOICES.tsv `en` cells are blanked so the build uses Japanese.
    """
    pp = PSP_TSV
    verified = {}
    psp_lines = open(pp, encoding='utf-8').read().split(NL)
    for i, line in enumerate(psp_lines[1:], 1):
        if not line.strip():
            continue
        r = line.split(TAB)
        if len(r) < 3 or not r[0].isdigit():
            raise ValueError(f'{pp}:{i + 1}: malformed row {line[:80]!r}')
        if r[2].startswith('ai-reviewed'):
            r[1], r[2] = 'TODO', 'TODO'
            psp_lines[i] = TAB.join(r)
        elif r[2] != 'TODO' and r[1].strip():
            verified[r[0]] = r[1]
    open(pp, 'w', encoding='utf-8', newline=NL).write(NL.join(psp_lines))

    print(f'choices: retained {len(verified)} PSP-sourced rows in {PSP_TSV}; manual table untouched')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'dump': dump, 'build': build, 'purge-unverified': purge_unverified,
     'sync-boot': sync_boot}[sys.argv[1] if len(sys.argv) > 1 else 'build']()
