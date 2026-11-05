#!/usr/bin/env python3
"""PSP-JP glyph map derivation + verification (mechanical, PSX-aligned).

Align PSP-JP word streams against PSX-JA text of the same box/unit and vote
word-code -> character. Nothing is ever typed in: every candidate character
comes from the PSX parallel text of the same row.

Votes cover mapped codes too, so the audit can catch wrong entries (the
マ/ま class): a code is verified when its votes agree with its map row and
flagged when they disagree.

Families (pos/id pairing only, never text search):
  E0-E3   align.tsv kind=ok rows (psx_box -> jp_box)
  talk    unit-index identity (PSX Talk.units[k] <-> PSP unit k)
  dng     dng_map.tsv rows (sub + offset proximity -> nearest JP box)

Usage (run from repo root):
  python tools/jp_automatch.py audit        votes vs current map (wrong-entry hunt)
  python tools/jp_automatch.py propose      unmapped codes with their vote splits
  python tools/jp_automatch.py structural   codes that never vote (icons/params)
  python tools/jp_automatch.py apply        write confident proposals + fixes
"""
import collections
import difflib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'matching'))
import toolbelt  # noqa: E402
import etext  # noqa: E402
import strlib  # noqa: E402
import port_story  # noqa: E402
import port_talk  # noqa: E402
from talk import Talk  # noqa: E402
from text import jp_glyph_map, orphan_runs, slot_table, TALK_DIR, DNG_DIR  # noqa: E402
from codec import decode_box  # noqa: E402

MAP = os.path.join(toolbelt.MAPPINGS, 'psp_jp_glyphs.tsv')
ALIGN_OK = ('ok',)

# never auto-fix: whitespace/punctuation, param words, and structural or
# screenshot-verified symbols whose decorative votes wander (card suits,
# arrows, braces). The audit still reports their splits.
NEVER = {0x0000, 0x0001, 0x0200, 0x0300, 0x002f, 0x0030,
         0x0043, 0x0204, 0x0205, 0x0206, 0x0207}

NOISE = {' ', '\u3000', '、', '。', '，', '．', '・', '：', '；', '？', '！',
         '…', '－', '-', '～', '~', '\u2018', '\u2019', '\u201c', '\u201d',
         '「', '」', '『', '』', '（', '）', '(', ')', '[', ']', '＜', '＞',
         '<', '>', '/', '／', '.', ',', ':', ';', '?', '!', '"', "'", '*'}

ATOK = re.compile(r'<[^>]+>|.')
BTOK = re.compile(r'<[^>]+>#?|\[[0-9a-f]{4}\]|.')
HOLE = re.compile(r'^\[([0-9a-f]{4})\]$')


def is_char(t):
    return not (t.startswith('<') or t.startswith('['))


def a_tokens(raw):
    return ATOK.findall(etext.decode(raw))


def b_units(raw):
    """[(code_or_None, rendered_token)] of a PSP box: the word stream with
    every glyph word visible as [hhhh] (empty map = full transparency) and
    controls/params as tags. One decoder (codec.decode_box); its param rules
    stay authoritative."""
    toks = BTOK.findall(decode_box(raw, {}, holes=[]))
    out = []
    for t in toks:
        m = HOLE.match(t)
        out.append((int(m.group(1), 16) if m else None, t))
    return out


def match_token(u, jm):
    """Alignment identity: mapped words match by character, unmapped words by
    unique opaque identity (they can never equal a PSX token)."""
    code, tok = u
    if code is None:
        return tok
    return jm.get(code, '\x00%04x' % code)


# ---------------------------------------------------------------------------
# alignment + votes
# ---------------------------------------------------------------------------

def _split_label_a(a):
    """(label, rest): PSX speaker label = name + '：' at box head."""
    for i, t in enumerate(a):
        if t == '<FF03>':
            break
        if t == '：' and i < 12:
            return a[:i + 1], a[i + 1:]
    return [], a


