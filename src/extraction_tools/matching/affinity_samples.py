"""Sample affinity lines generated from the game's own chart.

Everything derived, nothing typed:
  * rows        - only the classes the game actually indexes (demon +0x11,
                  PersonaDef.resist) - unindexed rows carry junk data;
  * columns     - the engine's element ids (spell/item element field ->
                  g_btl_affinity column, references/persona-decomp damage.c);
  * names       - the PSX affinity texts name types ("アギけいをはんしゃ");
                  a type word and a chart column co-occur across rows, so
                  word -> column falls out by voting. The English word comes
                  from the PSP glossary the same way (same slot, same claim).
  * behaviour   - the engine, not the texts: codes 13-15 HEAL the target
                  (enemymotion2.c STRIKE_MOTION_HEAL, c.hp += damage) =
                  Absorb 50/100/200%; codes 10-12 make the attack do
                  nothing (BTL_REACT_NULL) = Null; 4-9 scale the damage
                  (g_btl_affinity_scale, in eighths); 0-3 are the odd tail.

Usage: python src/extraction_tools/matching/affinity_samples.py
"""
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tables import be_runs  # noqa: E402
import affinity  # noqa: E402

B = 0x80010000 - 0x800
AFF_LO, AFF_HI = 0x27baa4, 0x28374c
SCALE = {4: 0.25, 5: 0.5, 6: 0.75, 7: 1.0, 8: 1.25, 9: 1.5, 0: 1.75,
         1: 0.0, 2: 0.0, 3: 0.0}


def behaviour(code):
    if code >= 13:
        return f'Absorb {50 * (1 << (code - 13))}%'
    if code >= 10:
        return 'Null'
    if code == 7:
        return 'normal'
    if code in (8, 9):
        return f'Weak (x{SCALE[code]:g})'
    if code in (4, 5, 6):
        return f'Resist (x{SCALE[code]:g})'
    return f'x{SCALE[code]:g} (unlabelled code {code})'


def chart_rows():
    # Locate the revision-1 chart in the shipped revision by its bytes.
    with open(os.path.join(ROOT, 'data', 'psx_rev1', 'BTLP.BIN'), 'rb') as f:
        rev1 = f.read()
    with open(os.path.join(ROOT, 'data', 'psx', 'BTLP.BIN'), 'rb') as f:
        retail = f.read()
    start = 0x800D5518 - 0x800643A0
    chart = rev1[start:start + 120 * 0x11]
    offset = retail.find(chart[:0x200])
    if offset < 0 or retail[offset:offset + len(chart)] != chart:
        raise SystemExit('affinity: chart not found in retail BTLP')
    return {k: {e: ((retail[offset + k * 0x11 + e // 2] >> 4)
                    if e % 2 == 0 else (retail[offset + k * 0x11 + e // 2] & 15))
                for e in range(34)}
            for k, _address, _ja in affinity.records()}


def used_classes():
    import demons
    import personas
    import struct
    d = open(os.path.join(ROOT, 'data', 'psx', 'SLPS_005.00'), 'rb').read()
    used = set()
    for k in range(demons.COUNT):
        a = demons.REC0 + k * demons.STRIDE - B
        used.add(d[a + 0x11])
    for k in range(personas.COUNT):
        a = personas.REC0 + k * personas.STRIDE - B
        used.add(d[a + 0x1A])
    return used


def psp_slots():
    d = open(os.path.join(ROOT, 'build', 'us_boot_decrypted.bin'), 'rb').read()
    return [t.replace('<FF03>', ' / ').replace('<FF01>', '').strip()
            for o, t, term in be_runs(d) if AFF_LO <= o < AFF_HI and term == 'FF01']


def psx_type_words(text):
    return re.findall(r'([ァ-ヶー]+)(?:けい)?を(?:はんしゃ|きゅうしゅう|きかない|がきかない)', text)


def main():
    rows, slots = chart_rows(), psp_slots()
    texts = {k: ja for k, _a, ja in affinity.records()}
    used = used_classes()
    # word -> column: a PSX type word and the row's distinctive column co-occur
    votes = collections.defaultdict(collections.Counter)
    for k in sorted(used):
        cs = rows.get(k)
        if not cs:
            continue
        # the texts' absorb/null claims name columns whose code is one of the
        # "does nothing / heals" family (10+); weak/strong claims name ladder
        # columns. Vote only where the counts line up.
        for word_re, code_lo, code_hi in (
                (r'を(?:はんしゃ|きゅうしゅう|きかない|がきかない)', 10, 16),
                (r'(?:によわい|につよく)', 4, 10)):
            ws = re.findall(r'([ァ-ヶー]+)(?:けい)?' + word_re, texts.get(k, ''))
            dist = [e for e, c in cs.items() if code_lo <= c < code_hi]
            if ws and len(dist) == len(ws):
                for w, e in zip(ws, dist):
                    votes[w][e] += 1
    names = {w: c.most_common(1)[0][0] for w, c in votes.items() if c.most_common(1)[0][1] >= 1}
    print('type word -> column (voted over the indexed classes):')
    for w, e in sorted(names.items(), key=lambda x: x[1]):
        print(f'   col {e:2}  {w}')
    print()
    rev = {e: w for w, e in names.items()}
    for k in (3, 5, 20, 22, 30, 40, 50, 62, 96):
        if k not in rows:
            continue
        cs = rows[k]
        dom = collections.Counter(cs.values()).most_common(1)[0][0]
        groups = collections.defaultdict(list)
        for e in sorted(cs):
            c = cs[e]
            if c == dom or c == 7:
                continue
            groups[behaviour(c)].append(rev.get(e, f'col{e}'))
        parts = [f'{lab}: {", ".join(es)}' for lab, es in groups.items()]
        print(f'[{k:3}] psx : {texts.get(k, "")}')
        print(f'      psp : {slots[k]}')
        print(f'      gen : ' + ' / '.join(parts) if parts else '      gen : (nothing but the baseline)')
        print(f'      base: every other element takes x{SCALE.get(dom, 0):g} '
              f'({behaviour(dom) if dom != 7 else "normal"})')
        print()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
