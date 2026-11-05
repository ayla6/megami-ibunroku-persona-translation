"""Generated promotion may not delete a human manual note or line."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import toolbelt


class ManualUpsert(unittest.TestCase):
    def test_generated_supersedes_queue_rows_and_manual_en_overrides(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            manual = root / 'manual'
            generated = root / 'generated'
            manual.mkdir(); generated.mkdir()
            p = manual / 'BTLP.tsv'
            original = ('id\tpos\tpsp\ten\tnote\n'
                        '1\t0x10\t\t\tPlease keep this research note; user-authored\n'
                        '2\t0x20\t\tUser wording\tHand-authored\n'
                        '3\t0x30\t\t\tunpaired; ja example\n')
            p.write_text(original, encoding='utf-8')
            with patch.object(toolbelt, 'MANUAL', str(manual)), \
                 patch.object(toolbelt, 'GENERATED', str(generated)), \
                 patch.object(toolbelt, 'psx_text_of', return_value={}):
                toolbelt.upsert_generated('BTLP', [
                    {'pos': '0x10', 'en': 'Source one'},
                    {'pos': '0x20', 'en': 'Source two'},
                    {'pos': '0x30', 'en': 'Source three'},
                ])
                got = {r['pos']: r for r in toolbelt.read_manual('BTLP')}
                self.assertEqual(got['0x20']['en'], 'User wording')
                # rows with empty English are queue rows, whatever their note:
                # generated now holds their wording, so they are gone
                self.assertNotIn('0x10', got)
                self.assertNotIn('0x30', got)
                merged = {r['pos']: r for r in toolbelt.merged_rows('BTLP')}
                self.assertEqual(merged['0x10']['en'], 'Source one')
                self.assertEqual(merged['0x20']['en'], 'User wording')
                self.assertEqual(merged['0x30']['en'], 'Source three')


if __name__ == '__main__':
    unittest.main()
