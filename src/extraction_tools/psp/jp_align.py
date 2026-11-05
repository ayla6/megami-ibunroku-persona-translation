"""JP glyph solver, round 2: Needleman-Wunsch alignment of PSX-decoded char
strings against PSP-JP unit streams, bootstrapped from certain anchors,
iterated to convergence.

Anchors (proven by parallel position / cards):
  01b9 01cb 019c 01a9 = peru-so-na, 10ac = sama(kanji), 015c 0133 0128 = ma-ku,
  0164 012b 014c = yukino, 014c = no, 09f1 = ko, 0027/0028 = brackets,
  0008 = ?, 0009 = !, 00cf-00d7 = digits 0-8, 0000 dropped (space/param noise).

Usage: python src/extraction_tools/psp/jp_align.py [rounds]
Writes src/extraction_tools/psp_glyphs.tsv (unit -> char + votes).
"""
import os
import re
import struct
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import etext  # noqa: E402
import efile  # noqa: E402
from text import load_psp  # noqa: E402

PSX = os.path.join(ROOT, 'data', 'psx', 'ADV')
OUT = toolbelt.PSP_GLYPHS

ANCHOR = {
    0x01b9: 'ペ', 0x01cb: 'ル', 0x019c: 'ソ', 0x01a9: 'ナ', 0x10ac: '様',
    0x015c: 'マ', 0x0133: 'ー', 0x0128: 'ク',
    0x0164: 'ゆ', 0x012b: 'き', 0x014c: 'の', 0x09f1: '子',
    0x0027: '「', 0x0028: '」', 0x0008: '？', 0x0009: '！',
    0x00cf: '０', 0x00d0: '１', 0x00d1: '２', 0x00d2: '３', 0x00d3: '４',
    0x00d4: '５', 0x00d5: '６', 0x00d6: '７', 0x00d7: '８',
}
PARAMISH = {0x0200, 0x0300, 0x0044, 0x0500, 0x0700}


def psx_seq(raw):
    t = etext.decode(raw)
    t = re.sub(r'<FF[0-9A-F]{2}>', '', t)
    return [c for c in t if c not in (' ', '　')]


def psp_seq(raw):
    out = []
    i = 0
    skip = 0
    while i + 1 <= len(raw):
        if skip:
            skip -= 1
            i += 2
            continue
        if raw[i] == 0xFF:
            op = raw[i + 1]
            i += 2
            if op in (0x18, 0x0E):
                skip = 1
                # card-style double param after 0200/0300
                if i + 1 <= len(raw) and raw[i] != 0xFF:
                    v = struct.unpack_from('>H', raw, i)[0]
                    if v in (0x0200, 0x0300):
                        skip = 3  # 0200/0300 0044 0000
            continue
        u = struct.unpack_from('>H', raw, i)[0]
        i += 2
        if u == 0x0000:
            continue
        out.append(u)
    return out


def align(units, chars, amap):
    """Needleman-Wunsch. Returns list of (unit|None, char|None) pairs."""
    n, m = len(units), len(chars)
    MATCH, MISM, UNK, GAP = 5, -5, -1, -3

    def score(u, c):
        if u in amap:
            return MATCH if amap[u] == c else MISM
        return UNK

    # banded DP would be nicer; boxes are small (<400), full matrix OK
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + GAP
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + GAP
    for i in range(1, n + 1):
        ui = units[i - 1]
        row, prow = dp[i], dp[i - 1]
        for j in range(1, m + 1):
            row[j] = max(prow[j] + GAP, row[j - 1] + GAP,
                         prow[j - 1] + score(ui, chars[j - 1]))
    pairs = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + score(units[i - 1], chars[j - 1]):
            pairs.append((units[i - 1], chars[j - 1]))
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + GAP:
            pairs.append((units[i - 1], None))
            i -= 1
        else:
            pairs.append((None, chars[j - 1]))
            j -= 1
    pairs.reverse()
    return pairs


def main(rounds=4):
    pairs = []  # (units, chars) per ordinal-paired box
    for e in ('E0', 'E1', 'E2', 'E3'):
        psx = efile.load(os.path.join(PSX, f'{e}.BIN')).entries
        psp = load_psp(e, 'jp').entries
        for pe, je in zip(psx, psp):
            if len(pe.boxes) != len(je.boxes):
                continue
            for k in range(len(pe.boxes)):
                u = psp_seq(je.box_bytes(k))
                c = psx_seq(pe.box_bytes(k))
                if u and c and abs(len(u) - len(c)) < max(len(u), len(c)) * 0.6:
                    pairs.append((u, c))
    print(f'{len(pairs)} alignable box pairs')
    amap = dict(ANCHOR)
    for r in range(int(rounds)):
        votes = defaultdict(Counter)
        total_score = 0
        for u, c in pairs:
            al = align(u, c, amap)
            # collect runs of unknown-unit alignments
            run = []
            for uu, cc in al + [(None, None)]:
                if uu is not None and cc is not None and uu not in amap:
                    run.append((uu, cc))
                else:
                    if len(run) >= 2:
                        for uu, cc in run:
                            votes[uu][cc] += 1
                    elif len(run) == 1 and (run[0][0] in amap or True):
                        pass
                    run = []
        added = 0
        for u, cnt in sorted(votes.items()):
            if u in amap:
                continue
            tot = sum(cnt.values())
            ch, n = cnt.most_common(1)[0]
            if tot >= 4 and n / tot >= 0.7:
                amap[u] = ch
                added += 1
        print(f'round {r}: map={len(amap)} (+{added})')
        if added == 0:
            break
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        for u in sorted(amap):
            f.write(f'{u:04x}\t{amap[u]}\n')
    print('wrote', OUT, len(amap), 'entries')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 4)
