"""Dungeon / floor names of the map files (D0x/D??M.BIN): the title of the MAP screen, probably the arrival banner.

  python src/injection_tools/dngnames.py dump    regenerate the TSVs only
  python src/injection_tools/dngnames.py         write build/<D0x>/D??M.BIN (port.py runs dump)

Every dungeon map file starts with a table {u32 x4}; word 2 is the offset of the NAME FIELD (one per floor, stride 0xC4): 10 slots of u16 glyph
indices (game font), padded with blank glyph 0, e.g. "　　ジョイ通り　　　" or "聖エルミン学園　１Ｆ" (floor suffix in the last
slots). At map load the field is copied to a buffer (RAM 0x801DD7FC for the current floor) and drawn by the overlay: Latin
full-width glyph codes (A = 0xA6, 0 = 0xC0, lowercase 0x723..) are drawn at HALF width, so 10 slots hold 10 characters.
English = plain text, centred with blanks.

Sources (2026-10-16): the PSP carries this game's floor-name list as
FF01-terminated BE records - US BOOT 0x28fc7a.. (151 rows), JP BOOT the
same list in Japanese (143 rows; the PSP-US build added rows for its
restructured dream areas). Alignment is fully mechanical:
  PSX rows <-> PSP-JP rows   normalized Japanese (spaces dropped, NFKC),
                             in-order queue match - same language, same
                             order, exact;
  PSP-JP rows <-> PSP-US rows sequence alignment over the floor-number
                             skeleton (1F/B10/none per row - the one
                             language-independent property a row has),
                             difflib; the PSP-US build's inserted rows
                             stay unmatched and unused.
No name is ever typed into this tool (AGENTS.md): the English comes from
the PSP-US rows only.

Coverage: canonical per-file tables (translation/generated/D0x/DxM.tsv,
id pos psp en) hold every row with the full PSP-US name; human overrides
and unfilled floors live in translation/manual/D0x/DxM.tsv (toolbelt).
The PSX name field holds 10 cells (20 bytes): short names ship as
glyph cells, 11-18 char names as pre-swapped VWF script bytes, longer
ones stay Japanese in the pack for the map-title hook below; the
generated file keeps the full name either way.
"""
import difflib
import glob
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import hashlib
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, 'extraction_tools', 'psp'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, 'extraction_tools', 'matching'))
import etext               # noqa: E402
import strlib              # noqa: E402
from tables import be_units, us_boot, jp_boot, jp_map   # noqa: E402

ROOT = etext.ROOT
SLOTS = 10
import toolbelt   # noqa: E402  (the canonical tables: generated/manual per file)
import source_plan  # noqa: E402  (text-free correspondence snapshots)

US_FLOOR_LO, US_FLOOR_HI = 0x28FC7A, 0x2922BB
JP_FLOOR_ANCHOR = '聖エルミン学園'


def norm(s):
    """Match key: no spaces, NFKC (　 gone, １Ｆ -> 1F), and no undecoded
    code placeholders - a box is one row now, and the codes the glyph map
    has not solved yet are not part of the name being matched."""
    s = re.sub(r'<[0-9A-Fa-f]{4}>', '', s)
    return ''.join(c for c in unicodedata.normalize('NFKC', s) if not c.isspace())


def floor_key(s):
    """Language-independent row key for sequence alignment: the floor
    number in the suffix (1F -> 1, B10 -> -10, none -> 0)."""
    m = re.search(r'(\d+)F$', unicodedata.normalize('NFKC', s).strip())
    if m:
        return int(m.group(1))
    m = re.search(r'B(\d+)$', unicodedata.normalize('NFKC', s).strip())
    if m:
        return -int(m.group(1))
    return 0


def psp_us_floor_rows():
    """The PSP-US floor-name list as (offset, text) - no Japanese input."""
    ub = us_boot()
    return [(o + US_FLOOR_LO, s.replace('<FF01>', '').strip())
            for o, s, t in be_units(ub[US_FLOOR_LO:US_FLOOR_HI],
                                    __import__('tables').US_MAP) if t == 'FF01']


