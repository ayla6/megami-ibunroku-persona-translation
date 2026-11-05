"""Targeted JP glyph solver: align PSP-JP answer slots (with [xxxx] holes)
against complete PSX answer strings; each hole unit votes for the PSX char
at the same position. Accepts winners by votes + consistency.

Usage: python src/extraction_tools/psp/jp_solve_slots.py [--apply]
Report-only by default; --apply appends winners to src/extraction_tools/psp_glyphs.tsv.
"""
import csv
import os
import re
import struct
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolbelt  # noqa: E402
from text import jp_glyph_map  # noqa: E402
import strlib  # noqa: E402

GLYPHS = toolbelt.PSP_GLYPHS
GEN = os.path.join(ROOT, 'translation', 'generated', 'TALK', 'ANSWERS.tsv')
HOLE = re.compile(r'\[([0-9a-f]{4})\]')


def psp_slots():
    """[(jp_text_with_holes, us_text)] over all PSP talk answer slots."""
    sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'matching'))
    from text import TALK_DIR, decode_talk_box as decode_talk
    from codec import US_MAP
    jm = jp_glyph_map()
    out = []
    for fn in sorted(os.listdir(TALK_DIR['jp'])):
        if not fn.endswith('.BIN') or fn == 'ETC.BIN':
            continue
        name = fn[:-4]
        pj = os.path.join(TALK_DIR['jp'], fn)
        pu = os.path.join(TALK_DIR['us'], fn)
        dj = open(pj, 'rb').read()
        du = open(pu, 'rb').read()
        hj = struct.unpack_from('<6I', dj, 0)
        hu = struct.unpack_from('<6I', du, 0)
        if hj[2] - hj[1] < 2048:
            continue
        tj = struct.unpack('<512I', dj[hj[1]:hj[1] + 2048])
        tu = struct.unpack('<512I', du[hu[1]:hu[1] + 2048])
        for k, (vj, vu) in enumerate(zip(tj, tu)):
            if vj == 0xFFFFFFFF or vu == 0xFFFFFFFF or vj >= hj[2] or vu >= hu[2]:
                continue
            jt = decode_talk(dj[vj:hj[2]], jm)
            ut = decode_talk(du[vu:hu[2]], US_MAP)
            if '[0' not in jt and '[0' not in ut:
                continue
            out.append((jt, ut))
    return out


def psx_answers():
    out = set()
    for r in list(csv.reader(open(GEN, encoding='utf-8'), delimiter='\t'))[1:]:
        if r and len(r) > 1 and r[1].strip():
            out.add(r[1])
    return out


def main(apply=False):
    slots = psp_slots()
    print('slots with holes:', len(slots))
    psx = psx_answers()
    votes = defaultdict(Counter)
    used = 0
    for jt, _ut in slots:
        pat = '^' + re.escape(jt)
        holes = []
        # build regex: [xxxx] -> (.), remembering units in order
        parts, units, last = [], [], 0
        for m in HOLE.finditer(jt):
            parts.append(re.escape(jt[last:m.start()]))
            parts.append('(.)')
            units.append(m.group(1))
            last = m.end()
        parts.append(re.escape(jt[last:]))
        rx = re.compile('^' + ''.join(parts) + '$')
        cands = set()
        for ja in psx:
            m = rx.match(ja)
            if m:
                cands.add((ja, m.groups()))
        if len(cands) != 1:
            continue
        used += 1
        _ja, groups = next(iter(cands))
        for u, ch in zip(units, groups):
            votes[u][ch] += 1
    print('unambiguous alignments:', used)
    winners = []
    for u, c in sorted(votes.items()):
        tot = sum(c.values())
        ch, n = c.most_common(1)[0]
        if tot >= 3 and n / tot >= 0.8:
            winners.append((u, ch, n, tot))
    print('winners (unit -> char votes/total):')
    for u, ch, n, tot in winners:
        print(f'  {u} -> {ch!r} ({n}/{tot})')
    if apply and winners:
        have = set()
        for u, _ch in strlib.tsv_fields(GLYPHS, 2):
            if u:
                have.add(u)
        new = [(u, ch) for u, ch, _n, _t in winners if u not in have]
        with open(GLYPHS, 'a', encoding='utf-8') as o:
            for u, ch in sorted(new):
                o.write(f'{u}\t{ch}\n')
        print(f'appended {len(new)} entries to {GLYPHS}')
    return winners


if __name__ == '__main__':
    main('--apply' in sys.argv[1:])
