"""Three-way box alignment: PSX <-> PSP-JP <-> PSP-US, per entry.

The PSX paragraph and the PSP box split the same script differently, so the
structural skeleton (control-code sequence + text length) is not enough to
tell two neighbouring lines apart: repeated lines, shared epic lines and
two-speaker scenes all produce near-identical skeletons, and a build that
inserted or cut a box shifts every slot after it. That is how a PSX box
bound its neighbour's English (and portrait) while the skeleton still
matched.

Alignment is therefore text-first:

  PSX <-> PSP-JP   Needleman-Wunsch scored on the normalized Japanese
                   wording (match_jp.dialogue_key) AND the speaker label
                   (port_common.canonical_ja), with the control skeleton
                   only as a tie-breaker. The two sides are the same
                   language: their words survive the PSP's restyling
                   (nameplates, punctuation, full stops), so wording is
                   the proof. Kana folding keeps 'まーく' and 'マーク'
                   the same label.

  PSP-JP -> PSP-US PSP keeps the script's slots across regions: when an
                   entry has the same box count on both sides the index
                   is the correspondence (the US is a translation of the
                   same slot, not a re-pagination). Only a count-changed
                   entry falls back to structural NW.

                   A slot's words can still be wrong when the PSP-US table
                   repeats one box's English in another slot (PSP-US ships
                   such duplicates: E1's Agastya Tree boxes 0/1 and E2 57's
                   welcome line). When a wording repeats while the Japanese
                   differs, the local English is the copy, not the
                   translation. The real English is then the wording the
                   same Japanese line carries elsewhere in the PSP script
                   (a global identical-JP twin), recorded in the row as a
                   source pointer. A donor is only taken when every other
                   identical-JP twin carries the same wording (a one-
                   character spelling slip in the PSP-US table folded) and
                   that wording differs from the local one: the same line
                   can legitimately be translated two ways, and then there
                   is no proof to borrow.

Output: translation/generated_mappings/align.tsv
  file entry psx_box jp_box us_box kind src_file src_entry src_box
kind: ok (bound) | us_extra (PSP-US box no PSX box owns) |
      us_missing (PSX box with no PSP-US partner)
src_*: the PSP-US unit that actually supplies the English when the local
       us_box slot repeats a sibling's wording (empty otherwise).

Usage: python src/extraction_tools/matching/align.py
"""
import difflib
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import efile  # noqa: E402
import etext  # noqa: E402
import strlib  # noqa: E402
import match_jp  # noqa: E402
from text import load_psp  # noqa: E402
from codec import US_MAP, decode_box  # noqa: E402
from port_common import canonical_ja  # noqa: E402

PSX = os.path.join(ROOT, 'data', 'psx', 'ADV')
OUT = os.path.join(toolbelt.MAPPINGS, 'align.tsv')

# A duplicate-wording repair may draw its English from any PSP story file
# (E4 carries the full Velvet Room script the menu entries abbreviated).
_PSP_FILES = ('E0', 'E1', 'E2', 'E3', 'E4')
# Wording this short is too generic to call a duplicate: '...' or 'Yes.'
# recur for unrelated lines by design.
_MIN_WORDING = 6
_TWINS = None

# Speaker label: PSX writes it inline before the full-width colon; PSP frames
# it as a portrait + name pair. Both are only compared after canonical_ja.
_PSX_LABEL = re.compile(r'(?:<FF0[0-9A-F]>(?:<[0-9A-F]{2}>)?)*([^：<]{1,12})：')
_PSP_LABEL = re.compile(r'<FF1B>([^<]*)<FF03>')

# Wording is the proof, so it outweighs the structural tie-breaker. A
# contradicted speaker label is strong evidence of a different line.
_TXT_WEIGHT = 12.0
_SPK_SAME = 4.0
_SPK_CONTAINED = 2.0
_SPK_DIFFERENT = -3.0
# PSP-JP and PSP-US are a translation pair: their wording cannot be
# compared, but a speaker name can (through terms.tsv's name/who/card data).
_US_LABEL_WEIGHT = 6.0

_JPM = {}
_US_LABELS = None


def jp_map():
    if not _JPM:
        for u, ch in strlib.tsv_fields(toolbelt.PSP_GLYPHS, 2):
            _JPM[int(u, 16)] = ch
    return _JPM


