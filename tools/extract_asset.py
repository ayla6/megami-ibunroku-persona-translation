"""Browse/extract disc files and TIM images, including images inside MES entries.

Examples:
  python tools/extract_asset.py list-files
  python tools/extract_asset.py extract-file ADV/MES.BIN --output scene.bin
  python tools/extract_asset.py list-images ADV/BST.BIN
  python tools/extract_asset.py list-images ADV/MES.BIN --entry 11
  python tools/extract_asset.py export-image ADV/MES.BIN --entry 11 --member 1 --output sheet.png

Lists are TSV. Exports refuse to overwrite files. Movie file exports retain
raw sectors; unsupported inner asset formats can still be extracted as files.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
import struct
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
import toolpath
import disc_data
import image_replacements as images
import mescodec
import modpack
import tim
from format_edits import mes_entry


@dataclass(frozen=True)
class AssetImage:
    offset: int
    width: int
    height: int
    bpp: int


def image_records(data: bytes) -> list[AssetImage]:
    result: list[AssetImage] = []
    end = 0
    for at, info in tim.find_tims(data):
        if at < end:
            continue
        if info['h'] <= 0 or info['px_w'] <= 0 or info['end'] > len(data):
            continue
        if info['end']-info['at'] != info['w']*2*info['h']:
            continue
        result.append(AssetImage(at, info['px_w'], info['h'], info['bpp']))
        end = info['end']
    return result


def read_container(path: Path, entry: int | None) -> bytes:
    data = path.read_bytes()
    if entry is None:
        return data
    return mescodec.decode(mes_entry(data, entry)[8:])[0]


def new_output(path: Path) -> None:
    if path.exists():
        raise ValueError(f'refusing to overwrite {path}')
    path.parent.mkdir(parents=True, exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    files = sub.add_parser('list-files', help='list every file in the original disc')
    files.add_argument('--image', type=Path)
    extract = sub.add_parser('extract-file', help='extract any disc file by its listed path')
    extract.add_argument('file')
    extract.add_argument('--image', type=Path)
    extract.add_argument('--output', type=Path, required=True)
    for command in ('list-images', 'export-image'):
        image = sub.add_parser(command, help='list/export TIM art from an extracted file or MES entry')
        image.add_argument('file', type=Path)
        image.add_argument('--entry', type=int, help='decode this MES archive entry first')
        if command == 'export-image':
            select = image.add_mutually_exclusive_group()
            select.add_argument('--member', type=int, default=0, help='image index printed by list-images')
            select.add_argument('--offset', type=lambda value: int(value,0), help='TIM offset in the selected file/entry')
            image.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in ('list-files', 'extract-file'):
            source = modpack.Source(str(args.image or disc_data.resolve_psx()))
            try:
                if args.command == 'list-files':
                    print('file\tbytes\tsector')
                    for path, (sector, size) in sorted(source.entries.items()):
                        print(f'{path}\t{size}\t{sector}')
                else:
                    path = args.file.upper()
                    if path not in source.entries:
                        raise ValueError(f'{path} is not on this disc; use list-files')
                    new_output(args.output)
                    args.output.write_bytes(source.read(path, path.endswith('.STR')))
                    print(args.output)
            finally:
                source.close()
            return 0
        path = args.file if args.file.is_file() else images.RETAIL/args.file
        data = read_container(path, args.entry)
        records = image_records(data)
        if args.command == 'list-images':
            print('member\toffset\twidth\theight\tbpp')
            for index, record in enumerate(records):
                print(f'{index}\t{record.offset:#x}\t{record.width}\t{record.height}\t{record.bpp}')
        else:
            if args.offset is not None:
                at = args.offset
            else:
                if not 0 <= args.member < len(records):
                    raise ValueError('image index outside the listing; use list-images first')
                at = records[args.member].offset
            image = images.tim_image(data, at)
            new_output(args.output)
            image.save(args.output, format='PNG')
            print(args.output)
        return 0
    except (OSError, ValueError, IndexError, KeyError, struct.error) as error:
        parser.exit(1, f'extract_asset: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