def psp_floor_rows():
    """(jp_rows, us_rows): the PSP floor-name lists as (offset, text) -
    the offset is the row's locator in extracted_text/psp_*/EBOOT.tsv."""
    us = psp_us_floor_rows()
    jb = jp_boot()
    JP = jp_map()
    inv = {v: k for k, v in JP.items()}
    pat = b''.join(struct.pack('>H', inv[c]) for c in JP_FLOOR_ANCHOR)
    start = jb.find(pat)
    if start < 0:
        raise SystemExit('dngnames: JP PSP floor table not found')
    jp = [(o + start, s.replace('<FF01>', '').strip())
          for o, s, t in be_units(jb[start:start + 0x4000], JP) if t == 'FF01']
    if not jp or not us:
        raise SystemExit('dngnames: empty PSP floor tables')
    return jp, us


def align_psp(jp_rows, us_rows):
    """JP-PSP row index -> US-PSP row index (or None): sequence alignment
    over the floor-number skeletons. The PSP-US build inserted rows for
    its restructured dream areas; difflib keeps the shared order and the
    insertions stay unmatched."""
    a = [floor_key(s) for _o, s in jp_rows]
    b = [floor_key(s) for _o, s in us_rows]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out = [None] * len(jp_rows)
    for bl in sm.get_matching_blocks():
        for k in range(bl.size):
            out[bl.a + k] = bl.b + k
    return out


def psx_floor_rows():
    """[(rel, offset, ja)] every PSX floor-name field, in order. rel =
    disc-relative path without extension (the TSV location per
    docs/TEXT_ARCHITECTURE.md)."""
    rows = []
    for fp in sorted(glob.glob(os.path.join(ROOT, 'data', 'psx', 'D0*', 'D*M.BIN'))):
        rel = os.path.relpath(fp, os.path.join(ROOT, 'data', 'psx'))
        rel = rel[:-4] if rel.endswith('.BIN') else rel
        for off, ja in source_names(open(fp, 'rb').read()):
            rows.append((rel, off, ja))
    return rows


def align_psx(psx, jp_rows, j2u, us_rows):
    """PSX row index -> JP-PSP row index (or None). The name match, in the
    three shapes one name field can take on either disc:

      exact     the normalized Japanese names are equal
      split     one side keeps only PART of the display string - the floor
                suffix is its own row ('Ｂ９' vs 'アラヤの岩戸 Ｂ９') - so
                the shorter normalized name sits inside the longer one and
                the two rows' floor numbers agree
      one-off   a single undecoded code point stands where the other side
                has a character ('地下鉄御影<0637>構内' vs
                '地下鉄御影駅構内'): near-equal normalized names

    A Japanese name is never ambiguous because it repeats - the same name
    always takes the same English - so the closest row wins outright and a
    table row is only spent where one name really does resolve to two
    different English names. A row with no US twin never wins over one
    that has it.
    """
    def en(i):
        u = j2u[i] if i is not None else None
        return us_rows[u][1] if u is not None else ''

    keys = [(i, norm(s), floor_key(s)) for i, (_o, s) in enumerate(jp_rows)]

    def score(k, fk, i):
        """(rule, similarity): which shape of match this is, and how tight.
        Exact beats a split row, a split row beats a near-equal one."""
        _i, nk, nfk = keys[i]
        if not nk or nfk != fk:
            return (0, 0.0)
        if nk == k:
            return (3, 1.0)
        if nk in k or k in nk:
            return (2, len(nk) / max(len(k), 1))
        r = difflib.SequenceMatcher(None, k, nk, autojunk=False).ratio()
        return (2, r) if r >= 0.85 else (0, 0.0)

    spent = set()
    out = []
    for _f, _o, ja in psx:
        k, fk = norm(ja), floor_key(ja)
        cand = [i for i, _nk, _nfk in keys if score(k, fk, i)[0]]
        if not cand:
            out.append(None)
            continue
        cand.sort(key=lambda i: (score(k, fk, i), en(i) != ''), reverse=True)
        top = score(k, fk, cand[0])
        level = [i for i in cand if score(k, fk, i) == top]
        live = [i for i in level if en(i)] or level  # an unpaired twin is
        if len({en(i) for i in live}) == 1:          # not a second name
            out.append(next((i for i in live if en(i)), live[0]))
            continue
        free = [i for i in live if i not in spent]
        pick = (free or live)[0]
        spent.add(pick)
        out.append(pick)
    return out