def decode_jp(raw):
    return decode_box(raw, jp_map(), holes=[])


def label_psx(text):
    m = _PSX_LABEL.match(text)
    return canonical_ja(m.group(1)).replace(' ', '') if m else None


def label_psp(text):
    m = _PSP_LABEL.search(text)
    return canonical_ja(m.group(1)).replace(' ', '') if m else None


def _us_labels():
    """{canonical Japanese name: English name} for the JP->US label check.

    Built from the same terms.tsv domains the porters read; no name is
    spelled in this file. The English side is reachable both as a value
    (Yukino) and as a canonical key (already-English labels).
    """
    global _US_LABELS
    if _US_LABELS is None:
        table = {}
        for domain in ('name', 'name_extra', 'who', 'card'):
            for ja, en in strlib.glossary(domain).items():
                table.setdefault(
                    re.sub(r'[\s　]+', '', canonical_ja(ja)), en)
                table.setdefault(ja.strip(), en)
                table.setdefault(
                    re.sub(r'\s+', '', en).lower(), en)
        _US_LABELS = table
    return _US_LABELS


def label_en(label):
    """The English a JP label is known to correspond to, or None."""
    if not label:
        return None
    table = _us_labels()
    key = re.sub(r'[\s　]+', '', canonical_ja(label))
    return table.get(key)


def _norm_en(text):
    return re.sub(r'\s+', '', (text or '')).lower()


def _us_label_bonus(a, b):
    """Agreement of a translated JP label with the PSP-US label."""
    if not a or not b:
        return 0.0
    a, b = _norm_en(a), _norm_en(b)
    if a == b:
        return _US_LABEL_WEIGHT
    if a in b or b in a:
        return _US_LABEL_WEIGHT / 2
    return -_US_LABEL_WEIGHT


def controls_psx(raw):
    out = []
    i = 0
    while i + 1 < len(raw):
        c = raw[i]
        if c == 0xFF:
            out.append(raw[i + 1])
            i += 2
        elif 0x80 <= c <= 0x87:
            i += 2
        else:
            i += 1
    return tuple(out)


def controls_psp(raw):
    out = []
    i = 0
    while i + 1 <= len(raw):
        if raw[i] == 0xFF:
            out.append(raw[i + 1])
            i += 2
        else:
            i += 2
    return tuple(out)


def textlen_psx(raw):
    n = 0
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == 0xFF:
            i += 2
        elif 0x80 <= c <= 0x87:
            i += 2
            n += 1
        else:
            i += 1
            n += 1
    return n


def textlen_psp(raw):
    n = 0
    i = 0
    while i + 1 <= len(raw):
        if raw[i] == 0xFF:
            i += 2
        else:
            i += 2
            n += 1
    return n


def skel_psx(raw):
    return (controls_psx(raw), textlen_psx(raw))


def skel_psp(raw):
    return (controls_psp(raw), textlen_psp(raw))


def norm_skel(ctrls):
    """Control skeleton ignoring 1B/18 (portrait/voice, PSP-only)."""
    return tuple(c for c in ctrls if c not in (0x1B, 0x18))


def sim(a, b):
    ca, la = a
    cb, lb = b
    na, nb = norm_skel(ca), norm_skel(cb)
    s = 0
    if na == nb:
        s += 6
    else:
        # longest common subsequence-ish bonus
        matches = 0
        lb_l = list(nb)
        for x in na:
            if x in lb_l:
                matches += 1
                lb_l.remove(x)
        s += matches
        s -= abs(len(na) - len(nb))
    # length proximity (units vs glyphs; EN ~1.8x JP chars, be generous)
    ratio = (la + 1) / (lb + 1)
    if 0.3 <= ratio <= 3.5:
        s += 2
    else:
        s -= 2
    return s


def skel_ja_psx(raw):
    """PSX box for PSX<->PSP-JP matching: skeleton plus decoded Japanese."""
    text = etext.decode(raw)
    return (controls_psx(raw), textlen_psx(raw),
            match_jp.dialogue_key(text, psx=True), label_psx(text))


