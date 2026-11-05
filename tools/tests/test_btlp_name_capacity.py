"""Capacity checks for source-derived battle-dialogue name inserts."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))

import etext
import name_tails


class BattleNameCapacity(unittest.TestCase):
    def test_source_names_fit_one_dialogue_insert(self):
        # The original BtlInsert is 0x18 bytes including its FF terminator.
        # This proves the compact encoding's capacity, not that the runtime
        # insertion path has yet been converted to use it.
        for family, records in (('item', name_tails.item_rows()),
                                ('demon', name_tails.demon_rows())):
            self.assertTrue(records, f'no source-derived {family} names')
            for ident, text in records:
                with self.subTest(family=family, ident=ident):
                    encoded = etext.encode(text, end=None)
                    self.assertLessEqual(len(encoded) + 1, 0x18)
                    self.assertNotIn(0xFF, encoded)
                    self.assertEqual(etext.decode(encoded), text)


if __name__ == '__main__':
    unittest.main()
