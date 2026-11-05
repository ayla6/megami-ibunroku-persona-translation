"""Battle config/control extraction is source-owned; drafts never vanish."""
from pathlib import Path
import contextlib
import io
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
sys.path.insert(0, str(ROOT / 'src/extraction_tools/psx'))
sys.path.insert(0, str(ROOT / 'tools'))
import battle_board_text as boards
import btlp
import extract_text_all
import toolbelt
import verify_disc


class BattleBoardText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = (ROOT / 'data/psx/BTLP.BIN').read_bytes()

    def test_pool_scan_and_descriptor_aliases(self):
        rows = boards.scan(self.stock)
        self.assertEqual(len(rows), 93)
        self.assertEqual(len({p for p, _ in rows}), 93)
        offsets = {p for p, _ in rows}
        for at, count, _pool in boards.BOARDS:
            for i in range(count):
                ptr = struct.unpack_from('<I', self.stock, at + i * 12 + 4)[0]
                self.assertIn(ptr - boards.BASE, offsets)

    def test_initial_and_direct_runtime_descriptor_links_are_distinct(self):
        initial = boards.initial_references(self.stock)
        direct = boards.direct_assignments(self.stock)
        self.assertEqual(len(initial), 89)
        # The alternate mode is assigned into the same descriptor at runtime;
        # it is not safe to equate absence in the initial table with disuse.
        self.assertNotIn(0x7a304, initial)
        self.assertIn((0x80080020 - boards.BASE, 0x7a304, 0x7a3b4), direct)
        self.assertIn((0x800800e4 - boards.BASE, 0x7a2fc, 0x7a3b4), direct)
        accounted = initial | {source for _code, source, _field in direct}
        self.assertEqual(len({off for off, _ in boards.scan(self.stock)} - accounted), 3)

    def test_retail_disc_bytes_and_exact_report_are_required(self):
        boards.verify_retail_bytes(self.stock, self.stock)
        boards.verify_draft_report(['pos'], [])
        for bad in ([], ['wrong'], ['pos', '0x1']):
            with self.assertRaises(ValueError):
                boards.verify_draft_report(bad, [])
        for off in (boards.POOLS[0][0], boards.BOARDS[0][0]):
            altered = bytearray(self.stock)
            altered[off] ^= 1
            with self.assertRaises(ValueError):
                boards.verify_retail_bytes(self.stock, altered)

    def test_level3_checks_actual_disc_before_exempting_drafts(self):
        pos = hex(boards.POOLS[0][0])
        rows = [{'pos': pos, 'en': 'full human draft'}]
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'build').mkdir()
            report = Path(tmp, 'build/btl_board_drafts.tsv')
            report.write_text('pos\n' + pos + '\n')
            with mock.patch.object(verify_disc, 'ROOT', tmp), \
                 mock.patch.object(verify_disc, 'fails', 0), mock.patch.object(verify_disc, 'checks', 0), \
                 mock.patch.object(verify_disc, 'translation_rels', return_value={'BTLP'}), \
                 mock.patch.object(verify_disc, '_row_forms', return_value=(None, [])), \
                 mock.patch.object(toolbelt, 'merged_rows', return_value=rows), \
                 mock.patch.object(btlp, 'data', return_value=self.stock), \
                 mock.patch.object(btlp, 'evt_messages', return_value=[]), \
                 mock.patch.object(btlp, 'neg_strings', return_value=[]), \
                 mock.patch.object(verify_disc.features, 'on', return_value=True):
                def check(image):
                    verify_disc.fails = verify_disc.checks = 0
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        verify_disc.level3(lambda name: image if name == 'BTLP.BIN' else b'')
                    return verify_disc.fails, out.getvalue()
                fails, out = check(self.stock)
                self.assertEqual(fails, 0)
                self.assertIn('1 battle-board draft(s) retained unshipped', out)
                altered = bytearray(self.stock)
                altered[boards.POOLS[0][0]] ^= 1
                fails, out = check(altered)
                self.assertGreater(fails, 0)
                self.assertIn('battle-board draft ownership', out)
                self.assertNotIn('draft(s) retained unshipped', out)
                report.unlink()
                fails, out = check(self.stock)
                self.assertGreater(fails, 0)
                self.assertIn('battle-board draft ownership', out)

    def test_pointer_and_padding_drift_are_rejected(self):
        altered = bytearray(self.stock)
        struct.pack_into('<I', altered, boards.BOARDS[0][0] + 4, boards.BASE)
        with self.assertRaises(ValueError):
            boards.scan(altered)
        altered = bytearray(self.stock)
        first = boards.POOLS[0][0]
        end = altered.index(0xff, first)
        altered[end + 1] = 1
        with self.assertRaises(ValueError):
            boards.scan(altered)

    def test_all_positions_are_canonical_and_manual(self):
        extracted = {r['pos']: r['text'] for r in toolbelt.read_extracted('psx', 'BTLP')}
        manual = {r['pos']: r for r in toolbelt.read_manual('BTLP')}
        generated = {r['pos']: r for r in toolbelt.read_generated('BTLP')}
        for offset, ja in boards.scan(self.stock):
            pos = hex(offset)
            self.assertEqual(extracted[pos], ja)
            # A later proven PSP match can graduate a gap into generated.
            row = manual.get(pos) or generated.get(pos)
            self.assertIsNotNone(row, pos)
            self.assertTrue(row.get('note') or row.get('en'))

    def test_dump_routes_only_unmatched_board_sources_to_manual(self):
        scanned = boards.scan(self.stock)[:2]
        first, second = (hex(off) for off, _ja in scanned)
        ja = {hex(off): text for off, text in scanned}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(toolbelt, 'GENERATED', str(Path(tmp, 'generated'))), \
                 mock.patch.object(toolbelt, 'MANUAL', str(Path(tmp, 'manual'))), \
                 mock.patch.object(toolbelt, 'psx_text_of', return_value=ja), \
                 mock.patch.object(btlp, 'data', return_value=self.stock), \
                 mock.patch.object(btlp, 'families', return_value=[(off, 'board') for off, _ in scanned]):
                toolbelt.write_generated('BTLP', [{'id': '0', 'pos': first,
                                                  'psp': 'EBOOT:1234', 'en': 'Matched source'}])
                btlp.dump()
                manual = {r['pos']: r for r in toolbelt.read_manual('BTLP')}
                self.assertNotIn(first, manual)
                self.assertIn(second, manual)
                self.assertEqual(manual[second]['en'], '')
                self.assertIn(ja[second], manual[second]['note'])
                self.assertEqual(toolbelt.read_generated('BTLP')[0]['en'], 'Matched source')

    def test_existing_extract_prefix_matches_binary_family_scan(self):
        rows = extract_text_all.btlp_rows('BTLP', str(ROOT / 'data/psx/BTLP.BIN'))
        canonical = [(int(r['pos'], 16), r['text'])
                     for r in toolbelt.read_extracted('psx', 'BTLP')]
        self.assertEqual(rows, canonical)

    def test_full_human_draft_is_reported_without_rewriting_it(self):
        pos = hex(boards.scan(self.stock)[0][0])
        wording = 'An arbitrarily long draft that must be kept verbatim.'
        rows = [{'pos': pos, 'en': wording}, {'pos': hex(boards.scan(self.stock)[1][0]), 'en': ''}]
        self.assertEqual(btlp.board_drafts(self.stock, rows), [pos])
        self.assertEqual(rows[0]['en'], wording)
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'build').mkdir()
            with mock.patch.object(btlp, 'ROOT', tmp), mock.patch.object(btlp, 'data', return_value=self.stock), \
                 mock.patch.object(toolbelt, 'merged_rows', return_value=rows), \
                 mock.patch.object(btlp, 'evt_build'), mock.patch.object(btlp, 'msg_build'), \
                 mock.patch.object(btlp, 'neg_build'), mock.patch.object(btlp, 'ban_build'), \
                 mock.patch.object(toolbelt, 'write_asm'):
                btlp.build()
            self.assertEqual(Path(tmp, 'build/btl_board_drafts.tsv').read_text(), 'pos\n' + pos + '\n')
        self.assertEqual(rows[0]['en'], wording)


if __name__ == '__main__':
    unittest.main()
