"""Shared typography rules and regressions measured from extracted sources."""
import csv
import itertools
from pathlib import Path
import random
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'),
                str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/extraction_tools/psp')]
import vwf_wrap as wrap
import port_controls
import port_story as story


class FlowRules(unittest.TestCase):
    def test_balanced_shape_is_a_cost_not_a_reward_for_wide_first_lines(self):
        self.assertLess(2 * wrap.fullness(100), wrap.fullness(180) + wrap.fullness(20))

    def test_commas_and_semicolons_close_proper_name_runs(self):
        self.assertFalse(wrap._caps_word('Example,'))
        self.assertFalse(wrap._caps_word('Example;'))
        self.assertTrue(wrap._caps_word('Example'))

    def test_punctuation_boundary_releases_a_connector(self):
        # A comma/semicolon/colon boundary is a real break: the connector may
        # start the next clause's line instead of being clamped to the word.
        items = wrap._glue_items([('w', w) for w in
                                  ["C'mon,", '<FFF3>,', 'if', 'ya']])
        self.assertIn(('w', 'if'), [it[:2] for it in items])
        items = wrap._glue_items([('w', w) for w in ['go', 'to', 'town']])
        self.assertIn(('w', 'go to'), [it[:2] for it in items])

    def test_closer_split_off_a_code_run_never_starts_a_line(self):
        pieces = wrap.word_pieces('<FF07><00>?')
        self.assertEqual(''.join(p[0] for p in pieces), '<FF07><00>?')
        self.assertFalse(pieces[-1][1])
        text = wrap.wrap('Nanjo: What should we do, <FF07><00>? '
                         'It may be a trap. Should we go in?')
        self.assertIn('<FF07><00>?', text)
        self.assertNotRegex(text, r'<FF03>\s*[.,!?;:»)\]]')

    def test_short_quoted_terms_have_soft_protection(self):
        items = wrap._glue_items([('w', w) for w in 'stop saying "young master." please'.split()])
        close = next(it for it in items if it[1] == 'master."')
        self.assertTrue(close[2])

    def test_marked_title_is_structural_but_marked_prose_is_not(self):
        self.assertTrue(port_controls.is_heading('＞ Example Title'))
        self.assertFalse(port_controls.is_heading('＞ This is ordinary prose'))

    def test_entire_shape_matches_exhaustive_optimum(self):
        rng = random.Random(107)
        for _ in range(20):
            words = ['x' * rng.randint(2, 14) for _ in range(7)]
            atoms = [a for _k, a in wrap.flow_model([('w', w) for w in words])]
            atoms[-1].fin = True
            spans = wrap.flow_layout(atoms, 25, len, tail=0)

            def cost(cuts):
                points = (0, *cuts, len(words))
                widths = [len(' '.join(words[a:b])) for a, b in zip(points, points[1:])]
                if max(widths) > 25:
                    return None
                rhythm = 2 * (len(widths) - 1)
                extra = 0
                for i, (a, b) in enumerate(zip(widths, widths[1:])):
                    if i == len(widths) - 2 and b * 2 < a:
                        extra += (a - 2*b) ** 2
                    elif b * 10 > a * 14:
                        extra += (b-a) ** 2
                shape = extra + sum(w*w // (len(widths)-i) for i, w in enumerate(widths)) + sum(
                    (b-a)**2 * (2 if b > a else 1) for a, b in zip(widths, widths[1:]))
                return len(widths), rhythm, shape

            costs = [c for n in range(len(words))
                     for cuts in itertools.combinations(range(1, len(words)), n)
                     if (c := cost(cuts)) is not None]
            self.assertEqual(cost(tuple(j+1 for _i, j in spans[:-1])), min(costs))


