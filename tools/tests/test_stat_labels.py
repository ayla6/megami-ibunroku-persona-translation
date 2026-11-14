"""The stat labels too wide for their art cells are drawn as text rows: every
patched call reaches the helper, and the helper reaches the row writer the
retail call used (each overlay has its own TileMapWriteRow) with the
glossary wording and its cell count.

Run after a build: reads build/{ADV,DNG,S2D}.BIN and build/persona.sym.
"""
from pathlib import Path
import re
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools/tests')]
from mips_cpu import CPU, REG  # noqa: E402

BASE = 0x800643C4


def jal_target(word):
    return 0x80000000 | (word & 0x03FFFFFF) << 2


class StatLabels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / 'build/persona.sym').exists():
            raise unittest.SkipTest('requires an assembled build')
        cls.sym = {m[2]: int(m[1], 16) for line in (ROOT / 'build/persona.sym').read_text().splitlines()
                   if (m := re.fullmatch(r'([0-9A-F]{8}) (\w+)', line.strip()))}
        if 'stat_label_text_adv' not in cls.sym:
            raise unittest.SkipTest('a build without the small-font kit')

    def test_every_label_call_reaches_its_overlays_writer(self):
        import menu_gfx
        import toolbelt
        labels = menu_gfx.text_labels()
        self.assertTrue(labels)
        for ovl in menu_gfx.STAT_LABEL_OVERLAYS:
            low = ovl.lower()
            built = (ROOT / f'build/{ovl}.BIN').read_bytes()
            retail = (ROOT / f'data/psx/{ovl}.BIN').read_bytes()
            helper = self.sym[f'stat_label_text_{low}']
            sites = [line.split()[1] for line in (ROOT / f'build/stat_labels_{low}.asm').read_text().splitlines()
                     if line.startswith('.org')][1::2]
            self.assertTrue(sites, ovl)
            for site in sites:
                at = int(site, 16) - BASE
                with self.subTest(overlay=ovl, site=site):
                    self.assertEqual(jal_target(struct.unpack_from('<I', built, at)[0]), helper)
                    writer = jal_target(struct.unpack_from('<I', retail, at)[0])
                    k = struct.unpack_from('<I', built, at - 4)[0] & 0xFFFF
                    c = CPU()
                    c.load(BASE, built)
                    c.r[REG['a2']], c.r[REG['sp']] = k, 0x801E0000
                    c.start(helper)
                    c.run(writer, limit=50)
                    text, _tile, cells = labels[k]
                    codes = bytes(c.read(c.r[REG['a0']] + i, 1) for i in range(len(text) + 1))
                    self.assertEqual(codes, bytes(toolbelt.smallfont_char(ch) for ch in text) + b'\xff')
                    self.assertEqual(c.r[REG['a3']], cells)
                    self.assertEqual(c.r[REG['a2']], 0)


if __name__ == '__main__':
    unittest.main()
