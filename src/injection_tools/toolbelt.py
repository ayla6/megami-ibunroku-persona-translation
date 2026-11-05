"""The single source of truth for everything under translation/ and
extracted_text/ (see docs/TEXT_ARCHITECTURE.md).

Every repo script reads and writes text tables through these functions -
never hand-rolled TSV parsing, never ad-hoc paths, never text search.
Import first (it puts src/injection_tools on the path):

    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    '..', '..', 'injection_tools'))  # depth varies
    import toolbelt  # noqa: E402

Layout (docs/TEXT_ARCHITECTURE.md):
- one TSV per real disc file, mirroring the disc's relative path:
  generated: translation/generated/D00/D00M.tsv   (id pos psp en)
  manual:    translation/manual/D00/D00M.tsv      (id pos psp en note)
- extracted: extracted_text/<region>/<relpath>.tsv  (id entry box pos text)
  region is psx / psp_us / psp_jp; the psp tree mirrors the PSP layout.
- `pos` is a ROM position within the file only: '0xc88' or 'entry:offset'
  where a file needs sub-structure (archive members). Multi-spot rows are
  comma-separated. `psp` points into the extracted PSP text: 'E2:127',
  'd00:239d8' / 'EBOOT:26b7c0' (its pos offset), 'KOUMAN:3' (a talk answer
  slot); comma-separated for a row assembled from several units.

Roles (each role is one tool; no overlap):
  dump  -> extracted_text/ (positions + scaffold; never invents text)
  port  -> generated/      (PSP wording; the ONLY place text is compared)
  build -> bytes at pos    (manual wins where filled; never searches)

Rules:
- manual `en` is sacred: automatic tools add rows for new positions and
  delete empty rows only; an emptied file is deleted, an emptied folder
  too. Never edit a human's translation.
- generated is ephemeral: no notes, no ja, rewritten freely.
- any `en` that exists but cannot ship fails the tool loudly (fail()).
- a stale manual pos fails the build for human re-homing; never guess by
  text content.

Columns (validated on read):
  GEN_COLS = ('id', 'pos', 'psp', 'en')
  MAN_COLS = ('id', 'pos', 'en', 'psp', 'note')
  EXT_COLS = ('id', 'entry', 'box', 'pos', 'text')      # extracted_text
"""
import os
import re
import threading

import strlib
import sys

# Serialize in-process table mutations: each update reads, merges and replaces
# a complete per-file table. Cross-process writers are sequenced by port.py.
_TABLE_LOCK = threading.RLock()


def _locked(fn):
    """Serialize a table mutator. See _TABLE_LOCK."""
    def wrapper(*a, **k):
        with _TABLE_LOCK:
            return fn(*a, **k)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

TOOL = os.path.basename(sys.argv[0]).rsplit('.', 1)[0] if sys.argv else 'tool'
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ADDRESSES_INC = os.path.join(ROOT, 'src', 'asm', 'common', 'addresses.inc')


def asm_equ(name, path=None):
    """The address/value constant `name` from an .inc of equ literals (the
    addresses.inc partition by default) - the one place these live. A tool
    that places bytes where an asm hook or data block expects them must READ
    the constant, never restate it: armips does not warn on overlapping
    .org claims. Literals only; expressions are the assembler's business."""
    with open(path or ADDRESSES_INC, encoding='utf-8') as f:
        contents = f.read()
    m = re.search(rf'^{re.escape(name)}\s+equ\s+(0x[0-9A-Fa-f]+|\d+)\s*(?:;.*)?$',
                  contents, re.M)
    if not m:
        raise SystemExit(f'{TOOL}: {name} is not a literal equ in '
                         f'{path or ADDRESSES_INC}')
    return int(m.group(1), 0)

GEN_COLS = ('id', 'pos', 'psp', 'en')
MAN_COLS = ('id', 'pos', 'psp', 'en', 'note')
EXT_COLS = ('id', 'entry', 'box', 'pos', 'text')

# THE OWNERSHIP RULE for translation/manual: a row's `en` is the human's.
# A row with an EMPTY `en` is a work-queue row - its note is a tool's
# explanation, whatever it says, and any tool may rewrite it or delete the
# row. Notes are never inspected to decide who owns a row.


def gap_marker(ja):
    """The 'nothing has sourced this row yet' marker route_gaps writes.

    The REASON comes first and the Japanese after it, because a worklist row
    is read by someone deciding what to type: 'unpaired' says why the row is
    there (no PSP-US wording is attached to it), and the line itself follows
    so the row can be identified without opening another tool. A row that
    gains a source leaves this marker behind for a real note."""
    ja = (ja or '').strip()
    # A POSITION WITH NO TEXT IN THE SCAN CANNOT BE TRANSLATED: saying which
    # it is (an image page, a slot the map does not cover) is the reason the
    # row is queued, and it is the only note such a row can ever deserve.
    return f'unpaired; ja {ja}' if ja else \
        'no source: the scan has no text at this position'


GENERATED = os.path.join(ROOT, 'translation', 'generated')
MANUAL = os.path.join(ROOT, 'translation', 'manual')
EXTRACTED = os.path.join(ROOT, 'extracted_text') if os.path.isdir(
    os.path.join(ROOT, 'extracted_text')) else os.path.join(ROOT, 'data', 'extracted_text')