def source_names(d):
    o = struct.unpack_from('<4I', d, 0)[2]
    p = o
    while p + 2 * SLOTS <= len(d):
        glyphs = struct.unpack_from('<10H', d, p)
        if any(w not in etext.glyph for w in glyphs):
            break
        ja = ''.join(etext.glyph[w] for w in glyphs)
        if not ja.strip('　'):
            break
        yield p, ja
        p += 0xC4


PLAN = os.path.join(toolbelt.MAPPINGS, 'dngname_port_plan.tsv')
PLAN_VERSION = '1'


class PlanError(ValueError):
    """A replay needs a fresh capture; never silently drop a name field."""


def plan_inputs():
    files = sorted(glob.glob(os.path.join(ROOT, 'data', 'psx', 'D0*', 'D*M.BIN')))
    psx = {os.path.relpath(fp, os.path.join(ROOT, 'data', 'psx'))[:-4]:
           hashlib.sha1(open(fp, 'rb').read()).hexdigest() for fp in files}
    us = hashlib.sha1(us_boot()).hexdigest()
    return psx, us


def plan_rule_digest():
    h = hashlib.sha1()
    for path in (os.path.abspath(__file__),
                 os.path.join(ROOT, 'src', 'extraction_tools', 'psp', 'tables.py')):
        h.update(open(path, 'rb').read())
    return h.hexdigest()


def load_plan():
    if not os.path.exists(PLAN):
        return None
    plan, matches = source_plan.read(PLAN)
    if plan.get('version') != PLAN_VERSION:
        raise PlanError('dngname plan version mismatch; recapture with PSP-JP')
    psx, us = plan_inputs()
    if {k[4:]: v for k, v in plan.items() if k.startswith('psx:')} != psx:
        raise PlanError('dngname plan does not match the PSX name files; recapture')
    if plan.get('us:EBOOT') != us:
        raise PlanError('dngname plan does not match the PSP-US BOOT; recapture')
    if plan.get('rule_sha1') != plan_rule_digest():
        raise PlanError('dngname plan does not match the matching rules; recapture')
    return matches


def replay_rows(psx, matches):
    us = dict(psp_us_floor_rows())
    if len(matches) != len(psx):
        raise PlanError('dngname plan does not cover every PSX name field; recapture')
    rows = []
    for (rel, off, ja), row in zip(psx, matches):
        if row['rel'] != rel or row['pos'] != hex(off):
            raise PlanError(f'dngname plan order does not match {rel}@{off:#x}; recapture')
        psp = ''
        if row['mode'] == 'ok':
            key = int(row['us_pos'], 16)
            if key not in us:
                raise PlanError(f'dngname plan has a stale US name at {key:#x}; recapture')
            psp = 'EBOOT:%x' % key
        rows.append((rel, off, ja, us[int(row['us_pos'], 16)] if psp else '', psp))
    return rows


def write_plan(path=PLAN):
    rows = build_rows(use_plan=False)
    psx = psx_floor_rows()
    if len(rows) != len(psx):
        raise PlanError('capture did not produce one decision per PSX name field')
    matches = []
    for rel, off, _ja, _en, psp in rows:
        row = {'rel': rel, 'pos': hex(off), 'us_sub': 'dngname',
               'mode': 'ok' if psp else 'none'}
        if psp:
            row['us_pos'] = hex(int(psp.split(':', 1)[1], 16))
        matches.append(row)
    psx_digest, us_digest = plan_inputs()
    metadata = {'version': PLAN_VERSION, 'rule_sha1': plan_rule_digest(),
                'us:EBOOT': us_digest}
    metadata.update({f'psx:{rel}': value for rel, value in psx_digest.items()})
    source_plan.write(path, metadata, matches)
    print(f'dngname plan: {len(matches)} decisions -> {path}')
    return matches


def build_rows(use_plan=True):
    """[(rel, off, ja, en, psp)] en = the full PSP-US name (the 10-cell
    field cap is a pack-format limit, not a wording limit; rows over the
    cap ship as VWF script bytes in the field, or via the map-title
    hook past 18 characters). psp = the PSP-US row's own locator
    ('EBOOT:<offset>'), the form every reader resolves - a pointer must
    open the extracted file and find the source row.

    A captured plan replays the name correspondence from PSX and PSP-US
    alone; without one (or during capture) the Japanese PSP table is read."""
    psx = psx_floor_rows()
    matches = load_plan() if use_plan else None
    if matches is not None:
        return replay_rows(psx, matches)
    jp_rows, us_rows = psp_floor_rows()
    j2u = align_psp(jp_rows, us_rows)
    p2j = align_psx(psx, jp_rows, j2u, us_rows)
    rows = []
    for i, (f, off, ja) in enumerate(psx):
        j = p2j[i]
        u = j2u[j] if j is not None else None
        en = us_rows[u][1] if u is not None else ''
        psp = 'EBOOT:%x' % us_rows[u][0] if u is not None else ''
        rows.append((f, off, ja, en, psp))
    return rows


