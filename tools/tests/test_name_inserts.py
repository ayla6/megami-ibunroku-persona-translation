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
        toks = [('t', '日本語'), ('c', '<FF0F><00>'), ('c', '<FF01>')]
        en, _, _ = port_story.reflow('', [('w', 'Hello'), ('u', 'NAME07')], toks)
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
        en = port_derive.fit_codes('Hello <FFF8>', 'こんにちは<FFF9>')
        self.assertIn('<FFF8>', en)
        self.assertNotIn('<FFF9>', en)

    def test_battle_does_not_accept_untranslated_dialogue_insert(self):
        ja = 'こんにちは<FFF9>'
        en = port_derive.fit_codes('Hello <FF07><01>', ja)
        self.assertFalse(port_derive.codes_match(en, ja))


if __name__ == '__main__':
    unittest.main()
