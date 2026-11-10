"""Exercise the assembled battle string uploader's staging reservations."""
from pathlib import Path
import struct
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
COUNTER = 0x800EBE44
QUEUE = 0x80066620
RETURN = 0x801F0000


class StringStaging(unittest.TestCase):
    def test_reserves_only_queued_cells(self):
        resident = ROOT / 'build/SLPS_005.00'
        symbols = ROOT / 'build/persona.sym'
        if not resident.exists() or not symbols.exists():
            self.skipTest('requires assembled resident image and symbols')
        blob = resident.read_bytes()
        base, size = struct.unpack_from('<II', blob, 0x18)
        entries = {line.split()[1]: int(line.split()[0], 16)
                   for line in symbols.read_text().splitlines()
                   if len(line.split()) == 2}
        c = CPU()
        c.load(base, blob[0x800:0x800 + size])
        c.write(QUEUE, 0x03E00008)  # jr ra: queue is outside this unit test
        c.write(QUEUE + 4, 0)
        c.r[REG['sp']] = 0x801E0000
        c.write(0x801D0004, 0)
        c.write(0x801D0008, 0)
        expected = 0
        for last in (2, 3, 2, 4, 1, 2):
            c.r[REG['a0']] = 0x801D0004
            c.r[REG['a1']] = last
            c.r[REG['ra']] = RETURN
            c.start(entries['btlp_str16_flush'])
            c.run(RETURN, limit=1000)
            expected += last + 1
            self.assertEqual(c.read(COUNTER), expected)
        self.assertLess(expected, (0x800EEB48 - 0x800EBE48) // 128)


if __name__ == '__main__':
    unittest.main()
