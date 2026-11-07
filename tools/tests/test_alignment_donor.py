"""Duplicate-wording repair borrows only an unambiguous identical-JP twin."""
from pathlib import Path
from unittest.mock import patch
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/injection_tools')]
import align


class TwinDonor(unittest.TestCase):
    KEY = 'key'

    def donor(self, rows, local, f='E1', ei=10):
        with patch.object(align, '_global_twins', return_value={self.KEY: rows}), \
                patch.object(align, '_jp_key', return_value=self.KEY):
            return align._twin_donor(f, ei, 'raw', local)

    def test_unanimous_twin_is_a_donor(self):
        rows = [('E2', 4, 1, 'Wording.'), ('E3', 7, 0, 'Wording.')]
        self.assertEqual(self.donor(rows, 'Copied wording.'),
                         ('E2', 4, 1))

    def test_same_file_donor_is_preferred(self):
        rows = [('E2', 4, 1, 'Wording.'), ('E1', 9, 2, 'Wording.')]
        self.assertEqual(self.donor(rows, 'Copied wording.'),
                         ('E1', 9, 2))

    def test_two_translations_are_not_a_donor(self):
        rows = [('E2', 4, 1, 'One wording.'), ('E3', 7, 0, 'Another.')]
        self.assertIsNone(self.donor(rows, 'Copied wording.'))

    def test_one_character_slip_does_not_hide_the_donor(self):
        rows = [('E2', 4, 1, 'agastyatreeyoungones.'),
                ('E2', 5, 0, 'agastyatreeyoungones.'),
                ('E3', 7, 0, 'atastyatreeyoungones.')]
        self.assertEqual(self.donor(rows, 'Copied wording.'),
                         ('E2', 4, 1))

    def test_one_letter_substitution_is_a_spelling_slip(self):
        rows = [('E2', 4, 1, 'heisdead'), ('E2', 5, 0, 'heisdead'),
                ('E3', 7, 0, 'heisdeaf')]
        self.assertEqual(self.donor(rows, 'Copied wording.'),
                         ('E2', 4, 1))

    def test_a_word_difference_is_a_different_wording(self):
        rows = [('E2', 4, 1, 'youngoneswelcome'), ('E2', 5, 0, 'youngoneswelcome'),
                ('E3', 7, 0, 'oldoneswelcome')]
        self.assertIsNone(self.donor(rows, 'Copied wording.'))

    def test_unanimous_local_wording_is_not_replaced(self):
        rows = [('E2', 4, 1, 'Same wording.')]
        self.assertIsNone(self.donor(rows, 'Same wording.'))

    def test_the_local_entry_is_not_its_own_twin(self):
        rows = [('E1', 10, 3, 'Other wording.')]
        self.assertIsNone(self.donor(rows, 'Local wording.'))

    def test_no_other_twin_is_no_donor(self):
        self.assertIsNone(self.donor([], 'Local wording.'))

    def test_a_known_copy_is_never_donor_evidence(self):
        rows = [(0, 'samewording', 'keyA'), (1, 'samewording', 'keyB')]
        self.assertEqual(align._duplicate_copy_boxes(rows), {0, 1})

    def test_repeated_wording_for_the_same_japanese_is_not_a_copy(self):
        rows = [(0, 'samewording', 'keyA'), (1, 'samewording', 'keyA')]
        self.assertEqual(align._duplicate_copy_boxes(rows), set())

    def test_short_wording_is_not_a_duplicate(self):
        rows = [(0, '...', 'keyA'), (1, '...', 'keyB')]
        self.assertEqual(align._duplicate_copy_boxes(rows), set())


class _Entry:
    def __init__(self, n):
        self.boxes = list(range(n))

    def box_bytes(self, i):
        return i


class DuplicateUs(unittest.TestCase):
    """The PSP-US copy check compares the Japanese WORDING, not box slots."""

    def copies(self, jp_keys, jum, ink='thesamewords'):
        jp = _Entry(len(jp_keys))
        us = _Entry(len(jp_keys))

        def key(raw):
            return jp_keys[raw]

        with patch.object(align, 'us_wording', return_value=ink), \
                patch.object(align, '_jp_key', side_effect=key):
            return align.duplicate_us(us, jp, jum)

    def test_identical_japanese_repeated_at_two_boxes_is_not_a_copy(self):
        # E1/160 boxes 34 and 35: the same line twice, legitimately repeated.
        self.assertEqual(
            self.copies(['same', 'same'], {0: 0, 1: 1}), set())

    def test_repeated_wording_for_different_japanese_is_a_copy(self):
        self.assertEqual(
            self.copies(['one', 'two'], {0: 0, 1: 1}), {0, 1})

    def test_a_box_without_a_japanese_partner_is_not_marked(self):
        self.assertEqual(
            self.copies(['one', 'two'], {0: 0}), set())


if __name__ == '__main__':
    unittest.main()
