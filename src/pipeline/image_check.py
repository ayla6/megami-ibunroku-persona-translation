"""Check that a disc image is the release this project patches.

  python src/pipeline/image_check.py <image.bin>

The patches use fixed addresses in the game's code, so they only fit the first Japanese release of
Megami Ibunroku Persona: Be Your True Mind (SLPS-00500). "Rev 1" has different code in SLPS_005.00, ADV,
BTLP, DNG, S2D, NAME, CASINO and the EXE files and is not supported.
"""
import os
import sys
import tempfile
import zlib

# Redump: Megami Ibunroku Persona - Be Your True Mind (Japan)
NAME = 'Megami Ibunroku Persona - Be Your True Mind (Japan)'
SIZE = 699705888
CRC32 = 0x360EB310
REV1_SIZE = 699672960
# Redump: Megami Ibunroku - Persona - Be Your True Mind (Japan) (Rev 1)
REV1_CRC32 = 0xFB8E5E2D


# A disc image's CRC32 is remembered by its path, size and modification
# time, so reading 700 MB happens once per image file, not once per tool
# that asks which disc it is. A changed or replaced file gets a new row.
CRC_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                         'build', 'step_cache', 'image-crc32.tsv')


def _crc_rows():
    try:
        with open(CRC_CACHE, encoding='utf-8') as f:
            return {(path, size, mtime): crc for path, size, mtime, crc
                    in (line.rstrip('\n').split('\t') for line in f if line.count('\t') == 3)}
    except OSError:
        return {}


def crc32(path):
    stat = os.stat(path)
    key = (os.path.abspath(path), str(stat.st_size), str(stat.st_mtime_ns))
    rows = _crc_rows()
    if key in rows:
        return int(rows[key], 16)
    c = 0
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 24)
            if not b:
                break
            c = zlib.crc32(b, c)
    c &= 0xFFFFFFFF
    rows = {k: v for k, v in _crc_rows().items() if k[0] != key[0]}
    rows[key] = f'{c:08X}'
    try:
        os.makedirs(os.path.dirname(CRC_CACHE), exist_ok=True)
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=os.path.dirname(CRC_CACHE),
                                         delete=False) as out:
            out.writelines('\t'.join((*k, v)) + '\n' for k, v in sorted(rows.items()))
        os.replace(out.name, CRC_CACHE)     # whole file at once: concurrent tools never see half
    except OSError:
        pass                                # no cache: the next call reads the file again
    return c


def problem(path):
    """None if the image is the supported release, else a message."""
    if not os.path.exists(path):
        return f'disc image not found: {path}'
    size = os.path.getsize(path)
    if size == REV1_SIZE:
        return (f'{path} looks like the "Rev 1" release ({size} bytes). Only the first release is supported '
                f'({SIZE} bytes, CRC32 {CRC32:08X}).')
    if size != SIZE:
        return f'{path}: {size} bytes, expected {SIZE} (single-track BIN of the first release, CRC32 {CRC32:08X}).'
    c = crc32(path)
    if c != CRC32:
        return f'{path}: CRC32 {c:08X}, expected {CRC32:08X} (a modified or different dump).'
    return None


def require(path):
    msg = problem(path)
    if msg:
        sys.exit('Wrong disc image: ' + msg)


def require_rev1(path):
    if not os.path.isfile(path):
        sys.exit(f'Wrong disc image: Rev 1 disc image not found: {path}')
    size = os.path.getsize(path)
    if size != REV1_SIZE:
        sys.exit(f'Wrong disc image: {path}: {size} bytes, expected Rev 1 {REV1_SIZE}')
    actual = crc32(path)
    if actual != REV1_CRC32:
        sys.exit(f'Wrong disc image: {path}: CRC32 {actual:08X}, expected Rev 1 {REV1_CRC32:08X}')


if __name__ == '__main__':
    msg = problem(sys.argv[1])
    print(msg or 'OK: first release of SLPS-00500 (CRC32 %08X)' % CRC32)
    sys.exit(1 if msg else 0)