def _split_label_b(bvec):
    """(label, rest): PSP label region = <FF1B> label <FF03> or
    [004f] name <FF03>."""
    if bvec and bvec[0][1] in ('<FF1B>', '[004f]'):
        for i, (_c, t) in enumerate(bvec):
            if t == '<FF03>':
                return bvec[:i + 1], bvec[i + 1:]
    return [], bvec


def _pages(units):
    """Split a unit list at page breaks (<FF04>): pages pair 1:1 across the
    versions, and PSP repeats its speaker label on every page while PSX
    writes it once - only per-page pairing lets those names vote."""
    out, cur = [], []
    for u in units:
        tok = u if isinstance(u, str) else u[1]
        if tok == '<FF04>':
            out.append(cur)
            cur = []
        else:
            cur.append(u)
    out.append(cur)
    return out


def vote_pair(avec, bvec, jm, votes, min_identity=0.6):
    """Vote one aligned pair. Regions whose texts do not actually correspond
    (PSP script rewrites, stray tails, misaligned rows) vote noise, so a
    region votes only when most of its PSX side matches the PSP side
    verbatim.

    Speaker labels are renamed between versions (PSX names vs PSP-JP
    descriptions), so a label region votes only when the two labels
    themselves correspond (named characters keep their names)."""
    a_pages = _pages([t for t in avec])
    b_pages = _pages([u for u in bvec])
    voted = False
    for pa, pb in zip(a_pages, b_pages):
        la, a = _split_label_a(pa)
        lb, pb = _split_label_b(pb)
        voted |= _vote_region(la, [u for u in lb], jm, votes, min_identity,
                              strict=True)
        voted |= _vote_region(a, pb, jm, votes, min_identity)
    return voted


def _vote_region(a, bvec, jm, votes, min_identity=0.6, strict=False):
    bm = [match_token(u, jm) for u in bvec]
    sm = difflib.SequenceMatcher(None, a, bm, autojunk=False)
    ops = sm.get_opcodes()
    nchar = sum(1 for t in a if is_char(t))
    matched = sum(i2 - i1 for tag, i1, i2, _j1, _j2 in ops
                  if tag == 'equal' for i in range(i1, i2) if is_char(a[i]))
    if nchar and matched / nchar < min_identity:
        return False
    for ti, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == 'equal':
            for i, j in zip(range(i1, i2), range(j1, j2)):
                _maybe_vote(a[i], bvec[j], votes)
        elif tag == 'replace':
            # Flank anchoring: a replace block votes only when the equal
            # text around it pins the position (a block with no matching
            # neighbor is a misaligned region and votes pure noise - the
            # 畏 8/神 8 split class).
            flanked = ((ti > 0 and ops[ti - 1][0] == 'equal')
                       and (ti + 1 < len(ops) and ops[ti + 1][0] == 'equal'))
            if strict:
                # label regions are short names: only clean 1:1 pairings
                # vote, and only when a matching neighbor pins the position
                # (at least one flank - labels run to the region edge)
                one = ((ti > 0 and ops[ti - 1][0] == 'equal')
                       or (ti + 1 < len(ops) and ops[ti + 1][0] == 'equal'))
                if (i2 - i1) == (j2 - j1) and one:
                    for i, j in zip(range(i1, i2), range(j1, j2)):
                        _maybe_vote(a[i], bvec[j], votes)
            elif flanked:
                _sub_nw(a[i1:i2], bm[j1:j2], bvec[j1:j2], votes)
    return True


def _maybe_vote(atok, bunit, votes):
    code, _ = bunit
    if code is not None and is_char(atok):
        votes[code][atok] += 1


