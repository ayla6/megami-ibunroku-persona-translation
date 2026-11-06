"""Execute the built map-screen title hook on the R3000.

The hook compares the map pack's 20-byte name field against the shared title
table and hands BgMapInit the full PSP wording. This test drives the assembled
code with mips_cpu, which models the R3000 load delay - the exact hazard that
once made every Japanese-keyed field miss and fall back to retail.

Run after assembly:
    python -m unittest discover -s tools/tests -p test_map_title.py -v
"""
from pathlib import Path
import re
import struct
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
DNG_BASE = 0x800643C4
ENTRY = 0x80096D2C
FALLBACK = 0x80096D34
PACK = 0x801DD000
CELLS = 0x800A0730
BZERO = 0x800412FC
BGMAP_INIT = 0x800765C4
RETURN = 0x801F0000
FIELD_OFF = 0x100


class BuiltMapTitle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [ROOT / 'build' / name for name in
                 ('DNG.BIN', 'persona.sym', 'dng_titles.bin')]
        if not all(p.exists() for p in paths):
            raise unittest.SkipTest('requires assembled map-title output')
        cls.dng, cls.title = paths[0].read_bytes(), paths[2].read_bytes()
        cls.sym = {}
        for line in paths[1].read_text(encoding='utf-8').splitlines():
            m = re.fullmatch(r'([0-9A-Fa-f]{8}) (\w+)', line)
            if m:
                cls.sym[m[2]] = int(m[1], 16)
        if 'dng_title_idx' not in cls.sym:
            raise unittest.SkipTest('build predates map-title hook')
        idx, blob = cls.sym['dng_title_idx'], cls.sym['dng_title_blob']
        count, rem = divmod(blob - idx, 24)
        if rem or not count:
            raise AssertionError('invalid title table bounds')
        cls.rows = []
        for i in range(count):
            entry = cls.title[i * 24:(i + 1) * 24]
            key = entry[:20]
            width = entry[20]
            offset = struct.unpack_from('<H', entry, 22)[0]
            start = (blob - idx) + offset
            end = cls.title.index(b'\xff\x01', start) + 2
            cls.rows.append((key, width, cls.title[start:end]))

    def machine(self, key):
        """A map pack whose entry 0 names the field that holds `key`."""
        c = CPU()
        c.load(DNG_BASE, self.dng)
        pack = bytearray(FIELD_OFF + len(key))
        struct.pack_into('<I', pack, 8, FIELD_OFF)   # entry table: map 0
        pack[FIELD_OFF:FIELD_OFF + len(key)] = key
        c.load(PACK, bytes(pack))
        c.r[REG['sp']], c.r[REG['ra']] = 0x801CF000, RETURN
        c.r[REG['a0']] = 0
        return c

    def execute(self, c):
        calls = []

        def intercept(cpu):
            if cpu.pc == FALLBACK:
                calls.append(('fallback',))
                cpu.pc, cpu.next_pc = RETURN, RETURN + 4
                return True
            if cpu.pc == BZERO:
                a0, a1 = cpu.r[REG['a0']], cpu.r[REG['a1']]
                for i in range(a1):
                    cpu.write(a0 + i, 0, 1)
                ret = cpu.r[REG['ra']]
                cpu.pc, cpu.next_pc = ret, ret + 4
                return True
            if cpu.pc == BGMAP_INIT:
                calls.append(('bgmap', cpu.r[REG['a0']], cpu.r[REG['a1']],
                              bytes(cpu.mem[cpu.offset(CELLS, 0x22):
                                            cpu.offset(CELLS, 0x22) + 0x22])))
                ret = cpu.r[REG['ra']]
                cpu.pc, cpu.next_pc = ret, ret + 4
                return True
            return False

        c.start(ENTRY)
        c.run(RETURN, limit=2000000, intercept=intercept)
        return calls

    def test_every_title_row_hits_and_copies_its_full_title(self):
        for i, (key, width, script) in enumerate(self.rows):
            with self.subTest(row=i, width=width):
                calls = self.execute(self.machine(key))
                self.assertEqual([c[0] for c in calls], ['bgmap'],
                                 'Japanese field fell back to retail')
                self.assertEqual(calls[0][1:3], (CELLS, 0))
                self.assertEqual(calls[0][3][:len(script)], script)
                self.assertEqual(calls[0][3][len(script)], 0)

    def test_unknown_field_uses_the_retail_fallback(self):
        keys = {row[0] for row in self.rows}
        key = bytearray(self.rows[-1][0])
        for pos in range(20):
            for value in range(256):
                key[pos] = value
                if bytes(key) not in keys:
                    break
            else:
                continue
            break
        self.assertNotIn(bytes(key), keys)
        calls = self.execute(self.machine(bytes(key)))
        self.assertEqual(calls, [('fallback',)])

    def test_mikage_subway_fields_show_the_full_names(self):
        pack = ROOT / 'build/D01/D0DM.BIN'
        if not pack.exists():
            self.skipTest('requires the built D01 pack')
        data = pack.read_bytes()
        expected = {'Mikage Subway West': 0x6a0,
                    'West Subway Entrance': 0x764,
                    'Mikage Subway East': 0x828,
                    'East Subway Entrance': 0x8ec}
        found = {}
        for key, _width, script in self.rows:
            text = ''.join(' ' if b == 0x88 else chr(b - 0x68)
                           for b in script[:-2])
            if text in expected:
                found[text] = key
        for text, off in expected.items():
            with self.subTest(name=text):
                self.assertIn(text, found, 'title table lost the PSP-US name')
                self.assertEqual(data[off:off + 20], found[text],
                                 'built pack field does not carry the title key')
                calls = self.execute(self.machine(found[text]))
                self.assertEqual([c[0] for c in calls], ['bgmap'])


if __name__ == '__main__':
    unittest.main()
