"""Run the assembled choice pointer comparison at its exclusive pool end."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools/tests')]
from mips_cpu import CPU, REG
import btlp


class ChoiceBound(unittest.TestCase):
    def test_pool_end_is_exclusive(self):
        image = (ROOT / 'build/BTLP.BIN').read_bytes()
        base, size, dest = 0x801c0000, 0x8000, 0x801b0000
        for offset, expected in ((size - 1, base + size - 1),
                                 (size, base + 0x100),
                                 (size + 1, base + 0x100)):
            with self.subTest(offset=offset):
                cpu = CPU()
                cpu.load(btlp.B, image)
                cpu.write(base, 0x100)
                cpu.r[REG['fp']] = base
                cpu.r[REG['v1']] = size
                cpu.r[REG['v0']] = offset
                cpu.r[REG['a0']] = 0
                cpu.r[REG['s0']] = dest
                cpu.start(0x8007e300)
                cpu.run(0x8007e334, limit=30)
                self.assertEqual(cpu.read(dest), expected)


if __name__ == '__main__':
    unittest.main()