def floor_pairs():
    """[(us_pos, jp_pos)] the PSP floor-name pairs this module proves
    (psx name -> JP row by normalized name, JP row -> US row by
    floor-skeleton sequence alignment). The JP twin of a US `psp`
    pointer - translation/generated_mappings/psp_pairs.tsv (boot_pairs.py)."""
    jp_rows, us_rows = psp_floor_rows()
    j2u = align_psp(jp_rows, us_rows)
    return [(us_rows[u][0], jp_rows[j][0])
            for j, u in enumerate(j2u) if u is not None]


asm_equ = toolbelt.asm_equ     # the addresses.inc reader: one shared implementation


TITLE_ASM = os.path.join(ROOT, 'build', 'dng_titles.asm')
TITLE_IMAGE = os.path.join(ROOT, 'build', 'dng_titles.bin')
TITLE_ORG = asm_equ('DNG_TITLE_TABLE_ADDR')   # past the DNG extension end
TITLE_HOOK = asm_equ('DNG_TITLE_HOOK_ADDR')   # dng/map_title.asm's hook
TITLE_BUDGET = TITLE_HOOK - TITLE_ORG
TITLE_CELLS = 0x800A0730        # g_map_name_cells (MapDrawName's buffer)


def vwf_bytes(en):
    """EN -> VWF script bytes (shared dialog engine encoding: ASCII+0x68,
    space 0x88) + FF01. Loud on non-ASCII (never silently mojibake)."""
    out = bytearray()
    for c in en:
        o = ord(c)
        if not 0x20 <= o <= 0x7E:
            raise SystemExit(f'dngnames: title {en!r}: {c!r} has no VWF byte')
        out.append(o + 0x68)
    return bytes(out) + b'\xff\x01'


def ja_field_bytes(ja):
    """JA field text -> the 20 field bytes (u16 glyph slots, LE). The
    hook matches these against the map pack's name field."""
    out = bytearray()
    for c in ja:
        g = etext.char2g.get(c)
        if g is None:
            return None
        out += struct.pack('<H', g)
    return bytes(out) if len(out) == 20 else None


SCRIPT_MAX = 18  # longest EN fitting the 20-byte field as script + FF01


def pack_field(ja, en):
    """The 20 field bytes to inject for (ja, en), or None to leave the
    retail JA field. <=10 chars: centred glyph cells. 11-18 chars: VWF
    script bytes, pairwise pre-swapped: the retail copy writes
    cells[2i] = field[2i+1]|0x80, cells[2i+1] = field[2i], and every
    script byte is already >= 0x80 (ASCII+0x68), so the swap is the
    only transform and the cells come out as the script + FF01."""
    if not en or not en.strip():
        return None
    if len(en) <= SLOTS:
        return field(en)
    script = vwf_bytes(en)[:-2]
    if len(script) > SCRIPT_MAX:
        return None
    if len(script) % 2:
        script += b'\x88'  # VWF space: the terminator must sit at an even
    raw = script + b'\xff\x01'  # cell offset so the pair-swapping copy
    swapped = b''.join(bytes((raw[i + 1], raw[i]))  # reproduces it exactly
                       for i in range(0, len(raw), 2))  # (odd field bytes
    return swapped + b'\x00' * (20 - len(swapped))  # gain 0x80 on the way in)


