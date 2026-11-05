"""Two rules that decide what a SOURCE is, not what a box shows.

A `psp` pointer can name a unit whose words are still Japanese (the US
build never localised every pack), and a PSX name insert carries a
parameter unit the PSP's spelling does not. Feeding the first into a
destination encoder re-spells the Japanese as glyph indices; comparing the
second as if both builds ate a unit deletes real wording.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'),
                str(ROOT / 'src/extraction_tools/matching')]
import match_jp       # noqa: E402
import port_derive    # noqa: E402


class SourceIsJapanese(unittest.TestCase):
    def test_a_japanese_box_is_not_a_translation(self):
        # d06's title logo: the US pack is byte-identical to the JP one
        self.assertTrue(port_derive.still_japanese(
            '女神異聞録<FF03>　　　　ＰＥＲＳＯＮＡ<FF03>'))
        self.assertTrue(port_derive.still_japanese('トラフーリありません<FF01>'))

    def test_english_with_a_glitch_head_is_a_translation(self):
        # both builds carry the undecoded head cells; the words are English
        self.assertFalse(port_derive.still_japanese('瞭 <FF0D>Feral Bite'))
        self.assertFalse(port_derive.still_japanese('畢 nBonecrusher'))

    def test_an_isolated_stray_run_in_english_is_furniture(self):
        # PSP-US shipped a few glyph runs inside its English (TENSI '収益').
        # That is not an untranslated box.
        self.assertFalse(port_derive.still_japanese(
            '<FF03>収益<FF03>Profit: 300<FF01>'))

    def test_empty_and_plain_english(self):
        self.assertFalse(port_derive.still_japanese(''))
        self.assertFalse(port_derive.still_japanese('Enemy 1: Bite'))


class RecordHead(unittest.TestCase):
    """A fixed field's glitch head is furniture, and the JP twin proves it.
    Two shapes: cells before the JP's own words, and the JP's own first
    cells (an icon the JP map reads as a kanji)."""

    def test_cells_before_the_jp_words(self):
        self.assertEqual(
            port_derive.wording_head('畢 n押し潰し', '畢 nBonecrusher'), 3)

    def test_the_jp_first_cells_are_the_head(self):
        # both builds carry the icon; the JP decodes it as 瞭 / 儖β
        self.assertEqual(
            port_derive.wording_head('瞭 <FF0D>噛み付き',
                                     '瞭 <FF0D>Feral Bite'), 8)
        self.assertEqual(
            port_derive.wording_head('儖β<FF0F>トラフーリ',
                                     '儖β<FF0F>Trafuri'), 8)

    def test_a_shared_word_is_not_a_head(self):
        # no cell before the divergence, and the JP's first words are its own
        self.assertEqual(port_derive.wording_head('HP回復', 'Restores HP'), 0)
        self.assertEqual(port_derive.wording_head('ペルソナ', 'Persona'), 0)


class NameInsertParameter(unittest.TestCase):
    """A PSX name insert (`<FF07>`/`<FF08>`/`<FF0F>`/`<FF10>`) is followed
    by one parameter unit; the PSP spells the same insert bare. The unit is
    only eaten on the PSX side - the character after a PSP insert is real
    wording ('<FF0F>の' is a name plus its particle)."""

    def test_psx_insert_eats_its_unit(self):
        self.assertEqual(match_jp.bare('<FF0F>の', psx=True), '')

    def test_psp_insert_keeps_the_wording(self):
        self.assertEqual(match_jp.bare('<FF0F>の'), 'の')

    def test_the_key_does_not_depend_on_the_parameter_spelling(self):
        # '<FF07><01>! We must hurry' and the same words without the insert
        # compare equal when the string is a PSX line.
        self.assertEqual(match_jp.bare('<FF07><01>! We must hurry', psx=True),
                         match_jp.bare('! We must hurry'))


if __name__ == '__main__':
    unittest.main()