def _sub_nw(A, BM, BU, votes):
    """Needleman-Wunsch inside a replace block. Tags never pair (they are
    structure); a char pairs with a word for +3 (same mapped char) or +1
    (a candidate: wrong entry or hole fill)."""
    n, m = len(A), len(BM)
    if not n or not m:
        return
    GAP = -2

    def sc(i, j):
        if not is_char(A[i]) or BM[j].startswith('<') or BM[j].startswith('#'):
            return None
        return 3 if A[i] == BM[j] else 1

    NEG = float('-inf')
    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    bt = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0
    for i in range(n + 1):
        for j in range(m + 1):
            if i and dp[i - 1][j] > NEG:
                v = dp[i - 1][j] + GAP
                if v > dp[i][j]:
                    dp[i][j], bt[i][j] = v, ('u', i - 1, j)
            if j and dp[i][j - 1] > NEG:
                v = dp[i][j - 1] + GAP
                if v > dp[i][j]:
                    dp[i][j], bt[i][j] = v, ('l', i, j - 1)
            if i and j:
                s = sc(i - 1, j - 1)
                if s is not None and dp[i - 1][j - 1] > NEG:
                    v = dp[i - 1][j - 1] + s
                    if v > dp[i][j]:
                        dp[i][j], bt[i][j] = v, ('d', i - 1, j - 1)
    i, j = n, m
    while i or j:
        step = bt[i][j]
        if step is None:
            return
        kind, i, j = step
        if kind == 'd':
            _maybe_vote(A[i], BU[j], votes)


# ---------------------------------------------------------------------------
# families (pos/id pairing only)
# ---------------------------------------------------------------------------

def pairs_E():
    for (f, ei), m in sorted(port_story.align_idx().items()):
        if f not in ('E0', 'E1', 'E2', 'E3'):
            continue
        for k, r in sorted(m.items()):
            if len(r) <= 5 or r[5] not in ALIGN_OK or not str(r[3]).isdigit():
                continue
            yield ((f, ei, k), a_tokens(port_story.psx_entries(f)[ei].box_bytes(k)),
                   b_units(port_story.jsp_entries(f)[ei].box_bytes(int(r[3]))))


def pairs_talk():
    psx_dir = os.path.join(ROOT, 'data', 'psx', 'TALK')
    for name in sorted(n[:-4] for n in os.listdir(TALK_DIR['jp']) if n.endswith('.BIN')):
        t = Talk(name, open(os.path.join(psx_dir, name + '.BIN'), 'rb').read())
        spans = port_talk.psp_unit_spans(os.path.join(TALK_DIR['jp'], name + '.BIN'))
        if not t.ok or len(t.units) != len(spans):
            print(f'  !! talk/{name}: psx ok={t.ok} units={len(t.units)} '
                  f'psp units={len(spans)} -- skipped (loud, never silent)')
            continue
        for k in range(len(t.units)):
            yield (('talk', name, k), a_tokens(t.units[k]), b_units(spans[k][1]))


def pairs_talk_answers():
    """PSX answer slot k <-> PSP-JP answer slot k (the tab slot is the
    pos/id pairing - never a text search)."""
    import talk as talkt
    psx_dir = os.path.join(ROOT, 'data', 'psx', 'TALK')
    for name in sorted(n[:-4] for n in os.listdir(TALK_DIR['jp']) if n.endswith('.BIN')):
        try:
            t = talkt.load(name)
        except Exception:
            continue
        if not t.ok or not t.s1_tab:
            continue
        d = open(os.path.join(TALK_DIR['jp'], name + '.BIN'), 'rb').read()
        h, tab = slot_table(d)
        by_off = {}
        for v, sp in t.s1:
            by_off[v] = sp[:t.s1_text_len(sp)]
        for k, a in enumerate(t.s1_tab):
            if a == 0xFFFFFFFF or k >= len(tab):
                continue
            v = tab[k]
            if v == 0xFFFFFFFF or v >= h[2]:
                continue
            seg = d[v:h[2]]
            cut = [x for x in (seg.find(b'\xff\xf5'), seg.find(b'\xff\xef')) if x >= 0]
            seg = seg[:min(cut) + 2] if cut else seg
            if a not in by_off or len(seg) < 2:
                continue
            yield (('talkans', name, k), a_tokens(by_off[a]), b_units(seg))