# The one place the generated-correspondence path is named; moving the
# directory is a change HERE and nowhere else. Authored extraction inputs
# live beside their tools (SOURCE_MAPPINGS).
MAPPINGS = os.path.join(ROOT, 'translation', 'generated_mappings')
SOURCE_MAPPINGS = os.path.join(ROOT, 'src', 'extraction_tools', 'matching')
PSP_GLYPHS = os.path.join(ROOT, 'src', 'extraction_tools', 'psp_glyphs.tsv')
GLOSSARY = os.path.join(MANUAL, 'terms.tsv')
WORDING_TABLES = (GLOSSARY,)
ASSETS = os.path.join(ROOT, 'data')

NL = '\n'
POS_RE = re.compile(r'^(\d+:)?0x[0-9a-f]+$')
ID_RE = re.compile(r'^\d+$')


def fail(msg):
    """Abort the build with a tool-prefixed error. Use for any row whose
    translation exists but cannot ship as-is."""
    raise SystemExit(f'{TOOL}: {msg}')


def ensure_parent(path):
    """Create the output directory for a generated file (fresh-clone safe)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

def rel_for(path):
    """THE binding: a real disc file -> its rel = its disc path under
    data/psx minus the .BIN extension. One rel per real file, period:
    ADV.BIN is 'ADV' and the story files inside the story dir are
    'ADV/E0'... - ADV.tsv and ADV/ sit side by side, so the extension is
    unnecessary for uniqueness."""
    rel = os.path.relpath(path, os.path.join(ROOT, 'data', 'psx'))
    return rel[:-4] if rel.endswith('.BIN') else rel


def bin_path(rel):
    """The real disc file for a rel (docs: rel = the disc path without
    extension; the file on disc may carry .BIN). THE binding - a rel never
    names anything but its own real file."""
    p = os.path.join(ROOT, 'data', 'psx', *rel.split('/'))
    for cand in (p, p + '.BIN'):
        if os.path.isfile(cand):
            return cand
    fail(f'{rel}: no such file under data/psx (looked for {p} and {p}.BIN)')


def _tsv_path(base, rel):
    """<base>/<rel>.tsv - the TSV mirrors the disc's relative path exactly
    (data/psx/D00/D00M.BIN -> generated/D00/D00M.tsv; data/psx/SLPS_005.00
    -> generated/SLPS_005.00.tsv). One table per real file, same tree."""
    return os.path.join(base, *rel.split('/')) + '.tsv'


def gen_path(rel):
    """translation/generated/<rel> for the real disc file <rel> (no ext)."""
    return _tsv_path(GENERATED, rel)


def man_path(rel):
    """translation/manual/<rel> for the real disc file <rel> (no ext)."""
    return _tsv_path(MANUAL, rel)


def ext_path(region, rel):
    """extracted_text/<region>/<rel>.tsv; rel mirrors the disc tree."""
    return os.path.join(EXTRACTED, region, *rel.split('/')) + '.tsv'


# ---------------------------------------------------------------------------
# row io
# ---------------------------------------------------------------------------

_READ_CACHE = {}


def _read(path, cols, optional):
    # The porters re-read the same extracts constantly (1775 reads in one
    # run). A row set changes only when the file does, so mtime+size is
    # the whole key and a write invalidates it by definition.
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
    except OSError:
        key = (path, 0, 0)
    if key in _READ_CACHE:
        return _READ_CACHE[key]
    rows = _read_uncached(path, cols, optional)
    _READ_CACHE[key] = rows
    return rows


def _read_uncached(path, cols, optional):
    if not os.path.exists(path):
        if optional:
            return []
        fail(f'{os.path.relpath(path, ROOT)}: missing (the dump/extract step '
             f'creates it - see docs/TEXT_ARCHITECTURE.md)')
    with open(path, encoding='utf-8') as f:
        lines = f.read().split(NL)
    if not lines or not lines[0].strip():
        fail(f'{os.path.relpath(path, ROOT)}: empty file (no header row)')
    head = lines[0].rstrip('\r').split('\t')
    if tuple(head) != tuple(cols):
        # A MANUAL FILE IS NOT NECESSARILY A ROW TABLE: translation/manual/
        # fmv/poems.tsv is a SOURCE table a builder reads with its own schema
        # (fmv_layout.poem_lines: movie/seq/text). A table that shares NO
        # column with the canonical one is not a row table, so the walker
        # skips it instead of aborting every porter that walks the tree. One
        # that shares a column but spells it wrong is still a plain error.
        if optional and not set(head) & set(cols):
            return []
        fail(f'{os.path.relpath(path, ROOT)}: header {head} != canonical '
             f'{list(cols)}')
    rows = []
    for n, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        f = line.rstrip('\r').split('\t')
        if len(f) > len(cols):
            fail(f'{os.path.relpath(path, ROOT)}:{n}: {len(f)} fields, header '
                 f'has {len(cols)}: {line[:80]!r}')
        f += [''] * (len(cols) - len(f))
        r = dict(zip(cols, f))
        if not ID_RE.match(r['id']):
            fail(f'{os.path.relpath(path, ROOT)}:{n}: bad id {r["id"]!r}')
        for p in r['pos'].split(','):
            if p and not POS_RE.match(p):
                fail(f'{os.path.relpath(path, ROOT)}:{n}: bad pos {p!r}')
        rows.append(r)
    return rows


def read_generated(rel, optional=False):
    """Rows (dicts keyed by GEN_COLS) of translation/generated/<rel>.tsv."""
    return _read(gen_path(rel), GEN_COLS, optional)


def read_manual(rel, optional=True):
    """Rows (dicts keyed by MAN_COLS) of translation/manual/<rel>.tsv.
    Optional by default: manual exists only where humans wrote."""
    return _read(man_path(rel), MAN_COLS, optional)


def read_extracted(region, rel, optional=False):
    """Rows (dicts keyed by EXT_COLS) of extracted_text/<region>/<rel>.tsv."""
    return _read(ext_path(region, rel), EXT_COLS, optional)


def _extract(reg, rel):
    if (reg, rel) not in _EXTRACT_CACHE:
        _EXTRACT_CACHE[(reg, rel)] = read_extracted(reg, rel, optional=True)
    return _EXTRACT_CACHE[(reg, rel)]


_EXTRACT_CACHE = {}


def psp_rel(name):
    """The extracted-text rel a `psp` pointer's name column names
    ('EBOOT', 'd16', 'KOUMAN' -> the extract's own rel)."""
    if name.startswith('pack/'):
        return name
    if re.fullmatch(r'd[0-9a-f]{2}m?', name):
        return 'pack/dng/' + name
    if re.fullmatch(r'e[0-9]', name, re.I):
        return 'pack/' + name.upper()
    if name.upper() in ('EBOOT', 'BOOT'):
        return 'EBOOT'
    return 'pack/talk/' + name.upper()


def psp_name(rel):
    """The shortest `psp` pointer name that resolves back to this extract
    rel ('EBOOT', 'd16', 'KOUMAN' - the forms every reader already knows).
    Falls back to the full rel, which the readers take verbatim."""
    if rel == 'EBOOT' or not rel.startswith('pack/'):
        return rel
    short = rel.split('/')[-1]
    return short if psp_rel(short) == rel else rel


def psp_loc(loc):
    """A locator's POSITION in ONE spelling.

    Porters write the same position both ways ('EBOOT:268b08' from the
    boot-table tables, 'EBOOT:0x268b08' from the pair map), so a lookup
    that compares the strings finds nothing half the time - which is how a
    three-text rule silently lost its Japanese twin. An offset normalises
    to lower-case hex with its 0x prefix; a locator keyed some other way
    (a family row key) is left exactly as it is."""
    try:
        return '0x%x' % int(loc, 16)
    except (TypeError, ValueError):
        return loc


def psx_rels():
    """Every PSX extract rel, canonical order (the port walks these)."""
    base = os.path.join(EXTRACTED, 'psx')
    out = []
    for dirpath, _d, files in os.walk(base):
        for f in sorted(files):
            if f.endswith('.tsv'):
                out.append(os.path.relpath(os.path.join(dirpath, f),
                                           base)[:-4].replace(os.sep, '/'))
    return sorted(out)


def psx_text_of(rel):
    """{pos: japanese} the PSX disc's own text of one file."""
    return {r['pos']: r['text']
            for r in read_extracted('psx', rel, optional=True)}


_PSP_INDEX = {}


def psp_wording(ptr):
    """The PSP-US wording a `psp` pointer names, or '' - what a row's
    over-cap cap was measured on. Never typed: read from the extract.
    Indexed per extract for repeated pointer lookups."""
    if not ptr or ptr.count(':') < 1:
        return ''
    parts = [p.strip() for p in ptr.split(',') if p.strip()]
    if len(parts) != 1:
        return ''                     # a merged row: no single draft
    name, loc = parts[0].split(':', 1)
    rel = psp_rel(name)
    if rel not in _PSP_INDEX:
        exact, heads = {}, []
        for r in _extract('psp_us', rel):
            exact[r['pos']] = r['text']
            try:
                heads.append((int(r['pos'], 16), r['text']))
            except ValueError:
                pass
        heads.sort()
        _PSP_INDEX[rel] = (exact, heads)
    exact, heads = _PSP_INDEX[rel]
    if loc in exact:
        return exact[loc]
    try:
        off = int(loc, 16)
    except ValueError:
        return ''
    import bisect
    i = bisect.bisect_right(heads, (off, '\uffff')) - 1
    return heads[i][1] if i >= 0 else ''


def read_eboot(region, lo=None, hi=None):
    """[(pos_int, text)] of EBOOT units in [lo, hi) - the single source for
    BOOT consumers. Region accepts the short form ('us'/'jp')."""
    region = {'us': 'psp_us', 'jp': 'psp_jp'}.get(region, region)
    rows = [(int(r['pos'], 16), r['text'])
            for r in read_extracted(region, 'EBOOT')]
    rows.sort()
    return [(p, t) for p, t in rows
            if (lo is None or p >= lo) and (hi is None or p < hi)]


def read_be(lo=None, hi=None):
    """[(pos_int, text)] of the BE text RECORDS of EBOOT.BIN in [lo, hi) -
    the porters' view (tables.be_runs), whose offsets are the ones
    translation/generated_mappings/*.tsv addresses name: a record starts at its first text
    unit, never at the binary in front of it. EBOOT.tsv is the same file
    scanned for units (be_units), which merge a record with the table
    before it - readers with map addresses use THIS. The cache is written
    by boot_tables.py 'be'; fail loud when it is not there yet."""
    path = os.path.join(ROOT, 'data', 'cache', 'boot_be.tsv')
    if not os.path.exists(path):
        fail(f'{path} missing - run: python '
             f'src/extraction_tools/psp/boot_tables.py be')
    rows = [(int(r['offset'], 16), r['en'])
            for r in strlib.tsv_rows(path, required=('offset', 'en'))]
    rows.sort()
    return [(p, t) for p, t in rows
            if (lo is None or p >= lo) and (hi is None or p < hi)]


def tidy_en(t):
    """Exactly one end code, at the end. A doubled terminator is what
    `talk` rejects ('must end with exactly one end code') and what `bpe`
    cannot round-trip (its unpacker stops at the first). One writer, one
    rule - not a fix per porter."""
    t = (t or '').rstrip()
    m = re.search(r'(<FFF5>|<FFEF>)', t)
    if m:
        t = t[:m.end()] if not t[m.end():].strip() else t
    t = re.sub(r'(<FFF5>|<FFEF>)(?:\s*(?:<FFF5>|<FFEF>))+', r'\1', t)
    return t


def _write(path, cols, rows):
    if 'en' in cols:
        for r in rows:
            r['en'] = tidy_en(r.get('en', ''))
    # Evict this path's mtime-keyed cache entries before replacing its contents.
    for k in [k for k in _READ_CACHE if k[0] == path]:
        del _READ_CACHE[k]
    rows = sorted(rows, key=lambda r: int(r['id']) if str(r['id']).isdigit() else 1 << 30)
    # ids are a file-local ordinal, not identity - `pos` is the identity.
    # Two writers can both claim the same next free int (generated and
    # manual keep separate counters), and the row set is still perfectly
    # valid. Renumber duplicate ordinals without changing position identity.
    seen = set()
    nxt = max((int(r['id']) for r in rows if str(r['id']).isdigit()), default=-1) + 1
    for r in rows:
        if r['id'] in seen:
            r['id'] = str(nxt)
            nxt += 1
        seen.add(r['id'])
    ensure_parent(path)
    with open(path, 'w', encoding='utf-8', newline=NL) as o:
        o.write('\t'.join(cols) + NL)
        for r in rows:
            o.write('\t'.join(r.get(c, '') for c in cols) + NL)
    return len(rows)


def _prune_empty(path, base):
    """Delete an empty table and prune the folders it leaves empty. A
    header-only TSV is not a worklist; it is an artefact of a writer that
    was asked to write nothing."""
    for k in [k for k in _READ_CACHE if k[0] == path]:
        del _READ_CACHE[k]
    if os.path.exists(path):
        os.remove(path)
    base = os.path.normpath(base)
    d = os.path.dirname(path)
    while (os.path.normpath(d).startswith(base + os.sep)
           and os.path.isdir(d) and not os.listdir(d)):
        os.rmdir(d)
        d = os.path.dirname(d)


@_locked
def write_generated(rel, rows):
    """Write translation/generated/<rel>.tsv (drops the note column by
    construction; generated has none). Generated holds filled rows only,
    so an empty list deletes the file and prunes emptied folders."""
    path = gen_path(rel)
    if not rows:
        _prune_empty(path, GENERATED)
        return 0
    # THE TABLES KEEP THE SOURCE'S SPELLING. A typographic apostrophe is the
    # PSP-US wording's own character, so folding it here would mean the
    # tables no longer hold what the source says. The fold belongs where text
    # becomes bytes - etext.spell, which encode, the QA gate and the width
    # pricing all call (one rule, so the same row measures and prints alike).
    return _write(path, GEN_COLS, rows)


@_locked
def write_manual(rel, rows):
    """THE manual writer. `en` here is a HUMAN's and ONLY a human's.

    NO SCRIPT FILLS IT. Not a porter, not a sweep, not a "restore", not a
    normaliser, nothing. A tool's wording goes to translation/generated/,
    or into the note as a draft in route_over's shape ('<reason>;
    <draft>'). The reason is not politeness: once a machine has written
    `en` there is no way to tell it from a human's line when the generated
    wording supersedes it, and it can never be cleared. So this refuses
    any caller that fills an `en` the file did not already have, and it
    refuses a caller that omits a human row (that is how a prune would
    delete someone's work).

    All rows are kept verbatim (manual = the human's work queue); an empty
    list deletes the file and prunes emptied folders."""
    on_disk = {r['pos']: r for r in read_manual(rel, optional=True)}
    for r in rows:
        new_en = (r.get('en') or '').strip()
        old_en = ((on_disk.get(r['pos']) or {}).get('en') or '').strip()
        if new_en and not old_en:
            fail(f'{man_path(rel)}: {r["pos"]}: {new_en[:40]!r} - no script '
                 f'fills manual\'s en; wording belongs in generated/, or in '
                 f'the note as \'<reason>; <draft>\'')
        previous = on_disk.get(r['pos']) or {}
        if old_en and (r.get('en', ''), r.get('note', '')) != (previous.get('en', ''), previous.get('note', '')):
            fail(f'{man_path(rel)}: {r["pos"]}: refusing to change a row with manual wording')
    # The same rule from the other side: a caller may rewrite or drop
    # queue rows, but it may not omit a row carrying English.
    passed = {r['pos'] for r in rows}
    for pos, old in on_disk.items():
        if (old.get('en') or '').strip() and pos not in passed:
            fail(f'{man_path(rel)}: {pos}: refusing to drop a human row '
                 f'(en {old["en"][:30]!r}, note {old["note"][:30]!r}; a '
                 f'caller omitted it)')
    path = man_path(rel)
    if not rows:
        _prune_empty(path, MANUAL)
        return 0
    return _write(path, MAN_COLS, rows)


@_locked
def route_gaps(rel, positions, stale=False):
    """The translation work queue: every scanned position without a
    filled translation gets a manual row - empty en, and its note is the
    row's original Japanese ('ja ...') so a reader sees what the row IS
    without opening another tool. note only says more when the porter
    routed over-limit. A generated translation supersedes a queue row
    (empty en) whatever its note says; a row with English survives."""
    man = {r['pos']: r for r in read_manual(rel, optional=True)}
    # Only a generated row that actually carries wording supersedes the
    # queue: generated keeps a row per scanned position, and an empty one is
    # still a gap (it must not delete the manual row that queues it).
    filled = {r['pos']: r for r in read_generated(rel, optional=True)
              if (r.get('en') or '').strip()}
    if stale and positions:
        known = set(positions)
        for pos, r in list(man.items()):
            if pos in known:
                continue
            # a queue row at a position the scan no longer has goes; English
            # there fails for re-homing
            if not (r.get('en') or '').strip():
                del man[pos]
                continue
            fail(f'{man_path(rel)}: row {r["id"]} pos {pos} is stale '
                 f'(the binary scan has no such position) - re-home it')
    nxt = max((int(r['id']) for r in man.values() if str(r['id']).strip().isdigit()),
              default=-1) + 1
    n = 0
    ja_of = psx_text_of(rel)
    for pos in positions:
        if pos not in filled and pos not in man:
            ja = ja_of.get(pos, '')
            man[pos] = {'id': str(nxt), 'pos': pos, 'en': '', 'psp': '',
                        'note': gap_marker(ja)}
            nxt += 1
            n += 1
    for r in man.values():
        if (r.get('en') or '').strip():
            continue
        note = (r.get('note') or '').strip()
        ja = ja_of.get(r['pos'], '')
        # A queue row the scan could not source before is rewritten now
        # that the scan has text there: the marker is the tool's, not the
        # translator's, so refreshing it is allowed (ownership rule).
        if not note or (note == gap_marker('') and ja):
            r['note'] = gap_marker(ja)
            n += 1
    for pos in [p for p, r in list(man.items())
                if p in filled and not r['en'].strip()]:
        del man[pos]                     # generated English supersedes a queue row
        n -= 1
    if man:
        out = list(man.values())
        for i, r in enumerate(out):
            if not str(r['id']).strip():
                r['id'] = str(i)
        write_manual(rel, out)
    else:
        write_manual(rel, [])
    return n


def write_extracted(region, rel, rows):
    """Write extracted_text/<region>/<rel>.tsv - THE writer; every extract
    has one shape (docs/TEXT_ARCHITECTURE.md):

        id  entry  box  pos  text

    id = source order in the file (the guiding number); entry = the
    container (archive entry index / section, empty for flat files); box =
    the unit index within its entry (the map files' psx_box/jp_box/us_box
    coordinate); pos = the unit's byte locator, the same cell format as
    generated/manual `pos` (the editor joins extracted context to rows
    with it). Callers may pass pos+text only - entry/box/id derive here,
    so no extractor can invent a shape of its own."""
    out, seq = [], {}
    for r in rows:
        pos = str(r.get('pos', ''))
        entry = str(r.get('entry', '') or '')
        if not entry:
            pre = pos.split(':', 1)[0] if ':' in pos else ''
            if pre.isdigit():
                entry = pre
        box = str(r.get('box', '') or '')
        if box == '':
            box = str(seq.get(entry, 0))
        seq[entry] = max(seq.get(entry, 0), int(str(box)) + 1) if str(box).lstrip('-').isdigit() else seq.get(entry, 0) + 1
        out.append({'id': str(r.get('id', '') or len(out)), 'entry': entry,
                    'box': box, 'pos': pos, 'text': r.get('text', '')})
    return _write(ext_path(region, rel), EXT_COLS, out)


# ---------------------------------------------------------------------------
# merge + dump lifecycle (the only merge rules in the repo)
# ---------------------------------------------------------------------------

def merge(rel, gen_rows, man_rows):
    """Merged rows for a builder: manual wins where it is filled - a human's
    shortened over-limit row lives in manual alone and MUST build - and
    generated supplies everything else. Keyed by pos, generated source
    order, manual-only rows after. Manual rows with empty en (gaps and
    un-adopted drafts) never reach a builder: the Japanese ships."""
    out = {}
    order = []
    for r in gen_rows:
        out[r['pos']] = dict(r)
        order.append(r['pos'])
    for r in man_rows:
        if (r.get('en') or '').strip():
            if r['pos'] not in out:
                order.append(r['pos'])
            out[r['pos']] = dict(r)      # manual wins
    return [out[p] for p in order]


# Two invariants of the textbox FORMAT itself, applied by the one writer every
# porter uses (a row that breaks them ships a box that moves on its own):
#   * a code's parameter is never missing - <FF0E>'s parameter is a SPACE in
#     the script, and an edge-blank rule can eat it, after which the encoder
#     reads the next byte as the parameter ('[charset] non-ASCII bytes: 01');
#   * a box ends with its dismissal wait - '<FF02><FF01>' - because that wait
#     is the press that closes the box.
_PARAM_LEN = {'05': 2, '06': 1, '0E': 1}
# Name insert fixup for the current table format, not a proven conversion
# between PSP and every destination interpreter. The PSP spells them with NO parameter ("My last
# name is <FF0F>."), the PSX with the member id, so a parameterless one takes
# a synthesized id - the PSP's bare form means "the player's name". Reading
# the next character as the id (what the generic rule did) asked for member
# 0x2E - a period - and printed junk (7 rows: D00 D08 D13).
# Dungeon field scripts use a different hero id and are converted before this
# fixer. A full-name insert is spelled given, space, family to preserve the
# western PSP wording. See TEXT_LAYOUT_SPEC.md for the engine distinctions.
NAME_INS = {'07': 'given', '08': 'nickname', '0F': 'family', '10': 'full'}
HERO_ID = '<01>'


def fix_textbox(en):
    """The format invariants of a textbox's text, or `en` untouched."""
    if '<FF' not in (en or ''):
        return en                      # a plain name/string: nothing to fix
    out, i = [], 0
    while i < len(en):
        m = re.match(r'<FF([0-9A-Fa-f]{2})>', en[i:])
        if m:
            code = m.group(1).upper()
            if code in NAME_INS:
                rest = en[i + m.end():]
                par = re.match(r'<[0-9A-Fa-f]{2}>', rest)
                pid = par.group(0) if par else HERO_ID
                i += m.end() + (par.end() if par else 0)
                if NAME_INS[code] == 'full':
                    out.append(f'<FF07>{pid} <FF0F>{pid}')
                else:
                    out.append(m.group(0) + pid)
                continue
            out.append(m.group(0))
            i += m.end()
            need = _PARAM_LEN.get(code, 0)
            if need:
                rest = en[i:]
                if not rest or rest.startswith('<FF'):
                    out.append(' ' * need)
                else:
                    out.append(rest[:need])
                    i += need
            continue
        out.append(en[i])
        i += 1
    s = ''.join(out)
    # ... and only the ADV family's box ends with <FF02><FF01>: the TALK
    # engine's end is <FFEF>/<FFF5> with its own waits (<FFFC>/<FFF6>), and
    # imposing an <FF02> there loses the whole unit at build time.
    if '<FF0E>' in s:
        # A choice row ends '<FF0E><param><FF01>'; a trailing wait prevents
        # the options from arming.
        s = re.sub(r'(<FF0E>.*?)(?:<FF02>)+(?=<FF01>|<FFEF>|<FFF5>|$)',
                   r'\1', s, flags=re.S)
        # ... AND THE PROMPT'S OWN LAYOUT IS PART OF THE ROW: its label may take
        # a line of its own when the question then sits whole on one line, and
        # the option block's gate counts the question, never the nameplate
        # (vwf_wrap.prompt_label_line; spec 3.9). This is the one place a row is
        # written, so a row is laid out at the moment it is ported.
        import vwf_wrap
        return vwf_wrap.choice_breaks(s, brk='<FFF6>' if '<FFF6>' in s else '<FF03>')
    if s.rstrip().endswith('<FF01>') and ('<FF03>' in s or '<FFF6>' in s):
        s = re.sub(r'(?:<FF03>)+\s*$', '', s)
        s = re.sub(r'(?:<FF02>)*(<FF01>)\s*$', lambda m: '<FF02>' + m.group(1), s)
        s = re.sub(r'(?:<FF03>)+(?=<FF02><FF01>)', '', s)
    return s


# Japanese LETTERS, not the punctuation sharing their Unicode blocks (notably
# the middle dot in shoulder-button groups and instruction bullets).
JP_LETTERS = r'[ぁ-ゖゝ-ゟァ-ヺーヽ-ヿ一-鿿]'


@_locked
def upsert_generated(rel, new_rows):
    """Merge rows into generated by pos. Generated holds FILLED rows only:
    rows whose en is empty are not written (they live in manual when
    routed, or are visible as untranslated JA in game). Existing rows win
    on filled en; new positions get fresh ids. The writer every porter
    uses - nothing may write generated TSVs by hand."""
    rows = {r['pos']: r for r in read_generated(rel, optional=True)}
    n = 0
    JA = re.compile(JP_LETTERS)
    for r in new_rows:
        # Untranslated PSP-US boxes remain gaps. Branch/name parameters are
        # structure and are excluded from the Japanese wording check.
        if JA.search(re.sub(r'<FFFD>.|<FF(07|08|0F)>(?:あ|<[^>]*>)?', '',
                            (r.get('en') or ''))):
            print(f'upsert_generated: {rel} {r["pos"]} source is still '
                  f'Japanese - kept as a gap')
            r = dict(r, en='')
        if r.get('en', '').strip():
            r = dict(r, en=fix_textbox(r['en']))
        cur = rows.get(r['pos'])
        if cur is not None:
            if r.get('en', '').strip():
                cur['en'] = r['en']
                cur['psp'] = r.get('psp', cur.get('psp', ''))
                n += 1
        elif r.get('en', '').strip():
            rows[r['pos']] = {'id': '', 'pos': r['pos'],
                              'en': r['en'], 'psp': r.get('psp', '')}
            n += 1
    out = []
    for r in rows.values():
        if JA.search(re.sub(r'<FFFD>.|<FF(07|08|0F)>(?:あ|<[^>]*>)?', '',
                            (r.get('en') or ''))):
            print(f'upsert_generated: {rel} {r["pos"]} held Japanese - '
                  f'withdrawn (it is a gap)')
            continue
        r['en'] = fix_textbox(r.get('en') or '')
        out.append(r)
    nxt = max((int(r['id']) for r in out if str(r['id']).strip().isdigit()),
              default=-1) + 1
    for r in out:
        if not str(r['id']).strip():
            r['id'] = str(nxt)
            nxt += 1
    write_generated(rel, out)
    route_gaps(rel, [])            # auto-clean superseded manual rows
    return n


def unport(rel, pos):
    """Take back a generated row whose source did not verify.

    The counterpart of upsert_generated: generated is ephemeral (docs/
    TEXT_ARCHITECTURE.md - 'rewritten freely'), and a row whose `psp` did
    not hold up must not keep building a wording nobody can account for.
    The Japanese ships again until someone supplies a real source. Never
    touches manual/: what a human wrote is theirs."""
    rows = [r for r in read_generated(rel, optional=True) if r['pos'] != pos]
    return write_generated(rel, rows)


def note_over(n, cap, unit='px'):
    """The only over-cap reason format, unit-explicit: 'over limit 265px/239px'
    (px), 'over limit 57 chars/25 chars' (cells), 'over limit 30B/28B' (bytes),
    'over limit 9 words/7 words' (slots). Symbol units glue, word units space."""
    u = (unit or '').strip()
    sep = ' ' if u not in ('px', 'B') else ''
    return f'over limit {n}{sep}{u}/{cap}{sep}{u}'


def over_note(reason, draft):
    """The canonical over-cap note: the mechanical reason first, the full
    PSP draft after '; '. THIS - never `en` - is where a draft lives: a
    draft in en would make the build fail until a human fixes every row."""
    return f'{reason}; {draft}'


@_locked
def route_over(rel, pos, psp, draft, reason):
    """THE over-limit writer (the only one). A draft that cannot ship lands
    in manual with EMPTY en and note = '<reason>; <draft>' (reason comes
    from note_over for size caps). The build never fails on a draft: en
    stays empty (the Japanese ships) until the human shortens the draft
    into en; only then does the row become theirs and build. A generated
    row carrying that same unshippable text is dropped here - a draft
    never lives in generated."""
    r = route_to_manual(rel, {'pos': pos, 'psp': psp, 'en': '',
                              'note': over_note(reason, draft)})
    rows = read_generated(rel, optional=True)
    # the draft supersedes whatever the row carried before: the porter has
    # re-derived this position and the text cannot ship, so a stale generated
    # row here would keep building the old (over-wide / over-slot) wording
    keep = [x for x in rows if x['pos'] != pos]
    if len(keep) != len(rows):
        write_generated(rel, keep)
    return r


def _drop_generated(rel, pos):
    """A row now living in manual must not also live in generated: both
    copies carry the same id and the merge reports it as a duplicate.
    route_over has always done this; the general writer must too."""
    rows = read_generated(rel, optional=True)
    keep = [r for r in rows if r['pos'] != pos]
    if len(keep) != len(rows):
        write_generated(rel, keep)


@_locked
def route_to_manual(rel, row):
    """Manual-queue upsert (gap rows and route_over drafts). Over-limit
    drafts must come through route_over - a filled en under an 'over
    limit' note is a bug and fails loud here. An existing manual row is
    left alone when its en is filled (the human's); a queue row (empty en)
    takes the new note and pointer - its note is a tool's explanation."""
    if (row.get('note') or '').startswith('over limit') and (row.get('en') or '').strip():
        fail(f'{man_path(rel)}: {row["pos"]}: over-limit drafts belong in the '
             f'note with empty en (use route_over), never in en')
    man = {r['pos']: r for r in read_manual(rel, optional=True)}
    cur = man.get(row['pos'])
    if cur and (cur.get('en') or '').strip():
        return False                     # manual English is human-owned, even with a PSP pointer
    if cur:
        cur['en'] = row.get('en', '')
        cur['note'] = row.get('note') or cur.get('note', '')
        cur['psp'] = row.get('psp', cur.get('psp', ''))
        write_manual(rel, list(man.values()))
        _drop_generated(rel, row['pos'])
        return True
    man[row['pos']] = {'id': row.get('id', ''), 'pos': row['pos'],
                       'en': row.get('en', ''), 'psp': row.get('psp', ''),
                       'note': row.get('note', '')}
    # id = next free int (stable per file, source order unknown here)
    used = {r['id'] for r in man.values() if r['id'].isdigit()}
    if not man[row['pos']]['id'] or man[row['pos']]['id'] in used - {man[row['pos']]['id']}:
        n = 0
        while str(n) in used:
            n += 1
        man[row['pos']]['id'] = str(n)
    write_manual(rel, list(man.values()))
    return True


def dump_scaffold(rel, positions, keep_other=False):
    """Dump lifecycle for one file: write the generated scaffold for
    `positions` [(pos, psp, ...)], PRESERVING filled en by pos and keeping
    manual (untouched). Returns (generated_rows, manual_rows). New
    positions get empty en; vanished positions drop out (an emptied file
    disappears). Rows are numbered id = source order within the file.

    `keep_other` preserves positions owned by other scanners in a shared
    file (SLPS_005.00: names, choices, descriptions and affinity lines).
    The default treats this scan as the complete position surface."""
    old = {r['pos']: r for r in read_generated(rel, optional=True)}
    rows = []
    nxt = max((int(r['id']) for r in old.values() if str(r['id']).strip().isdigit()),
              default=-1) + 1
    known = {s[0] for s in positions}
    if keep_other:
        for pos, prev in old.items():
            if pos not in known and (prev.get('en') or '').strip():
                rows.append(dict(prev))
    for i, spec in enumerate(positions):
        pos, psp = spec[0], (spec[1] if len(spec) > 1 else '')
        prev = old.get(pos, {})
        if (prev.get('en') or '').strip():
            rid = prev.get('id') or str(nxt)
            if rid == str(nxt):
                nxt += 1
            rows.append({'id': rid, 'pos': pos, 'en': prev['en'],
                         'psp': prev.get('psp', psp)})
    if rows:
        write_generated(rel, rows)
    else:
        p = gen_path(rel)
        if os.path.exists(p):
            os.remove(p)
        d = os.path.dirname(p)
        while d.startswith(GENERATED) and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
            d = os.path.dirname(d)
    route_gaps(rel, [s[0] for s in positions])   # the human work queue
    return rows, read_manual(rel, optional=True)


# ---------------------------------------------------------------------------
# the one injection engine (docs/TEXT_ARCHITECTURE.md: build = read merged
# rows, encode en, place bytes at pos; never search)
# ---------------------------------------------------------------------------

def merged_rows(rel):
    """manual-over-generated rows for the file <rel>, keyed by pos, in
    generated source order. THE read path for every builder."""
    return merge(rel, read_generated(rel, optional=True),
                 read_manual(rel, optional=True))


def asm_header(tool):
    return f';; generated by tools/{tool}.py build - do not edit' + NL


def asm_org_bytes(o, pos, data, comment=''):
    if comment:
        o.write(f'; {comment}' + NL)
    o.write(f'.org {pos:#x}' + NL + '    .byte '
            + ', '.join(f'0x{x:02X}' for x in data) + NL)


def write_asm(path, tool, body):
    """Write a build/*.asm from a string body, creating the dir."""
    ensure_parent(path)
    with open(path, 'w', encoding='utf-8', newline=NL) as o:
        o.write(asm_header(tool))
        o.write(body)
    return path


class Patch:
    """Builder accumulator: encode + place, then emit one asm file.

    The common shape every injector had its own copy of: for each row,
    encode `en`, pad/fit it to a field, write bytes at pos (as .org
    output or into a binary copy). Positions come from the TSV - no
    builder ever searches for text to find a destination.
    """

    def __init__(self, tool, out):
        self.tool = tool
        self.out = out
        self.body = []
        self.n = 0

    def org(self, pos, data, comment=''):
        if comment:
            self.body.append(f'; {comment}')
        self.body.append(f'.org {pos:#x}')
        self.body.append('    .byte ' + ', '.join(f'0x{x:02X}' for x in data))
        self.n += 1

    def write(self):
        write_asm(self.out, self.tool, NL.join(self.body) + NL)
        return self.n


def fit_field(data, width, pad=b'\xff', tool='tool', what=''):
    """Fixed-width field: truncate/fail + pad. Fails loud on overflow (the
    user's rule: an `en` that cannot ship fails the build)."""
    if len(data) > width:
        fail(f'{what}: {len(data)} bytes > {width}-byte field')
    return data + pad * (width - len(data))


# ---------------------------------------------------------------------------
# encoders: one family per render path (the only other per-system variance)
# ---------------------------------------------------------------------------

EXTRA_GLYPH = {'-': '－', '.': '．', '?': '？', '&': '＆', '/': '／',
               ':': '：', '!': '！'}


def glyph_char(c, lower=True, space=0):
    """Game-font glyph index for one char (names, items, map titles).
    Full-width A-Z/a-z/0-9 and the ASCII punctuation set; kanji/kana pass
    through the font map (mixed labels like Lost森)."""
    import etext
    if c == ' ':
        return space
    if 'A' <= c <= 'Z':
        return etext.char2g[chr(0xFF21 + ord(c) - 65)]
    if lower and 'a' <= c <= 'z':
        return etext.char2g[chr(0xFF41 + ord(c) - 97)]
    if '0' <= c <= '9':
        return etext.char2g[chr(0xFF10 + ord(c) - 48)]
    if c in EXTRA_GLYPH:
        return etext.char2g[EXTRA_GLYPH[c]]
    return etext.char2g[c]


def smallfont_char(c):
    """Battle small-font byte (banners/names render here, NOT the dialogue
    VWF: VWF bytes draw wrong glyphs on this path)."""
    import etext
    c = etext.spell(c)                  # '’' is the ASCII apostrophe's cell
    import smallfont_lc
    if 'a' <= c <= 'z' or c in smallfont_lc.PUNCT_CODES:
        return smallfont_lc.code(c)
    if 'A' <= c <= 'Z' or '0' <= c <= '9' or c in " .-/:'":
        import items
        return items.glyph(c)
    fail(f'{c!r} is not in the small font')


def glyph_bytes(text, enc=glyph_char, **kw):
    return bytes(enc(c, **kw) for c in text)


# ---------------------------------------------------------------------------
# addressing: one resolver per file family (build never searches text)
# ---------------------------------------------------------------------------

OVERLAY_SLOT = 0x800643C4      # every overlay loads here (DNG/BTLP/S2D/ADV/NAME)
EXE_BASE = 0x80010000          # SLPS_005.00 resident EXE
EXE_FILE_BIAS = 0x800          # file offset = VA - EXE_BASE + EXE_FILE_BIAS


def file_va(rel, off):
    """Canonical file offset -> the RAM VA an asm .org needs (the inverse of
    va_file_offset; the rel decides EXE vs overlay)."""
    if rel == 'SLPS_005.00':
        return off - EXE_FILE_BIAS + EXE_BASE
    return off + OVERLAY_SLOT


def va_file_offset(va):
    """VA -> offset within the file that owns it. SLPS EXE for resident
    addresses; overlay addresses are slot-relative (which overlay file is
    decided by the caller's rel). Anything else fails loud - never a
    negative offset."""
    if EXE_BASE <= va < OVERLAY_SLOT:
        return va - EXE_BASE + EXE_FILE_BIAS
    if OVERLAY_SLOT <= va < 0x80200000:
        return va - OVERLAY_SLOT
    fail(f'va {va:#x} is outside the EXE (0x80010000+) and overlay (0x800643C4+) ranges')


def parse_pos(pos):
    """One pos token -> (entry, offset); entry is '' or the sub-structure
    name/index ('entry:offset')."""
    if ':' in pos:
        e, o = pos.split(':', 1)
        return e, int(o, 16)
    return '', int(pos, 16)


def pos_offsets(pos):
    """Multi-spot pos field -> [(entry, offset), ...]. Builders write every
    spot; nothing anywhere searches for text to find a destination."""
    return [parse_pos(p) for p in pos.split(',') if p]


# ---------------------------------------------------------------------------
# misc
# ---------------------------------------------------------------------------

def fail_if_unshippable(rel, rid, en, reason):
    """The loud-failure rule: translation exists but cannot ship."""
    if en.strip():
        fail(f'{rel} id {rid}: {reason}')


def ensure_parent_all(*paths):
    for p in paths:
        ensure_parent(p)
