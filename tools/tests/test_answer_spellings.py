"""Spelling joins use paired Japanese slots, not handwritten readings."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/injection_tools'), str(ROOT / 'src/extraction_tools/psp')]
from port_answers import (SlotSpellings, _no_punct, answer_punct_key, derive_boot_answer,
                          spelling_key)


class AnswerSpellings(unittest.TestCase):
    def test_field_source_gets_answer_terminator(self):
        en, why = derive_boot_answer(' Example<FF01>', '例<FFF5>')
        self.assertEqual((en, why), ('Example<FFF5>', ''))

    def test_width_punctuation_and_small_kana(self):
        self.assertEqual(spelling_key('はあ、どうも…<FFF5>'),
                         spelling_key('はぁ,どうも…<FFF5>'))
        self.assertEqual(spelling_key('Ｙｅｓ？<FFF5>'), spelling_key('Yes?<FFF5>'))

    def test_punctuation_only_variants_share_a_key(self):
        self.assertEqual(_no_punct('内緒…<FFF5>'), _no_punct('内緒<FFF5>'))
        self.assertNotEqual(_no_punct('しゃ<FFF5>'), _no_punct('しや<FFF5>'))

    def test_english_terminal_punctuation_is_not_a_second_wording(self):
        self.assertEqual(answer_punct_key("It's a secret!<FFF5>"),
                         answer_punct_key("It's a secret.<FFF5>"))

    def test_kana_kanji_change_learned_between_matching_neighbours(self):
        pairs = {0: ('あい', 'あい'), 1: ('何んですか', 'なんですか'),
                 2: ('うえ', 'うえ')}
        learned = SlotSpellings([pairs])
        self.assertTrue(learned.rules)
        self.assertEqual(learned.key('何んですって'), learned.key('なんですって'))
        # Context is learned, not a universal reading for the isolated kanji.
        self.assertNotEqual(learned.key('何ですか'), learned.key('なですか'))

    def test_kana_kanji_direction_is_symmetric(self):
        pairs = {0: ('あい', 'あい'), 1: ('なんですか', '何んですか'),
                 2: ('うえ', 'うえ')}
        learned = SlotSpellings([pairs])
        self.assertEqual(learned.key('何んですか'), learned.key('なんですか'))

    def test_no_learning_without_both_anchors(self):
        learned = SlotSpellings([{1: ('何んですか', 'なんですか')}])
        self.assertFalse(learned.rules)

    def test_unrelated_answers_are_not_spelling_changes(self):
        learned = SlotSpellings([{0: ('あ', 'あ'), 1: ('ミカン', 'いちご'),
                                  2: ('う', 'う')}])
        self.assertFalse(learned.rules)

    def test_single_kanji_variant_learned_between_matching_neighbours(self):
        pairs = {0: ('あい', 'あい'), 1: ('鎌遜する', '謙遜する'),
                 2: ('うえ', 'うえ')}
        learned = SlotSpellings([pairs])
        self.assertEqual(learned.key('鎌遜する'), learned.key('謙遜する'))
        self.assertNotEqual(learned.key('鎌'), learned.key('謙'))

    def test_controls_and_parameters_are_not_spelling_variants(self):
        self.assertNotEqual(spelling_key('はい<FFF5>'), spelling_key('はい<FF01>'))
        self.assertNotEqual(spelling_key('はい<FF06><01>'),
                            spelling_key('はい<FF06><02>'))

    def test_conflicting_learned_readings_are_refused(self):
        groups = [{0: ('あい', 'あい'), 1: ('何んですか', target),
                   2: ('うえ', 'うえ')}
                  for target in ('なんですか', 'にんですか')]
        self.assertFalse(SlotSpellings(groups).rules)


if __name__ == '__main__':
    unittest.main()
