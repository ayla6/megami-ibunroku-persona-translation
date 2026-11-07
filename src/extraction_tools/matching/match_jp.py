"""Find a PSX unit's Japanese in the extracted PSP trees - THE matcher.

A match is the `psp` pointer that porters and builders read
(docs/TEXT_ARCHITECTURE.md). The matching layer owns this lookup; the viewer
calls it.

How a unit is found (AGENTS.md: never a typed name, never a hand-written
mapping - align the structures mechanically):

  containment   one normalized string sits inside the other - the same
                words under a record header, a reworded prefix or a
                trailing terminator
  needles       small IDENTIFIABLE fragments, rare ones first, then wider;
                whole strings are never compared for equality because the
                two sides decode differently and reword freely
  kana folding  port_common.canonical_ja: the PSX labels in hiragana, the
                PSP names in katakana ('すらいむ' / 'スライム')

How strong an answer is (port_common's tiers - this decides what a caller
may DO with it, and nothing here may overrule it):

  exact        the same words, only codes and spacing apart
  canonical    the same after canonical_ja too - same words, other script
  lead         merely similar. NEVER written to generated/: it is a
               suggestion for a human, and callers must surface it as one.

A candidate set is only as good as its ambiguity: several different
English wordings for one Japanese string is not a match, it is a choice.
"""
import bisect
import os
import re
import sys
import unicodedata
from collections import defaultdict
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'matching'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
import toolbelt            # noqa: E402
from port_common import canonical_ja   # noqa: E402

TOK_RE = re.compile(r'<[^>]*>|\[[0-9a-fA-F]{4}\]')
NEEDLE = 5                  # needle length in characters
NEEDLE_RARE = 4             # a needle seen in at most this many rows
NEEDLE_LOOSE = 60           # ... and the loose pass, when nothing is rare
_KANA = {chr(c): chr(c - 0x60) for c in range(0x30A1, 0x30F7)}


_SPEAKER = re.compile(
    r'^\s*(?:<FF1B>[^<>]{0,28}<FF03>'          # portrait + name
    r'|[＞>])')                                 # box-head arrow

# --- the JP-row lookups and lead scoring (the leftover net runs these) ---
_JPCACHE = {}


def note_jp(note):
    """The JP pointer a tool parked in a note. Written as
    `[EBOOT:0x1eba8e]` or bare, so the
    wording can sit anywhere in the note without breaking the parse."""
    m = re.search(r'\[([^\s\]]+:[^\s\]]+)\]', note or '')
    if m:
        return m.group(1)
    tail = (note or '').rsplit(' ', 1)
    return tail[-1] if len(tail) == 2 and ':' in tail[-1] else ''


def jp_row_at(ptr):
    """(rel, row) of the PSP-JP unit a pointer names."""
    import toolbelt
    if ':' not in ptr:
        return None, None
    name, loc = ptr.split(':', 1)
    rel = toolbelt.psp_rel(name)
    # the pointer's spelling is the porters': compare positions, not strings
    loc = toolbelt.psp_loc(loc.strip())
    if (rel, loc) not in _JPCACHE:
        _JPCACHE[(rel, loc)] = next(
            (r for r in toolbelt.read_extracted('psp_jp', rel, optional=True)
             if toolbelt.psp_loc(r['pos']) == loc), None)
    return rel, _JPCACHE[(rel, loc)]


def twin_of(crel, row):
    """The PSP-US row of a matched PSP-JP row, or None where nobody proved
    the twin (never guessed)."""
    if crel is None or row is None:
        return None
    t = us_twin(crel, row)
    return t if t is not None and t['text'].strip() else None


def same_psx_text(ja):
    """The one machine wording already built for this exact PSX Japanese
    text, or ''.

    A same-text bridge, not a JP<->US guess: a fixed one-line table row
    whose Japanese is byte-for-byte another row that already has generated
    English may reuse that wording. Only rows with an empty `psp` are used
    as sources: a row with a JP<->US pointer may itself be a mispaired
    port (the known `Toufei` case), and a same-text bridge must not
    launder that. Ambiguous text is refused."""
    import toolbelt
    if same_psx_text.cache is None:
        import collections
        found = collections.defaultdict(set)
        for crel in toolbelt.psx_rels():
            psx = toolbelt.psx_text_of(crel)
            for g in toolbelt.read_generated(crel, optional=True):
                if (not (g.get('en') or '').strip()
                        or (g.get('psp') or '').strip()):
                    continue
                jt = psx.get(g['pos'])
                if jt:
                    found[jt].add(g['en'])
        same_psx_text.cache = {k: next(iter(v)) for k, v in found.items()
                               if len(v) == 1}
    return same_psx_text.cache.get(ja, '')


same_psx_text.cache = None


def _covered(psx_key, psp_key):
    """The fraction of `psx_key` that `psp_key` accounts for."""
    import difflib
    if not psx_key or not psp_key:
        return 0.0
    sm = difflib.SequenceMatcher(None, psx_key, psp_key)
    covered = sum(block.size for block in sm.get_matching_blocks())
    return covered / len(psx_key)


def lead_coverage(ja, jp):
    """How much of the PSX box the matched Japanese candidate accounts for.
    1.0 means the candidate covers every comparable character in the box.
    The number says how much of the box a slot join or a similarity search
    actually explains; a lead never prints the US twin."""
    return _covered(bare(ja, psx=True), bare(jp))
# the PSX twin of a nameplate: the speaker written INLINE before a
# full-width colon (麻希：かわいくない！). Same framing, other build.
_INLINE_NAME = re.compile(r'^[^：。<>\[\]\s]{1,12}：')
# punctuation is not wording - dropped from the match key only
_PUNCT = {ord(c): None for c in '。．.!！？?…~、,，;；:：・·'}  


# The PSX spells a name insert as the code PLUS the member id; the PSP
# spells the same insert with no parameter at all
# (docs/TEXT_LAYOUT_SPEC.md, "Name inserts"). A PSX insert's parameter is
# never text - decoded, it arrives as the character the id happens to be,
# so '<FF07>あ' decodes to a stray あ that no PSP row can carry. Where a
# PSX name insert sits mid-line, the leftover character alone is what made
# an otherwise identical line score as a lead.
PSX_NAME_INSERT = frozenset((0x07, 0x08, 0x0F, 0x10))


def strip_params(s, psx=False):
    """Drop each control code's PARAMETER units along with the code.

    `<FF05>` consumes the next unit (codec.E_PARAM_UNITS) - a result index,
    a width, a number - and talktl spells it `<FFFD>#`: it is never text.
    Decoded, it arrives as an ordinary character ('逃げのびた。<FF05>で' ends
    in a stray で belonging to the code), and leaving it in the key is what
    made the same line score as a lead.

    `psx` says the string is a PSX line, where a name insert takes one
    parameter unit (PSX_NAME_INSERT). The PSP's insert has none, so the
    unit is only eaten on the PSX side: eating the character after a PSP
    insert would delete real wording ('<FF0F>の' is a name plus its
    particle)."""
    import codec
    out, drop, i = [], 0, 0
    while i < len(s):
        m = TOK_RE.match(s, i)
        if m:
            code = m.group(0)
            out.append(code)
            if code.startswith('<') and len(code) == 6:
                op = int(code[3:5], 16)
                drop += codec.E_PARAM_UNITS.get(op, 0)
                if psx and op in PSX_NAME_INSERT:
                    drop += 1
            elif drop and code.startswith('<') and len(code) == 4:
                # a parameter byte the page has no glyph for arrives
                # undecoded as '<XX>': it IS the unit being dropped, so it
                # must not eat the next real character ('<FF0F><01>まだ'
                # keyed as 'だ').
                drop -= 1
            i = m.end()
            continue
        if drop:
            drop -= 1
        else:
            out.append(s[i])
        i += 1
    return ''.join(out)