def emit_titles(rows, resolved):
    """build/dng_titles.asm: JA-match index + EN blob for the map-title
    hook (dng/map_title.asm). Keyed by the injected field bytes (JA
    bytes where the pack keeps Japanese), so the runtime field always
    matches its own row. Deduped by field (same field always takes the
    same EN - conflicts fail loudly)."""
    import vwf_wrap  # noqa: E402
    table = {}
    for f, off, ja, en, note in rows:
        en = resolved.get(ja, '')
        if not en.strip():
            continue
        jb = pack_field(ja, en) or ja_field_bytes(ja)
        if jb is None:
            raise SystemExit(f'dngnames: title JA unencodable: {ja!r}')
        if jb in table and table[jb][0] != en:
            raise SystemExit(
                f'dngnames: same JA field takes two titles: {ja!r}: '
                f'{table[jb][0]!r} vs {en!r}')
        table.setdefault(jb, (en, vwf_wrap.text_width(en)))
    items = sorted(table.items())
    blobs = [vwf_bytes(en) for _jb, (en, _px) in items]
    total = 24 * len(items) + sum(len(b) for b in blobs)
    if total > TITLE_BUDGET:
        raise SystemExit(
            f'dngnames: titles table {total:#x} overflows the '
            f'{TITLE_ORG:#x}+{TITLE_BUDGET:#x} budget '
            f'(hook code sits at {TITLE_HOOK:#x})')
    # The held-START field draws this full title into ten 16px cells.
    widths = Path(ROOT, 'src', 'asm', 'font', 'vwf_width.bin').read_bytes()
    index = Path(ROOT, 'src', 'asm', 'font', 'vwf_index.bin').read_bytes()
    if len(index) != 2 * len(widths):
        raise SystemExit('dngnames: VWF title index/width table lengths differ')
    offsets = struct.unpack(f'<{len(widths)}H', index)
    maximum = asm_equ('DNG_FIELD_TITLE_WIDTH')
    for (_jb, (en, px)), script in zip(items, blobs):
        if not script.endswith(b'\xff\x01'):
            raise SystemExit(f'dngnames: title lacks FF01: {en!r}')
        chars = [b - 0x88 for b in script[:-2]]
        if any(c < 0 or c >= len(widths) for c in chars):
            raise SystemExit(f'dngnames: title is not a plain VWF glyph run: {en!r}')
        if any(not widths[c] for c in chars) or sum(widths[c] for c in chars) != px:
            raise SystemExit(f'dngnames: title width disagrees with encoded glyphs: {en!r}')
        # The ordinary and wide spaces intentionally share blank art.
        if any(c not in (0, len(widths) - 1) and offsets[c] == offsets[0] for c in chars):
            raise SystemExit(f'dngnames: title needs an unallocated VWF glyph: {en!r}')
        if px > maximum:
            raise SystemExit(f'dngnames: full title exceeds held-pause strip: {en!r} ({px}/{maximum}px)')
    with open(TITLE_ASM, 'w', encoding='utf-8', newline='\n') as o:
        o.write(';; generated by tools/dngnames.py - map-title JA-match table '
                '+ EN blob\n')
        o.write(f'.org {TITLE_ORG:#x}\n')
        o.write('dng_title_idx:\n')
        blob_off = 0
        for (jb, (en, px)), eb in zip(items, blobs):
            o.write('    .byte ' + ', '.join(f'{b:#x}' for b in jb) + '\n')
            o.write(f'    .byte {px}          ; strip width px\n')
            o.write('    .byte 0\n')
            o.write(f'    .halfword {blob_off:#x}  ; into dng_title_blob\n')
            blob_off += len(eb)
        o.write(f'dng_title_count equ {len(items)}\n')
        o.write('dng_title_blob:\n')
        for eb in blobs:
            o.write('    .byte ' + ', '.join(f'{b:#x}' for b in eb) + '\n')
        o.write('dng_title_blob_end:\n')
    # Independent binary serialization for readback, including every key,
    # width, offset and encoded title; armips must reproduce it exactly.
    image = bytearray()
    blob_off = 0
    for (key, (_en, px)), encoded in zip(items, blobs):
        if len(key) != 20:
            raise SystemExit('dngnames: title key is not 20 bytes')
        image.extend(key + struct.pack('<BBH', px, 0, blob_off))
        blob_off += len(encoded)
    image.extend(b''.join(blobs))
    with open(TITLE_IMAGE, 'wb') as f:
        f.write(image)
    print(f'dngnames: titles table: {len(items)} rows, {total:#x} of '
          f'{TITLE_BUDGET:#x} -> {TITLE_ASM}')


