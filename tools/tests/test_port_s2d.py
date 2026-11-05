"""S2D source-coordinate regressions: python -m unittest discover -s tools/tests."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import os
import re
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/extraction_tools/psp'))
sys.path.insert(0, str(ROOT / 'src/extraction_tools/matching'))
import eboot
import port_s2d
import tables


class SourceCoordinates(unittest.TestCase):
    def test_standalone_refreshes_when_source_mapping_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / 'extract.tsv'
            target.write_text('cached')
            source = base / 's2d_map.tsv'
            source.write_text('map')
            os.utime(source, ns=(1, 1))
            os.utime(target, ns=(2, 2))
            with patch.object(eboot.toolbelt, 'ext_path', return_value=str(target)), \
                    patch.object(eboot.toolbelt, 'SOURCE_MAPPINGS', directory), \
                    patch.object(eboot.os.path, 'exists', side_effect=lambda p: Path(p) in (target, source)), \
                    patch.object(eboot, 'dump') as dump, \
                    patch.object(eboot, 'us_boot', return_value=b''):
                self.assertFalse(eboot.ensure_us())
                os.utime(source, ns=(3, 3))
                self.assertTrue(eboot.ensure_us())
                dump.assert_called_once()

    def test_le_pointer_not_preceding_be_terminator(self):
        glyphs = {0x01ff: 'X', 0x0101: 'A', 0x0102: 'B'}
        raw = b'\xff\x01' + struct.pack('<3H', 0x0101, 0x0102, 0)
        self.assertEqual(tables.le_string_at(raw, 2, glyphs, with_end=True),
                         ('AB', 8))

    def test_le_unknown_and_unterminated_fail(self):
        for raw in (struct.pack('<2H', 9, 0), struct.pack('<H', 1)):
            with self.assertRaises(ValueError):
                tables.le_string_at(raw, 0, {1: 'A'})

    def test_be_spans_preserve_existing_api(self):
        raw = struct.pack('>4H', 1, 2, 3, 0xff01)
        glyphs = {1: 'a', 2: 'b', 3: 'c'}
        basic = tables.be_runs(raw, glyphs)
        spans = tables.be_runs(raw, glyphs, with_spans=True)
        self.assertEqual([r[:3] for r in spans], basic)
        self.assertEqual(spans[0][3], len(raw))

    def test_overlay_wins_collision_and_removes_only_proven_interior(self):
        with patch.object(eboot, 'mapped_units', return_value=[(10, 'proven', 20)]), \
                patch.object(eboot, 'le_strings', return_value=[(10, 'aaa'), (12, 'noise'), (30, 'outside')]), \
                patch.object(eboot, 'be_boxes', return_value=[(10, 'bbb', '')]), \
                patch.object(eboot.toolbelt, 'write_extracted') as writer, \
                redirect_stdout(StringIO()):
            eboot.dump('psp_us', b'', {1: 'a'})
        self.assertEqual([(r['pos'], r['text']) for r in writer.call_args.args[2]],
                         [('0xa', 'proven'), ('0x1e', 'outside')])

    def test_jp_does_not_apply_us_source_coordinates(self):
        with patch.object(eboot, 'mapped_units') as mapped, \
                patch.object(eboot, 'le_strings', return_value=[]), \
                patch.object(eboot, 'be_boxes', return_value=[(10, 'Japanese', '')]), \
                patch.object(eboot.toolbelt, 'write_extracted'), \
                redirect_stdout(StringIO()):
            eboot.dump('psp_jp', b'', {})
        mapped.assert_not_called()


@unittest.skipUnless(Path(tables.US_CACHE).exists(), 'requires decrypted PSP input')
class DiscRegression(unittest.TestCase):
    def setUp(self):
        fresh = patch.object(eboot, 'ensure_us')
        fresh.start()
        self.addCleanup(fresh.stop)

    @classmethod
    def setUpClass(cls):
        with patch.object(eboot.toolbelt, 'write_extracted') as writer, redirect_stdout(StringIO()):
            eboot.dump('psp_us', tables.us_boot(), tables.US_LE, tables.US_SPACE)
        cls.extracted = writer.call_args.args[2]

    def test_every_authored_mapping_survives_canonical_extraction(self):
        with patch.object(port_s2d.toolbelt, 'read_extracted', return_value=self.extracted), \
                patch.object(port_s2d.toolbelt, 'read_generated', return_value=[]), \
                patch.object(port_s2d, 'portrait_twin', return_value=None), \
                patch.object(port_s2d.match_jp, 'exact_twins', return_value={}), \
                patch.object(port_s2d.match_jp, 'psx_jp_target', return_value=None), \
                patch.object(port_s2d.toolbelt, 'upsert_generated', side_effect=lambda rel, rows: len(rows)) as writer, \
                redirect_stdout(StringIO()) as report:
            port_s2d.port(True)
        rows = writer.call_args.args[1]
        self.assertIn('failed 0', report.getvalue())
        self.assertEqual(len(rows), 77)  # 30 authored script mappings + 47 names
        bypos = {r['pos']: r for r in rows}
        for pos in ('0x46a4a', '0x47bb8', '0x47be0', '0x47c08'):
            self.assertTrue(bypos[pos]['en'])
        for row in rows:
            self.assertFalse(any('\u3040' <= ch <= '\u9fff' for ch in row['en']), row)
        # Derivation itself, not just the source heads, sees no false LE units.
        self.assertEqual({r['pos'] for r in rows}, set(bypos))

    def test_report_is_read_only_and_empty_generated_is_not_filled(self):
        with patch.object(port_s2d.toolbelt, 'read_extracted', return_value=self.extracted), \
                patch.object(port_s2d.toolbelt, 'read_generated', return_value=[{'pos': '0x46a4a', 'en': ''}]), \
                patch.object(port_s2d, 'portrait_twin', return_value=None), \
                patch.object(port_s2d.match_jp, 'exact_twins', return_value={}), \
                patch.object(port_s2d.match_jp, 'psx_jp_target', return_value=None), \
                patch.object(port_s2d.toolbelt, 'upsert_generated') as writer, \
                redirect_stdout(StringIO()) as report:
            port_s2d.port(False)
        writer.assert_not_called()
        self.assertIn('77 rows filled; failed 0', report.getvalue())


class PortraitDialogue(unittest.TestCase):
    JP = '<FF1B>話者<FF03>全文の台詞です。<FF02><FF01>'
    US = '<FF1B>Speaker<FF03>A complete sentence.<FF02><FF01>'
    PSX = '話者：全文の台詞です。<FF02>'

    def test_only_complete_portraits_are_indexed(self):
        rows = [{'pos': '0x10', 'text': self.JP},
                {'pos': '0x20', 'text': '全文の台詞です。'},
                {'pos': '0x30', 'text': self.JP.removesuffix('<FF01>')}]
        index = port_s2d.portrait_index(rows)
        self.assertEqual(sum(map(len, index.values())), 1)

    def test_proven_twin_only_and_exact_whole_dialogue(self):
        jp = {'pos': '0x10', 'text': self.JP}
        us = {'pos': '0x20', 'text': self.US}
        index = port_s2d.portrait_index([jp])
        with patch.object(port_s2d.match_jp, 'us_twin', return_value=None):
            self.assertIsNone(port_s2d.portrait_twin(self.PSX, index))
        with patch.object(port_s2d.match_jp, 'us_twin', return_value=us) as twin:
            self.assertEqual(port_s2d.portrait_twin(self.PSX, index), us)
            self.assertIsNone(port_s2d.portrait_twin('全文', index))
            twin.assert_called_once_with('EBOOT', jp)

    def test_ambiguous_and_untranslated_twins_stay_gaps(self):
        index = port_s2d.portrait_index([
            {'pos': '0x10', 'text': self.JP}, {'pos': '0x11', 'text': self.JP}])
        with patch.object(port_s2d.match_jp, 'us_twin', side_effect=[
                {'pos': '0x20', 'text': self.US},
                {'pos': '0x21', 'text': self.US.replace('complete', 'different')}]):
            self.assertIsNone(port_s2d.portrait_twin(self.PSX, index))
        with patch.object(port_s2d.match_jp, 'us_twin', return_value={
                'pos': '0x20', 'text': self.JP}):
            self.assertIsNone(port_s2d.portrait_twin(self.PSX, index))

    def test_whole_body_requires_the_same_parseable_japanese_speaker(self):
        index = port_s2d.portrait_index([{'pos': '0x10', 'text': self.JP}])
        with patch.object(port_s2d.match_jp, 'us_twin') as twin:
            for ja in (self.PSX.replace('話者：', '別人：'),
                       self.PSX.replace('話者：', ''), self.JP):
                self.assertIsNone(port_s2d.portrait_twin(ja, index))
            twin.assert_not_called()
        # Kana presentation differences are normalized, never dictionary mapped.
        index = port_s2d.portrait_index([
            {'pos': '0x10', 'text': self.JP.replace('話者', 'カタカナ')}])
        us = {'pos': '0x20', 'text': self.US}
        with patch.object(port_s2d.match_jp, 'us_twin', return_value=us):
            self.assertEqual(port_s2d.portrait_twin(
                self.PSX.replace('話者', 'かたかな'), index), us)

    def test_later_japanese_page_speaker_must_also_be_corroborated(self):
        for head in ('<FF1B>別人<FF03>', ''):
            jp = self.JP.removesuffix('<FF01>') + '<FF04>' + head + '次の台詞。<FF02><FF01>'
            ja = self.PSX + '次の台詞。<FF02>'
            index = port_s2d.portrait_index([{'pos': '0x10', 'text': jp}])
            with self.subTest(head=head), patch.object(
                    port_s2d.match_jp, 'us_twin') as twin:
                self.assertIsNone(port_s2d.portrait_twin(ja, index))
                twin.assert_not_called()

    def test_numeric_pause_units_encode_as_raw_psx_parameter_bytes(self):
        for parameter, expected in (('<0010>', bytes.fromhex('0010')),
                                    ('<7800>', bytes.fromhex('7800'))):
            raw = self.US.replace('sentence.', 'sentence.<FF05>' + parameter)
            en = port_s2d.decoded_en(raw)
            encoded = port_s2d.etext.encode(en)
            pause = encoded.index(b'\xff\x05')
            self.assertEqual(encoded[pause + 2:pause + 4], expected)
            self.assertNotIn(parameter, en)

    def test_malformed_pause_parameters_fail_closed(self):
        for parameter in ('x', '<10>', ''):
            raw = self.US.replace('sentence.', 'sentence.<FF05>' + parameter)
            with self.subTest(parameter=parameter), self.assertRaises(ValueError):
                port_s2d.decoded_en(raw)

    def test_authored_pages_labels_and_timing_order(self):
        raw = ('<FF1B>First speaker<FF03>First sentence.<FF02><FF04>'
               '<FF1B>Other speaker<FF03>Second sentence.<FF02><FF01>')
        en = port_s2d.decoded_en(raw)
        self.assertEqual(en, 'First speaker: First sentence.<FF02><FF04>'
                         'Other speaker: Second sentence.<FF02><FF01>')
        self.assertNotIn('<FF1B>', en)

    def test_repeated_speaker_is_not_reprinted_across_pages(self):
        raw = ('<FF1B>Speaker<FF03>Hello <FF07>!<FF02><FF04>'
               '<FF1B>Speaker<FF03>Again.<FF02><FF04>'
               '<FF1B>Other<FF03>Answer.<FF02><FF04>'
               '<FF1B>Speaker<FF03>Return.<FF02><FF01>')
        en = port_s2d.decoded_en(raw)
        self.assertEqual(en.count('Speaker:'), 2)
        self.assertIn('<FF04>Again.', en)
        self.assertIn('<FF07><01>', en)
        self.assertIn('<FF04>Other: Answer.', en)

    def test_legacy_path_does_not_add_japanese_name_insert(self):
        en = port_s2d.build_en('<FF0F><01>', 'Speaker', [('w', 'Hello!')])
        self.assertEqual(en, 'Speaker: Hello!')

    def test_prose_breaks_rejoin_hyphens_but_separate_words(self):
        for text, expected in (
                ('bunny-<FF03>girls', 'bunny-girls'),
                ('bunny- \t<FF03>\n  girls', 'bunny-girls'),
                ('normal<FF03>words', 'normal words'),
                ('normal  \t<FF03>\n  words', 'normal words'),
                ('normal   words', 'normal words')):
            with self.subTest(text=text):
                raw = '<FF1B>Speaker<FF03>' + text + '<FF02><FF01>'
                self.assertEqual(port_s2d.decoded_en(raw),
                                 'Speaker: ' + expected + '<FF02><FF01>')

    def test_inline_wait_cannot_reset_the_physical_pen(self):
        raw = '<FF1B>Speaker<FF03>First sentence.<FF02>Second sentence.<FF02><FF01>'
        with self.assertRaisesRegex(ValueError, 'wait-in-place'):
            port_s2d.decoded_en(raw)
        # Independent layouts would each fit while the actual combined line
        # overflows. Refuse rather than insert a break or move the wait.
        raw = self.US.replace('A complete sentence.', 'W' * 20 + '<FF02>' + 'W' * 20)
        with self.assertRaises(ValueError):
            port_s2d.decoded_en(raw)

    def test_insert_and_pause_parameters_are_kept(self):
        raw = '<FF1B>Speaker<FF03>Hello <FF07>!<FF05><10><00><FF02><FF01>'
        en = port_s2d.decoded_en(raw)
        self.assertIn('<FF07><01>', en)
        self.assertIn('<FF05><10><00>', en)
        self.assertTrue(en.endswith('<FF02><FF01>'))

    def test_unsupported_and_overflow_refused(self):
        for raw in (self.US.replace('sentence.', 'sentence.<FF0E><01>'),
                    self.US.replace('A complete sentence.', 'Long prose sentence. ' * 30),
                    self.US.removesuffix('<FF01>')):
            with self.assertRaises(ValueError):
                port_s2d.decoded_en(raw)

    @unittest.skipUnless((ROOT / 'data/extracted_text/psp_jp/EBOOT.tsv').exists(),
                         'requires extracted PSP input')
    def test_both_real_shrine_rows_use_complete_proven_us_dialogue(self):
        jp_rows = port_s2d.toolbelt.read_extracted('psp_jp', 'EBOOT')
        index = port_s2d.portrait_index(jp_rows)
        psx = port_s2d.toolbelt.read_extracted('psx', 'S2D')
        for pos in ('0x46d08', '0x46d54'):
            with self.subTest(pos=pos):
                ja = next(r['text'] for r in psx if r['pos'] == pos)
                us = port_s2d.portrait_twin(ja, index)
                self.assertIsNotNone(us)
                en = port_s2d.decoded_en(us['text'])
                heads = re.findall(r'<FF1B>([^<>]+)<FF03>', us['text'])
                for head in set(heads):
                    self.assertIn(head + ':', en)
                self.assertEqual(en.count('<FF04>'), us['text'].count('<FF04>'))
                self.assertEqual(en.count('<FF02>'), us['text'].count('<FF02>'))
                self.assertNotIn('<FF1B>', en)
                self.assertFalse(port_s2d.port_derive.HOLES.search(en))
                self.assertEqual(port_s2d.tstatus.ship_errors(ja, en), [])

    @unittest.skipUnless((ROOT / 'data/extracted_text/psp_jp/EBOOT.tsv').exists(),
                         'requires extracted PSP input')
    def test_port_fills_real_shrine_gaps_once_without_rewriting_filled_rows(self):
        existing = port_s2d.toolbelt.read_generated('S2D', optional=True)
        sentinel = {'pos': '0x46c90', 'en': 'Existing wording must stay untouched.'}
        gaps = {'0x46d08', '0x46d54'}
        existing = [r for r in existing if r['pos'] not in gaps | {sentinel['pos']}] + [sentinel]
        with patch.object(eboot, 'ensure_us'), \
                patch.object(port_s2d.toolbelt, 'read_generated', return_value=existing), \
                patch.object(port_s2d.toolbelt, 'upsert_generated',
                             side_effect=lambda rel, rows: len(rows)) as writer, \
                redirect_stdout(StringIO()):
            port_s2d.port(True)
        rows = writer.call_args.args[1]
        bypos = {r['pos']: r for r in rows}
        self.assertEqual(len(rows), len(bypos))
        self.assertNotIn(sentinel['pos'], bypos)
        for pos in ('0x46d08', '0x46d54'):
            self.assertTrue(bypos[pos]['en'])
            self.assertTrue(bypos[pos]['psp'].startswith('EBOOT:'))


if __name__ == '__main__':
    unittest.main()