def skel_ja_psp(raw):
    """PSP-JP box for PSX<->PSP-JP matching."""
    text = decode_jp(raw)
    return (controls_psp(raw), textlen_psp(raw),
            match_jp.dialogue_key(text), label_psp(text))


def _ratio(a, b):
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _speaker_bonus(a, b):
    if not a or not b:
        # A label on one side and none on the other is common (PSX inline
        # name vs a PSP narration/card box); it says nothing either way.
        return 0.0
    if a == b:
        return _SPK_SAME
    if a in b or b in a:
        return _SPK_CONTAINED
    return _SPK_DIFFERENT


def sim_ja(a, b):
    """Similarity of two Japanese boxes (see module docstring). The
    structural skeleton keeps its vote, but the wording and the speaker
    decide the pair."""
    s = sim(a[:2], b[:2])
    s += _TXT_WEIGHT * _ratio(a[2], b[2])
    s += _speaker_bonus(a[3], b[3])
    return s


def skel_us_jp(raw):
    """PSP-JP box for the JP->US leg: skeleton + label in English."""
    text = decode_jp(raw)
    return (controls_psp(raw), textlen_psp(raw),
            label_en(label_psp(text)))


def skel_us_psp(raw):
    """PSP-US box for the JP->US leg: skeleton + its own label."""
    text = decode_box(raw, US_MAP, holes=[])
    return (controls_psp(raw), textlen_psp(raw), label_psp(text))


def sim_us(a, b):
    s = sim(a[:2], b[:2])
    s += _us_label_bonus(a[2], b[2])
    return s


def nw(A, B, gap=-4, sim_fn=None):
    """Pairwise Needleman-Wunsch; sim_fn overrides the box similarity
    (port_btlevt passes its battle-box variant)."""
    fn = sim_fn or sim
    n, m = len(A), len(B)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + gap
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = max(dp[i - 1][j] + gap, dp[i][j - 1] + gap,
                           dp[i - 1][j - 1] + fn(A[i - 1], B[j - 1]))
    pairs = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + fn(A[i - 1], B[j - 1]):
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + gap:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return pairs


def decode_us(raw):
    out = []
    i = 0
    while i + 1 <= len(raw):
        if raw[i] == 0xFF:
            out.append('<FF%02X>' % raw[i + 1])
            i += 2
        else:
            u = struct.unpack_from('>H', raw, i)[0]
            out.append(US_MAP.get(u, '[%04x]' % u))
            i += 2
    return ''.join(out)


def _word_len(text):
    return len(re.sub(r'[^a-z0-9]', '', text))


def us_wording(raw):
    """What a PSP-US box SAYS, ignoring its codes.

    The PSP-US table carries the JP source's choice glyph as a leftover
    (`<FF0E>` swallowed a kana as its parameter), so non-ASCII text is not
    wording. Whitespace and control markers do not change what is said;
    punctuation does ('Ms. Saeko!' is not 'Ms. Saeko...?')."""
    text = decode_box(raw, US_MAP, holes=[])
    text = re.sub(r'<[^>]*>|\[[0-9a-f]{4}\]', '', text)
    text = ''.join(ch for ch in text if ch.isascii())
    return re.sub(r'\s+', '', text).lower()


def _jp_key(raw):
    text = decode_jp(raw)
    return (match_jp.dialogue_key(text), label_psp(text))


def _global_twins():
    """{(JP wording, label): [(file, entry, box, US wording)]}.

    Every PSP story box whose Japanese wording recurs elsewhere, indexed
    across E0-E4. Only entries whose JP/US box counts agree are indexed: a
    count-changed entry's JP->US partners are structural, not proven, and a
    donor must be a proven translation of the same words. A box whose English
    repeats a sibling's while its Japanese differs is a known copy, so it is
    never indexed - otherwise the same wrong wording in two entries would
    support itself as a donor."""
    global _TWINS
    if _TWINS is None:
        idx = {}
        for f in _PSP_FILES:
            jp = load_psp(f, 'jp').entries
            us = load_psp(f, 'us').entries
            for ei in range(min(len(jp), len(us))):
                if len(jp[ei].boxes) != len(us[ei].boxes):
                    continue
                boxes = [(j, us_wording(us[ei].box_bytes(j)),
                          _jp_key(jp[ei].box_bytes(j)))
                         for j in range(len(jp[ei].boxes))]
                # A box that already repeats a sibling's wording is a known
                # copy. Its English is not this line's translation, so it is
                # never evidence - and the wrong wording recurs in another
                # entry by construction.
                copies = _duplicate_copy_boxes(boxes)
                for j, ink, key in boxes:
                    if j in copies or _word_len(ink) < _MIN_WORDING:
                        continue
                    idx.setdefault(key, []).append((f, ei, j, ink))
        _TWINS = idx
    return _TWINS