def dump():
    """Canonical port rows per disc file (id pos psp en): the full PSP-US
    name at every PSX name-field position; floors without a PSP row stay a
    manual gap (never guessed)."""
    rows = build_rows()
    by_rel = {}
    for rel, off, ja, en, psp in rows:
        by_rel.setdefault(rel, []).append((hex(off), psp, en))
    for rel, spec in by_rel.items():
        toolbelt.upsert_generated(rel, [{'pos': pos, 'psp': psp, 'en': en}
                                       for pos, psp, en in spec])
        toolbelt.route_gaps(rel, [pos for pos, _psp, _en in spec])
    over = sum(1 for _f, _o, _ja, en, _p in rows if en and len(en) > SLOTS)
    noev = sum(1 for _f, _o, _ja, en, _p in rows if not en)
    print(f'dngnames: {len(rows)} rows, {len(rows) - noev} PSP-named '
          f'({over} over 10 cells: field script or map-title hook), '
          f'{noev} without a PSP row')


def resolved_en(rows):
    """ja -> en from the canonical merged rows (manual wins where filled).
    No length cap - pack_field() routes short names to glyph cells,
    11-18 char names to field script bytes, longer ones to the hook."""
    en = {}
    pos2ja = {}
    for rel, off, ja, _row_en, _psp in rows:
        pos2ja.setdefault(rel, {})[hex(off)] = ja
    for rel, pmap in pos2ja.items():
        for r in toolbelt.merged_rows(rel):
            ja = pmap.get(r['pos'])
            if ja is not None and etext.has_text(r.get('en', '')):
                en[ja] = r['en']
    return en


EXTRA = {'-': '－', '.': '．', '?': '？', '&': '＆', '/': '／', ':': '：', '!': '！'}


def glyph(c):
    if c == ' ':
        return 0
    if 'A' <= c <= 'Z':
        return etext.char2g[chr(0xFF21 + ord(c) - 65)]
    if 'a' <= c <= 'z':
        return etext.char2g[chr(0xFF41 + ord(c) - 97)]
    if '0' <= c <= '9':
        return etext.char2g[chr(0xFF10 + ord(c) - 48)]
    if c in EXTRA:
        return etext.char2g[EXTRA[c]]
    # kanji etc. for mixed labels (Lost森): the game font has them
    return etext.char2g[c]


def field(t):
    if len(t) > SLOTS:
        raise SystemExit(f'dngnames: {t!r} is {len(t)} characters, max {SLOTS}')
    lead = (SLOTS - len(t)) // 2
    s = ' ' * lead + t
    s += ' ' * (SLOTS - len(s))
    return b''.join(struct.pack('<H', glyph(c)) for c in s)