_DNG_RAW = {}


def dng_raw(sub):
    if sub not in _DNG_RAW:
        p = os.path.join(DNG_DIR['jp'], sub, sub + '.bin')
        d = open(p, 'rb').read()
        _DNG_RAW[sub] = [(s, d[s:e]) for s, e in orphan_runs(d, set(jp_glyph_map()))]
    return _DNG_RAW[sub]


def pairs_dng():
    p = os.path.join(toolbelt.MATCHING, 'dng_map.tsv')
    for row in strlib.tsv_rows(p, required=('key', 'sub', 'off')):
        sub, off = row['sub'], int(row['off'], 16)
        best, bd = None, None
        for s, raw in dng_raw(sub):
            dd = abs(s - off)
            if bd is None or dd < bd:
                best, bd = (s, raw), dd
        if best is None or bd >= 0x300:
            print(f'  !! dng/{sub}+{off:#x}: no JP box within range -- skipped')
            continue
        yield (('dng', sub, best[0]), ATOK.findall(row['key']), b_units(best[1]))


FAMILIES = {'E': pairs_E, 'talk': pairs_talk, 'talkans': pairs_talk_answers,
            'dng': pairs_dng}


def collect(fams):
    votes = collections.defaultdict(collections.Counter)
    where = {}
    npairs = 0
    for fam in fams:
        n0 = npairs
        trusted = 0
        for key, avec, bvec in FAMILIES[fam]():
            npairs += 1
            if vote_pair(avec, bvec, jp_glyph_map(), votes):
                trusted += 1
            for code, _ in bvec:
                if code is not None:
                    where.setdefault(code, f'{fam}:{key}')
        print(f'  {fam}: {npairs - n0} aligned pairs ({trusted} trusted)')
    return votes, where, npairs


# ---------------------------------------------------------------------------
# map I/O
# ---------------------------------------------------------------------------

def load_map():
    return {int(u, 16): ch for u, ch in strlib.tsv_fields(MAP, 2) if u}


def write_map(new, fixed):
    """Row edits in place, additions appended (existing order preserved)."""
    lines = open(MAP, encoding='utf-8').read().split('\n')
    out = []
    for line in lines:
        f = line.split('\t')
        if len(f) >= 2 and f[0]:
            code = int(f[0], 16)
            if code in fixed:
                out.append(f'{f[0]}\t{fixed[code]}')
                continue
        out.append(line)
    while out and out[-1] == '':
        out.pop()
    for code in sorted(new):
        out.append(f'{code:04x}\t{new[code]}')
    open(MAP, 'w', encoding='utf-8', newline='\n').write('\n'.join(out) + '\n')
    print(f'wrote {MAP}: {len(fixed)} fixed, {len(new)} added')


# ---------------------------------------------------------------------------
# modes
# ---------------------------------------------------------------------------