def bare(s, psx=False):
    """The comparable part of a unit: codes and undecoded code points
    gone, NFKC, whitespace gone. What is left is what two builds of the
    same line can be expected to share.

    A leading SPEAKER TAG goes too. The PSP frames a line as
    `<FF1B>イゴール<FF03>` (portrait + name) or `[004f]NMan's voice<FF03>`
    (nameplate icon + name); the PSX writes the same line bare or inline.
    It is UI framing the two builds disagree about by construction, and
    dropping it is deterministic - the same words either way - so a line
    that IS the same line stops looking like a lead.

    `psx` marks a PSX line: its name inserts carry a parameter unit, the
    PSP's carry none (strip_params)."""
    s = _SPEAKER.sub('', s or '')
    s = _INLINE_NAME.sub('', s)
    s = strip_params(s, psx)
    s = TOK_RE.sub('', s)
    s = ''.join(c for c in unicodedata.normalize('NFKC', s)
                if not c.isspace())
    # punctuation is not wording: one build writes 相性が合わず、発動できません
    # and the other 相性が合わず　発動できません - the words are identical.
    # The match key drops it everywhere; the wording itself is never touched.
    return s.translate(_PUNCT) if s else s


def dialogue_key(text, psx=False):
    """Comparable dialogue wording, never a rewrite of stored text.

    A repeated authored-page speaker is furniture just like the first one.
    Strip it only at a box/page head, not arbitrary inline portrait codes.
    Quote styles differ between the two Japanese releases.

    `psx` is `bare`'s: a PSX line's name inserts carry the member id unit
    (`<FF07>あ`, the extracted shape of the player's name), the PSP's
    spelling of the same insert carries none. Without it every dialogue
    line that names the player keys differently on the two sides and can
    never pair.
    """
    text = re.sub(r'(^\s*|(?<=<FF04>)\s*)<FF1B>[^<>]+<FF03>', '', text or '')
    text = text.translate({ord(c): None for c in '「」『』"“”'})
    return norm(text, psx)


def norm(s, psx=False):
    """The match key: `bare` with kana folded, so a hiragana label and its
    katakana twin are the same key. `psx` is `bare`'s: a PSX line's name
    inserts carry the member id, the PSP's do not."""
    return ''.join(_KANA.get(c, c) for c in bare(s, psx))


def needle_len(k):
    """How big a fragment to search for: the standard size, shrunk to fit
    a short string so 'くちさけ' still has a needle at all."""
    return min(NEEDLE, max(2, len(k) - 1))


_INDEX = {}


def index():
    """[(rel, row, key)] of every PSP-JP row, plus the needle -> rows
    postings. Built once per process. Every row with language in it is
    indexed: a short row is exactly the row a demon name has to match, so
    length may size the needle but may never keep a row out."""
    if not _INDEX:
        corpus = []
        for rel in _rels('psp_jp'):
            for r in toolbelt.read_extracted('psp_jp', rel):
                k = norm(r['text'])
                if len(k) >= 2:
                    corpus.append((rel, r, k))
        post = defaultdict(set)
        for i, (_rel, _r, k) in enumerate(corpus):
            for n in {3, needle_len(k)}:
                for g in {k[j:j + n] for j in range(len(k) - n + 1)}:
                    post[g].add(i)
        _INDEX['rows'] = corpus
        _INDEX['post'] = post
        _INDEX['df'] = {g: len(v) for g, v in post.items()}
    return _INDEX


def _rels(region):
    """The extracted rels of one region ('EBOOT', 'pack/E0', ...)."""
    base = os.path.join(toolbelt.EXTRACTED, region)
    out = []
    for dirpath, _dirs, files in os.walk(base):
        for f in sorted(files):
            if f.endswith('.tsv'):
                out.append(os.path.relpath(os.path.join(dirpath, f),
                                           base)[:-4].replace(os.sep, '/'))
    return sorted(out)


def tier(psx_text, psp_text):
    """port_common's strength for one pair: 'exact', 'canonical' or 'lead'.
    Only the first two may ever become generated output. The PSX side's
    key drops its name-insert parameters; the PSP side has none."""
    a, b = bare(psx_text, psx=True), bare(psp_text)
    if not a or not b:
        return 'lead'
    if a == b:
        return 'exact'
    if canonical_ja(a) == canonical_ja(b):
        return 'canonical'
    return 'lead'


SAME_LINE = 0.7                 # lead_coverage above this: one line, reworded


def same_line(ja, jp):
    """Do these two Japanese units say the same line?

    The two tests the matching already owns: `tier` for the same words, and
    `lead_coverage` for a line one build reworded or shortened (the PSP drops
    a clause, the PSX keeps it). Below that they are DIFFERENT lines - and a
    row built from a different line is a row showing another box's wording.
    """
    if tier(ja, jp) in ('exact', 'canonical'):
        return True
    a, b = bare(ja, psx=True), bare(jp)
    return _covered(a, b) >= SAME_LINE or _covered(b, a) >= SAME_LINE


def _entry_box_counts(rows):
    c = collections.defaultdict(set)
    for r in rows:
        c[r['entry']].add(r['box'])
    return {k: len(v) for k, v in c.items()}


def coordinate_join(rel):
    """Is (entry, box) a real shared coordinate for this extract AS A WHOLE?

    The PSP keeps a script's slots across regions, so within one entry the
    box index is the correspondence. This test asks the stricter question -
    whether EVERY entry has the same box count on both sides - and is used
    where the whole file must line up. `entry_join` is the per-entry form
    the twin lookup needs: a build that dropped a box in one entry must not
    disable the coordinate proof for every other entry.

    EBOOT is the counter case: `entry` is empty on both sides and `box` is
    a global index, so the JP scan (14,202 boxes) and the US scan (4,223)
    number unrelated rows and box 7715 means nothing across them."""
    if rel not in _JOIN:
        jp = toolbelt.read_extracted('psp_jp', rel, optional=True)
        us = toolbelt.read_extracted('psp_us', rel, optional=True)
        if not jp or not us:
            _JOIN[rel] = False
        else:
            _JOIN[rel] = (_entry_box_counts(jp) == _entry_box_counts(us))
    return _JOIN[rel]


_JOIN = {}


def entry_join(rel, entry):
    """Is (entry, box) a real shared coordinate for THIS entry?

    True where the Japanese and US builds enumerate the entry to the same
    box count: the two builds carry the same script, so equal counts mean
    the slot index is the correspondence (the same per-entry rule the
    aligner uses, align.jp_us_map). An entry whose count changed is not a
    coordinate at all, and the twin lookup falls back to the proven pair
    map."""
    if rel not in _ENTRY_JOIN:
        jp = toolbelt.read_extracted('psp_jp', rel, optional=True) or []
        us = toolbelt.read_extracted('psp_us', rel, optional=True) or []
        jb, ub = _entry_box_counts(jp), _entry_box_counts(us)
        _ENTRY_JOIN[rel] = {k for k, n in jb.items() if ub.get(k) == n}
    return entry in _ENTRY_JOIN[rel]


_ENTRY_JOIN = {}


PROVEN = frozenset(('read', 'anchor', 'grid', 'floor', 'box'))
# The pair-map methods that PROVE two rows are one unit. 'align' is
# deliberately absent: it derives pairs from table order and proves
# nothing on its own (boot_pairs/match_jp.pair_how both say so).

_BETWEEN = {}
_BETWEEN_JP = {}


