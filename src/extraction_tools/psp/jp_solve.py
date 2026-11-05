"""JP glyph solver: co-occurrence vote of PSX-decoded chars against PSP-JP
units on ordinal-paired boxes (entries whose box counts match exactly).

Anchors already proven by parallel position (US 'Persona' <-> JP 01b9 01cb
019c 01a9 10ac; cards: no=014c, yukino, ko=09f1, mark=015c 0133 0128,
0027=open-quote, 0028=close-quote?):

Usage: python src/extraction_tools/psp/jp_solve.py [min_votes]
"""
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import etext  # noqa: E402
import efile  # noqa: E402
from text import load_psp  # noqa: E402

PSX = os.path.join(ROOT, 'data', 'psx', 'ADV')


def psx_chars(raw):
    """Decoded PSX box text minus control codes (chars only)."""
    t = etext.decode(raw)
    return re.sub(r'<FF[0-9A-F]{2}>', '', t)


def psp_units(raw):
    """PSP unit list minus FF xx controls."""
    import struct
    out = []
    i = 0
    while i + 1 <= len(raw):
        if raw[i] == 0xFF:
            i += 2
        else:
            out.append(struct.unpack_from('>H', raw, i)[0])
            i += 2
    while out and out[0] == 0x0000:
        out.pop(0)
    return out


def main(min_votes=3):
    co = defaultdict(Counter)  # unit -> Counter(char)
    npairs = 0
    for e in ('E0', 'E1', 'E2', 'E3'):
        psx = efile.load(os.path.join(PSX, f'{e}.BIN')).entries
        psp = load_psp(e, 'jp').entries
        for pe, je in zip(psx, psp):
            if len(pe.boxes) != len(je.boxes):
                continue
            for k in range(len(pe.boxes)):
                chars = psx_chars(pe.box_bytes(k))
                units = psp_units(je.box_bytes(k))
                npairs += 1
                for ch in set(chars):
                    for u in set(units):
                        co[u][ch] += 1
    print(f'{npairs} paired boxes')
    for u in sorted(co):
        tot = sum(co[u].values())
        if tot < int(min_votes):
            continue
        top = co[u].most_common(4)
        conf = top[0][1] / tot
        print(f'{u:04x} x{tot:<6} ' + ' '.join(f'{ch}({n})' for ch, n in top)
              + f'  conf={conf:.2f}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 3)
