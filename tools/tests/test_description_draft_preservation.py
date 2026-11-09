"""Long human description drafts survive builds without being shortened."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import descs
import toolbelt


class DescriptionDrafts(unittest.TestCase):
    def test_description_never_ships_a_line_or_page_move(self):
        start, _end = descs.strings(descs.data())[0]
        pos = hex(start - descs.B)
        for code in ('<FF03>', '<FF04>', '<FFF6>'):
            rows = descs.read_rows()
            rows[pos] = {'pos': pos, 'en': f'First{code}second', 'psp': '', 'id': 'test'}
            with self.subTest(code=code), patch.object(descs, 'read_rows', return_value=rows):
                with self.assertRaisesRegex(SystemExit, 'one-row description'):
                    descs.build()

    def test_overwide_human_line_is_kept_but_not_silently_shipped(self):
        source = descs.data()
        start, end = descs.strings(source)[0]
        pos = hex(start - descs.B)
        rows = descs.read_rows()
        authored = 'W' * 40
        rows[pos] = {'pos': pos, 'en': authored, 'psp': '', 'id': 'human'}
        man = toolbelt.read_manual('SLPS_005.00')
        man = [r for r in man if r['pos'] != pos] + [
            {'id': 'human', 'pos': pos, 'en': authored, 'psp': '', 'note': 'keep this'}]
        with TemporaryDirectory() as d:
            root = Path(d)
            with patch.object(descs, 'OUT', str(root / 'descs.asm')), \
                 patch.object(descs, 'DRAFT_OUT', str(root / 'descs_drafts.tsv')), \
                 patch.object(descs, 'read_rows', return_value=rows), \
                 patch.object(toolbelt, 'read_manual', return_value=man), \
                 patch.object(toolbelt, 'route_over') as route:
                descs.build()
                self.assertEqual(rows[pos]['en'], authored)
                self.assertEqual(next(r for r in man if r['pos'] == pos)['en'], authored)
                self.assertFalse(any(call.args[1] == pos for call in route.call_args_list))
                report = (root / 'descs_drafts.tsv').read_text()
                self.assertIn(pos, report)
                self.assertIn(authored, report)
                self.assertTrue((root / 'descs.asm').is_file())


if __name__ == '__main__':
    unittest.main()
