"""Fixed battle UI and owned proportional names sample independent artwork."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools/tests')]
import btlfont
import smallfont_lc
import smallfont_variants as variants
import smallfont_vwf as sf
from mips_cpu import CPU, REG
from test_btlp_text_class import SYM, SLPS, run


class BattleArt(unittest.TestCase):
    def test_fixed_latin_is_original_and_vwf_copies_are_complete(self):
        retail, _, _ = sf.disc_page()
        smallfont_lc.draw(retail, 256)
        thin = sf.thin_page_indices()[0]
        page = btlfont.battle_page()
        mapping, _ = btlfont.art_mapping()
        for code in variants.editable_codes():
            self.assertEqual(sf.glyph_rows(page, 256, code), sf.glyph_rows(retail, 256, code))
            dest = mapping.get(code, code)
            self.assertEqual(sf.glyph_rows(page, 256, dest), sf.glyph_rows(thin, 256, code))
        self.assertFalse(set(mapping.values()) & variants.protected_codes())

    def test_assembled_selector_matches_both_faces_for_every_printable_code(self):
        mapping, _ = btlfont.art_mapping()
        for proportional in (False, True):
            for code in [0, *variants.editable_codes()]:
                c = CPU()
                c.load(0x80010000, SLPS)
                c.r[REG['sp']] = 0x801FF000
                c.r[REG['ra']] = 0x8000FFF0
                c.r[REG['a0']] = code
                c.r[REG['at']] = 0 if proportional else 0xFFFFFFFF
                before = c.r.copy()
                run(c, REG, SYM['btl_sf_art_code'])
                self.assertEqual(c.r[REG['a0']], mapping.get(code, code) if proportional else code)
                for reg in range(2, 32):
                    if reg != REG['a0']:
                        self.assertEqual(c.r[reg], before[reg], (code, reg))