# (names distinct from the module's own _KANA table and _PUNCT above)
_KANA_RE = re.compile(r'[\u3040-\u30ff]')
_KANA_LETTER = re.compile(r'[\u3041-\u3096\u30a1-\u30fa\u30fc]')
_ALIEN = re.compile(r'[\u0370-\u03ff\u0400-\u04ff\u00c0-\u00ff]')
_UNKNOWN_UNIT = re.compile(r'\[[0-9A-Fa-f]{4}\]')
_JAPANESE = re.compile(r'[\u3040-\u30ff\u4e00-\u9fff]')
_WORDS = re.compile(r'[A-Za-z]')
_CODES_RE = re.compile(r'<[0-9A-Fa-f]{2,4}>|\[[0-9a-f]{4}\]')


def jp_unit(text):
    """Is this PSP-JP extract row a TEXT unit, or decoder noise?

    The extracts hold rows nobody wrote: a region decoded as text that was
    not text ('如饗', '帋林偐宗饗'). They are not units of the message table -
    the PSP never displayed them - so they must not consume a slot in an
    order join, or every real row after them lands one off. A Japanese line
    says something in kana, or (a name, a code reading) in Latin letters.
    The kana are LETTERS: the iteration and voicing marks (ゝゞヽヾ゛゜) and
    ・ turn up all over noise ('ó諮゜繊届渙兮', '餘ヽ繊') and say nothing."""
    s = _CODES_RE.sub('', text or '')
    if _KANA_LETTER.search(s):
        return True
    if _ALIEN.search(s):
        return False        # Cyrillic, Greek, accented Latin: only noise
    # no kana: a Latin line (a name, a code reading), or a COMPLETE message
    # in kanji (a name, a place, '失敗!!') - it ends on the end code and
    # holds no unit the decoder could not read ([xxxx])
    return (len(_WORDS.findall(s)) >= 2
            or (bool(s.strip()) and (text or '').rstrip().endswith('<FF01>')
                and not _UNKNOWN_UNIT.search(text)))


def us_unit(text):
    """The same question for the PSP-US side, where the line is English.

    A US line carries no Japanese: the remade game's extractor produced the
    same noise rows ('嶝嶝竭', 'aaaaaa驚后'), and a row with kana/kanji in it
    is either that noise or a line nobody translated - neither can supply
    wording, and both would shift the join."""
    return not _JAPANESE.search(_CODES_RE.sub('', text or ''))


_ORDER = {}
_ORDER_JP = {}


# PSP BE text uses one 16-bit unit per glyph/control, including unknown units.
_PORTRAIT_UNITS = re.compile(r'<[0-9A-Fa-f]{4}>|\[[0-9A-Fa-f]{4}\]|.', re.S)
_PORTRAIT_HEAD = re.compile(r'^\s*<FF1B>[^<>]+<FF03>')


