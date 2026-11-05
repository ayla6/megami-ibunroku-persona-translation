"""QA worklist: suspect PSX<->US pairs in the PSP port tables.

Two detectors, both targeting the "confidently wrong English" bug class
(shifted pairs in box-count-mismatched entries, shared-text misfires):

1. unreviewed pairs of entries whose PSX/JP/US box counts differ (the 47/2
   bug class: a PSX box silently binds the neighbor's US box; same speaker,
   so no speaker-mismatch flag fires);
2. one English text serving visibly different Japanese (a shifted pair
   reusing the neighbor's US box is the usual cause).

Prints each suspect with its PSX Japanese and the English it would inject;
a human either extends align_fix.tsv (repoint or gap, see
repair_alignment.py) or accepts the pair in src/extraction_tools/matching/accept.tsv.

Usage: python src/extraction_tools/matching/qa_alignment.py
"""
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
import toolbelt  # noqa: E402
import etext  # noqa: E402
from text import load_psp  # noqa: E402
from port_story import psx_entries, usp_entries  # noqa: E402

ALIGN = os.path.join(toolbelt.MAPPINGS, 'align.tsv')
FIX = os.path.join(toolbelt.SOURCE_MAPPINGS, 'align_fix.tsv')
GEN = os.path.join(ROOT, 'translation', 'generated', 'ADV')


def box_counts(f):
    psx = psx_entries(f)
    jp = load_psp(f, 'jp')
    us = load_psp(f, 'us')
    bad = {}
    for ei in range(len(psx)):
        n, nj, nu = len(psx[ei].boxes), len(jp.entries[ei].boxes), len(us.entries[ei].boxes)
        if not (n == nj == nu):
            bad[ei] = (n, nj, nu)
    return bad


def divergent_ja():
    """Second detector: one English text serving visibly different Japanese
    (the 47/2 bug signature: a shifted pair reuses the neighbor's US box).
    Legit shared text has identical JA; anything else is suspect."""
    import re
    import collections

    def en_norm(s):
        s = re.sub(r'<FF[0-9A-F]{2}>|<[0-9A-F]{2}>|<[0-9A-F]{4}>', ' ', s)
        return re.sub(r'\s+', ' ', s).strip().lower()

    def ja_norm(s):
        s = re.sub(r'<FF[0-9A-F]{2}>|<[0-9A-F]{2}>|<[0-9A-F]{4}>', '', s)
        return re.sub(r'[\s\u3000]', '', s)

    groups = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in ('E0', 'E1', 'E2', 'E3'):
        for r in csv.reader(open(os.path.join(GEN, f + '.tsv'), encoding='utf-8'), delimiter='\t'):
            if not r or not r[0].isdigit() or len(r) < 4:
                continue
            en = en_norm(r[3])
            if len(en) > 15:
                groups[en][ja_norm(r[2])].append((f, r[0], r[1]))
    n = 0
    import difflib
    for en, jas in sorted(groups.items()):
        if len(jas) < 2:
            continue
        # real bugs have low JA similarity across groups; minor rewordings
        # (same scene, one kana difference) are benign
        reps = list(jas)
        worst = min(
            difflib.SequenceMatcher(None, reps[i], reps[j]).ratio()
            for i in range(len(reps)) for j in range(i + 1, len(reps)))
        if worst >= 0.5:
            continue
        n += 1
        print(f'== shared EN, divergent JA (sim {worst:.2f}): {en[:80]}')
        for ja, locs in jas.items():
            print(f'   {len(locs)}x {ja[:60]}  e.g. {locs[0][0]}/{locs[0][1]}/{locs[0][2]}')
    print(f'{n} shared-EN texts with divergent JA')


def main():
    fixed = set()
    for r in csv.reader(open(FIX, encoding='utf-8'), delimiter='\t'):
        if len(r) >= 3 and r[0] and r[2].isdigit():
            fixed.add((r[0], int(r[1]), int(r[2])))
    pairs = {}
    for r in csv.reader(open(ALIGN, encoding='utf-8'), delimiter='\t'):
        if not r or r[0] == 'file' or len(r) < 6 or not r[2].isdigit():
            continue
        pairs[(r[0], int(r[1]), int(r[2]))] = r
    suspect = 0
    for f in ('E0', 'E1', 'E2', 'E3'):
        bad = box_counts(f)
        gen = {}
        for r in csv.reader(open(os.path.join(GEN, f + '.tsv'), encoding='utf-8'), delimiter='\t'):
            if r and r[0].isdigit() and len(r) > 3:
                gen[(int(r[0]), int(r[1]))] = r[3]
        psx = psx_entries(f)
        for ei in sorted(bad):
            for (gentry, k), en in gen.items():
                key = (f, ei, k)
                if gentry != ei or key in fixed:
                    continue
                r = pairs.get(key)
                if not r or r[5] != 'ok':
                    continue
                ja = etext.decode(psx[ei].box_bytes(k))
                suspect += 1
                print(f'== {f}/{ei}/{k} (boxes psx/jp/us={bad[ei]}) pairs->us {r[4]}')
                print(f'   ja: {ja[:100]}')
                print(f'   en: {en[:100]}')
    print(f'{suspect} unreviewed pairs in box-count-mismatched entries')
    print()
    divergent_ja()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
