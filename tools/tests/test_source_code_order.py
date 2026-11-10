"""PSP controls are translated in place, never fitted to Japanese slots."""
from pathlib import Path
import re
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/extraction_tools/psp'),
                str(ROOT / 'src/injection_tools')]
import port_codes
import port_derive
import port_story
import port_btlevt
import port_btlneg
import vwf_wrap
import tstatus
from codec import US_MAP, decode_box


def raw(text):
    glyphs = {v: k for k, v in US_MAP.items()}
    out = bytearray()
    for token in re.findall(r'<[0-9A-F]{4}>|.', text):
        out.extend(struct.pack('>H', int(token[1:-1], 16) if token.startswith('<') else glyphs[token]))
    return bytes(out)


class SourceControls(unittest.TestCase):
    def story(self, text):
        segments, flags = port_story.us_parts(raw(text))
        self.assertEqual(flags, [])
        items = [('w', word) for _lab, words in segments for word in words]
        out, _, flags = port_story.reflow(None, items)
        self.assertEqual(flags, [])
        return port_story._clean(out)

    def test_numeric_inserts_keep_their_source_words_and_spaces(self):
        for source, target in (('<FF11>', '<FF11>'), ('<FF1A><8200>', '<FF12>')):
            text = f'You have {source} units.<FF02><FF01>'
            self.assertEqual(self.story(text), f'You have {target} units.<FF02><FF01>')

    def test_mixed_inserts_and_pauses_stay_in_source_order(self):
        out = self.story('First <FF11> units,<FF05><1E00> then <FF07> gets <FF1A><8200> units.<FF02><FF01>')
        positions = [out.index(token) for token in ('First', '<FF11>', '<FF05><1E><00>', 'then', '<FF07><01>', '<FF12>')]
        self.assertEqual(positions, sorted(positions))

    def test_unknown_variable_is_not_paired_with_a_japanese_insert(self):
        with self.assertRaisesRegex(ValueError, 'unsupported PSP variable'):
            port_codes.adv_variable(0xFFFF)

    def test_shared_translation_preserves_source_counts(self):
        source = 'One<FF05><1E00> two<FF05><1E00> three<FF02><FF04>Four<FF01>'
        expected = 'One<FFFC> two<FFFC> three<FFFB><FFF7>Four'
        for ja in ('', '日本語<FFF9>', '日本語<FFFC><FFFC><FFFC><FFEF>'):
            self.assertEqual(port_derive.translate_codes(source, ja, interpreter='battle'), expected)

    def test_battle_composition_never_parks_japanese_codes_at_sentence_ends(self):
        out = port_btlevt.compose(['Before <FFF8>, after<FF05><1E00> this.', 'Next <FF07>.'], '')
        self.assertEqual(out, 'Before <FFF8>, after<FFFC> this.<FFFB><FFF7>Next <FFF9>.')

    def test_bare_extracted_pause_translates_without_eating_following_text(self):
        self.assertEqual(port_codes.battle('Before<FF05> after<FF05>!'),
                         'Before<FFFC> after<FFFC>!')

    def test_battle_wrap_prices_insert_width(self):
        text = 'Some words ' + '<FFF9>' + ' and more words after the actor name.'
        out, _ = port_btlevt.rewrap(text)
        for line in out.split('<FFF6>'):
            self.assertLessEqual(vwf_wrap.text_width(line), vwf_wrap.BOX_WIDTH)

    def test_dialogue_does_not_trim_source_controls_to_japanese_counts(self):
        text = 'One<FF05><1E00> two<FF05><1E00> three<FF02><FF01>'
        self.assertEqual(port_derive.translate_codes(text, '日本語<FF01>'),
                         'One<FF05><1E><00> two<FF05><1E><00> three<FF02><FF01>')

    def test_clean_edges_keeps_runtime_insert_spacing(self):
        for code in ('<FF11>', '<FF12>') + vwf_wrap.INSERT_CODES:
            text = f'Before {code} after'
            self.assertEqual(vwf_wrap.clean_edges(text), text)

    def test_formatting_does_not_consume_following_runtime_controls(self):
        text = 'Before <FF18><0700><FF1A><8200><FF18><0000> after<FF01>'
        self.assertEqual(port_derive.translate_codes(text), 'Before <FF12> after<FF01>')

    def test_negotiation_sources_retain_controls_without_balancing(self):
        source = [(1, '', 'Before<FFFC> after<FF01>'),
                  (2, '', 'Next <FFF8> value.<FF01>')]
        speaker, text = port_btlneg.source_message(source, [1, 2])
        self.assertEqual(speaker, '')
        self.assertEqual(text, 'Before<FFFC> after<FF01>Next <FFF8> value.')

    def test_battle_operands_travel_with_their_translated_instruction(self):
        self.assertEqual(port_codes.battle('A<FF06><0300>B<FF0E><0100>C'),
                         'A<FFFE><03>B<FFF1><01>C')
        self.assertEqual(vwf_wrap.atoms('<FFFE><03>'), [('c', '<FFFE><03>')])

    def test_validation_never_requires_importing_japanese_controls(self):
        self.assertTrue(port_derive.codes_match('Before<FFFC> after<FFFC>',
                                               interpreter='battle'))
        self.assertFalse(port_derive.codes_match('Before<FF07> after', interpreter='battle'))
        errors = tstatus.check('前<FF06><03>後<FF06><00><FF01>',
                               'Before after<FF01>', want_label=None)
        self.assertNotIn('codes', [kind for kind, _ in errors])

    def test_every_real_coin_and_card_source_retains_insert_position(self):
        if not (ROOT / 'data/psp_us').exists():
            self.skipTest('requires PSP-US data')
        checked = 0
        for file in ('E0', 'E1', 'E2', 'E3'):
            for entry in port_story.usp_entries(file):
                for k in range(len(entry.boxes)):
                    data = entry.box_bytes(k)
                    source = decode_box(data, holes=[])
                    if '<FF11>' not in source and '<FF1A><8200>' not in source:
                        continue
                    segments, flags = port_story.us_parts(data, ja='')
                    self.assertEqual(flags, [])
                    out, _, _ = port_story.reflow(None, [('w', w) for _lab, ws in segments for w in ws])
                    out = re.sub(r'<FF0[234]>', ' ', port_story._clean(out))
                    expected = source.replace('<FF1A><8200>', '<FF12>').replace('＞', '')
                    expected = re.sub(r'<FF0[234]>', ' ', expected)
                    self.assertEqual(' '.join(out.split()), ' '.join(expected.split()), (file, k))
                    checked += 1
        self.assertGreater(checked, 40)


if __name__ == '__main__':
    unittest.main()
