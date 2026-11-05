"""The party marker name is centred on the width the row actually draws.

Retail BtlBuildMarkers sets x = 12 - n * 4 (n glyphs at 8 px). The patch
rewrites that count loop in place: a row the battle bridge draws VWF is
centred on its packed advances, any other row keeps the retail formula, and
the registers the rest of the function reads are left exactly as retail
left them at 0x800AA150.
"""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools/tests')]
from mips_cpu import CPU, REG  # noqa: E402

SYM = {m.group(2): int(m.group(1), 16)
       for line in (ROOT / 'build/persona.sym').read_text().splitlines()
       if (m := re.fullmatch(r'([0-9A-Fa-f]{8})\s+(\S+)', line))}
START, END = 0x800AA0F8, 0x800AA150
ROW, TEXT, S3 = 0x80100000, 0x80100100, 0x80100200


def run(codes):
    c = CPU()
    c.load(0x80010000, (ROOT / 'build/SLPS_005.00').read_bytes()[0x800:])
    c.load(0x800643C4, (ROOT / 'build/BTLP.BIN').read_bytes())
    c.load(TEXT, bytes(codes) + b'\xff' * (9 - len(codes)))
    c.write(ROW + 4, TEXT)
    c.write(ROW + 8, 8, 1)                       # the marker name row's count
    for r in range(1, 32):
        c.r[r] = 0x5A5A0000 + r
    c.r[REG['s7']], c.r[REG['s3']] = ROW, S3
    c.r[REG['sp']], c.r[REG['ra']] = 0x801FF000, 0x8000FFF0
    c.start(START)
    for _ in range(2000):
        if c.pc == END:
            return c
        c.step()
    raise AssertionError('the marker name code did not reach 0x800AA150')


class MarkerNameCentre(unittest.TestCase):
    def check_retail_state(self, c):
        want = {'a0': 0, 'a1': S3 + 4, 'a2': 0, 'a3': 0x8005D6D8,
                't0': 0x10, 't1': 8, 't3': 0xFF, 'v1': 0x20}
        for reg, value in want.items():
            self.assertEqual(c.r[REG[reg]], value, reg)
        for reg in ('s0', 's1', 's2', 's4', 's5', 's6', 'fp', 'sp'):
            self.assertEqual(c.r[REG[reg]], 0x5A5A0000 + REG[reg] if reg != 'sp' else 0x801FF000, reg)

    def test_party_names_keep_retail_width_and_centring(self):
        widths = (ROOT / 'build/sf_width.bin').read_bytes()
        # the party names as the battle stores them (from a battle RAM dump)
        for codes in ([0xb3, 0x23, 0x3a, 0xcc, 0x39, 0x23, 0x3a],    # Nao-nao
                      [0xb2, 0x23, 0x3d, 0x36],                        # Mark
                      [0xbe, 0x40, 0x36, 0x34, 0x39, 0x3a]):           # Yukino
            with self.subTest(codes=bytes(codes).hex()):
                c = run(codes)
                width = len(codes) * 8
                self.assertEqual(c.r[REG['v0']], ((24 - width) >> 1) & 0xFFFFFFFF)
                self.check_retail_state(c)

    def test_a_row_the_bridge_keeps_retail_keeps_retail_centring(self):
        codes = [0x01, 0x02, 0x03]                   # kana cells: not VWF text
        c = run(codes)
        self.assertEqual(c.r[REG['v0']], (12 - len(codes) * 4) & 0xFFFFFFFF)
        self.check_retail_state(c)


if __name__ == '__main__':
    unittest.main()
