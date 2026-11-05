"""Split the three-way box alignment into the two replicable mappings.

align.tsv (`align.py`) needs all three disc sets at once. The split
lets verifiers check each leg with the minimal ISOs:

  python src/extraction_tools/matching/split_maps.py split
    translation/generated_mappings/map_jp_psx.tsv   file,entry,psx_box,jp_box,kind
      structure leg: verifiable with PSX + PSP-JP discs only
    translation/generated_mappings/map_us_jp.tsv    file,entry,jp_box,us_box,kind
      wording leg: verifiable with PSP-JP + PSP-US discs only (saved US_MAP)

Both files are MACHINE-GENERATED correspondences; extracted PSP text is stored separately.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'injection_tools'))
import toolbelt  # noqa: E402
import strlib  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
MAPPINGS = toolbelt.MAPPINGS
STRUCT_OUT = os.path.join(MAPPINGS, 'map_jp_psx.tsv')
WORD_OUT = os.path.join(MAPPINGS, 'map_us_jp.tsv')
NL = chr(10)


def cmd_split():
    cols = strlib.tsv_cols(os.path.join(MAPPINGS, 'align.tsv'))
    need = ('file', 'entry', 'psx_box', 'jp_box', 'us_box', 'kind')
    missing = [c for c in need if c not in cols]
    if missing:
        raise ValueError(f'align.tsv: header lacks {missing}')
    struct_out = ['file\tentry\tpsx_box\tjp_box\tkind']
    word_out = ['file\tentry\tjp_box\tus_box\tkind']
    for r in strlib.tsv_rows(os.path.join(MAPPINGS, 'align.tsv'), required=need):
        struct_out.append(TAB.join([r['file'], r['entry'], r['psx_box'],
                                    r['jp_box'], r['kind']]))
        word_out.append(TAB.join([r['file'], r['entry'], r['jp_box'],
                                   r['us_box'], r['kind']]))
    os.makedirs(MAPPINGS, exist_ok=True)
    open(STRUCT_OUT, 'w', encoding='utf-8', newline=NL).write(NL.join(struct_out))
    open(WORD_OUT, 'w', encoding='utf-8', newline=NL).write(NL.join(word_out))
    print(f'maps: {len(struct_out) - 1} rows -> translation/generated_mappings/map_jp_psx.tsv, map_us_jp.tsv')


TAB = chr(9)


if __name__ == '__main__':
    if (sys.argv[1:] or ['split'])[0] == 'split':
        cmd_split()
    else:
        raise SystemExit(__doc__)