def main(mode, fams):
    jm = jp_glyph_map()
    votes, where, npairs = collect(fams)
    print(f'total aligned pairs: {npairs}; codes with votes: {len(votes)}')
    cur = load_map()

    if mode == 'audit':
        bad = good = unvoted = 0
        print(f'{"code":6} {"map":4} {"votes":6} conf  top-verdict')
        for code in sorted(set(cur) | set(votes)):
            v = votes.get(code)
            if not v:
                unvoted += 1
                continue
            tot = sum(v.values())
            top, n = v.most_common(1)[0]
            if code not in cur:
                continue
            mark = 'OK' if top == cur[code] else 'MISMATCH'
            if mark == 'OK':
                good += 1
            else:
                bad += 1
                print(f'{code:04x} {cur[code]!r:4} x{tot:<5} {n / tot:.2f} '
                      f'{v.most_common(4)} {mark} <- {where.get(code)}')
        print(f'confirmed: {good}  mismatches: {bad}  mapped-with-no-votes: {unvoted}')

    elif mode == 'propose':
        print(f'{"code":6} {"top":4} {"votes":6} conf  split')
        for code in sorted(votes, key=lambda c: -sum(votes[c].values())):
            if code in cur:
                continue
            v = votes[code]
            tot = sum(v.values())
            top, n = v.most_common(1)[0]
            print(f'{code:04x} {top!r:4} x{tot:<5} {n / tot:.2f} '
                  f'{v.most_common(4)} <- {where.get(code)}')

    elif mode == 'detail':
        for code in sorted(int(a, 16) for a in sys.argv[1:]
                           if a.startswith('0x') or a.startswith('0X')):
            v = votes.get(code, collections.Counter())
            print(f'0x{code:04x} mapped={cur.get(code)!r} '
                  f'tot={sum(v.values())} {v.most_common(12)} <- {where.get(code)}')

    elif mode == 'structural':
        seen = collections.Counter()
        for code, _w in sorted(where.items()):
            pass
        no = [c for c in sorted(where) if c not in votes and c not in cur]
        nomap = [c for c in sorted(where) if c not in votes and c in cur]
        print('codes with occurrences but zero char votes, NOT mapped:')
        for c in no:
            print(f'  0x{c:04x} <- {where[c]}')
        print('codes with occurrences but zero char votes, already mapped:')
        for c in nomap:
            print(f'  0x{c:04x} {cur[c]!r} <- {where[c]}')

    elif mode == 'apply':
        new, fixed = {}, {}
        for code in sorted(votes):
            # Whitespace/punctuation votes are alignment noise (interchangeable
            # at mismatch boundaries) and never decide an entry: the punct
            # entries themselves are NEVER-apply (screenshot-verified rows).
            v = collections.Counter({ch: n for ch, n in votes[code].items()
                                     if ch not in NOISE})
            if not v:
                continue
            tot = sum(v.values())
            top, n = v.most_common(1)[0]
            conf = n / tot
            second = v.most_common(2)[1][1] if len(v) > 1 else 0
            ratio = (n / second) if second else float('inf')
            # never auto-map to a punctuation/whitespace char either: those
            # rows are screenshot-verified (0027/0028 quotes, 0005 bullets...)
            # Tier 1: the signal must dominate (share >= 0.65, >= 2x the
            # runner-up, >= 5 votes) - alignment noise scatters across
            # neighbors while real readings concentrate (verified against
            # raw pairs: 0eb1 罰 11/思 5, 0a6f 趣 8/い 4). Tier 2: small
            # clean sweeps (conf 1.0, >= 3 votes).
            # Never FIX a row whose value is punctuation/space/symbol: those
            # rows are individually evidence-established (quotes, brackets,
            # dots - confirmed 400+:1 in the votes) and a dirty alignment
            # can flip them transiently (their wrong values break the
            # anchors that vote on them). Adds of punct targets are blocked
            # above.
            accept = (code not in NEVER and top not in NOISE
                      and (code not in cur or cur[code] not in NOISE)
                      and ((n >= 5 and conf >= 0.65 and ratio >= 2)
                           or (n >= 2 and conf == 1.0)))
            if accept and code not in cur:
                new[code] = top
            elif accept and top != cur[code]:
                fixed[code] = top
        for code, ch in sorted(new.items()):
            print(f'  + {code:04x} -> {ch!r}  ({sum(votes[code].values())} votes)')
        for code, ch in sorted(fixed.items()):
            print(f'  ~ {code:04x} {cur[code]!r} -> {ch!r}  '
                  f'({sum(votes[code].values())} votes)')
        write_map(new, fixed)

    else:
        raise SystemExit(f'unknown mode {mode!r} (audit|propose|structural|apply)')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    fams = [f for a in sys.argv[1:] if a.startswith('--families=')
            for f in a.split('=', 1)[1].split(',')]
    main(args[0] if args else 'propose',
         fams or ['E', 'talk', 'talkans', 'dng'])
