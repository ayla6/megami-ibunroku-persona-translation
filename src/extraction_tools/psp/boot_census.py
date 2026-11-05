"""Structural census of the decrypted PSP-US BOOT image: every text region,
mapped.

The skepticism this answers: "have we really extracted all text from
BOOT.BIN?" Instead of claiming it, this tool enumerates every decodable
string under the strict decoders (LE C-strings + BE glyph/code runs over the
whole image), clusters the BE records and labels each cluster against the
known domains. Anything unlabeled is printed with a sample: that list, empty
or not, is the complete set of unexamined BOOT text.

Usage: python src/extraction_tools/psp/boot_census.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
from tables import be_runs, le_strings, us_boot  # noqa: E402
import boot_tables as BT  # noqa: E402

US_LE = __import__('tables').US_LE
US_SPACE = __import__('tables').US_SPACE
NL = chr(10)

# Known-text area labels, in address order. A cluster that overlaps one of
# these ranges is examined; anything else goes on the UNKNOWN list.
LABELS = [
    (0x19a000, 0x1c0000, 'stray glyph runs in the module/graphics area'),
    (0x1e4000, 0x1e8000, 'battle-menu words (stray)'),
    (0x1e8000, 0x1f0000, 'battle messages (stray)'),
    (0x1ee68e, 0x1eea90, 'treasure box messages'),
    (0x250000, 0x253000, 'casino / trade words'),
    (0x2641e8, 0x264450, 'system data & Memory Stick messages'),
    (0x265860, 0x270481, 'name tables (personas, skills, items, demons)'),
    (0x27144e, 0x276e2b, 'nicknames + enemy name bank'),
    (0x277474, 0x28382d, 'item/skill description banks + affinity blurbs'),
    (0x28651c, 0x287a00, 'elements / ailments / races / arcana words'),
    (0x289716, 0x28b76b, 'town & dungeon event dialogue'),
    (0x28b800, 0x28c000, 'location names (LE 0x40 table)'),
    (0x28fc7a, 0x2922bb, 'map screen floor names'),
    (0x2923cc, 0x293000, 'automap legends / field spell effects'),
    (0x294000, 0x298000, 'stray glyph runs (field graphics noise)'),
    (0x29adfc, 0x29eceb, 'battle command & status messages'),
    (0x29f000, 0x2a1000, 'stray glyph runs (graphics noise)'),
    (0x2a1e96, 0x2a2030, 'Persona rank / skill learn messages'),
    (0x2a4bb4, 0x2a5e1d, 'stat & level messages'),
    (0x2a7d64, 0x2a8fa3, 'spell card banter'),
    (0x2a93b6, 0x2adf57, 'contact / negotiation messages'),
    (0x2b1c94, 0x2b3a63, 'dungeon map names'),
    (0x2b4c92, 0x2be633, 'automap room & place names'),
    (0x2bfbd0, 0x2bfffd, 'treasure box trap messages'),
    (0x2c06ec, 0x2c1360, 'shop/menu option blob + NPC name labels'),
    (0x2c727e, 0x2d3b23, 'casino rules & help'),
    (0x2d3cd4, 0x2d4100, 'fusion effect words'),
    (0x2d44a6, 0x2d4ed3, 'Velvet Room dialogue'),
    (0x2d61a0, 0x2d7100, 'shop clerk lines'),
    (0x2d71b0, 0x2d7900, 'shop names & prompts (LE)'),
    (0x2d7966, 0x2d8281, 'difficulty select text'),
    (0x2d83c8, 0x2d8400, 'chapter titles (LE)'),
    (0x2d9000, 0x2d9500, 'stray glyph runs (graphics noise)'),
    (0x2d9e66, 0x2daab3, 'shop / casino item names'),
]

KNOWN_LE = [('races',) + BT.LE_TABLES['races']]
KNOWN_BE = [
    ('personas',) + BT.TABLES['personas'],
    ('demons',) + BT.TABLES['demons'],
    ('items',) + BT.TABLES['items'],
    ('skills',) + BT.TABLES['skills'],
    ('nicknames',) + BT.TABLES['nicknames'],
]


def label_at(lo, hi):
    for a, b, lab in LABELS:
        if lo <= b and hi >= a:
            return lab
    return None


def le_gap_runs(offsets, min_run=4):
    """[(start, stride, count)] runs of C-string offsets with constant gap."""
    runs = []
    i = 0
    offs = sorted(offsets)
    while i < len(offs) - 1:
        gap = offs[i + 1] - offs[i]
        if gap <= 0 or gap > 0x200:
            i += 1
            continue
        cur = [offs[i], offs[i + 1]]
        while (i + len(cur) < len(offs)
               and offs[i + len(cur)] - offs[i + len(cur) - 1] == gap):
            cur.append(offs[i + len(cur)])
        if len(cur) >= min_run:
            runs.append((cur[0], gap, len(cur)))
        i += len(cur) if len(cur) >= min_run else 1
    return runs


def main():
    d = us_boot()
    strs = le_strings(d, US_LE, US_SPACE)
    print(f'LE C-strings: {len(strs)} (all in boot_strings.tsv)')
    lu = dict(strs)
    for start, gap, count in le_gap_runs([o for o, _ in strs]):
        label = ''
        for name, base, stride, n in KNOWN_LE:
            if start == base and gap == stride and count >= n - 2:
                label = f'  = {name} table'
        sample = ' / '.join(lu[o] for o in sorted(lu) if start <= o < start + gap * 3)[:100]
        print(f'LE run x{count} stride {gap:#x} at {start:#x}{label}: {sample}')

    recs = be_runs(d)
    print(f'BE records (whole image): {len(recs)} '
          f'({sum(1 for _, _, t in recs if t == "FF01")} boxes; all in boot_be.tsv)')
    # cluster: gap < 0x400 between records
    clusters = []
    cur = [recs[0]]
    for r in recs[1:]:
        if r[0] - cur[-1][0] < 0x400:
            cur.append(r)
        else:
            clusters.append(cur)
            cur = [r]
    clusters.append(cur)
    unknown = []
    for c in clusters:
        lo, hi = c[0][0], c[-1][0]
        lab = label_at(lo, hi)
        sample = ' / '.join(t.replace('<FF01>', '')[:24] for _, t, _ in c[:3])[:100]
        if lab:
            print(f'BE cluster {lo:#x}-{hi:#x} x{len(c)}: {lab}: {sample}')
        else:
            unknown.append((lo, hi, c, sample))
    print()
    if unknown:
        print(f'UNKNOWN BE clusters ({len(unknown)}) — the unexamined text:')
        for lo, hi, c, sample in unknown:
            print(f'  {lo:#x}-{hi:#x} x{len(c)}: {sample}')
    else:
        print('UNKNOWN BE clusters: none — every cluster is labeled above')


if __name__ == '__main__':
    main()
