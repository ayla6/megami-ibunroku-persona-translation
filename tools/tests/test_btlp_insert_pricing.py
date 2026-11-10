"""From the decomp: the cap of a battle insert code follows the slot its case writes.

`BtlSetInsert`'s case numbers are not slot numbers (case 2 fills slot 3,
case 3 slot 4, case 4 slot 6, case 6 slot 2). Pricing a code by its case
number gives the wrong copy cap - it did: <FFF4> (item) was priced at the
8-glyph short copy and <FFF9> (party member) at the 10-glyph long one.
The patched copy resolves <FFF3>/<FFF4> to complete ported names, so those
two are priced at the widest name of their family instead.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
sys.path.insert(0, str(ROOT / 'src/extraction_tools/matching'))
import vwf_wrap


class BattleInsertPricing(unittest.TestCase):
    def test_code_to_slot_is_read_from_the_case_body(self):
        self.assertEqual(vwf_wrap.btl_insert_slots(), {
            0xF8: 0, 0xFA: 1, 0xF0: 2, 0xF3: 3,
            0xF4: 4, 0xF2: 5, 0xF9: 6})

    def test_cap_follows_the_slot_not_the_case_number(self):
        caps = vwf_wrap.btl_insert_caps()
        short, long = 8, 10
        # case 3 (long) writes slot 4, the code <FFF4>
        self.assertEqual(caps[0xF4], long)
        # case 4 (short) writes slot 6, the code <FFF9>
        self.assertEqual(caps[0xF9], short)
        # case 2 (long) writes slot 3, the code <FFF3>
        self.assertEqual(caps[0xF3], long)
        # case 6 (raw long copy) writes slot 2, the code <FFF0>
        self.assertEqual(caps[0xF0], long)
        self.assertEqual(caps[0xF2], long)
        self.assertEqual(caps[0xFA], short)

    def test_complete_names_are_priced_from_the_port_table(self):
        table = vwf_wrap.insert_widths()
        self.assertIn('<FFF3>', table)
        self.assertIn('<FFF4>', table)
        widths = vwf_wrap.battle_insert_widths()
        self.assertEqual(widths['<FFF3>'], table['<FFF3>'])
        self.assertEqual(widths['<FFF4>'], table['<FFF4>'])

    def test_fixed_fields_keep_the_decomp_cap(self):
        widths = vwf_wrap.battle_insert_widths()
        for token, code in (('<FFFA>', 0xFA), ('<FFF9>', 0xF9),
                            ('<FFF0>', 0xF0)):
            with self.subTest(token=token):
                self.assertEqual(widths[token],
                                 vwf_wrap.btl_insert_caps()[code]
                                 * vwf_wrap._NAME_GLYPH)

    def test_port_widths_bound_their_name_family(self):
        """The table's px is the widest name that family can print."""
        import port_widths
        names = port_widths.family_names()
        for token, family in (('<FFF2>', 'demon'), ('<FFF3>', 'demon'), ('<FFF4>', 'item')):
            with self.subTest(token=token):
                widest = max(sum(vwf_wrap.char_width(c) for c in name)
                             for name in names[family] if name)
                self.assertEqual(vwf_wrap.text_width(token), widest)

    def test_shipped_battle_rows_fit_with_the_new_pricing(self):
        import re
        import toolbelt
        for row in toolbelt.merged_rows('BTLP'):
            text = (row.get('en') or '').strip()
            if not text:
                continue
            for line in re.split(r'<FFF6>|<FFFB><FFF7>|<FF03>|<FF04>|<FFEF>', text):
                with self.subTest(pos=row['pos'], line=line):
                    self.assertLessEqual(vwf_wrap.text_width(line), 239)


if __name__ == '__main__':
    unittest.main()
