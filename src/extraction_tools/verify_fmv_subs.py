"""Byte-verify the in-engine FMV subtitle payloads on dist/Persona-TL.bin.

MOVIE.EXE plays every movie and gets the full blob (all speech, the quote
cards with their zoom ladder, the ending poems):

  - EXE/MOVIE.EXE header t_size (file offset 0x1C) == 0xE0000 + len(movie_subs.bin)
  - the blob (build/movie_subs.bin) is byte-identical in EXE/MOVIE.EXE at
    the RAM home offset (0x80160000 - 0x80080000 + 0x800)
  - no obsolete raw plate textures; compiled-ink lookup RAM stays clear

OPEN.EXE plays only the opening quote, and the resident loads OPEN.BIN (the
title's pack) at 0x80180000 immediately before it starts, so its reduced
payload (build/movie_subs_open.bin) must end below that address:

  - EXE/OPEN.EXE header t_size == 0xE0000 + len(movie_subs_open.bin)
  - the reduced blob is byte-identical in EXE/OPEN.EXE at the same home
  - the payload ends below 0x80180000
  - compiled-ink lookup RAM stays clear

Hooks: MOVIE.EXE 0x80080FBC -> jal 0x80160000,
       OPEN.EXE 0x80088F90 -> jal 0x80160008,
       frame trampolines 0x800813B4 -> 0x80161FE0 and
       0x80089410 -> 0x80161FC0.

Run: python src/extraction_tools/verify_fmv_subs.py
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'injection_tools'))
from build_disc import Disc  # noqa: E402

disc = Disc(os.path.join(ROOT, 'dist', 'Persona-TL.bin'))
pvd = disc.user(16)
root_lba, = struct.unpack_from('<I', pvd, 158)
root_size, = struct.unpack_from('<I', pvd, 166)
entries = {p.upper(): (e, s) for p, e, s, *_ in disc.walk(root_lba, root_size)}

def read_file(path):
    ext, size = entries[path.upper()]
    return b''.join(disc.user(ext + n) for n in range((size + 2047) // 2048))[:size]

movie = read_file('EXE/MOVIE.EXE')
openg = read_file('EXE/OPEN.EXE')
blob = open(os.path.join(ROOT, 'build', 'movie_subs.bin'), 'rb').read()
open_blob = open(os.path.join(ROOT, 'build', 'movie_subs_open.bin'), 'rb').read()

fail = 0
def check(name, cond, detail=''):
    global fail
    print(('PASS ' if cond else 'FAIL ') + name + (' - ' + detail if detail and not cond else ''))
    if not cond:
        fail = 1

want_tsize = 0xE0000 + len(blob)
tsize, = struct.unpack_from('<I', movie, 0x1C)
check('MOVIE.EXE t_size covers blob', tsize == want_tsize,
      f't_size {tsize:#x} want {want_tsize:#x}')

want_open_tsize = 0xE0000 + len(open_blob)
open_tsize, = struct.unpack_from('<I', openg, 0x1C)
check('OPEN.EXE t_size covers reduced blob', open_tsize == want_open_tsize,
      f't_size {open_tsize:#x} want {want_open_tsize:#x}')

blob_off = 0x80160000 - 0x80080000 + 0x800
check('blob byte-identical in MOVIE.EXE', movie[blob_off:blob_off + len(blob)] == blob,
      f'at file offset {blob_off:#x}')
check('reduced blob byte-identical in OPEN.EXE',
      openg[blob_off:blob_off + len(open_blob)] == open_blob,
      f'at file offset {blob_off:#x}')

open_end = 0x80160000 + len(open_blob)
check('reduced blob ends below OPEN.BIN', open_end <= 0x80180000,
      f'ends {open_end:#x}')
# CdLoadPsExe's CdReadPolled() rounds t_size up to whole sectors, so the
# loader writes past t_size to the next 2048-byte boundary.
open_read = (open_tsize + 2047) & ~2047
check('sector-rounded OPEN.EXE load ends below OPEN.BIN',
      0x80080000 + open_read <= 0x80180000,
      f'rounded {open_tsize:#x}->{open_read:#x}, ends {0x80080000 + open_read:#x}')

tex = open(os.path.join(ROOT, 'build', 'movie_subs_tex.bin'), 'rb').read()
check('no obsolete raw plate texture payload', not tex)
scratch_start = 0x80128000 - 0x80080000 + 0x800
scratch_end = 0x80130000 - 0x80080000 + 0x800
meta_start = 0x8013FF00 - 0x80080000 + 0x800
meta_end = meta_start + 8 * 16
for name, data, payload in (('MOVIE.EXE', movie, blob), ('OPEN.EXE', openg, open_blob)):
    check(name + ' compiled-ink lookup RAM is clear in load image',
          not any(data[scratch_start:scratch_end]))
    check(name + ' compiled-ink cache metadata is clear in load image',
          not any(data[meta_start:meta_end]))
    check(name + ' renderer data format is FMS4',
          struct.unpack_from('<I', payload, 0x2000)[0] == 0x34534D46)

aux = open(os.path.join(ROOT, 'build', 'movie_subs_open_zoom.bin'), 'rb').read()
aux_off = scratch_end
check('OPEN.EXE auxiliary zoom levels are byte-identical', openg[aux_off:aux_off + len(aux)] == aux)
check('auxiliary zoom levels stay between ink lookups and metadata',
      aux_off + len(aux) <= meta_start)
check('MOVIE.EXE does not load unused auxiliary zoom data', not any(movie[aux_off:meta_start]))

for name, data in (('MOVIE.EXE', movie), ('OPEN.EXE', openg)):
    for number in range(39):
        rec, = struct.unpack_from('<I', data, blob_off + 0x2018 + number * 4)
        while rec:
            at = rec - 0x80080000 + 0x800
            first, last, lines, flags = struct.unpack_from('<HHBB', data, at)
            if first == 0xFFFF:
                break
            if flags & 0x10:
                patch, = struct.unpack_from('<I', data, at + 8)
                patch_off = patch - 0x80080000 + 0x800
                count, = struct.unpack_from('<H', data, patch_off + 776)
                width, = struct.unpack_from('<H', data, at + 26)
                stride = (((width + 3) & ~3) + 8) * data[at + 7] + 4
                for level in range(count):
                    ptr, = struct.unpack_from('<I', data, patch_off + 780 + 4 * level)
                    begin = ptr - 0x80080000 + 0x800
                    within_blob = blob_off + 0x2000 <= begin and begin + stride <= len(data)
                    within_aux = name == 'OPEN.EXE' and aux_off <= begin and begin + stride <= aux_off + len(aux)
                    check(f'{name} movie {number:02X} zoom level {level} has a safe source',
                          ptr % 4 == 0 and (within_blob or within_aux))
            rec += 32 + 8 * lines

for name, data, off in (('MOVIE.EXE hook', movie, 0x80080FBC - 0x80080000 + 0x800),
                        ('OPEN.EXE hook', openg, 0x80088F90 - 0x80080000 + 0x800)):
    addr = 0x80160000 if 'MOVIE' in name else 0x80160008
    want = 0x0C000000 | ((addr >> 2) & 0x3FFFFFF)   # jal
    got, = struct.unpack_from('<I', data, off)
    check(name + ' jal-encoded', got == want, f'got {got:#010x} want {want:#010x}')

for name, data, address, target in (
        ('MOVIE.EXE idle CD-poll hook', movie, 0x80081374, 0x80160010),
        ('OPEN.EXE idle CD-poll hook', openg, 0x800893BC, 0x80160018)):
    at = address - 0x80080000 + 0x800
    got, = struct.unpack_from('<I', data, at)
    want = 0x0C000000 | ((target >> 2) & 0x3FFFFFF)
    check(name + ' jal-encoded', got == want)
    with open(os.path.join(ROOT, 'data', 'psx', 'EXE', name.split()[0]), 'rb') as retail_file:
        retail = retail_file.read()
    check(name + ' preserves original argument delay slot', data[at + 4:at + 8] == retail[at + 4:at + 8])

# The stream-frame trampolines live at the end of the renderer code; their
# addresses move whenever the renderer grows, so verify the assembled jumps
# (not just the source constants).
for name, data, addr, target in (
        ('MOVIE.EXE frame trampoline', movie, 0x800813B4, 0x80161FE0),
        ('OPEN.EXE frame trampoline', openg, 0x80089410, 0x80161FC0)):
    off = addr - 0x80080000 + 0x800
    want = 0x08000000 | ((target >> 2) & 0x3FFFFFF)   # j
    got, = struct.unpack_from('<I', data, off)
    check(name + ' j-encoded', got == want, f'got {got:#010x} want {want:#010x}')

sys.exit(fail)
