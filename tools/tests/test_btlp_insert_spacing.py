"""Battle insertions and speaker labels retain meaningful source spacing."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
sys.path.insert(0, str(ROOT / 'src/extraction_tools/matching'))
import btlp
import etext
import port_derive
import port_story
import toolbelt
import vwf_wrap


class InsertSpacing(unittest.TestCase):
    def test_all_real_battle_insert_tokens_keep_authored_word_gaps(self):
        self.assertTrue(vwf_wrap.BTL_INSERT_WIDTHS)
        for token in vwf_wrap.BTL_INSERT_WIDTHS:
            with self.subTest(token=token):
                self.assertEqual(vwf_wrap.clean_edges('Before ' + token + ' after'),
                                 'Before ' + token + ' after')
                self.assertEqual(vwf_wrap.clean_edges('Before ' + token + '!'),
                                 'Before ' + token + '!')
                self.assertEqual(vwf_wrap.clean_edges(token + ' after'), token + ' after')
                self.assertEqual(vwf_wrap.clean_edges('Before ' + token + '<FFF6> after'),
                                 'Before ' + token + '<FFF6>after')
        self.assertEqual(vwf_wrap.clean_edges('Before <FFF6> after'), 'Before<FFF6>after')

    def test_psp_authored_battle_sentence_keeps_spaces(self):
        ja = next(r['text'] for r in toolbelt.read_extracted('psx', 'BTLP')
                  if r['pos'] == '0x681d4')
        source = toolbelt.psp_wording('EBOOT:2adece')
        self.assertIn(' <FFFA> tried', source)
        result, reason = port_derive.derive(source, ja, 'BTLP', '0x681d4')
        self.assertEqual(reason, '')
        self.assertEqual(result, '＞ <FFFA> tried to persuade it!')

    def test_speaker_label_punctuation_body_keeps_authored_space(self):
        self.assertEqual(port_story.layout_box('<FFF9>: !!', brk='<FFF6>'), '<FFF9>: !!')
        self.assertEqual(port_story.layout_box('Speaker: !!', brk='<FFF6>'), 'Speaker: !!')
        self.assertEqual(port_story.layout_box('Speaker: Hello!', brk='<FFF6>'), 'Speaker: Hello!')
        self.assertEqual(port_story.layout_box('Wait !', brk='<FFF6>'), 'Wait!')

    def test_untranslated_label_adds_only_a_visible_body_gap(self):
        colon = etext.encode('：', end=None)
        space = etext.encode(' ', end=None)
        original = bytes.fromhex('fff9') + colon + etext.encode('！！', end=b'\xff\xf5')
        self.assertEqual(btlp.evt_original_layout(original), original[:4] + space + original[4:])
        self.assertEqual(btlp.evt_original_layout(original[:4] + space + original[4:]),
                         original[:4] + space + original[4:])
        self.assertEqual(btlp.evt_original_layout(bytes.fromhex('fff9') + colon + b'\xff\xf5'),
                         bytes.fromhex('fff9') + colon + b'\xff\xf5')
        self.assertEqual(btlp.evt_original_layout(etext.encode('Text：！！', end=b'\xff\xf5')),
                         etext.encode('Text：！！', end=b'\xff\xf5'))
        numeric = bytes.fromhex('fff8') + colon + etext.encode('！！', end=b'\xff\xf5')
        self.assertEqual(btlp.evt_original_layout(numeric), numeric)

    def test_screenshot_original_keeps_original_glyph_bytes(self):
        data = btlp.data()
        raw = next(data[a-btlp.B:e-btlp.B] for a, e in btlp.evt_messages(data)
                   if a-btlp.B == 0x6b6b0)
        laid = btlp.evt_original_layout(raw)
        self.assertEqual(laid, raw[:4] + etext.encode(' ', end=None) + raw[4:])
        self.assertEqual(laid.replace(etext.encode(' ', end=None), b'', 1), raw)


if __name__ == '__main__':
    unittest.main()
