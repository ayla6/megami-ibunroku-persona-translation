"""Map PSP BOOT location labels to PSX S2D names where they fit the PSX field."""
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
import toolbelt  # noqa: E402
import etext  # noqa: E402
import s2dnames  # noqa: E402
import vwf_wrap  # noqa: E402

MAP = os.path.join(toolbelt.SOURCE_MAPPINGS, 'boot_s2dnames.tsv')
US_TEXT = os.path.join(ROOT, 'data', 'cache', 'boot_strings_us.tsv')
OUT = os.path.join(ROOT, 'translation', 'generated', 'S2D.BIN', 'S2DNAMES.tsv')


def main():
    boot = {}
    for row in csv.DictReader(open(US_TEXT, encoding='utf-8'), delimiter='\t'):
        boot[int(row['offset'], 16)] = row['text']
    source = open(os.path.join(ROOT, 'data', 'psx', 'S2D.BIN'), 'rb').read()
    records = s2dnames.names(source)
    names = [etext.decode(source[a - s2dnames.B:e - s2dnames.B - 2]).replace('<00>', '')
             for a, e in records]
    result = []
    skipped = []
    for row in csv.DictReader(open(MAP, encoding='utf-8'), delimiter='\t'):
        idx = int(row['psx_idx'])
        us = boot[int(row['us_boot_offset'], 16)]
        ja = names[idx]
        try:
            px = vwf_wrap.text_width(us)
            if px > s2dnames.LABEL_LIMIT:
                raise ValueError(f'{px}px exceeds the {s2dnames.LABEL_LIMIT}px label limit')
            encoded = etext.encode(us, end=None) + bytes((0xFF, 0x01))
        except (KeyError, SystemExit, ValueError) as ex:
            skipped.append((idx, ja, us, str(ex)))
            continue
        result.append((idx, f'{records[idx][0]:08X}', ja, us))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8', newline='') as out:
        w = csv.writer(out, delimiter='\t', lineterminator='\n')
        w.writerow(('idx', 'ram', 'ja', 'en'))
        w.writerows(result)
    print(f'S2D labels: {len(result)} PSP-US ports fit automatically; {len(skipped)} stay manual -> {OUT}')
    for idx, ja, en, why in skipped[:15]:
        print(f'  {idx}: {ja} -> {en!r} ({why})')


if __name__ == '__main__':
    main()
