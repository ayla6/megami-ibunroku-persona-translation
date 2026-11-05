"""Three-way box alignment: PSX <-> PSP-JP <-> PSP-US, per entry.

Pairwise Needleman-Wunsch on box skeletons (control-code sequence + text
length). Handles the merge/split cases (PSX 7344 / JP 7322 / US 7242 boxes;
59 entries differ in count).

Output: translation/generated_mappings/align.tsv
  file entry psx_box jp_box us_box kind
kind: ok (1:1:1) | merge (N PSX -> fewer) | split | jp_only | us_only | psx_only

Usage: python src/extraction_tools/matching/align.py
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
import toolbelt  # noqa: E402
import toolbelt  # noqa: E402
import efile  # noqa: E402
from text import load_psp  # noqa: E402
from codec import US_MAP  # noqa: E402

PSX = os.path.join(ROOT, 'data', 'psx', 'ADV')
OUT = os.path.join(toolbelt.MAPPINGS, 'align.tsv')


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
        i = j = 0
        matches = 0
        la_l, lb_l = list(na), list(nb)
        for x in la_l:
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


def main():
    rows = []
    stats = {'ok': 0, 'merge': 0, 'split': 0, 'gap': 0}
    for e in ('E0', 'E1', 'E2', 'E3'):
        psx = efile.load(os.path.join(PSX, f'{e}.BIN')).entries
        jp = load_psp(e, 'jp').entries
        us = load_psp(e, 'us').entries
        for ei in range(len(psx)):
            A = [skel_psx(psx[ei].box_bytes(k)) for k in range(len(psx[ei].boxes))]
            B = [skel_psp(jp[ei].box_bytes(k)) for k in range(len(jp[ei].boxes))]
            C = [skel_psp(us[ei].box_bytes(k)) for k in range(len(us[ei].boxes))]
            # Pair PSX with PSP-US directly; attach PSP-JP independently as a
            # Japanese source anchor. The box counts can differ by region.
            pu = nw(A, C)
            pj = nw(A, B)
            jof = {}
            for p, j in pj:
                if p is not None and j is not None:
                    jof.setdefault(p, j)
            for p, u in pu:
                if p is None:
                    rows.append((e, ei, None, None, u, 'us_extra'))
                    stats['gap'] += 1
                    continue
                j = jof.get(p)
                if u is None:
                    rows.append((e, ei, p, j, None, 'us_missing'))
                    stats['gap'] += 1
                    continue
                rows.append((e, ei, p, j, u, 'ok'))
                stats['ok'] += 1
    # merge detection: multiple psx rows sharing one us box
    seen = {}
    for r in rows:
        if r[5] == 'ok':
            key = (r[0], r[1], r[4])
            if key in seen:
                rows[rows.index(r)] = (r[0], r[1], r[2], r[3], r[4], 'merge')
                prev = seen[key]
                rows[rows.index(prev)] = (prev[0], prev[1], prev[2], prev[3], prev[4], 'merge')
                stats['merge'] += 2
                stats['ok'] -= 2
            else:
                seen[key] = r
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('file\tentry\tpsx_box\tjp_box\tus_box\tkind\n')
        for e, ei, p, j, u, kind in rows:
            f.write(f'{e}\t{ei}\t{p}\t{j if j is not None else ""}\t'
                    f'{u if u is not None else ""}\t{kind}\n')
    print(stats, 'rows:', len(rows))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