def _spelling_slip(a, b):
    """Are two US wordings one transcribed character apart?

    The PSP-US table itself misspells a word now and then (`atastyatree` for
    `agastyatree` in one entry, consistent across that entry's boxes). One
    inserted/deleted character, one substituted character or one adjacent
    transposition is a slip, not a reword: two different translations of the
    same Japanese line differ in words, not in a single letter."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) != len(b):
        short, long = (a, b) if len(a) < len(b) else (b, a)
        return any(long[:i] + long[i + 1:] == short
                   for i in range(len(long)))
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    if len(diff) == 1:
        return True
    return (len(diff) == 2 and diff[1] == diff[0] + 1
            and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])


def _twin_donor(f, ei, jp_raw, local_ink):
    """(src_file, src_entry, src_box) whose English translates `jp_raw`
    when the local PSP-US slot repeats another line's wording, else None.

    The other identical-Japanese twins must agree on one wording. The same
    Japanese line can legitimately be translated differently in different
    contexts, so a plurality is not proof: a twin with one wording and
    another twin with a different one means there is no unambiguous English
    to borrow, and the local slot is left alone. A one-character spelling
    slip in the PSP-US table is not a different translation; it is folded
    into the majority spelling. The chosen wording must also differ from
    the local one - otherwise the local slot is not the copy."""
    rows = [(sf, se, sj, ink)
            for sf, se, sj, ink in _global_twins().get(_jp_key(jp_raw), ())
            if not (sf == f and se == ei)]
    counts = {}
    for *_where, ink in rows:
        counts[ink] = counts.get(ink, 0) + 1
    if not counts:
        return None
    best = max(counts.values())
    tops = [ink for ink, n in counts.items() if n == best]
    if len(tops) != 1:
        return None
    ink = tops[0]
    if any(not _spelling_slip(ink, other) for other in counts if other != ink):
        return None
    if ink == local_ink:
        return None
    same = sorted(r[:3] for r in rows if r[3] == ink and r[0] == f)
    other = sorted(r[:3] for r in rows if r[3] == ink)
    return (same or other)[0]


def _duplicate_copy_boxes(rows):
    """Boxes whose US wording repeats a sibling's while the Japanese differs.

    `rows` is [(box, its US wording, its JP key or None)]. A repeated wording
    with different Japanese is the PSP-US table reusing one line's English,
    so the box is a copy, not a translation - it is not repaired evidence and
    it is never a donor for anyone else (the same wrong wording can occur in
    more than one entry)."""
    groups = {}
    for box, ink, key in rows:
        if _word_len(ink) >= _MIN_WORDING:
            groups.setdefault(ink, []).append((box, key))
    bad = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        # A box with no proven Japanese partner is not evidence either way:
        # it neither supplies a key nor is marked a copy. Only two DIFFERENT
        # Japanese lines sharing one wording prove a copy.
        keys = {key for _box, key in group if key is not None}
        if len(keys) > 1:
            bad.update(box for box, key in group if key is not None)
    return bad


def duplicate_us(us_entry, jp_entry, jum):
    """PSP-US boxes whose wording repeats a sibling's while the Japanese
    differs: the PSP-US table reused one line's English for another slot.
    Only a box whose Japanese partner is known can be repaired."""
    if us_entry is None or jp_entry is None:
        return set()
    jp_of_u = {}
    for j, u in jum.items():
        jp_of_u.setdefault(u, j)
    # Compare the Japanese WORDING, not the box index: two boxes can repeat a
    # line with the same words at different slots, and that is not a copy.
    return _duplicate_copy_boxes(
        (u, us_wording(us_entry.box_bytes(u)),
         _jp_key(jp_entry.box_bytes(jp_of_u[u])) if u in jp_of_u else None)
        for u in range(len(us_entry.boxes)))


def jp_us_map(jp_entry, us_entry):
    """{jp_box: us_box} for one entry.

    The PSP is the same build in both regions: it keeps the script's slots,
    so equal box counts make the index the correspondence. An entry whose
    count changed is the only one that needs structural NW."""
    n, m = len(jp_entry.boxes), len(us_entry.boxes)
    if n == m:
        return dict(enumerate(range(m)))
    B = [skel_us_jp(jp_entry.box_bytes(k)) for k in range(n)]
    C = [skel_us_psp(us_entry.box_bytes(k)) for k in range(m)]
    return {j: u for j, u in nw(B, C, sim_fn=sim_us)
            if j is not None and u is not None}


def align_entry(f, ei, psx_entry, jp_entry, us_entry):
    """Rows for one entry: (psx_box, jp_box, us_box, kind, src).

    `src` is (file, entry, box) of the PSP-US unit that supplies the words
    when this entry's own slot repeats a sibling's wording, else None."""
    A = [skel_ja_psx(psx_entry.box_bytes(k))
         for k in range(len(psx_entry.boxes))]
    B = ([skel_ja_psp(jp_entry.box_bytes(k))
          for k in range(len(jp_entry.boxes))] if jp_entry is not None else [])
    C = ([skel_psp(us_entry.box_bytes(k))
          for k in range(len(us_entry.boxes))] if us_entry is not None else [])

    jmap = {p: j for p, j in nw(A, B, sim_fn=sim_ja)
            if p is not None and j is not None}
    jum = jp_us_map(jp_entry, us_entry) if jp_entry is not None and us_entry is not None else {}
    # A PSP-US slot that repeats a different line's wording is not a
    # translation: find the English this Japanese line carries elsewhere.
    dup = duplicate_us(us_entry, jp_entry, jum)
    # The US twin of a PSX box whose Japanese the text matcher could not
    # place. Structural only: it is the last resort for a PSX-only box,
    # never a competitor of a text-proven Japanese partner.
    direct = {p: u for p, u in nw([a[:2] for a in A], C)
              if p is not None and u is not None}

    rows = []
    used = set()
    for p in range(len(A)):
        j = jmap.get(p)
        if j is not None:
            # A text-proven Japanese partner is authoritative. If the PSP-US
            # translation has no box for it (a line dropped or merged on the
            # way to English), the PSX box is a gap - taking the neighbour's
            # box would give it the wrong words and the wrong portrait.
            u = jum.get(j)
        else:
            u = direct.get(p)
        src = None
        if u is not None and u in dup and j is not None:
            src = _twin_donor(f, ei, jp_entry.box_bytes(j),
                              us_wording(us_entry.box_bytes(u)))
        if u is not None:
            used.add(u)
            rows.append((p, j, u, 'ok', src))
        else:
            rows.append((p, j, None, 'us_missing', None))
    for u in range(len(C)):
        if u not in used:
            rows.append((None, None, u, 'us_extra', None))
    return rows


def main():
    rows = []
    stats = {'ok': 0, 'us_missing': 0, 'us_extra': 0}
    for e in ('E0', 'E1', 'E2', 'E3'):
        psx = efile.load(os.path.join(PSX, f'{e}.BIN')).entries
        jp = load_psp(e, 'jp').entries
        us = load_psp(e, 'us').entries
        for ei in range(len(psx)):
            je = jp[ei] if ei < len(jp) else None
            ue = us[ei] if ei < len(us) else None
            for p, j, u, kind, src in align_entry(e, ei, psx[ei], je, ue):
                rows.append((e, ei, p, j, u, kind, src))
                stats[kind] += 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('file\tentry\tpsx_box\tjp_box\tus_box\tkind\t'
                'src_file\tsrc_entry\tsrc_box\n')
        for e, ei, p, j, u, kind, src in rows:
            sf, se, sb = src if src is not None else ('', '', '')
            cell = lambda v: '' if v is None else str(v)
            f.write(f'{e}\t{ei}\t{p}\t{cell(j)}\t{cell(u)}\t{kind}\t'
                    f'{sf}\t{se}\t{sb}\n')
    print(stats, 'rows:', len(rows))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
