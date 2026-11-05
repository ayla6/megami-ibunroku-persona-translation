"""Inventory of text-like data in every disc file (not only the extracted ones).

  python src/extraction_tools/psx/scan_text.py <image.bin> [max_mb]

For each file below max_mb (default 3) counts game-encoded strings: a run of >= 6 text
tokens (byte < 0x80, or 0x80-0x87 + 1 byte) ending in a terminator FF01/FF02/FFF5/FFFC,
using the glyph map to require mostly known kana/kanji. Writes a local inventory under `scratch/` (it indexes files, it
is not per-file text - extracted_text holds only text units).
"""
import csv
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
import extract as ex  # noqa: E402

TERMS = {(0xFF, 0x01), (0xFF, 0x02), (0xFF, 0xF5), (0xFF, 0xFC)}


def count_strings(d):
    n = tot = 0
    i = d.find(b'\xff')
    while i != -1 and i + 1 < len(d):
        if (d[i], d[i + 1]) in TERMS:
            j, toks = i, 0
            while j > 0 and toks < 40:
                if j >= 2 and 0x80 <= d[j - 2] <= 0x87:
                    j -= 2
                elif d[j - 1] < 0x80 and not (j >= 2 and 0x80 <= d[j - 2] <= 0x87):
                    j -= 1
                else:
                    break
                toks += 1
            if toks >= 6:
                n += 1
                tot += i - j
        i = d.find(b'\xff', i + 2)
    return n, tot


def main():
    img = sys.argv[1]
    maxb = int(float(sys.argv[2]) * 1_000_000) if len(sys.argv) > 2 else 3_000_000
    res = []
    with open(img, 'rb') as f:
        pvd = ex.read_sectors(f, 16, 2048)
        rl, = struct.unpack_from('<I', pvd, 158)
        rs, = struct.unpack_from('<I', pvd, 166)
        for p, l, s in ex.walk(f, rl, rs):
            if p.endswith(('.VB', '.STR')) or s > maxb:
                continue
            n, t = count_strings(ex.read_sectors(f, l, s))
            if n >= 5:
                res.append((n, t, p, s))
    res.sort(reverse=True)
    out = os.path.join(ROOT, 'scratch', 'text_sources.tsv')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(('file', 'string_count', 'text_bytes', 'file_size'))
        w.writerows((p, n, t, s) for n, t, p, s in res)
    for n, t, p, s in res[:45]:
        print(f'{n:6d} {t:8d}  {p:22s} {s}')
    print(len(res), 'files')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
