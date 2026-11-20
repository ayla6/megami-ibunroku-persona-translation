"""Choice grids must fit the box the engine draws.

The ADV message box is three 16 px rows (roomsetup.c: g_bg_layers[4].h =
0x30) and the prompt's arming line is the first, so the option list may use
two. A 2x2 grid is therefore the only four-option shape; wording that cannot
fit it must be over limit, never a taller single-column list that scrolls its
first option out of view (choices.layout -> OverLimit -> toolbelt.route_over).
"""
import sys
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import choices  # noqa: E402


def row(idx, rows, cols, width=7):
    return {'idx': idx, 'ptr': 0, 'params': bytes([rows, cols, width, 0])}


class ChoiceLayout(unittest.TestCase):
    def test_a_two_by_two_grid_that_fits_keeps_both_columns(self):
        text, rn, cn, _w = choices.layout(
            row(0, 2, 2), 'Start|Quit<FF03>Coins|Rules')
        self.assertEqual((rn, cn), (2, 2))

    def test_column_two_starts_on_its_stop(self):
        # 'Start game' (70 px) and 'Check coins' (74 px) sit 58 and 54 px
        # short of the 128 px stop: whole 4 px spaces then 1 px blanks put
        # both rows' column 2 on the stop exactly.
        import vwf_wrap
        import make_vwf_font
        text, rn, cn, w = choices.layout(
            row(3, 2, 2), 'Start game|Stop playing<FF03>Check coins|See explanations')
        starts = set()
        for line, col2 in zip(text.split('<FF03>'), ('Stop playing', 'See explanations')):
            starts.add(vwf_wrap.text_width(line[:line.index(col2)]))
        self.assertEqual(starts, {(w + 1) * 16})

    def test_four_options_that_fit_no_two_column_width_are_over_limit(self):
        # Four options cannot become a taller single column: the box has two
        # option rows, so the row is a manual draft instead of a broken grid.
        wide = 'W' * 40
        with self.assertRaises(choices.OverLimit):
            choices.layout(row(1, 2, 2),
                           f'{wide}|{wide}<FF03>{wide}|{wide}')

    def test_a_short_one_by_two_grid_still_folds_to_two_rows(self):
        # No width fits both cells side by side, but two options fit the
        # two-row list, so the order survives as a single column.
        text, rn, cn, _w = choices.layout(
            row(2, 1, 2), 'W' * 20 + '|' + 'W' * 20)
        self.assertEqual((rn, cn), (2, 1))
        self.assertIn('<FF03>', text)


if __name__ == '__main__':
    unittest.main()
