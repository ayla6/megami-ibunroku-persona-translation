"""The PSP-JP -> PSP-US order join between proven pairs (match_jp).

A gap pairs by order only where the pairing cannot be shifted: equal unit
counts with identical control codes, split at landmarks (a code skeleton
that occurs once on each side), and every pair must be the same kind of unit
(speaker line or not, narration or not, a known speaker's name must agree).
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'src/extraction_tools/matching')]
import match_jp  # noqa: E402

E, F3, F4 = (0xFF01,), (0xFFF3, 0xFF01), (0xFFF4, 0xFF01)


def join(a, b, ok=lambda p, q: True):
    ga = [f'j{i}' for i in range(len(a))]
    gb = [f'u{i}' for i in range(len(b))]
    return match_jp._landmark_join(ga, gb, dict(zip(ga, a)), dict(zip(gb, b)), ok)


class OrderJoin(unittest.TestCase):
    def test_equal_gap_pairs_whole(self):
        self.assertEqual(join([E, F3, E], [E, F3, E]), {'j0': 'u0', 'j1': 'u1', 'j2': 'u2'})

    def test_a_cut_line_in_a_uniform_run_pairs_nothing_in_that_run(self):
        # JP: E E E <F3> E E ; US lost one E before the landmark
        got = join([E, E, E, F3, E, E], [E, E, F3, E, E])
        self.assertEqual(got.get('j3'), 'u2')                       # the landmark
        self.assertEqual({'j4': 'u3', 'j5': 'u4'}.items() <= got.items(), True)
        self.assertFalse({'j0', 'j1', 'j2'} & got.keys())          # the broken run

    def test_a_repeated_skeleton_is_not_a_landmark(self):
        self.assertEqual(join([F3, E, F3], [F3, F3]), {})

    def test_landmarks_out_of_order_are_dropped(self):
        self.assertEqual(join([F3, E, F4], [F4, E, E, F3]), {})

    def test_a_unit_kind_mismatch_refuses_the_stretch(self):
        no = lambda p, q: not (p == 'j1' and q == 'u1')
        self.assertEqual(join([E, E, E], [E, E, E], no), {})

    def walk(self, a, b, paired=None):
        ga = [f'j{i}' for i in range(len(a))]
        gb = [f'u{i}' for i in range(len(b))]
        return match_jp._walk_join(ga, gb, dict(zip(ga, a)), dict(zip(gb, b)),
                                   lambda p, q: True, paired or {})

    def test_walk_pairs_a_tail_the_other_build_runs_past(self):
        # JP ends after three messages; US continues with other material
        X = (0xFFFC, 0xFF01)
        got = self.walk([E, E, E], [E, E, E, X, X])
        self.assertEqual(got, {'j0': 'u0', 'j1': 'u1', 'j2': 'u2'})

    def test_walk_refuses_a_run_where_one_line_was_cut(self):
        # a known pair at each end; US lost one of the uniform middle lines
        got = self.walk([F3, E, E, E, F4], [F3, E, E, F4], {'j0': 'u0', 'j4': 'u3'})
        self.assertFalse({'j1', 'j2', 'j3'} & got.keys())

    def test_walk_never_steps_over_units_without_an_end_code(self):
        self.assertEqual(self.walk([(), ()], [(), ()]), {})
        self.assertEqual(self.walk([(0xFF0B,), (0xFF0B,)], [(0xFF0B,), (0xFF0B,)]), {})

    def test_rereads_are_page_slices_of_an_enclosing_row(self):
        whole = '<FF1B>Maki<FF03>A<FF04><FF1B>Maki<FF03>B<FF01>'
        rows = [{'pos': '0x100', 'text': whole},
                {'pos': '0x102', 'text': 'Maki<FF03>A<FF04>'},
                {'pos': '0x112', 'text': 'Maki<FF03>B<FF01>'},
                {'pos': '0x104', 'text': 'Xaki<FF03>A<FF04>'}]
        self.assertEqual(match_jp._rereads(rows), {'0x102', '0x112'})

    def test_end_walk_needs_a_visible_divergence(self):
        X = (0xFFFC, 0xFF01)
        walk = lambda a, b: match_jp._end_walk(
            [f'j{i}' for i in range(len(a))], [f'u{i}' for i in range(len(b))],
            {f'j{i}': c for i, c in enumerate(a)}, {f'u{i}': c for i, c in enumerate(b)},
            lambda p, q: True)
        self.assertEqual(walk([E, E, F3], [E, E, X]), {'j0': 'u0', 'j1': 'u1'})
        self.assertEqual(walk([E, E], [E, E, E]), {})      # ran off one side

    def test_same_unit_rules(self):
        speakers = {'麻希': 'Maki'}
        same = match_jp._same_unit
        self.assertTrue(same('<FF1B>麻希<FF03>あ<FF01>', '<FF1B>Maki<FF03>a<FF01>', speakers))
        self.assertFalse(same('<FF1B>麻希<FF03>あ<FF01>', '<FF1B>Nanjo<FF03>a<FF01>', speakers))
        self.assertFalse(same('<FF1B>麻希<FF03>あ<FF01>', 'a<FF01>', speakers))
        self.assertFalse(same('カード!<FF01>', '＞ Nanjo tried bribing<FF01>', speakers))
        self.assertTrue(same(' ＞悪魔は去った.<FF01>', '＞ The demon left.<FF01>', speakers))

    def test_exact_twins_pair_repeats_by_occurrence_only_when_counts_agree(self):
        rows = match_jp.toolbelt.read_extracted('psp_jp', 'EBOOT')
        line = next(r['text'] for r in rows if '悪魔は逃げていった' in r['text'])
        copies = sum(1 for r in rows if match_jp.bare(r['text']) == match_jp.bare(line))
        got = match_jp.exact_twins('EBOOT', [(k, line) for k in range(copies)])
        self.assertEqual(len(got), copies)
        self.assertEqual(match_jp.exact_twins('EBOOT', [(k, line) for k in range(copies + 1)]), {})


if __name__ == '__main__':
    unittest.main()