def _portrait_records(rows):
    """Maximal complete portrait records and invalid overlapping spans.

    Opposite-endian and page-suffix extracts are not additional messages.
    A contained portrait is discarded ONLY if its physical units equal the
    owner's suffix. Crossing or inconsistent overlaps invalidate both spans.
    """
    records, bad = [], []
    for row in rows:
        text = row['text']
        if not _PORTRAIT_HEAD.match(text):
            continue
        units = _PORTRAIT_UNITS.findall(text)
        start = int(row['pos'], 16)
        end = start + 2 * len(units)
        if not units or units[-1] != '<FF01>' or units.count('<FF01>') != 1:
            bad.append((start, end))
            continue
        records.append((start, end, row, units))
    maximal = []
    for rec in sorted(records, key=lambda r: (r[0], -r[1])):
        a, b, row, units = rec
        if maximal and a < maximal[-1][1]:
            x, y, _owner, whole = maximal[-1]
            if b == y and (a - x) % 2 == 0 and whole[(a - x) // 2:] == units:
                continue
            bad.append((x, max(y, b)))
        maximal.append(rec)
    return maximal, bad


def _portrait_signature(text):
    """Every page's speaker plus controls, retaining meaningful parameters.

    Line geometry and protagonist name spelling/omission differ by language.
    They are ignored ONLY for pairing. All other controls and parameter units
    must agree, including choices, pauses and page/end markers.
    """
    import codec
    speakers = []
    for page in text.split('<FF04>'):
        head = _PORTRAIT_HEAD.match(page)
        if not head:
            return None
        speakers.append(re.search(r'<FF1B>([^<>]+)<FF03>', head.group()).group(1))
        if '<FF1B>' in page[head.end():]:
            return None
    units = _PORTRAIT_UNITS.findall(text)
    controls, i = [], 0
    while i < len(units):
        unit = units[i]
        i += 1
        if not re.fullmatch(r'<FF[0-9A-F]{2}>', unit):
            # Unknown numeric units cannot safely be dismissed as prose.
            if unit.startswith(('<', '[')):
                return None
            continue
        code = int(unit[3:5], 16)
        if code in (3, 7, 8, 15, 16):
            continue
        controls.append(unit)
        count = codec.E_PARAM_UNITS.get(code, 0)
        if i + count > len(units):
            return None
        controls.extend(units[i:i + count])
        i += count
    return tuple(speakers), tuple(controls)


def _portrait_gap_pairs(anchors, jp_rows, us_rows):
    """Whole EBOOT gaps proved by complete units, speakers and controls.

    Speaker correspondences come solely from independently PROVEN anchors.
    No align votes, local skips, fuzzy wording, or typed name mappings enter.
    """
    jr, jbad = _portrait_records(jp_rows)
    ur, ubad = _portrait_records(us_rows)

    def owner(records, at):
        # Canonicalize an interior/padded anchor to the full portrait unit.
        hits = [r for r in records if r[0] <= at < r[1]]
        return hits[0] if len(hits) == 1 else None

    names = defaultdict(set)
    for a, b in anchors:
        x, y = owner(jr, a), owner(ur, b)
        if x is None or y is None:
            continue
        sx, sy = _portrait_signature(x[2]['text']), _portrait_signature(y[2]['text'])
        if sx and sy and sx[1] == sy[1] and len(sx[0]) == len(sy[0]):
            for ja, en in zip(sx[0], sy[0]):
                names[ja].add(en)
    names = {ja: next(iter(en)) for ja, en in names.items() if len(en) == 1}
    # Both directions must be unique: a collapsed identity is not a speaker proof.
    counts = collections.Counter(names.values())
    names = {ja: en for ja, en in names.items() if counts[en] == 1}
    canonical = sorted(set((owner(jr, a)[0] if owner(jr, a) else a,
                            owner(ur, b)[0] if owner(ur, b) else b)
                           for a, b in anchors))
    # Conflicting independent anchors cannot define a safe table order.
    if (len({a for a, _b in canonical}) != len(canonical)
            or len({b for _a, b in canonical}) != len(canonical)):
        return {}
    out = {}
    for (a0, b0), (a1, b1) in zip(canonical, canonical[1:]):
        if a1 <= a0 or b1 <= b0:
            continue
        if (any(a < a1 and b > a0 for a, b in jbad)
                or any(a < b1 and b > b0 for a, b in ubad)):
            continue
        ga = [r for r in jr if a0 < r[0] < a1]
        gb = [r for r in ur if b0 < r[0] < b1]
        # Nonportrait linguistic units may be genuine inserted records, not noise.
        def uncovered(rows, records, lo, hi, is_unit):
            return any(lo < int(r['pos'], 16) < hi and is_unit(r['text'])
                       and not any(a <= int(r['pos'], 16) < b for a, b, *_ in records)
                       for r in rows)
        if (not ga or len(ga) != len(gb)
                or uncovered(jp_rows, jr, a0, a1, jp_unit)
                or uncovered(us_rows, ur, b0, b1, us_unit)):
            continue
        pairs = {}
        for x, y in zip(ga, gb):
            sx, sy = _portrait_signature(x[2]['text']), _portrait_signature(y[2]['text'])
            if (not sx or not sy or sx[1] != sy[1]
                    or tuple(names.get(s) for s in sx[0]) != sy[0]):
                break
            pairs[x[2]['pos']] = y[2]['pos']
        else:
            out.update(pairs)
    return out


_SPEAKER_HEAD = re.compile(r'^\s*<FF1B>([^<>]+)<FF03>')


def _speaker(text):
    m = _SPEAKER_HEAD.match(text or '')
    return m.group(1).strip() if m else None


def _speaker_map(rel):
    """{JP speaker label -> US speaker label}, learned from the PROVEN pairs
    only: a label pairs when at least 4 proven pairs show it and 90% of
    them agree. The PSP frames dialogue as <FF1B>name<FF03>; the skeleton
    ignores that portrait code, so two lines with the same codes but
    different speakers would otherwise look alike to an order join."""
    if rel in _SPEAKERS:
        return _SPEAKERS[rel]
    seen = defaultdict(collections.Counter)
    ja = jp_by_pos(rel)
    for jp_pos, us_pos in (_between(rel) or ((), (), ()))[0]:
        j = ja.get(f'{jp_pos:#x}')
        u = _us_row_at(rel, f'{us_pos:#x}')   # a pair offset may sit inside the unit
        sj, su = _speaker((j or {}).get('text')), _speaker((u or {}).get('text'))
        if sj and su:
            seen[sj][su] += 1
    out = {}
    for sj, c in seen.items():
        su, n = c.most_common(1)[0]
        if sum(c.values()) >= 4 and n >= 0.9 * sum(c.values()):
            out[sj] = su
    _SPEAKERS[rel] = out
    return out


_SPEAKERS = {}


def _same_unit(ta, tb, speakers):
    """Can these two units be one message? Both or neither are speaker
    lines, both or neither are narration (＞), and a JP speaker the proven
    pairs map contradicts is a different line."""
    sa, sb = _speaker(ta), _speaker(tb)
    if (sa is None) != (sb is None):
        return False
    # narration is framed the same way in both builds: a leading ＞
    if (ta or '').lstrip().startswith('＞') != (tb or '').lstrip().startswith('＞'):
        return False
    return sa is None or sa not in speakers or speakers[sa] == sb


def _gaps(anchors):
    """The anchor pairs that bound one stretch of the same messages in both
    builds: two proven pairs adjacent in JP order whose US offsets also
    rise, AND two adjacent in US order whose JP offsets also rise - the US
    executable moved some text blocks, so the pairs that bound a moved
    block are neighbours in US order only. Such a US-order stretch is used
    only when no other proven pair lies inside it on BOTH sides; a pair with
    one side inside and its partner elsewhere is moved material, and the
    landmark join's own checks keep it from pairing. The JP-order
    stretches are the join's original gaps, unchanged."""
    jp_sorted = sorted(anchors)
    us_sorted = sorted(anchors, key=lambda ab: ab[1])
    out = []
    for seq in (jp_sorted, us_sorted):
        for lo, hi in zip(seq, seq[1:]):
            (a0, b0), (a1, b1) = lo, hi
            if not (a0 < a1 and b0 < b1):
                continue
            # an anchor inside one interval whose partner lies OUTSIDE the
            # other is material the other build moved elsewhere: it does not
            # contradict the stretch. One whose partner is inside both is a
            # pair this stretch would have to split at - not a US-order gap.
            crossing = any(a0 < a < a1 and b0 < b < b1 for a, b in anchors)
            if seq is us_sorted and crossing:
                continue
            if (lo, hi) not in out:
                out.append((lo, hi))
    return out


def _join_codes(text):
    """The control codes two builds of one message must share, for the
    order join: boot_pairs.skeleton without the line break (FF03). English
    re-wraps a line, so where one build breaks it is layout, not identity;
    the waits, pages, end code, name inserts and parameters stay."""
    import boot_pairs
    return tuple(c for c in boot_pairs.skeleton(text)[0] if c != 0xFF03)


def _landmark_join(ga, gb, sa, sb, ok=lambda p, q: True):
    """{JP pos: US pos} for one gap between two proven pairs.

    The strict rule first: both sides hold the same number of units and
    every pair carries the same control codes - the whole gap pairs by
    order. When it does not (a build cut or added a record, or decoder noise
    survived on one side), the gap is NOT paired by order across the break.
    Instead it is split at LANDMARKS: a unit whose code skeleton occurs
    exactly once among this gap's units on each side, and carries a real
    code (not only the end code), is the same message in both builds; the
    landmarks must also stand in the same order on both sides (any that
    cross are dropped). Each stretch between two landmarks is a smaller gap
    and gets the same treatment, so the strict rule still decides every
    pair. A stretch of uniform lines with a record missing on one side stays
    unpaired - its break cannot be located, so nothing in it is guessed."""
    if not ga or not gb:
        return {}
    if len(ga) == len(gb) and all(sa[p] == sb[q] and ok(p, q)
                                  for p, q in zip(ga, gb)):
        return dict(zip(ga, gb))
    ca = collections.Counter(sa[p] for p in ga)
    cb = collections.Counter(sb[q] for q in gb)
    where_b = {sb[q]: j for j, q in enumerate(gb)}
    marks = [(i, where_b[sa[p]]) for i, p in enumerate(ga)
             if ca[sa[p]] == 1 and cb.get(sa[p]) == 1
             and any(c >= 0xFF00 and c != 0xFF01 for c in sa[p])]
    marks = [(i, j) for i, j in marks if ok(ga[i], gb[j])]
    # keep only landmarks every other landmark agrees with on order
    marks = [(i, j) for i, j in marks
             if all((i < i2) == (j < j2) for i2, j2 in marks if i2 != i)]
    if not marks:
        return {}
    out = {}
    lo_a = lo_b = 0
    for i, j in marks + [(len(ga), len(gb))]:
        sub_a, sub_b = ga[lo_a:i], gb[lo_b:j]
        if (sub_a or sub_b) and (len(sub_a), len(sub_b)) != (len(ga), len(gb)):
            out.update(_landmark_join(sub_a, sub_b, sa, sb, ok))
        if i < len(ga):
            out[ga[i]] = gb[j]
        lo_a, lo_b = i + 1, j + 1
    return out


def _walk_join(ga, gb, sa, sb, ok, paired):
    """{JP pos: US pos} for units the bounded join left open, by LOCKSTEP.

    From every pair that is already known - the gap's two proven ends and
    the pairs the bounded join made - walk forward on both sides one unit at
    a time, and from the next known pair walk backward, while each step is
    the same kind of unit with the same codes (`ok`, `sa`/`sb`); a walk stops
    at its first mismatch or at a unit already paired. A unit both walks
    reach is kept when they agree. A unit only one walk reaches is kept only
    when the opposite walk stopped on a MISMATCH before it - the builds
    really diverge there (one runs on with other material). Had it stopped
    on a paired unit or the gap's end, the two walks simply did not meet:
    a line one build cut leaves exactly that, and nothing there is taken. Only complete MESSAGES walk (the
    end code FF01 on both): a name, a list item or a record whose header
    bytes decode as a code says nothing about which line it is, so only the
    bounded join may pair it."""
    ia = {p: i for i, p in enumerate(ga)}
    ib = {q: j for j, q in enumerate(gb)}
    known = sorted((ia[p], ib[q]) for p, q in paired.items())
    used_a = {i for i, _j in known}
    used_b = {j for _i, j in known}

    def walk(seeds, step):
        """{i: j} walked, and {i: why the walk that would reach i stopped}"""
        got, stop = {}, {}
        for i, j in seeds:
            i, j = i + step, j + step
            while 0 <= i < len(ga) and 0 <= j < len(gb):
                if i in used_a or j in used_b:
                    why = 'blocked'
                    break
                if not (0xFF01 in sa[ga[i]] and sa[ga[i]] == sb[gb[j]]
                        and ok(ga[i], gb[j])):
                    why = 'mismatch'
                    break
                got.setdefault(i, j)
                i, j = i + step, j + step
            else:
                why = 'blocked'
            # every JP unit this walk did not reach, up to the next known
            # pair, learns why it was not reached
            while 0 <= i < len(ga) and i not in used_a:
                stop.setdefault(i, why)
                i += step
        return got, stop

    fwd, fstop = walk([(-1, -1)] + known, 1)
    bwd, bstop = walk(known + [(len(ga), len(gb))], -1)
    out, taken = {}, set()
    for i in sorted(set(fwd) | set(bwd)):
        if i in fwd and i in bwd:
            if fwd[i] != bwd[i]:
                continue                   # the two walks disagree here
            j = fwd[i]
        elif i in fwd and bstop.get(i) == 'mismatch':
            j = fwd[i]                     # the other build diverged below
        elif i in bwd and fstop.get(i) == 'mismatch':
            j = bwd[i]                     # ... or above
        else:
            continue
        if j in taken:
            continue
        taken.add(j)
        out[ga[i]] = gb[j]
    return out


def _rereads(rows):
    """Positions of rows that are another row's bytes read again.

    The extractor starts a row at every referenced offset, and the PSP
    references each page of a portrait record as well as the record: so
    `<FF1B>Maki<FF03>A<FF04><FF1B>Maki<FF03>B<FF01>` also comes out as
    `Maki<FF03>A<FF04>` and `Maki<FF03>B<FF01>` at offsets inside it. A row
    that starts inside an earlier row and whose units are exactly that
    row's units at the same place is no message of its own (one unit = two
    bytes)."""
    spans = []
    for r in rows:
        units = _PORTRAIT_UNITS.findall(r['text'])
        start = int(r['pos'], 16)
        spans.append((start, start + 2 * len(units), r['pos'], units))
    spans.sort(key=lambda s: (s[0], -s[1]))
    out, open_ = set(), []
    for a, b, pos, units in spans:
        open_ = [s for s in open_ if s[1] > a]
        for x, y, _p, whole in open_:
            k = (a - x) // 2
            if b <= y and (a - x) % 2 == 0 and whole[k:k + len(units)] == units:
                out.add(pos)
                break
        else:
            open_.append((a, b, pos, units))
    return out


def _end_walk(ga, gb, sa, sb, ok):
    """{JP pos: US pos} walked in lockstep from a proven pair on a side with no
    gap (the file's open end, or a block the US moved), `ga`/`gb` ordered
    away from that pair. Same steps as _walk_join; there is no opposite
    walk to cross-check, so the run is kept only when it ENDS ON A MISMATCH
    - the builds visibly diverge there. A walk that runs off either side
    proves nothing about where the two lists part, and pairs nothing."""
    out = {}
    for p, q in zip(ga, gb):
        if not (0xFF01 in sa[p] and sa[p] == sb[q] and ok(p, q)):
            return out
        out[p] = q
    return {}


def _order_pairs(rel):
    """{JP pos: US pos} - the rows the pair map leaves out, paired by ORDER.

    Between two pairs the map PROVED, the two builds list the same messages
    in the same sequence, so the rows in between pair by order once each
    side's decoder noise is dropped (jp_unit/us_unit) and so is a row that
    re-reads another's bytes (_rereads). The join is taken
    whole or not at all: every pair in the gap must also carry the same
    control-code sequence (boot_pairs.skeleton's code part - the lengths
    differ by language), so a single row the noise rule got wrong makes the
    whole gap refuse instead of quietly shifting every line after it. That
    gate is what makes this stronger than 'align' (which proves nothing on
    its own) and it is why a gap with unequal unit counts is refused
    outright: an inserted or cut record cannot be located without content
    the two languages share."""
    if rel in _ORDER:
        return _ORDER[rel]
    out = {}
    got = _between(rel)
    if got:
        import boot_pairs
        anchors, jp_rows, us_rows = got
        ja, us = jp_by_pos(rel), us_by_pos(rel)
        speakers = _speaker_map(rel)
        again_a, again_b = _rereads(ja.values()), _rereads(us.values())
        jp_o = [o for o, _p in jp_rows]
        us_o = [o for o, _p in us_rows]
        for (a0, b0), (a1, b1) in _gaps(anchors):
            lo, hi = bisect.bisect_right(jp_o, a0), bisect.bisect_left(jp_o, a1)
            ga = [p for _o, p in jp_rows[lo:hi]
                  if p in ja and p not in again_a and jp_unit(ja[p]['text'])]
            lo, hi = bisect.bisect_right(us_o, b0), bisect.bisect_left(us_o, b1)
            gb = [p for _o, p in us_rows[lo:hi]
                  if p in us and p not in again_b and us_unit(us[p]['text'])]
            sa = {p: _join_codes(ja[p]['text']) for p in ga}
            sb = {q: _join_codes(us[q]['text']) for q in gb}
            same = (lambda p, q:
                    _same_unit(ja[p]['text'], us[q]['text'], speakers))
            bounded = _landmark_join(ga, gb, sa, sb, same)
            out.update(bounded)
            out.update(_walk_join(ga, gb, sa, sb, same, bounded))
        # THE OPEN SIDES: a proven pair with no gap on one side - past the
        # last pair in JP order or before the first, or where the next pair
        # in JP order lies the other way in US order (a block the US moved).
        # Each side is bounded by its own next proven pair.
        if anchors:
            jp_sorted = sorted(a for a, _b in anchors)
            us_sorted = sorted(b for _a, b in anchors)
            has_gap = set()
            for lo, hi in _gaps(anchors):
                has_gap.add((lo, 1))
                has_gap.add((hi, -1))

            def nxt(seq, x, away):
                k = (bisect.bisect_right(seq, x) if away > 0
                     else bisect.bisect_left(seq, x) - 1)
                return seq[k] if 0 <= k < len(seq) else (1 << 62) * away

            for (a0, b0) in anchors:
                for away in (1, -1):
                    if ((a0, b0), away) in has_gap:
                        continue
                    a_far, b_far = nxt(jp_sorted, a0, away), nxt(us_sorted, b0, away)
                    ga = [p for o, p in jp_rows
                          if (o - a0) * away > 0 and (a_far - o) * away > 0
                          and p in ja and p not in again_a
                          and jp_unit(ja[p]['text'])]
                    gb = [q for o, q in us_rows
                          if (o - b0) * away > 0 and (b_far - o) * away > 0
                          and q in us and q not in again_b
                          and us_unit(us[q]['text'])]
                    if away < 0:
                        ga, gb = ga[::-1], gb[::-1]
                    sa = {p: _join_codes(ja[p]['text']) for p in ga}
                    sb = {q: _join_codes(us[q]['text']) for q in gb}
                    same = (lambda p, q:
                            _same_unit(ja[p]['text'], us[q]['text'], speakers))
                    for p, q in _end_walk(ga, gb, sa, sb, same).items():
                        out.setdefault(p, q)
    if rel == 'EBOOT' and got:
        # Additional proof for full portrait records; strict joins above retain
        # their behavior. Never overwrite a strict result with a disagreement.
        extra = _portrait_gap_pairs(anchors, list(ja.values()), list(us.values()))
        out.update((p, q) for p, q in extra.items() if p not in out)
    _ORDER[rel] = out
    return out


def _order_jp(rel, us_pos):
    """The JP twin of a US row, by the same whole-gap join."""
    if rel not in _ORDER_JP:
        _ORDER_JP[rel] = {u: j for j, u in _order_pairs(rel).items()}
    return _ORDER_JP[rel].get(us_pos)


def _between_jp_row(rel, us_pos):
    """The JP row behind a US row whose pair only the between-anchors
    order join proves - the same join, walked from the US side (a worker
    process that never ran the forward join still needs the Japanese
    twin, and the anchors are in the map either way)."""
    me = _us_row_pos(rel, us_pos)          # a pointer may name a byte inside
    if me is None:
        return None
    hit = _order_jp(rel, me)
    return jp_by_pos(rel).get(hit) if hit else None


def _between(rel):
    """(anchors, jp_rows, us_rows) for the order join, or None when this
    rel cannot take one: the PROVEN pairs as (jp offset, us offset), and
    both builds' rows as (offset, pos) in table order."""
    if rel in _BETWEEN:
        return _BETWEEN[rel]
    pairs = []
    for line in open(os.path.join(toolbelt.MAPPINGS, 'psp_pairs.tsv'),
                     encoding='utf-8').read().splitlines()[1:]:
        f = line.split('\t')
        if (len(f) >= 4 and f[0] == toolbelt.psp_name(rel)
                and set(f[3].split(',')) & PROVEN):
            try:
                pairs.append((int(f[2], 16), int(f[1], 16)))
            except (TypeError, ValueError):
                # this rel keys its positions some other way
                # (entry:offset): the order join does not apply
                _BETWEEN[rel] = None
                return None
    try:
        anchors = sorted(pairs)
        jp_rows = sorted((int(r['pos'], 16), r['pos']) for r in
                         toolbelt.read_extracted('psp_jp', rel))
        us_rows = sorted((int(r['pos'], 16), r['pos']) for r in
                         toolbelt.read_extracted('psp_us', rel))
    except (TypeError, ValueError):
        _BETWEEN[rel] = None
        return None
    _BETWEEN[rel] = (anchors, jp_rows, us_rows)
    return _BETWEEN[rel]


def gap_pairs(anchors, rows_a, rows_b, me):
    """[(pos a, pos b)] of the rows between the proven pair that straddles
    `me` on side A, paired by ORDER with side B's rows in the same gap.

    Only when both gaps hold the same number of rows: a cut record or an
    added one makes the two sides drift, and then the gap pairs nothing -
    the anchors outside it are untouched, so a table that drifts by a line
    still joins. This is align's idea bounded by anchors that were earned
    (align alone proves nothing: see us_twin)."""
    below = [(a, b) for a, b in anchors if a < me]
    above = [(a, b) for a, b in anchors if a > me]
    if not below or not above:
        return []
    (a0, b0), (a1, b1) = below[-1], above[0]
    ga = [p for o, p in rows_a if a0 < o < a1]
    gb = [p for o, p in rows_b if b0 < o < b1]
    if not ga or len(ga) != len(gb):
        return []
    return list(zip(ga, gb))


def between_us_twin(rel, row):
    """The US twin of a JP row whose pairing no method proved: the two
    builds keep the same table SEQUENCE, so between two rows whose pair
    IS proven, the rows in between pair by order (gap_pairs)."""
    try:
        int(row['pos'], 16)
    except (TypeError, ValueError):
        return None
    hit = _order_pairs(rel).get(row['pos'])
    if not hit:
        return None
    us = us_by_pos(rel).get(hit)
    if us is not None:
        # remember the pair so the three-text rules can read this row's
        # Japanese twin (jp_text_of_us) without a pair-map row
        _BETWEEN_JP[(rel, hit)] = row
    return us


def us_twin(rel, row):
    """The PSP-US row of a PSP-JP row - never guessed: same (entry, box)
    where that is a shared coordinate, the verified pair map
    (translation/generated_mappings/psp_pairs.tsv) where a matcher proved the twin, and
    nothing at all where nobody did.

    A pair-map offset may name a byte INSIDE the US unit, not its first
    decoded byte (boot_pairs.covering: pointers are table addresses, the
    extractor keys rows by the start of their text). Resolve it the same
    way the boot-table porters do. align.tsv is deliberately NOT used
    here: it aligns each side to the PSX, and a shifted box can make two
    different JP boxes share one US partner; that is not a proof that
    either JP row's WORDS are that US row's words."""
    if entry_join(rel, row['entry']):
        hit = _us_by_coord(rel).get((row['entry'], row['box']))
        if hit is not None:
            return hit
    other = _pairs().get(row['pos'])
    # A pair the methods merely DERIVED is not a twin. boot_pairs votes
    # with proofs - a reader's confirmation, an exact-text anchor, the
    # verified slot grid, the floor skeleton, a shared (entry, box) - and
    # with 'align', which proves nothing on its own (its own docstring
    # says so). Taking an align-only pair is exactly how one unit's
    # wording reached another unit's box: the two builds' rows do not line
    # up where their tables drift, and only a proof says these are one
    # unit. Anything else stays unmapped - wrong pairs are how a reader
    # sees one unit's Japanese beside another's English.
    if other and PROVEN.intersection(pair_how(row['pos']).split(',')):
        return _us_row_at(rel, other)
    # THE ORDER JOIN, between two pairs the map proved: not 'align' (which
    # pairs each side to the PSX and lets drift move a box), but the two
    # builds' own table sequence, read whole - every row of the gap paired
    # at once, both sides' decoder noise dropped first, and the gap refused
    # unless the unit counts agree AND every pair carries the same control
    # codes. A shift anywhere breaks the codes, which is what makes this a
    # proof rather than a vote (between_us_twin).
    return between_us_twin(rel, row)


def us_candidate(rel, row):
    """(US row, how) of a JP row's partner by a method that is NOT a proof.

    The pair map also holds what boot_pairs DERIVED: the message tables are
    aligned by order between proven anchors ('align'), and a family's slot
    grid names a twin whose wording the PSP reworded. That is the right
    table at the right place - which is what a WORKLIST NOTE needs, so a
    reader sees the English a row would carry - but it is not a proof, so it
    never reaches `en` (us_twin refuses it). Two lines' order is not their
    identity: the measured drift is small, not zero, and one line's English
    in another line's box is exactly the failure this project refuses."""
    if rel is None or row is None:
        return None, ''
    loc = _pairs().get(row['pos'])
    if not loc:
        return None, ''
    how = pair_how(row['pos'])
    if PROVEN.intersection(how.split(',')):
        return None, ''            # a proven twin: us_twin's business
    us = _us_row_at(rel, loc)
    return (us, how) if us is not None and (us['text'] or '').strip() else (None, '')


_US_BY_POS = {}


def us_by_pos(rel):
    if rel not in _US_BY_POS:
        _US_BY_POS[rel] = {r['pos']: r
                           for r in toolbelt.read_extracted('psp_us', rel)}
    return _US_BY_POS[rel]


_JP_BY_POS = {}


def jp_by_pos(rel):
    if rel not in _JP_BY_POS:
        _JP_BY_POS[rel] = {r['pos']: r for r in
                           toolbelt.read_extracted('psp_jp', rel, optional=True)
                           or []}
    return _JP_BY_POS[rel]


def _us_row_pos(rel, loc):
    """The offset of the US row that OWNS a locator - the row's own start,
    where the locator names a byte inside it (a table address)."""
    row = _us_row_at(rel, loc)
    if row is None:
        return None
    try:
        return int(row['pos'], 16)
    except (TypeError, ValueError):
        return None


_US_BY_COORD = {}


def _us_by_coord(rel):
    if rel not in _US_BY_COORD:
        _US_BY_COORD[rel] = {(r['entry'], r['box']): r
                             for r in toolbelt.read_extracted('psp_us', rel)}
    return _US_BY_COORD[rel]


_US_SORTED = {}


def _us_sorted(rel):
    """The US rows in table order, for the covering lookup. A rel whose
    positions are NOT offsets - a family row keys 'entry:offset' - has
    nothing to cover: those locators resolve exactly, by their own key."""
    if rel not in _US_SORTED:
        keep = []
        for r in toolbelt.read_extracted('psp_us', rel, optional=True) or []:
            try:
                keep.append((int(r['pos'], 16), r))
            except (TypeError, ValueError):
                continue
        keep.sort(key=lambda t: t[0])
        _US_SORTED[rel] = [r for _o, r in keep]
    return _US_SORTED[rel]


_JP_OF_US = {}
_US_PAIR_OFFS = {}


def _us_pair_offs():
    """([offsets], [jp pos]) of the PROVEN pairs, by US offset.

    The pair map runs jp -> us, so a US row is found through its offset -
    and that offset may name a byte INSIDE the unit (the map keys table
    addresses; the extract keys rows by the start of their text), which is
    why the caller resolves it through the covering row. An 'align' pair is
    derived, not proof, and is not here."""
    if not _US_PAIR_OFFS:
        pairs = []
        for jp_pos, us_pos in _pairs().items():
            if not PROVEN.intersection(pair_how(jp_pos).split(',')):
                continue
            try:
                pairs.append((int(us_pos, 16), jp_pos))
            except (TypeError, ValueError):
                continue
        pairs.sort()
        _US_PAIR_OFFS['offs'] = [o for o, _ in pairs]
        _US_PAIR_OFFS['jp'] = [j for _, j in pairs]
    return _US_PAIR_OFFS['offs'], _US_PAIR_OFFS['jp']


def _us_span(rel, start):
    """(start, end) of the US row that begins at `start` - the byte span
    any of the pair map's offsets for it must fall in."""
    offs = [int(r['pos'], 16) for r in _us_sorted(rel)]
    i = bisect.bisect_left(offs, start)
    end = offs[i + 1] if i + 1 < len(offs) else start + 0x1000
    return start, max(end, start + 1)


def _jp_pos_of_us(rel, loc):
    """The JP row this US locator's PROVEN pair names, or ''.

    The exact inversion first; then, like us_twin, the pair's offset
    resolved through the row that COVERS the locator - a pair may name a
    byte inside the US unit (the map keys table addresses, the extract
    keys rows by the start of their text). Only PROVEN pairs speak."""
    if rel not in _JP_OF_US:
        inv = {}
        for jp_pos, us_pos in _pairs().items():
            if not PROVEN.intersection(pair_how(jp_pos).split(',')):
                continue
            inv.setdefault(toolbelt.psp_loc(us_pos), jp_pos)
        _JP_OF_US[rel] = inv
    hit = _JP_OF_US[rel].get(loc)
    if hit:
        return hit
    start = _us_row_pos(rel, loc)
    if start is None:
        return ''
    offs, jps = _us_pair_offs()
    hits = {jps[k] for k in range(
        bisect.bisect_left(offs, start),
        bisect.bisect_left(offs, _us_span(rel, start)[1]))}
    return hits.pop() if len(hits) == 1 else ''



def jp_text_of_us(ptr):
    """The Japanese TWIN's text of a PSP-US pointer - '' when nobody
    proved the pair. The inverse of us_twin: the pair map runs jp -> us,
    so the reverse lookup is its inversion, and like us_twin it only
    trusts PROVEN pairs. This is for rules that must read all three
    texts of a unit (the box-head '>' keeps/edits by psx/jp/us)."""
    if not ptr or ':' not in ptr:
        return ''
    name, loc = ptr.split(':', 1)
    rel = toolbelt.psp_rel(name)
    if not rel:
        return ''
    # ONE spelling for a position (toolbelt.psp_loc): the pair map writes
    # 'EBOOT:0x268b08', the boot-table porters 'EBOOT:268b08', and a
    # string comparison between them finds no twin at all.
    loc = toolbelt.psp_loc(loc.strip())
    bet = _BETWEEN_JP.get((rel, loc))
    if bet is not None:
        return bet.get('text') or ''
    jr = _between_jp_row(rel, loc)
    if jr is not None:
        return jr.get('text') or ''
    jp_pos = _jp_pos_of_us(rel, loc)
    if not jp_pos:
        return ''
    for r in toolbelt.read_extracted('psp_jp', rel, optional=True):
        if toolbelt.psp_loc(r['pos']) == toolbelt.psp_loc(jp_pos):
            return r.get('text') or ''
    return ''


def _us_row_at(rel, pos):
    """The US row whose unit holds `pos`; exact first, covering otherwise."""
    hit = us_by_pos(rel).get(pos)
    if hit is not None:
        return hit
    try:
        off = int(pos, 16)
    except (TypeError, ValueError):
        return None
    import boot_pairs
    return boot_pairs.covering(_us_sorted(rel), off)


_PAIRS = {}


def _pairs():
    """{jp pos: us pos} the verified PSP-US <-> PSP-JP unit pairs
    (src/extraction_tools/matching/boot_pairs.py). Only verified pairs are
    here - where a matcher did not prove the twin there is no twin."""
    if not _PAIRS:
        path = os.path.join(toolbelt.MAPPINGS, 'psp_pairs.tsv')
        if os.path.exists(path):
            for line in open(path, encoding='utf-8').read().splitlines()[1:]:
                f = line.split('\t')
                if len(f) >= 3:
                    _PAIRS[f[2]] = f[1]
    return _PAIRS


_HOW = {}


def psx_jp_confirmed(rel, psx_pos, jp_pos):
    """Did a READER confirm that this PSX row's source is this JP row?

    This is the OTHER arrow from `pair_how`: the pair map says which US
    row a JP row's wording comes from, while this says that the JP row is
    the PSX line's source at all. Text similarity can only ever suggest
    that - a stray あ, a reworded description, a speaker tag - and a
    reader who can read both sides is what settles it.

    src/extraction_tools/matching/psx_jp_extra.tsv, the counterpart of psp_pairs_extra.
    Offsets only; the strings in its note column are commentary."""
    path = os.path.join(toolbelt.SOURCE_MAPPINGS, 'psx_jp_extra.tsv')
    if not os.path.exists(path):
        return False
    want = f'{rel}\t{psx_pos}\t{jp_ptr_key(jp_pos)}'
    for line in open(path, encoding='utf-8').read().splitlines()[1:]:
        if line.startswith(want):
            return True
    return False


def psx_jp_target(rel, psx_pos):
    """The JP row a READER said is this PSX line's source, or ''.

    Distinct from `psx_jp_confirmed`, which asks whether the reader agreed
    with a candidate somebody else produced. This returns the reader's own
    answer and it OVERRIDES the matcher: the matcher's job is to guess
    where similarity leads, and where a reader has been there the guess is
    not evidence, it is noise. A row the matcher sent to `．．．` is exactly
    the row a reader is needed for."""
    path = os.path.join(toolbelt.SOURCE_MAPPINGS, 'psx_jp_extra.tsv')
    if not os.path.exists(path):
        return ''
    want = f'{rel}\t{psx_pos}\t'
    for line in open(path, encoding='utf-8').read().splitlines()[1:]:
        if line.startswith(want):
            return line.split('\t')[2]
    return ''


def jp_ptr_key(jp_ptr):
    """'EBOOT:27d8a4' / 'EBOOT: 0x27d8a4' -> 'EBOOT:0x27d8a4' (normalised),
    so the map, the notes and a reader all name a row the same way."""
    key = (jp_ptr or '').strip()
    if ':' not in key:
        return key
    name, loc = key.split(':', 1)
    return f'{name}:{toolbelt.psp_loc(loc.strip())}'


def pair_how(jp_pos):
    """How the pair for this JP row was proved ('read', 'anchor', 'grid',
    'align', ...). A pairing a READER confirmed against both builds is
    evidence in its own right - stronger than any text-similarity tier -
    so callers may port on it even where the two Japanese strings differ
    (extraction trimming a glyph, a description reworded between builds).
    'align' is derived and proves nothing on its own."""
    if not _HOW:
        path = os.path.join(toolbelt.MAPPINGS, 'psp_pairs.tsv')
        if os.path.exists(path):
            for line in open(path, encoding='utf-8').read().splitlines()[1:]:
                f = line.split('\t')
                if len(f) >= 4:
                    _HOW[f[2]] = f[3]
    return _HOW.get(jp_pos, '')


_PSX_EXTRACT = {}
_JP_SLOTS = {}


def _psx_extract(rel):
    """{pos: row} of the PSX extract, cached."""
    if rel not in _PSX_EXTRACT:
        _PSX_EXTRACT[rel] = {r['pos']: r for r in
                             toolbelt.read_extracted('psx', rel,
                                                     optional=True) or []}
    return _PSX_EXTRACT[rel]


def psx_jp_rel(rel):
    """The PSP-JP extract that carries the same script file:
    'ADV/E1' -> 'pack/E1', 'TALK/X' -> 'pack/talk/X', 'D01/D08' ->
    'pack/dng/d08'. '' where the two builds keep no parallel file."""
    if rel.startswith('ADV/'):
        return 'pack/' + rel[4:]
    if rel.startswith('TALK/'):
        return 'pack/talk/' + rel[5:]
    m = re.fullmatch(r'D\d\d/(d[0-9a-f]{2})', rel)
    return f'pack/dng/{m.group(1)}' if m else ''


def psx_id_twin(rel, psx_pos, floor=0.35):
    """The PSP-JP row that occupies this PSX line's slot, or None.

    The PSP kept the script's slots: the same (entry, box) is the same
    line even where the PSP REWROTE it - nameplates instead of inline
    speakers, full stops, quotes - which is exactly the line whose
    similarity fails, so the shared slot is the proof and the text only
    validates. Candidates are the same slot and its +-2 neighbours (the
    build inserted and cut boxes, so a slot may drift by a line: PSX
    12/26 is the PSP's 12/27); the winner must cover `floor` of the PSX
    box (lead_coverage, the one scorer), and a slot the PSP has no row
    for pairs with nothing rather than guessing."""
    jrel = psx_jp_rel(rel)
    if not jrel:
        return None
    p = _psx_extract(rel).get(psx_pos)
    if p is None:
        return None
    jp = toolbelt.read_extracted('psp_jp', jrel, optional=True) or []
    by_slot = _JP_SLOTS.get(jrel)
    if by_slot is None:
        by_slot = _JP_SLOTS[jrel] = {(r['entry'], r['box']): r for r in jp}
    entry, box = p['entry'], p['box']
    try:
        b = int(box)
    except ValueError:
        return None
    ja = _psx_extract(rel).get(psx_pos, {}).get('text') or \
        (toolbelt.psx_text_of(rel).get(psx_pos, ''))
    best, best_cov = None, floor
    for d in (0, 1, -1, 2, -2):
        cand = by_slot.get((entry, str(b + d)))
        if cand is None:
            continue
        cov = lead_coverage(ja, cand['text'])
        if cov > best_cov:
            best, best_cov = cand, cov
    return best


# a speaker framing a box or a page (<FF04>) - the PSP repeats it per page
_PAGE_SPEAKERS = re.compile(r'(^\s*|(?<=<FF04>)\s*)<FF1B>[^<>]+<FF03>')


def exact_twins(rel, texts):
    """{key -> PSP-JP row} for PSX lines whose Japanese is EXACTLY one PSP-JP
    row of `rel` (the `bare` key: codes, spacing and punctuation are not
    wording - tier 'exact'; a speaker repeated at a page head is framing,
    and the PSX name insert's parameter unit is not text).

    `texts` is [(key, japanese)] in the PSX's own order. A line that occurs
    k times on the PSX pairs with the PSP-JP rows carrying it in order of
    occurrence, and only when the PSP has exactly k of them too: a count
    that differs means one build cut or added a copy, and then no copy is
    paired. A line with no PSP-JP row stays unpaired."""
    by_key = defaultdict(list)
    for r in sorted(toolbelt.read_extracted('psp_jp', rel),
                    key=lambda r: int(r['pos'], 16)):
        k = bare(_PAGE_SPEAKERS.sub('', r['text']))
        if len(k) >= 2:
            by_key[k].append(r)
    mine = defaultdict(list)
    for key, ja in texts:
        # a PSX name insert carries one parameter unit (etext keys it by the
        # member id); the PSP's has none - its next character is the line's
        # own (strip_params, psx)
        k = bare(_PAGE_SPEAKERS.sub('', ja or ''), psx=True)
        if len(k) >= 2:
            mine[k].append(key)
    out = {}
    for k, keys in mine.items():
        rows = by_key.get(k, ())
        if len(rows) == len(keys):
            out.update(zip(keys, rows))
    return out


def unanimous_twin(rel, ja):
    """The proven US row for a PSX line whose Japanese is exactly one or more
    PSP-JP rows of `rel` (exact_twins' key) that ALL have the same proven US
    wording - or None. Copies that agree make the occurrence count moot:
    whichever copy a slot pairs with, the wording is the same."""
    k = bare(_PAGE_SPEAKERS.sub('', ja or ''), psx=True)
    if len(k) < 2:
        return None
    rows = [r for r in toolbelt.read_extracted('psp_jp', rel)
            if bare(_PAGE_SPEAKERS.sub('', r['text'])) == k]
    us = [us_twin(rel, r) for r in rows]
    if not us or any(u is None for u in us):
        return None
    return us[0] if len({u['text'].strip() for u in us}) == 1 else None


def find(ja, want=6):
    """[(rel, row, tier, ratio)] the PSP-JP rows that carry this Japanese,
    best first. Tier is the caller's licence: 'exact' and 'canonical' may
    be ported, 'lead' may only be shown to a human."""
    idx = index()
    corpus = idx['rows']
    k = norm(ja, psx=True)
    if len(k) < 2:
        return []
    import difflib

    def ratio(i):
        return difflib.SequenceMatcher(None, k, corpus[i][2][:400],
                                       autojunk=False).ratio()

    def show(hits, floor=0.25):
        ranked = sorted(((ratio(i), i) for i in hits), reverse=True)
        out = []
        for r, i in ranked[:want]:
            if r <= floor:
                continue
            rel, row, t = corpus[i]
            out.append((rel, row, tier(ja, row['text']), r))
        return out

    sub = [i for i, (_rel, _r, t) in enumerate(corpus)
           if t and (k in t or (len(t) >= 3 and t in k))]
    if sub:
        sub.sort(key=lambda i: abs(len(corpus[i][2]) - len(k)))
        return show(sub[:200], 0.0)

    n = needle_len(k)
    df, post = idx['df'], idx['post']
    for cap, size in ((NEEDLE_RARE, n), (NEEDLE_LOOSE, n), (10 ** 9, n),
                      (10 ** 9, 3)):
        score = defaultdict(int)
        gs = {k[j:j + size] for j in range(len(k) - size + 1)}
        for g in gs:
            if 0 < df.get(g, 10 ** 9) <= cap:
                for i in post[g]:
                    score[i] += 1
        if score:
            # ties break on corpus order, not on set-iteration order: a
            # re-run must pick the same candidate (PYTHONHASHSEED aside).
            return show(sorted(score, key=lambda i: (-score[i], i))[:200])
    return []
