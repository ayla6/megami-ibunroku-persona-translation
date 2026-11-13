"""Instruction glyphs, structural captions and PSX control adaptation."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/extraction_tools/psp'), str(ROOT / 'src/injection_tools')]
import port_controls
import port_derive
import port_story


class Controls(unittest.TestCase):
    def test_face_buttons_follow_the_corresponding_psx_actions(self):
        self.assertEqual(port_controls.adapt_buttons(
            '【× button】 Add. 【○ button】 Remove.', '【○ボタン】追加【×ボタン】取消'),
            '【○ button】 Add. 【× button】 Remove.')

    def test_shoulders_expand_from_the_source_not_a_global_substitution(self):
        self.assertEqual(port_controls.adapt_buttons(
            '【R button】 【L button】', '【Ｒ１・Ｒ２ボタン】【Ｌ１・Ｌ２ボタン】'),
            '【R1・R2 button】 【L1・L2 button】')
        self.assertEqual(port_controls.adapt_buttons(
            'Press the R button.', 'Ｒ２ボタンを押す'), 'Press the R2 button.')

    def test_inline_groups_keep_their_english_separators_when_unchanged(self):
        for group in ('○/×/△/□', '○, ×, △, and □'):
            text = f'Press the {group} buttons, then the R button.'
            self.assertEqual(port_controls.adapt_buttons(
                text, '○・×・△・□の各ボタン。Ｒ１かＲ２ボタン'),
                f'Press the {group} buttons, then the R1・R2 button.')
            self.assertEqual(port_controls.adapt_buttons(
                text, '○・×・△・□のいづれかで固定。Ｒ１かＲ２ボタン'),
                f'Press the {group} buttons, then the R1・R2 button.')

    def test_descriptive_buttons_are_never_controller_symbols(self):
        text = '【Directional buttons】 The red button and the second button.'
        self.assertEqual(port_controls.adapt_buttons(text, '方向キー。赤いボタン。第２ボタン'), text)

    def test_mismatched_reference_count_is_not_guessed(self):
        text = '【× button】 【R button】'
        self.assertEqual(port_controls.adapt_buttons(text, '【○ボタン】'), text)

    def test_line_wrapped_reference_and_repeat_derivation(self):
        text = 'Press R<FF03>button.'
        result = port_controls.adapt_buttons(text, 'Ｒ１・Ｒ２ボタン')
        self.assertEqual(result, 'Press R1・R2<FF03>button.')
        self.assertEqual(port_controls.adapt_buttons(result, 'Ｒ１・Ｒ２ボタン'), result)

    def test_middle_dot_is_punctuation_not_a_japanese_remnant(self):
        self.assertFalse(port_derive.HOLES.search('【R1・R2 button】'))
        self.assertEqual(port_derive.stray_jp('R1・R2'), 'R1・R2')
        self.assertTrue(port_derive.HOLES.search('あ'))
        self.assertTrue(port_derive.HOLES.search('カ'))

    def test_writer_accepts_symbolic_button_separator(self):
        import toolbelt
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(toolbelt, 'GENERATED', directory), \
                    patch.object(toolbelt, 'route_gaps'):
                toolbelt.upsert_generated('instruction-test', [
                    {'pos': '0x0', 'psp': '', 'en': '【R1・R2 button】'},
                    {'pos': '0x1', 'psp': '', 'en': 'カナ'}])
                rows = toolbelt.read_generated('instruction-test')
        self.assertEqual([r['en'] for r in rows], ['【R1・R2 button】'])


class InstructionLayout(unittest.TestCase):
    def test_visible_brackets_caption_marks_and_bullets_survive_raw_decode(self):
        reverse = {}
        for unit, ch in port_story.US_MAP.items():
            reverse.setdefault(ch, unit)
        text = '【A】＞B＞・C'
        raw = b''.join(reverse[c].to_bytes(2, 'big') for c in text) + b'\xff\x01'
        segments, flags = port_story.us_parts(raw)
        self.assertFalse(flags)
        self.assertEqual(segments, [(None, [text, port_story.US_BRK + 'FF01'])])

    def test_structural_caption_breaks_survive_shared_layout(self):
        for heading in ('【○ button】', '＞Before starting＞', '＜During play＞'):
            result = port_story.layout_box(heading + '<FF03>Add a coin.<FF02><FF01>')
            self.assertIn(heading + '<FF03>Add a coin.', result)

    def test_prose_breaks_still_reflow(self):
        self.assertEqual(port_story.layout_box('Add a<FF03>coin.<FF02><FF01>'),
                         'Add a coin.<FF02><FF01>')

    def test_writer_uses_each_rows_own_japanese_for_decorations(self):
        entries = [SimpleNamespace(boxes=[(0x10, 0), (0x20, 0)])]
        ports = [('E0', 0, 0, '説明', '＞Heading＞'),
                 ('E0', 0, 1, '＜説明＞', '＞Heading＞')]
        with patch.object(port_story.efile, 'load', return_value=SimpleNamespace(entries=entries)), \
                patch.object(port_story, 'psp_lookup', return_value=lambda e, b: 'source'), \
                patch.object(port_story.toolbelt, 'upsert_generated', return_value=2) as write, \
                patch.object(port_story.toolbelt, 'route_gaps'):
            port_story.store_generated(ports)
        rows = write.call_args.args[1]
        self.assertEqual([r['en'] for r in rows], ['Heading', '＞Heading＞'])


class ReportedInstruction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows, _counts = port_story.convert_entry('E0', 13)
        entry = port_story.psx_entries('E0')[13]
        index = next(i for i, (start, _end) in enumerate(entry.boxes) if start == 0x40D8)
        cls.ja, cls.en, cls.errors = rows[index][1:]

    def test_reported_row_preserves_headings_and_psx_controls(self):
        self.assertFalse(self.errors)
        self.assertTrue(self.en.startswith('【○ button】'))
        self.assertIn('【× button】', self.en)
        self.assertIn('【R1・R2 button】', self.en)
        self.assertIn('【L1・L2 button】', self.en)
        self.assertIn('【Directional buttons】', self.en)
        self.assertIn('＜Before starting＞<FF03>Add a coin to the bet.', self.en)
        self.assertNotIn('Before starting Add', self.en)


if __name__ == '__main__':
    unittest.main()