def verify():
    """Read back the generated index and independently reassemble the field hook."""
    build = os.path.join(ROOT, 'build')
    image = Path(build, 'DNG.BIN').read_bytes()
    expected = Path(TITLE_IMAGE).read_bytes()
    sym = {}
    for line in Path(build, 'persona.sym').read_text(encoding='utf-8').splitlines():
        match = re.match(r'^([0-9a-fA-F]{8})\s+(\S+)', line)
        if match:
            sym[match[2]] = int(match[1], 16)
    base = asm_equ('OVERLAY_SLOT_ADDR')
    start = asm_equ('DNG_FIELD_TITLE_ADDR')
    limit = asm_equ('DNG_FIELD_TITLE_LIMIT')
    entry = asm_equ('DNG_FIELD_TITLE_ENTRY')
    width = asm_equ('DNG_FIELD_TITLE_WIDTH')
    hook, pixels, end = (sym[n] for n in ('dng_field_title_hook', 'dng_field_title_pixels', 'dng_field_title_end'))
    idx, blob, blob_end = (sym[n] for n in ('dng_title_idx', 'dng_title_blob', 'dng_title_blob_end'))
    if not (sym['dng_spill_hook_end'] <= asm_equ('DNG_SPILL_LIMIT') <= start == hook < pixels < end <= limit == idx
            and pixels % 4 == 0 and end - pixels == width * 16 // 2
            and idx <= blob <= blob_end <= asm_equ('DNG_TITLE_HOOK_ADDR')
            and (blob - idx) % 24 == 0 and blob_end - idx == len(expected)):
        raise SystemExit('dngnames: verify: title code/data violates its owned windows')
    if image[idx - base:blob_end - base] != expected:
        raise SystemExit('dngnames: verify: title table/blob differs from the generated bytes')
    if image[pixels - base:end - base] != bytes(end - pixels):
        raise SystemExit('dngnames: verify: title scratch is not zero at load')
    retail_path = os.path.join(ROOT, 'data', 'psx', 'DNG.BIN')
    retail = Path(retail_path).read_bytes()
    if retail[entry - base:entry - base + 8] != struct.pack('<II', 0x27BDFFD8, 0xAFB00018):
        raise SystemExit('dngnames: verify: stolen field uploader prologue is not retail')
    # Armips permits a later .org to overwrite an earlier feature silently.
    # Assemble the actual hook alone against the original DNG in a temporary
    # workspace, with the built symbols, then compare every emitted byte.
    armips = next((p for p in (os.path.join(ROOT, 'external_tools', 'armips', 'armips.exe'),
                                os.path.join(ROOT, 'external_tools', 'armips', 'armips'))
                   if os.path.exists(p)), None) or shutil.which('armips')
    if not armips:
        raise SystemExit('dngnames: verify: armips is required for independent hook readback')
    defs = {name: asm_equ(name) for name in ('DNG_FIELD_TITLE_ENTRY', 'DNG_FIELD_TITLE_ADDR',
            'DNG_FIELD_TITLE_WIDTH', 'DNG_FIELD_TITLE_LIMIT', 'DNG_TITLE_TABLE_ADDR', 'DNG_SPILL_LIMIT')}
    defs.update({name: sym[name] for name in ('dng_title_idx', 'dng_title_blob', 'vwf_font_index', 'vwf_font_width')})
    defs['dng_title_count'] = (blob - idx) // 24
    widths = Path(ROOT, 'src', 'asm', 'font', 'vwf_width.bin').read_bytes()
    defs.update(VWF_FIRST_BYTE=0x88, VWF_GLYPHS=len(widths))
    with tempfile.TemporaryDirectory(prefix='dng-field-title-') as tmp:
        isolated = os.path.join(tmp, 'isolated.bin')
        script = os.path.join(tmp, 'verify.asm')
        src = os.path.join(ROOT, 'src', 'asm', 'dng', 'field_title.asm')
        with open(script, 'w', encoding='utf-8') as f:
            f.write('.psx\n' + ''.join(f'.definelabel {name}, 0x{value:X}\n' for name, value in defs.items()))
            f.write(f'.open "{retail_path}", "{isolated}", 0x{base:X}\n')
            f.write(f'.include "{src}"\n.close\n')
        result = subprocess.run([armips, script], capture_output=True, text=True)
        if result.returncode:
            raise SystemExit('dngnames: verify: isolated assembler failed: ' + result.stdout + result.stderr)
        reference = Path(isolated).read_bytes()
    for lo, hi in ((entry, entry + 8), (start, end)):
        if image[lo - base:hi - base] != reference[lo - base:hi - base]:
            raise SystemExit('dngnames: verify: field title hook/code differs from independently assembled bytes')
    loaded_end = base + ((len(image) + 0x7FF) & ~0x7FF)
    if loaded_end > asm_equ('DNG_ITEM_DATA_END'):
        raise SystemExit('dngnames: verify: sector-rounded DNG load reaches the work area')
    print(f'dngnames: verify: {defs["dng_title_count"]} titles {idx:#x}..{blob_end:#x}; '
          f'field renderer {start:#x}..{pixels:#x}, scratch {pixels:#x}..{end:#x}')


def main():
    rows = [(rel, off, ja, '', '') for rel, off, ja in psx_floor_rows()]
    en = resolved_en(rows)
    emit_titles(rows, en)
    n = 0
    for fp in sorted(glob.glob(os.path.join(ROOT, 'data', 'psx', 'D0*', 'D*M.BIN'))):
        d = bytearray(open(fp, 'rb').read())
        if len(d) < 16:
            continue
        k = 0
        for p, ja in source_names(d):
            out = pack_field(ja, en.get(ja, ''))
            if out is None:
                continue
            d[p:p + 2 * SLOTS] = out
            k += 1
        # Always write the file back (even unchanged): a skipped file would
        # leave a stale copy from a previous build behind.
        out = os.path.join(ROOT, 'build', os.path.basename(os.path.dirname(fp)), os.path.basename(fp))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, 'wb') as o:
            o.write(d)
        n += k
    print(f'dngnames: wrote {n} floor names')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    {'verify': verify, 'dump': dump, 'plan': write_plan}.get(sys.argv[1] if sys.argv[1:] else '', main)()
