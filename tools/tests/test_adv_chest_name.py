"""Execute the field pickup's assembled sprite writer and screen clamp."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools/tests')]
from mips_cpu import CPU, REG
import items
import name_tails
import smallfont_variants
import toolbelt

BASE = 0x800643c4
STACK = 0x801e0000
BLOCK = 0x80057400
CELLS = BLOCK + 8
COUNT = 20
ITEM = 0x800f7eb8


class PickupName(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [ROOT / 'build' / p for p in ('ADV.BIN', 'SLPS_005.00', 'sf_field_width.bin')]
        if not all(p.exists() for p in paths):
            raise unittest.SkipTest('requires assembled ADV, resident image and widths')
        cls.adv, cls.slps, cls.metrics = [p.read_bytes() for p in paths]
        cls.retail = (ROOT / 'data/psx/ADV.BIN').read_bytes()
        symbols = {}
        for line in (ROOT / 'build/persona.sym').read_text().splitlines():
            parts = line.split()
            if len(parts) == 2:
                try:
                    symbols[parts[1]] = int(parts[0], 16)
                except ValueError:
                    pass
        cls.symbols = symbols

    def machine(self):
        c = CPU()
        c.load(BASE, self.adv)
        addr, size = struct.unpack_from('<II', self.slps, 0x18)
        c.load(addr, self.slps[0x800:0x800 + size])
        c.r[REG['sp']] = STACK
        return c

    def test_all_items_write_full_names_with_shared_metrics(self):
        c = self.machine()
        c.r[REG['ra']] = 0x801f0000
        c.start(0x80081c14)
        c.run(0x80081c38, limit=2000)
        self.assertEqual(c.read(BLOCK), 0x114)
        self.assertEqual(c.read(BLOCK + 4), 0x000c0008)
        self.assertEqual(c.read(0x800b5a1c), BLOCK)
        self.assertEqual(c.read(0x800b5a26, 2), toolbelt.asm_equ('SF_BAR_MARK'))
        self.assertEqual(self.adv[0x800b59f4 - BASE:0x800b5a1c - BASE],
                         self.retail[0x800b59f4 - BASE:0x800b5a1c - BASE])
        self.assertEqual(self.adv[0x800b5a28 - BASE:0x800b5a44 - BASE],
                         self.retail[0x800b5a28 - BASE:0x800b5a44 - BASE])
        regular = dict(zip(smallfont_variants.editable_codes(),
                           smallfont_variants.cell_codes()[0]))
        item_rows = name_tails.item_rows()
        self.assertTrue(item_rows, 'no source-derived item names')
        for ident, name in item_rows:
            with self.subTest(ident=ident):
                glyphs = items.encode(name)
                self.assertLessEqual(len(glyphs), COUNT)
                # Retail's clear makes every unused cell invisible.
                for k in range(COUNT):
                    c.write(CELLS + k * 8, 0xff, 1)
                c.write(ITEM, ident, 2)
                c.r[REG['s3']] = CELLS
                c.r[REG['sp']] = STACK
                c.start(0x80081c84)
                c.run(0x80081cac, limit=30000)
                self.assertEqual(bytes(c.read(STACK + k, 1) for k in range(len(glyphs) + 1)),
                                 glyphs + b'\xff')
                self.assertEqual(c.r[REG['t0']], CELLS + len(glyphs) * 8)
                pen = 0
                for k, glyph in enumerate(glyphs):
                    self.assertNotEqual(c.read(CELLS + k * 8, 1), 0xff)
                    self.assertEqual(c.read(CELLS + k * 8 + 2, 1), 0x1e)
                    self.assertEqual(c.read(CELLS + k * 8 + 3, 1), self.metrics[glyph] & 15)
                    self.assertLessEqual(self.metrics[glyph] & 15, 8)
                    expected_uv = smallfont_variants.cell_uv(regular.get(glyph, glyph))
                    self.assertEqual((c.read(CELLS + k * 8, 1), c.read(CELLS + k * 8 + 1, 1)),
                                     expected_uv)
                    c.r[REG['s4']] = pen
                    c.r[REG['s6']] = CELLS + k * 8
                    c.r[REG['t9']] = 0x800b5a1c
                    c.r[REG['a3']] = 8
                    c.start(toolbelt.asm_equ('ADV_BAR_ADV_SITE'))
                    c.run(toolbelt.asm_equ('ADV_BAR_ADV_SITE') + 8, limit=30)
                    pen += self.metrics[glyph] & 15
                    self.assertEqual(c.r[REG['s4']], pen)
                if len(glyphs) < COUNT:
                    self.assertEqual(c.read(CELLS + len(glyphs) * 8, 1), 0xff)

    def test_clamp_keeps_every_name_footprint_on_screen(self):
        c = self.machine()
        for count in range(1, COUNT + 1):
            for x in (-100, -32, 0, 100, 200, 300):
                with self.subTest(count=count, x=x):
                    c.r[REG['t0']] = CELLS + count * 8
                    c.r[REG['s3']] = CELLS
                    c.r[REG['a3']] = x & 0xffffffff
                    c.start(self.symbols['chest_clamp_entry'])
                    c.run(0x80065eb0, limit=50)
                    actual = c.r[REG['a3']]
                    if actual & 0x80000000:
                        actual -= 0x100000000
                    self.assertGreaterEqual(actual + 32, 0)
                    self.assertLessEqual(actual + 32 + count * 8, 320)
                    self.assertEqual(actual, max(-32, min(x, 288 - count * 8)))

    def test_persona_data_skips_the_pickup_helper(self):
        c = self.machine()
        c.r[REG['s3']] = CELLS
        c.r[REG['t0']] = CELLS
        c.start(toolbelt.asm_equ('ADV_PDATA_TAIL') + 12)
        c.run(toolbelt.asm_equ('ADV_PDATA_TAIL') + 0x30, limit=3)


if __name__ == '__main__':
    unittest.main()
