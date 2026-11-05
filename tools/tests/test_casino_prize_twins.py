"""The PSP prize table pairs with the PSX prize bar by sequence (casinoprize).

The PSP keeps each prize as a bonus line then a name, in reverse PSX order;
the pool is the unique longest run that reproduces the PSX bonus kinds, and a
name whose digits differ from the PSX name is a different prize.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'),
                str(ROOT / 'src/extraction_tools/matching')]
import casinoprize  # noqa: E402
import toolbelt  # noqa: E402


class PrizeTwins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = Path(toolbelt.bin_path('CASINO')).read_bytes()
        cls.recs = [(hex(o),) + ja.partition('\uff19')
                    for o, _r, ja in casinoprize.records(src)]
        cls.twins = casinoprize.psp_prize_twins(cls.recs)

    def name_of(self, ja):
        return [self.twins.get(p, (None,))[0] for p, n, _s, _t in self.recs if n == ja]

    def test_sets_take_the_psp_table_name(self):
        self.assertTrue(set(self.name_of('ストーンセット')) == {'Stone Set'})
        self.assertTrue(set(self.name_of('ジュエリーセット')) == {'Gem Set'})

    def test_a_different_count_is_a_different_prize(self):
        self.assertEqual(set(self.name_of('メタルカード８８まい')), {None})

    def test_bonus_kinds(self):
        self.assertEqual(casinoprize.tail_kind('Ｃ１００００００'), '1000000')
        self.assertEqual(casinoprize.tail_kind('+1,000,000 Coins<FF01>'), '1000000')
        self.assertEqual(casinoprize.tail_kind('メタルカード'), 'metal')
        self.assertEqual(casinoprize.tail_kind('+Metal Card'), 'metal')

    def test_complete_prize_encodes_separator_and_coin_icon(self):
        self.assertEqual(casinoprize.encode_prize('ABC+C5000'),
                         casinoprize.fw('ABC') + casinoprize.PLUS
                         + casinoprize.fw('C5000'))

    def test_builder_does_not_append_original_bonus_again(self):
        with patch.object(casinoprize, 'rows', return_value={0: ['ABC+C5000', '']}):
            text, data = casinoprize.translate(0, 'test９Ｃ５０００')
        self.assertEqual(text, 'ABC+C5000')
        self.assertEqual(data, casinoprize.encode_prize(text))

    def test_limit_is_on_complete_line_not_just_the_name(self):
        with patch.object(casinoprize, 'rows', return_value={0: ['A' * 20, '']}):
            with self.assertRaises(SystemExit):
                casinoprize.translate(0, 'test')

    def test_cap_does_not_subtract_bonus_from_complete_line_again(self):
        import port_caps
        for pos, _name, _sep, _tail in self.recs:
            self.assertEqual(port_caps.dest_cap('CASINO', pos),
                             (casinoprize.MAX_CELLS, 'chars', 1))

    def test_last_resort_cannot_replace_complete_prizes_with_names(self):
        import port_derive
        self.assertNotIn('CASINO', port_derive.LAST_RESORT_TABLES)


if __name__ == '__main__':
    unittest.main()
