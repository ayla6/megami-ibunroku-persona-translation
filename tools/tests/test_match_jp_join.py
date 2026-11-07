"""JP<->US twins use the slot join per entry, not only per file."""
from pathlib import Path
from unittest.mock import patch
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/injection_tools')]
import match_jp


def rows(counts):
    return [{'entry': str(entry), 'box': str(box), 'pos': f'{entry}:{box}',
             'text': 'x'}
            for entry, n in counts.items() for box in range(n)]


class EntryJoin(unittest.TestCase):
    REL = 'pack/__join_test__'

    def setUp(self):
        match_jp._ENTRY_JOIN.clear()
        self.addCleanup(match_jp._ENTRY_JOIN.clear)

    def join(self, jp_counts, us_counts):
        jp, us = rows(jp_counts), rows(us_counts)

        def extracted(region, _rel, optional=False):
            return jp if region == 'psp_jp' else us

        with patch.object(match_jp.toolbelt, 'read_extracted',
                          side_effect=extracted):
            return match_jp.entry_join(self.REL, '1'), \
                match_jp.entry_join(self.REL, '2')

    def test_one_changed_entry_does_not_disable_the_others(self):
        # pack/E3: entry 2 lost a box on the US side, entry 36 did not.
        self.assertEqual(self.join({1: 3, 2: 2}, {1: 3, 2: 1}), (True, False))

    def test_an_entry_on_one_side_only_is_not_a_coordinate(self):
        self.assertEqual(self.join({1: 3, 2: 2}, {1: 3}), (True, False))

    def test_equal_counts_join(self):
        self.assertEqual(self.join({1: 2, 2: 4}, {1: 2, 2: 4}), (True, True))


if __name__ == '__main__':
    unittest.main()