class ReportedLayouts(unittest.TestCase):
    CASES = {'balanced': ('E2', 65, 0x132C), 'long_label': ('E0', 19, 0x190C),
             'student': ('E2', 10, 0x1550), 'short_speech': ('E0', 11, 0x14FC),
             'comma_card': ('E0', 11, 0x1510), 'title': ('E0', 6, 0x1458),
             'taper': ('E0', 10, 0x1414), 'whole_speech': ('E2', 32, 0x1678),
             'quote': ('E2', 32, 0x1574), 'bare_card': ('E0', 57, 0x1FC0),
             'nickname': ('E0', 4, 0x1480), 'opening_tail': ('E0', 0, 0x1CF8),
             'opening_taper': ('E0', 0, 0x1D54), 'greeting': ('E0', 0, 0x1E58)}

    @classmethod
    def setUpClass(cls):
        entries = {}
        cls.result = {}
        for key, (f, e, pos) in cls.CASES.items():
            if (f, e) not in entries:
                entries[f, e] = story.convert_entry(f, e)[0]
            entry = story.psx_entries(f)[e]
            i = next(i for i, (off, _end) in enumerate(entry.boxes) if off == pos)
            cls.result[key] = entries[f, e][i][2]

    def lines(self, key):
        return [re.sub(r'<[^>]+>', '', line) for line in self.result[key].split('<FF03>')]

    def test_comma_separated_names_balance_in_two_lines(self):
        lines = self.lines('balanced')
        self.assertEqual(len(lines), 2)
        self.assertEqual(len(lines[0].split()), 4)
        self.assertTrue(lines[0].endswith(','))
        self.assertLess(abs(wrap.text_width(lines[0])-wrap.text_width(lines[1])), 20)

    def test_labels_do_not_steal_one_word_from_the_speech(self):
        for key in ('long_label', 'student', 'short_speech', 'whole_speech'):
            self.assertTrue(self.lines(key)[0].endswith(':'), self.result[key])
            self.assertNotIn('<FF02><FF03>', self.result[key])

    def test_authored_comma_is_not_replaced_with_a_dash(self):
        text = self.result['comma_card']
        self.assertNotIn(' - ', text)
        self.assertIn(',', self.lines('comma_card')[0])
        self.assertEqual(len(self.lines('comma_card')), 3)

    def test_nickname_can_split_at_hyphen_only_to_save_the_scroll(self):
        text = self.result['nickname']
        self.assertEqual(len(self.lines('nickname')), 3)
        self.assertIn('Nickname:', text)
        self.assertIn('-<FF03>', text)
        self.assertNotIn('<FF02><FF03>', text)

    def test_title_keeps_its_own_line_without_a_scroll(self):
        page = self.result['title'].split('<FF04>')[0]
        self.assertEqual(page.count('<FF03>'), 2)
        self.assertNotIn('<FF02><FF03>', page)
        self.assertEqual(len(page.split('<FF03>')[0].split()), 2)

    def test_three_line_block_does_not_have_a_hollow_middle(self):
        widths = [wrap.text_width(line) for line in self.lines('taper')]
        self.assertEqual(len(widths), 3)
        self.assertGreaterEqual(widths[0], widths[1])
        self.assertGreaterEqual(widths[1], widths[2])

    def test_short_quoted_term_is_not_split(self):
        self.assertNotRegex(self.result['quote'], r'"[^"<]*<FF03>[^"<]*"')

    def test_comma_does_not_strand_the_opening_vocative(self):
        lines = self.result['opening_tail'].split('<FF04>')[-1].split('<FF03>')
        self.assertEqual([len(re.sub(r'<[^>]+>', '', line).split()) for line in lines], [5, 4])
        widths = [wrap.text_width(line) for line in lines]
        self.assertLess(abs(widths[0] - widths[1]), 20)

    def test_opening_block_uses_fewest_lines_and_tapers(self):
        # The comma after "future, exactly," releases "but": the block now
        # fits two lines (238/184 px) instead of a three-line dip.
        lines = self.result['opening_taper'].split('<FF04>')[1].split('<FF03>')
        self.assertEqual([len(re.sub(r'<[^>]+>', '', line).split()) for line in lines], [6, 5])
        widths = [wrap.text_width(line) for line in lines]
        self.assertEqual(len(widths), 2)
        self.assertGreaterEqual(widths[0], widths[1])

    def test_greeting_still_breaks_at_its_sentence_boundary(self):
        lines = self.lines('greeting')
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].endswith('!'))
        self.assertEqual(len(lines[0].split()), 4)

    def test_actual_limits_are_not_silently_relaxed(self):
        for key, text in self.result.items():
            self.assertTrue(text)
            for region in re.split(r'<FF0[124]>', text):
                lines = region.split('<FF03>')
                for i, line in enumerate(lines):
                    self.assertLessEqual(wrap.text_width(line), 240 if i == len(lines)-1 else 239,
                                         (key, line))

    def test_card_wording_is_preserved_from_the_extracted_psp_source(self):
        # Names and complete wording come from the actual extraction, never
        # a hand-written fixture or an abbreviated nickname field.
        with (ROOT / 'translation/generated/ADV/E0.tsv').open() as f:
            generated = {r['pos']: r for r in csv.DictReader(f, delimiter='\t')}
        with (ROOT / 'data/extracted_text/psp_us/pack/E0.tsv').open() as f:
            sources = {r['id']: r['text'] for r in csv.DictReader(f, delimiter='\t')}

        def plain(text):
            text = re.sub(r'-<FF03>', '-', text)
            text = re.sub(r'<[^>]+>', ' ', text).replace('＞', '').replace(' - ', ' ')
            return ' '.join(text.split())

        for key in ('comma_card', 'bare_card', 'nickname'):
            _f, e, pos = self.CASES[key]
            pointer = generated[f'{e}:{pos:#x}']['psp'].split(':')[1]
            self.assertEqual(plain(self.result[key]), plain(sources[pointer]))


if __name__ == '__main__':
    unittest.main()
