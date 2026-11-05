"""Fixed-name fit rules, using glyph codes rather than authored name mappings."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
sys.path.insert(0, str(ROOT / 'src/extraction_tools/matching'))
import items
import demons
import port_caps
import smallfont_vwf as sf


class CondensedNames(unittest.TestCase):
    def test_least_tier_and_unfittable_natural_width(self):
        with patch.object(sf, '_field_widths', return_value=bytes([0x34]) * 256):
            for codes, budget, expected in (([10] * 4, 16, (0, 16)),
                                             ([10, 0, 11, 0, 12], 16, (1, 16)),
                                             ([10] * 5, 16, (2, 15)),
                                             ([10] * 6, 16, (None, 24))):
                with self.subTest(codes=codes):
                    self.assertEqual(sf.condensed_tier(iter(codes), budget), expected)

    def test_minimum_advance_and_unchanged_bearings(self):
        for metric in (1, 0x22, 0x46):
            for code in (0, 174):
                for tier in sf.CONDENSED:
                    advance = sf.tier_adv(metric, code, tier)
                    self.assertGreaterEqual(advance, 1)
                    if tier < 2:
                        self.assertLessEqual(advance, metric & 15)
        self.assertGreaterEqual(sf.tier_adv(0x22, 174, 2), 2)
        self.assertEqual(sf.tier_adv(4, 0, 1), 2)
        self.assertEqual(sf.tier_adv(4, 0, 2), 1)

    def test_field_rows_measure_with_the_field_table(self):
        text = 'Strong: Magic / Weak: Axe, Arrow'
        field = sf._field_widths()
        self.assertEqual(sf.field_line_px(text),
                         sum(sf.tier_adv(field[sf.char_code(c)], sf.char_code(c), 0)
                             for c in text))
        self.assertEqual(port_caps.measure('affinity', text)[1], sf.field_line_px(text))

    def test_build_and_port_share_the_same_fit_gate(self):
        for family, module in (('items', items), ('demons', demons)):
            for length in range(1, module.MAXLEN + 1):
                text = 'R' * length
                tier, px = module.name_fit(text)
                result = port_caps.measure(family, text)
                self.assertEqual(result[0], tier is not None)
                if tier is None:
                    self.assertEqual(result[1:4], (module.name_px(text), 80, 'px'))
                else:
                    self.assertLessEqual(px, 80)
            self.assertFalse(port_caps.measure(family, 'i' * (module.MAXLEN + 1))[0])


if __name__ == '__main__':
    unittest.main()
