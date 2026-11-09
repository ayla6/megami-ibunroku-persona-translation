"""PSP-US wording owns name-insert kinds across the dialogue porters."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/injection_tools')]
import port_story
import port_s2d
import port_dng
import port_derive
import tstatus


class NameInserts(unittest.TestCase):
    def test_story_uses_psp_marker_even_when_japanese_differs(self):
        en, _, _ = port_story.reflow('', [('w', 'Hello'), ('u', 'NAME07')])
        self.assertIn('<FF07><01>', en)
        self.assertNotIn('<FF0F>', en)

    def test_s2d_does_not_copy_or_add_japanese_inserts(self):
        ja = '名前：<FF0F><00>？<FF02><FF01>'
        en = '<FF1B>Mark<FF03>Hello <FF07>!<FF02><FF01>'
        out = port_s2d.decoded_en(en, ja)
        self.assertIn('<FF07><01>', out)
        self.assertNotIn('<FF0F>', out)
        self.assertNotIn('<FF0F>', port_s2d.script_text(ja, 'Hello!'))

    def test_dungeon_keeps_english_kind(self):
        ja = '名前：<FF0F><00>？<FF02><FF01>'
        en = 'Hello <FF07><01>!<FF02><FF01>'
        out = port_dng.assemble(ja, en)
        self.assertIn('<FF07><01>', out)
        self.assertNotIn('<FF0F>', out)

    def test_name_difference_is_not_a_japanese_code_mismatch(self):
        ja = '名前：<FF0F><01>！<FF02><FF01>'
        en = 'Name: <FF07><01>!<FF02><FF01>'
        self.assertNotIn('codes', [kind for kind, _ in tstatus.check(ja, en)])

    def test_battle_fitting_does_not_replace_one_insert_with_another(self):
        en = port_derive.translate_codes('Hello <FFF8>', interpreter='battle')
        self.assertIn('<FFF8>', en)
        self.assertNotIn('<FFF9>', en)

    def test_battle_translates_given_name_to_its_own_slot(self):
        ja = '<FFF9>が復活した'
        en = port_derive.translate_codes('<FF07> was revived.', interpreter='battle')
        self.assertIn('<FFF9>', en)
        self.assertNotIn('<FF07>', en)
        self.assertTrue(port_derive.codes_match(en, ja))

    def test_battle_drops_the_dialogue_member_parameter(self):
        ja = '<FFF9>が復活した'
        en = port_derive.translate_codes('<FF07><01> was revived.', interpreter='battle')
        self.assertEqual(en, '<FFF9> was revived.')
        self.assertTrue(port_derive.codes_match(en, ja))

    def test_battle_refuses_a_name_kind_it_has_no_slot_for(self):
        ja = '<FFF9>が復活した'
        for kind in ('<FF08>', '<FF0F>', '<FF10>'):
            en = port_derive.translate_codes(f'{kind} was revived.', interpreter='battle')
            self.assertNotIn('<FFF9>', en, kind)
            self.assertFalse(port_derive.codes_match(en, ja), kind)

    def test_battle_does_not_invent_a_japanese_name_insert(self):
        ja = '<FFF9>が復活した'
        en = port_derive.translate_codes('was revived.', interpreter='battle')
        self.assertEqual(en, 'was revived.')
        self.assertTrue(port_derive.codes_match(en, ja))

    def test_battle_translates_every_psp_insert_independent_of_japanese(self):
        ja = '<FFF9>が復活した'
        en = port_derive.translate_codes('<FF07> and <FF07> were revived.', interpreter='battle')
        self.assertEqual(en, '<FFF9> and <FFF9> were revived.')
        self.assertTrue(port_derive.codes_match(en, ja))

    def test_dialogue_keeps_the_psp_given_name(self):
        ja = '名前は<FF0F>だ'
        en = port_derive.translate_codes('<FF07>', ja)
        self.assertEqual(en, '<FF07>')


if __name__ == '__main__':
    unittest.main()
