"""Choice-box data invariants (tools/talk_choices.py).

The negotiation box can only show what the TALK row tables say: the <FFFD>
parameter indexes a 12-byte row (count, id0, id1, id2) and a third id >= 0x1F4
means two entries.  These tests pin the shipped corpus facts that an in-game
screenshot has to agree with; they skip when the local game data is absent.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import talk_choices  # noqa: E402

COL = {name: i for i, name in enumerate(talk_choices.HEAD)}


class ChoiceRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        psx = ROOT / 'data' / 'psx' / 'TALK'
        if not psx.is_dir():
            raise unittest.SkipTest('requires data/psx/TALK')
        (_h, _o, _q, cls.rows, cls.opts,
         cls.questions, cls.probs) = talk_choices.scan(
            str(psx), str(ROOT / 'build' / 'TALK'))
        cls.ref = [r for r in cls.rows if r[COL['referenced']] == 'Y']

    def test_referenced_options_all_resolve(self):
        self.assertEqual([(r[0], r[1]) for r in self.ref
                          if r[COL['fallback']] == 'Y'], [],
                         'a reachable choice hit the pointer fallback')
        missing = [(r[0], r[1])
                   for r in self.ref
                   if any(not t for t in r[COL['en0']:COL['en2'] + 1][:r[COL['eff_count']]])]
        self.assertEqual(missing, [], 'a reachable choice shows no text')

    def test_retail_bound_would_collapse_sinsi_three_entry_rows(self):
        # The reported screen: before btlp/choice_answer_bound.asm, the engine
        # rejected every answer pointer above 0x801CFFFF and substituted
        # directory entry 0. SINSI's three-entry rows sit above that retail
        # limit, so all three options became entry 0 ("I have a lot."). With
        # the loaded answer-pool end as the bound they show their real texts.
        import talk
        bp = ROOT / 'build' / 'TALK' / 'SINSI.BIN'
        if not bp.exists():
            raise unittest.SkipTest('requires build/TALK/SINSI.BIN')
        b = talk.Talk('SINSI', bp.read_bytes())
        rows = {r[1]: r for r in self.ref
                if r[0] == 'SINSI' and r[COL['eff_count']] == 3}
        self.assertTrue({108, 109, 110, 111, 112,
                         113, 114, 115, 116, 117} <= set(rows))
        for n in (108, 109, 110, 111, 112, 113, 114, 115, 116, 117):
            r = rows[n]
            ids = [r[COL['id0']], r[COL['id1']], r[COL['id2']]]
            retail = [talk_choices.engine_text(b, i, 0x801CFFFF) for i in ids]
            fixed = [talk_choices.engine_text(b, i, 0x801C0000 + b.hdr[2])
                     for i in ids]
            self.assertEqual(set(retail), {'I have a lot.<FFF5>'},
                             f'SINSI row {n}: {retail}')
            self.assertEqual(len(set(fixed)), 3, f'SINSI row {n}: {fixed}')

    def test_referenced_rows_are_two_or_three_entries(self):
        bad = [(r[0], r[1], r[COL['eff_count']]) for r in self.ref
               if r[COL['eff_count']] not in (2, 3)]
        self.assertEqual(bad, [])

    def test_no_reachable_row_repeats_all_three_options(self):
        self.assertEqual([(r[0], r[1]) for r in self.ref
                          if r[COL['same3']] == 'Y'], [])

    def test_reachable_duplicate_wording_is_known(self):
        # PSP-US uses the same English for two different JP answers in these
        # two rows; nothing else in the corpus repeats a reachable option.
        got = {(r[0], r[1]) for r in self.ref if r[COL['duplicate']] == 'Y'}
        self.assertEqual(got, {('BASKET', 40), ('KOUMAN', 38)})
        rows = {(r[0], r[1]): r for r in self.ref}
        self.assertEqual(rows[('BASKET', 40)][COL['en0']],
                         rows[('BASKET', 40)][COL['en1']])
        self.assertEqual(rows[('KOUMAN', 38)][COL['en0']],
                         rows[('KOUMAN', 38)][COL['en1']])

    def test_i_have_a_lot_is_only_a_first_option_of_two(self):
        got = {(o[0], o[1], o[3]) for o in self.opts
               if o[0] == 'SINSI' and o[2] == 'Y'
               and 'I have a lot.' in o[6]}
        self.assertEqual(got, {('SINSI', 0, 0), ('SINSI', 6, 0),
                               ('SINSI', 12, 0), ('SINSI', 18, 0)})
        for f, r, _i in got:
            row = next(x for x in self.ref if x[0] == f and x[1] == r)
            self.assertEqual(row[COL['eff_count']], 2)
            self.assertEqual(row[COL['duplicate']], 'N')

    def test_three_entry_rows_show_three_texts(self):
        # KOUMAN 38 is the one 3-entry row with repeated wording (PSP-US uses
        # one translation for two JP answers); every other one is distinct.
        for r in self.ref:
            if r[COL['eff_count']] != 3:
                continue
            texts = r[COL['en0']:COL['en2'] + 1]
            self.assertTrue(all(texts), f'{r[0]} row {r[1]}')
            want = 2 if (r[0], r[1]) == ('KOUMAN', 38) else 3
            self.assertEqual(len(set(texts)), want,
                             f'{r[0]} row {r[1]}: {texts}')


if __name__ == '__main__':
    unittest.main()
