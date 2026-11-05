#!/usr/bin/env python3
"""Re-extract every side of every disc file - one command.

  python tools/extract_all.py            everything, in order
  python tools/extract_all.py psx        the PSX side only
  python tools/extract_all.py psp        both PSP sides only
  python tools/extract_all.py maps       the unit pair maps only

Stages (each is a repo tool; this only runs them in order and fails loud):

  psx   src/extraction_tools/psx/extract_text_all.py
        -> data/extracted_text/psx/<rel>.tsv
  psp   src/extraction_tools/psp/eboot.py
        -> data/extracted_text/psp_{jp,us}/EBOOT.tsv
        src/extraction_tools/psp/text.py cache|talk-slots|dng
        src/extraction_tools/psp/end_images.py transcript (ENDALL: pixels, transcribed)
        -> data/extracted_text/psp_{jp,us}/pack/...
  maps  src/extraction_tools/matching/boot_pairs.py --apply
        -> translation/generated_mappings/psp_pairs.tsv (the PSP-US <-> PSP-JP unit pairs)

Every stage rewrites its outputs from the discs; nothing is incremental,
so a full re-extract is exactly this command and nothing else.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STAGES = {
    'psx': [('src/extraction_tools/psx/extract_text_all.py', ())],
    'psp': [('src/extraction_tools/psp/eboot.py', ()),
            ('src/extraction_tools/psp/text.py', ('cache',)),
            ('src/extraction_tools/psp/text.py', ('talk-slots',)),
            ('src/extraction_tools/psp/text.py', ('dng',)),
            ('src/extraction_tools/psp/end_images.py', ('transcript',))],
    'maps': [('src/extraction_tools/matching/boot_pairs.py', ('--apply',))],
}
ORDER = ('psx', 'psp', 'maps')


def rows_in(region):
    base = os.path.join(ROOT, 'data', 'extracted_text', region)
    n = 0
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            if f.endswith('.tsv'):
                with open(os.path.join(dirpath, f), encoding='utf-8') as fh:
                    n += max(sum(1 for line in fh) - 1, 0)
    return n


def main():
    want = sys.argv[1:] or list(ORDER)
    for w in want:
        if w not in STAGES:
            sys.exit(f'extract_all: unknown stage {w!r} ({" ".join(ORDER)})')
    hole_stages = 0
    for stage in ORDER:
        if stage not in want:
            continue
        for script, args in STAGES[stage]:
            print(f'extract_all: {stage} <- {script} {" ".join(args)}'.rstrip())
            r = subprocess.run([sys.executable, os.path.join(ROOT, script), *args],
                               stderr=subprocess.PIPE, text=True)
            if r.stderr:
                sys.stderr.write(r.stderr)
            if not r.returncode:
                continue
            if 'glyph-map holes' in r.stderr:
                # the stage wrote its rows and printed the hole worklist:
                # a glyph map to fix, not an extraction failure
                hole_stages += 1
                print(f'extract_all: {script} {" ".join(args)} extracted '
                      f'({r.returncode}) with glyph-map holes listed above')
            else:
                sys.exit(f'extract_all: {script} {" ".join(args)} failed '
                         f'({r.returncode})')
    print('extract_all: rows ' + '  '.join(
        f'{region}={rows_in(region)}' for region in ('psx', 'psp_jp', 'psp_us')))
    if hole_stages:
        print(f'extract_all: {hole_stages} stage(s) met glyph-map holes - '
              f'every row is extracted, the codes above need mapping')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
