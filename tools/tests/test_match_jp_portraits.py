"""Conservative PSP portrait pairing; no extraction, table writes, or builds."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/injection_tools')]
import match_jp


def row(pos, speaker, body='text'):
    return {'pos': hex(pos), 'entry': '', 'box': '',
            'text': f'<FF1B>{speaker}<FF03>{body}<FF02><FF01>'}


class PortraitProof(unittest.TestCase):
    def setUp(self):
        self.jp = [row(0x100, '甲'), row(0x200, '乙'), row(0x300, '甲'),
                   row(0x500, '乙')]
        self.us = [row(0x1000, 'First'), row(0x2000, 'Second'),
                   row(0x3000, 'First'), row(0x5000, 'Second')]
        self.anchors = [(0x100, 0x1000), (0x300, 0x3000), (0x500, 0x5000)]

    def proof(self):
        return match_jp._portrait_gap_pairs(self.anchors, self.jp, self.us)

    def assert_rejected(self):
        self.assertNotIn('0x200', self.proof())

    def test_whole_gap_with_independently_learned_speaker(self):
        self.assertEqual(self.proof()['0x200'], '0x2000')

    def test_layout_and_name_insert_differences_are_match_only(self):
        self.jp[1] = row(0x200, '乙', 'a<FF0F>b<FF03>c')
        self.us[1] = row(0x2000, 'Second', 'abc')
        self.assertEqual(self.proof()['0x200'], '0x2000')
        self.assertIn('<FF0F>', self.jp[1]['text'])

    def test_anchor_inside_leading_space_owns_complete_unit(self):
        self.us[2]['text'] = ' ' + self.us[2]['text']
        self.anchors[1] = (0x300, 0x3002)
        self.assertEqual(self.proof()['0x200'], '0x2000')

    def test_extra_portrait_and_extra_plain_record_reject_gap(self):
        for extra in (row(0x2100, 'Second'),
                      {'pos': '0x2100', 'text': 'extra<FF02><FF01>'}):
            self.us.append(extra)
            self.assert_rejected()
            self.us.pop()

    def test_contradictory_canonical_anchor_rejects(self):
        self.anchors.append((0x300, 0x5000))
        self.assert_rejected()

    def test_missing_speaker_proof(self):
        self.anchors.pop()
        self.assert_rejected()

    def test_ambiguous_speaker_proof(self):
        self.jp.append(row(0x700, '乙'))
        self.us.append(row(0x7000, 'Other'))
        self.anchors.append((0x700, 0x7000))
        self.assert_rejected()

    def test_every_authored_page_speaker_is_checked(self):
        self.jp[1] = row(0x200, '乙', 'a<FF02><FF04><FF1B>乙<FF03>b')
        self.us[1] = row(0x2000, 'Second',
                         'a<FF02><FF04><FF1B>First<FF03>b')
        self.assert_rejected()

    def test_choice_and_pause_parameters_not_discarded(self):
        for code in ('FF0E', 'FF05'):
            self.jp[1] = row(0x200, '乙', f'a<{code}><0001>b')
            self.us[1] = row(0x2000, 'Second', f'a<{code}><0002>b')
            self.assert_rejected()

    def test_meaningful_control_mismatch(self):
        self.us[1] = row(0x2000, 'Second', 'text<FF04>')
        self.assert_rejected()

    def test_unterminated_portrait_not_silently_skipped(self):
        self.us.append({'pos': '0x2100', 'text': '<FF1B>Second<FF03>cut'})
        self.assert_rejected()

    def test_true_contained_page_suffix_not_an_extra_record(self):
        text = '<FF1B>Second<FF03>first<FF02><FF04>'
        tail = '<FF1B>Second<FF03>last<FF02><FF01>'
        self.us[1]['text'] = text + tail
        self.jp[1]['text'] = ('<FF1B>乙<FF03>first<FF02><FF04>'
                              '<FF1B>乙<FF03>last<FF02><FF01>')
        offset = 0x2000 + 2 * len(match_jp._PORTRAIT_UNITS.findall(text))
        self.us.append({'pos': hex(offset), 'text': tail})
        self.assertEqual(self.proof()['0x200'], '0x2000')
        self.us[-1]['text'] = tail.replace('last', 'fake')
        self.assert_rejected()

    def test_crossing_portrait_overlap_rejected(self):
        self.us.append(row(0x2002, 'Second'))
        self.assert_rejected()

    def test_padded_authored_page_head_only(self):
        padded = ('<FF1B>甲<FF03>first<FF02><FF04>  '
                  '<FF1B>甲<FF03>last<FF02><FF01>')
        plain = padded.replace('<FF04>  ', '<FF04>')
        self.assertEqual(match_jp.dialogue_key(padded),
                         match_jp.dialogue_key(plain))
        self.assertIn('甲', match_jp.dialogue_key('first  <FF1B>甲<FF03>last'))
        self.jp[1] = row(0x200, '乙', 'first<FF02><FF04>  <FF1B>乙<FF03>last')
        self.us[1] = row(0x2000, 'Second',
                         'first<FF02><FF04> <FF1B>Second<FF03>last')
        self.assertEqual(self.proof()['0x200'], '0x2000')

    def test_unknown_controls_and_parameters_fail_closed(self):
        self.jp[1] = row(0x200, '乙', 'a<FF05><0001>b')
        self.us[1] = row(0x2000, 'Second', 'a<FF05><0002>b')
        self.assert_rejected()
        self.us[1] = row(0x2000, 'Second', 'a<FF99>b')
        self.assert_rejected()
        self.us[1] = row(0x2000, 'Second', 'a[1234]b')
        self.assert_rejected()

    def test_quote_and_repeated_page_speaker_normalization(self):
        a = '甲：「same」<FF02>「words」<FF03>end<FF02>'
        b = ('<FF1B>甲<FF03>"same"<FF02><FF04>'
             '<FF1B>甲<FF03>"words"<FF03>end<FF02><FF01>')
        self.assertEqual(match_jp.dialogue_key(a), match_jp.dialogue_key(b))
        inline = 'word<FF1B>甲<FF03>other'
        self.assertIn('甲', match_jp.dialogue_key(inline))


class RealShrineProof(unittest.TestCase):
    def test_real_sources_prove_both_shrine_rows(self):
        source = ROOT / 'data/extracted_text/psp_jp/EBOOT.tsv'
        if not source.exists():
            self.skipTest('local game extracts unavailable')
        jp = match_jp.toolbelt.read_extracted('psp_jp', 'EBOOT')
        us = match_jp.toolbelt.read_extracted('psp_us', 'EBOOT')
        anchors = match_jp._between('EBOOT')[0]
        pairs = match_jp._portrait_gap_pairs(anchors, jp, us)
        self.assertEqual(pairs['0x27dc0c'], '0x28a07e')
        self.assertEqual(pairs['0x27dbc0'], '0x289fb2')
        integrated = match_jp._order_pairs('EBOOT')
        self.assertEqual(integrated['0x27dc0c'], '0x28a07e')
        self.assertEqual(integrated['0x27dbc0'], '0x289fb2')
        psx = match_jp.toolbelt.read_extracted('psx', 'S2D')
        lookup = {r['pos']: r for r in jp}
        for idx, pos in ((1, '0x27dc0c'), (2, '0x27dbc0')):
            # the PSX side carries a member-id unit after each name insert
            self.assertEqual(match_jp.dialogue_key(psx[idx]['text'], psx=True),
                             match_jp.dialogue_key(lookup[pos]['text']))


if __name__ == '__main__':
    unittest.main()
