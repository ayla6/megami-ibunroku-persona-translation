"""Pack-wide u16 text survey (both PSP regions, read-only).

Current extractors cover pack/E?.BIN, pack/talk/*.BIN, BOOT.BIN and ENDALL
images; everything else is unexamined. This tool scans every remaining pack
file for stride-aligned u16 string tables (LE/BE, 0x10 stride, the shape PSP
menus and race lists take) plus printable ASCII, and reports where
translatable text lives that no extractor reads yet.

Covered files (E/talk/BOOT/ENDALL-images) and model containers (MIG magic)
are skipped. Files over CAP_MB are sampled head-only and marked as such.

Usage: python src/extraction_tools/psp/survey.py [min_run]
"""
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'extraction_tools', 'psp'))
from codec import US_MAP  # noqa: E402
from tables import jp_map, stride_runs  # noqa: E402

PACK = {'us': os.path.join(ROOT, 'data', 'psp_us', 'PSP_GAME', 'USRDIR', 'pack'),
        'jp': os.path.join(ROOT, 'data', 'psp_jp', 'PSP_GAME', 'USRDIR', 'pack')}
SKIP_DIRS = ('talk',)
SKIP_FILES = {'E0.BIN', 'E1.BIN', 'E2.BIN', 'E3.BIN', 'E4.BIN', 'ENDALL.BIN'}
CAP_MB = 8
ASCII_RE = re.compile(rb'[\x20-\x7e]{8,}')


def files(region):
    base = PACK[region]
    for dirpath, _dirs, fns in os.walk(base):
        rel = os.path.relpath(dirpath, base)
        if rel.split(os.sep)[0] in SKIP_DIRS:
            continue
        for fn in sorted(fns):
            if fn in SKIP_FILES:
                continue
            yield os.path.join(dirpath, fn)


def summary(path, region, glyphs, min_run):
    try:
        with open(path, 'rb') as f:
            head = f.read(CAP_MB * 1024 * 1024)
            f.seek(0, os.SEEK_END)
            size = f.tell()
    except OSError as ex:
        return {'file': path, 'error': str(ex)}
    if head[:12].rstrip(b'.0123456789') in (b'MIG',):
        return {'file': path, 'size': size, 'kind': 'model(MIG)', 'runs': []}
    data = head
    sampled = size > len(head)
    runs = []
    for endian in ('<', '>'):
        for off, texts in stride_runs(data, stride=0x10, min_run=min_run,
                                      endian=endian, glyphs=glyphs):
            runs.append((endian, off, len(texts), texts[:4]))
    ascii_n = len(ASCII_RE.findall(data))
    return {'file': path, 'size': size, 'sampled': sampled,
            'ascii_runs': ascii_n, 'runs': sorted(runs, key=lambda r: -r[2])[:6]}


def main():
    min_run = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    glyphs = {'us': US_MAP, 'jp': dict(jp_map())}
    glyphs['jp'].setdefault(0x8140, ' ')
    print('file\tregion\tsize\tascii\truns')
    total = 0
    for region in ('us', 'jp'):
        for path in files(region):
            rel = os.path.relpath(path, PACK[region])
            rep = summary(path, region, glyphs[region], min_run)
            if 'error' in rep:
                print(f'{rel}\t{region}\tERR {rep["error"]}')
                continue
            total += 1
            tag = rep.get('kind', '')
            smp = ' (head-sampled)' if rep.get('sampled') else ''
            print(f'{rel}\t{region}\t{rep["size"]}{smp}\t{rep.get("ascii_runs", 0)}\t{tag}')
            for endian, off, n, sample in rep['runs']:
                e = 'LE' if endian == '<' else 'BE'
                print(f'    {e} run x{n} at {off:#x}: {" / ".join(sample)[:160]}')
    print(f'{total} files scanned')


if __name__ == '__main__':
    main()
