"""Local repair of misaligned PSX<->US pairs (drives align_fix.tsv).

For entries with speaker-mismatch flags (and neighbors): windowed
Needleman-Wunsch over PSX x US boxes with label (WHO-normalized) + skeleton
scores, pinned by neighboring good pairs. PSP-ported entries are never touched.
Gaps (us_missing) inside windows may find
partners; true cuts stay manual.

Writes `src/extraction_tools/matching/align_fix.tsv` (file, entry, psx, jp, us).
`port_story.py` prefers it over `align.tsv`.

Usage: python src/extraction_tools/matching/repair_alignment.py [--apply]
Without --apply: print proposed repairs. With --apply: write align_fix.tsv.
"""
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import toolbelt  # noqa: E402
import etext  # noqa: E402
import strlib              # noqa: E402
import efile  # noqa: E402
from text import load_psp  # noqa: E402
from codec import decode_box  # noqa: E402
from align import skel_psx, skel_psp, sim  # noqa: E402
from port_story import WHO, psx_entries, usp_entries  # noqa: E402

FIX = os.path.join(toolbelt.SOURCE_MAPPINGS, 'align_fix.tsv')


def us_label(raw):
    import struct
    i = 0
    n = len(raw)
    while i + 1 < n:
        if raw[i] == 0xFF:
            if raw[i + 1] == 0x1B:
                i += 2
                lab = []
                while i + 1 < n and raw[i] != 0xFF:
                    u = struct.unpack_from('>H', raw, i)[0]
                    i += 2
                    from codec import US_MAP
                    ch = US_MAP.get(u, '')
                    lab.append(ch if ch else '')
                return ''.join(lab).strip() or None
            i += 2
        else:
            i += 2
    return None


def psx_label(raw):
    t = etext.decode(raw)
    m = re.match(r'(?:<FF0[0-9A-F]>(?:<[0-9A-F]{2}>)?)*([^：<]{1,12})：', t)
    return m.group(1) if m else None


def lab_score(a, b):
    if a is None or b is None:
        return 0
    if a in WHO and b in WHO:
        return 10 if WHO[a] == WHO[b] else -10
    return 2 if a == b else 0


def nw(A, B, gap=-6):
    n, m = len(A), len(B)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + gap
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = max(dp[i - 1][j] + gap, dp[i][j - 1] + gap,
                           dp[i - 1][j - 1] + A[i - 1][j - 1])
    pairs = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + A[i - 1][j - 1]:
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


def main(apply=False):
    # flagged boxes per entry
    flags = {}
    for r in strlib.tsv_rows(os.path.join(ROOT, 'translation', 'generated', 'ADV', 'story_errors.tsv'),
                             required=('file', 'entry', 'box', 'errors')):
        if 'speaker-mismatch' in r['errors'] or 'no-pair' in r['errors'] or 'card-mismatch' in r['errors']:
            flags.setdefault((r['file'], int(r['entry'])), set()).add(int(r['box']))
    # Verified-good entries are off-limits (E0/0 pilot). Everything else with
    # flags gets repair windows; overrides only change future conversions,
    # and bulk --apply deterministically rewrites affected rows.
    SKIP = {('E0', 0)}
    proposals = []
    for (f, ei), ks in sorted(flags.items()):
        if (f, ei) in SKIP:
            continue
        psx = psx_entries(f)[ei]
        usp = usp_entries(f)[ei]
        np_, nu = len(psx.boxes), len(usp.boxes)
        lo = max(0, min(ks) - 5)
        hi = min(np_ - 1, max(ks) + 5)
        # current US window: partners of PSX lo..hi from align.tsv
        cur = {}
        for r in csv.reader(open(os.path.join(toolbelt.MAPPINGS, 'align.tsv'), encoding='utf-8'), delimiter='\t'):
            if len(r) > 5 and r[0] == f and r[1] == str(ei) and r[2] not in ('', 'None') and r[5] == 'ok':
                cur[int(r[2])] = int(r[4])
        ulo = max(0, min([cur.get(k, k) for k in range(lo, hi + 1)]) - 3)
        uhi = min(nu - 1, max([cur.get(k, k) for k in range(lo, hi + 1)]) + 3)
        P = list(range(lo, hi + 1))
        U = list(range(ulo, uhi + 1))
        pl = [psx_label(psx.box_bytes(k)) for k in P]
        ul = [us_label(usp.box_bytes(k)) for k in U]
        sk = [skel_psx(psx.box_bytes(k)) for k in P]
        su = [skel_psp(usp.box_bytes(k)) for k in U]
        A = [[lab_score(pl[i], ul[j]) + sim(sk[i], su[j]) for j in range(len(U))] for i in range(len(P))]
        pairs = nw(A, [(None, None)] * len(U))
        # evaluate whether the proposed pairs resolve flagged boxes
        newpairs = {}
        for i, j in pairs:
            if i is not None and j is not None:
                newpairs[P[i]] = U[j]
        ok = True
        for k in ks:
            if k < lo or k > hi:
                continue
            u = newpairs.get(k)
            if u is None:
                continue  # gap is an acceptable outcome (true cut)
            a = psx_label(psx.box_bytes(k))
            b = us_label(usp.box_bytes(u))
            if a and b and a in WHO and b in WHO and WHO[a] != WHO[b] and 'Girl' not in b:
                ok = False
        status = 'ACCEPT' if ok else 'REJECT'
        print(f'{f}/{ei} window {lo}-{hi} x US {ulo}-{uhi}: {status}')
        for k in sorted(ks):
            if k < lo or k > hi:
                continue
            print(f'  PSX{k} -> US{newpairs.get(k, "(gap)")} (was {cur.get(k, "(gap)")})')
        if ok and apply:
            for k in sorted(ks):
                if k < lo or k > hi:
                    continue
                proposals.append((f, ei, k, newpairs.get(k)))
    if apply:
        with open(FIX, 'a', encoding='utf-8') as fh:
            for f, ei, k, u in proposals:
                fh.write(f'{f}\t{ei}\t{k}\t\t{u if u is not None else ""}\n')
        print(f'wrote {len(proposals)} overrides to align_fix.tsv')


if __name__ == '__main__':
    main('--apply' in sys.argv)
