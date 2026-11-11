"""The deviation self-check reuses its parsed input without weakening QA."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import tstatus


class DeviationSequences(unittest.TestCase):
    def test_streamed_reviewed_rows_equal_the_independent_manual_pass(self):
        reviewed = set()
        list(tstatus.rows(reviewed=reviewed))
        old = tstatus.reviewed_set.cache
        self.addCleanup(setattr, tstatus.reviewed_set, 'cache', old)
        tstatus.reviewed_set.cache = None
        self.assertEqual(reviewed, tstatus.reviewed_set())

    def test_classification_parses_each_box_once_and_reconciles(self):
        ja = 'Before <FF07><01> after<FF01>'
        en = 'Before <FF07><02> after<FF01>'
        with patch.object(tstatus, 'seq_nopause', wraps=tstatus.seq_nopause) as parse:
            deviations, valid = tstatus.classify_deviations(ja, en)
        self.assertTrue(valid)
        self.assertEqual(parse.call_count, 2)
        self.assertTrue(tstatus.match_with_deviations(ja, en, deviations))
        self.assertFalse(tstatus.match_with_deviations(ja, en, []))

    def test_invalid_input_and_invalid_deviation_remain_rejected(self):
        with patch.object(tstatus, 'seq_nopause', side_effect=ValueError('bad box')):
            self.assertEqual(tstatus.classify_deviations('x', 'y'), ([], False))
            self.assertFalse(tstatus.match_with_deviations('x', 'y', []))
        self.assertFalse(tstatus.match_with_deviations('x<FF01>', 'y<FF01>',
                                                      [('invalid', '', '')]))


if __name__ == '__main__':
    unittest.main()
