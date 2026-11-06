"""Start skips the movie MOVIE.EXE is playing.

The frame loop already calls PadRead(1) at 0x80080FBC and throws the result
away. The VSync call right after it still has the pad word in v0, so the
patch routes that call through a stub: when Start is held it raises
g_movie_end, the same flag StrGetReadyFrame raises two frames from the end.
The loop leaves through its ordinary end-of-stream path, so the movie-after
table and teardown still run.

The stub lives in the zero padding the EXE already carries below the
subtitle blob, so only the VSync call changes inside the retail image.
"""
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools/tests')]
from mips_cpu import CPU, REG  # noqa: E402

BASE = 0x80080000 - 0x800          # file offset 0, i.e. MOVIE_EXE_ADDR
HOOK = 0x80080FC4                  # jal VSync
HOOK_END = 0x80080FCC              # return address of the hook
VSYNC = 0x8008AD88
STUB = 0x8015FF00
GP = 0x800A929C                    # g_movie_end at gp+0
G_MOVIE_END = GP
STACK = 0x801FF000
PAD_START = 0x0800
PAD_CROSS = 0x0040
PAD_SELECT = 0x0100

# The stub, exactly as assembled.
STUB_WORDS = (
    0x27BDFFE8,   # addiu sp, sp, -0x18
    0xAFBF0014,   # sw    ra, 0x14(sp)
    0x30480800,   # andi  t0, v0, 0x800
    0x11000003,   # beqz  t0, 0x8015ff1c
    0x00000000,   # nop   (delay slot)
    0x34080001,   # ori   t0, zero, 1
    0xAF880000,   # sw    t0, (gp)
    0x0C022B62,   # jal   0x8008ad88 (VSync)
    0x00002021,   # move  a0, zero (delay slot)
    0x8FBF0014,   # lw    ra, 0x14(sp)
    0x27BD0018,   # addiu sp, sp, 0x18
    0x03E00008,   # jr    ra
    0x00000000,   # nop   (delay slot)
)


class SkipFmv(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        armips = ROOT / 'external_tools/armips/armips'
        if not armips.exists():
            raise unittest.SkipTest('requires armips')
        cls.tmp = tempfile.TemporaryDirectory(prefix='skipfmv-', dir='/tmp/opencode')
        work = Path(cls.tmp.name)
        source = work / 'fixture.asm'
        source.write_text(
            '.psx\n'
            f'.include "{ROOT / "src/asm/common/addresses.inc"}"\n'
            f'.open "{ROOT / "data/psx/EXE/MOVIE.EXE"}", '
            f'"{work / "MOVIE.EXE"}", MOVIE_EXE_ADDR\n'
            f'.include "{ROOT / "src/asm/qol/skip_fmv_movie.asm"}"\n'
            '.close\n')
        symbols = work / 'fixture.sym'
        result = subprocess.run([str(armips), str(source), '-sym2', str(symbols),
                                 '-erroronwarning'], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.image = (work / 'MOVIE.EXE').read_bytes()
        cls.retail = (ROOT / 'data/psx/EXE/MOVIE.EXE').read_bytes()
        cls.symbols = {}
        for line in symbols.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and re.fullmatch(r'[0-9A-Fa-f]{8}', parts[0]):
                cls.symbols[parts[1]] = int(parts[0], 16)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def word(self, address):
        return struct.unpack('<I', self.image[address - BASE:address - BASE + 4])[0]

    def test_the_hook_is_the_only_change_in_the_retail_image(self):
        changed = {BASE + i for i in range(0, len(self.retail), 4)
                   if self.image[i:i + 4] != self.retail[i:i + 4]}
        self.assertEqual(changed, {HOOK})
        self.assertEqual(self.word(HOOK), 0x0C000000 | ((STUB >> 2) & 0x03FFFFFF))
        # the delay slot that hands the stub a0 = 0 is retail's and stays
        self.assertEqual(self.word(HOOK + 4), 0x00002021)

    def test_the_stub_is_in_the_loaded_padding(self):
        for index, expected in enumerate(STUB_WORDS):
            self.assertEqual(self.word(STUB + 4 * index), expected,
                             f'{STUB + 4 * index:#x}')
        # nothing after the stub: the file ends where it ends, so the rest
        # of the padding stays zero and the EXE does not grow at the tail
        self.assertEqual(len(self.image) - (STUB - BASE + len(STUB_WORDS) * 4), 0)
        self.assertEqual(self.symbols['mov_vsync_call'], HOOK)
        self.assertEqual(self.symbols['mov_skip_stub'], STUB)
        self.assertEqual(self.symbols['mov_pad_start'], PAD_START)

    def test_start_raises_the_end_flag(self):
        for pad, expected in ((PAD_START, 1), (0, 0),
                              (PAD_CROSS, 0), (PAD_SELECT, 0),
                              (PAD_START | PAD_CROSS, 1)):
            with self.subTest(pad=pad):
                self.assertEqual(self.skip(pad), expected)

    def skip(self, pad):
        cpu = CPU()
        cpu.load(BASE, self.image)
        cpu.write(VSYNC, 0x03E00008)        # jr ra: VSync returns at once
        cpu.write(VSYNC + 4, 0)
        cpu.write(G_MOVIE_END, 0)
        cpu.r[REG['gp']] = GP
        cpu.r[REG['sp']] = STACK
        cpu.r[REG['v0']] = pad              # PadRead's word
        cpu.start(HOOK)
        cpu.run(HOOK_END, limit=100)
        return cpu.read(G_MOVIE_END, 4)


if __name__ == '__main__':
    unittest.main()
