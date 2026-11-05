"""PSP-proven boot wording belongs to canonical PSX translation rows."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import btlcmd
import btlmsg
import partynames
import personality_source
import psp_build_sources
import tables
import toolbelt


class BootRows(unittest.TestCase):
    def test_canonical_rows_equal_freshly_proven_source(self):
        written = {}
        with patch.object(toolbelt, 'upsert_generated', side_effect=lambda rel, rows: written.update({rel: rows})):
            psp_build_sources.capture()
        for rel, expected in written.items():
            actual = {row['pos']: row for row in toolbelt.read_generated(rel)}
            for row in expected:
                with self.subTest(rel=rel, pos=row['pos']):
                    self.assertEqual((actual[row['pos']]['psp'], actual[row['pos']]['en']),
                                     (row['psp'], row['en']))

    def test_build_consumers_do_not_read_psp(self):
        with patch.object(tables, 'jp_boot', side_effect=AssertionError('PSP JP read')), \
                patch.object(tables, 'us_boot', side_effect=AssertionError('PSP US read')), \
                patch.object(toolbelt, 'read_extracted', side_effect=AssertionError('PSP extract read')):
            self.assertEqual(len(personality_source.read()), personality_source.COUNT)
            self.assertEqual(len(partynames.members()), 8)
            self.assertEqual(len(btlcmd.translated_commands(btlmsg.data())), btlcmd.COUNT)

    def test_missing_rows_fail_closed(self):
        with patch.object(toolbelt, 'merged_rows', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'missing battle command'):
                btlcmd.translated_commands(btlmsg.data())
            with self.assertRaisesRegex(ValueError, 'missing personality'):
                personality_source.read()
            with self.assertRaises(SystemExit):
                partynames.members()


if __name__ == '__main__':
    unittest.main()
