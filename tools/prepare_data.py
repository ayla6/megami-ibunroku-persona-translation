#!/usr/bin/env python3
"""Find the game discs under data/discs/ and extract the missing data trees.

  python tools/prepare_data.py              extract every disc that is present
  python tools/prepare_data.py --list       show what is recognized, extract nothing
  python tools/prepare_data.py --only psx   extract only that kind
  python tools/prepare_data.py --force      re-extract even if the tree is complete

Recognized kinds are `psx`, `psx-rev1`, `psp-jp` and `psp-us`; they map to
data/psx, data/psx_rev1, data/psp_jp and data/psp_us. Discs may have any file
name and sit in any subdirectory of data/discs/. Identification is from the
image itself (size/CRC32 for PSX, ISO9660 + PARAM.SFO DISC_ID for PSP), so no
names are read from the folder or file name.

The build calls the same discovery automatically: it finds the Rev 0 image
when the default path is absent, extracts data/psx when it is missing, and
extracts data/psp_us when a porting build needs it. This command is for doing
that ahead of time, and for the Rev 1 and PSP-JP trees the build does not
consume on a normal run.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'injection_tools'))
import disc_data  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--discs', default=str(disc_data.DISCS),
                        help='folder to search (default: data/discs)')
    parser.add_argument('--only', metavar='KIND',
                        help='comma-separated kinds: psx,psx-rev1,psp-jp,psp-us')
    parser.add_argument('--force', action='store_true',
                        help='re-extract even when the target tree is complete')
    parser.add_argument('--list', action='store_true',
                        help='list recognized discs and exit')
    args = parser.parse_args(argv)

    discs_dir = Path(args.discs)
    if args.list:
        discs = disc_data.discover(discs_dir)
        if not discs:
            print(f'prepare_data: no supported discs under {discs_dir}')
            return 0
        for disc in discs:
            print(f'{disc.kind:9} {disc.label}\n          {disc.path}')
        return 0

    only = None
    if args.only:
        only = {kind.strip() for kind in args.only.split(',') if kind.strip()}
    disc_data.prepare(discs_dir, only=only, force=args.force)
    return 0


if __name__ == '__main__':
    sys.exit(main())
