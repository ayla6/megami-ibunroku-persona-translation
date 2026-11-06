"""One location slot feeds two strings: the arrival banner and its map labels.

The slot's own row is the banner name (BANNER_LIMIT). A manual row keyed at
any of the slot's map-label pointer words supplies the shorter label wording
(LABEL_LIMIT); without one the label repeats the banner name. The builder
rewires the banner table word to the former and every label pointer to the
latter, so the two consumers never share a string.
"""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools')]
import s2d
import toolbelt
import vwf_wrap


class NameSplit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        built = ROOT / 'build/S2D.BIN'
        if not built.exists():
            raise unittest.SkipTest('requires assembled build/S2D.BIN')
        cls.built = built.read_bytes()
        cls.stock = s2d.data()
        cls.slots = s2d.name_slots(cls.stock)
        cls.refs = s2d.name_refs(cls.stock, cls.slots)
        cls.label_words = s2d.label_table_refs(cls.stock)
        cls.rows = {int(r['pos'], 16): r
                    for r in toolbelt.merged_rows('S2D')
                    if (r.get('en') or '').strip()}
        cls.all_manual = {int(r['pos'], 16): r
                          for r in toolbelt.read_manual('S2D', optional=True)}
        cls.manual = {pos: r for pos, r in cls.all_manual.items()
                      if (r.get('en') or '').strip()}

    def string_at(self, address):
        off = address - s2d.B
        end = self.built.index(b'\xff\x01', off) + 2
        return self.built[off:end]

    def word(self, address):
        return struct.unpack_from('<I', self.built, address - s2d.B)[0]

    def test_banner_and_map_label_reach_their_own_strings(self):
        split = 0
        for i, (start, _end) in enumerate(self.slots):
            slot_row = self.rows.get(start - s2d.B)
            if slot_row is None:
                continue
            refs = s2d.label_refs(self.refs, i, self.label_words)
            label_rows = [self.manual[w - s2d.B]
                          for w in refs
                          if w - s2d.B in self.manual]
            if not label_rows:
                continue
            split += 1
            label_text = label_rows[0]['en'].strip()
            banner_text = slot_row['en'].strip()
            self.assertLessEqual(vwf_wrap.text_width(label_text),
                                 s2d.LABEL_LIMIT)
            self.assertLessEqual(vwf_wrap.text_width(banner_text),
                                 s2d.BANNER_LIMIT)

            banner_at = self.word(s2d.NAME_TABLE_ADDR + 4 * i)
            self.assertEqual(self.string_at(banner_at),
                             s2d.name_bytes(banner_text))

            label_at = self.word(refs[0])
            self.assertEqual(self.string_at(label_at),
                             s2d.name_bytes(label_text))
            for where in refs:
                self.assertEqual(self.word(where), label_at,
                                 f'slot {i} has labels on two strings')
            if label_text != banner_text:
                self.assertNotEqual(banner_at, label_at,
                                    f'slot {i} shares one string')
        self.assertGreater(split, 0, 'no slot carries a separate map label')

    def test_every_over_limit_label_is_queued_or_shortened_into_the_strip(self):
        over = 0
        for i, (start, _end) in enumerate(self.slots):
            refs = s2d.label_refs(self.refs, i, self.label_words)
            slot_row = self.rows.get(start - s2d.B)
            if not refs or slot_row is None:
                continue
            full = slot_row['en'].strip()
            if vwf_wrap.text_width(full) <= s2d.LABEL_LIMIT:
                continue
            over += 1
            rows = [self.all_manual[w - s2d.B]
                    for w in refs if w - s2d.B in self.all_manual]
            self.assertTrue(rows, f'slot {i} {full!r} has no manual label row')
            row = rows[0]
            text = (row.get('en') or '').strip()
            if text:
                self.assertLessEqual(vwf_wrap.text_width(text),
                                     s2d.LABEL_LIMIT, row['pos'])
                continue
            self.assertEqual(row['note'],
                             toolbelt.over_note(
                                 toolbelt.note_over(
                                     vwf_wrap.text_width(full),
                                     s2d.LABEL_LIMIT), full))
            self.assertEqual(row['psp'], slot_row['psp'])
        self.assertGreater(over, 0, 'no label-bearing name exceeded the strip')


class LabelDraftQueue(unittest.TestCase):
    """An over-limit label is queued in manual at a label word, never at the
    slot's own pos (that row is the banner name and must keep shipping)."""

    @classmethod
    def setUpClass(cls):
        stock = s2d.data()
        cls.slots = s2d.name_slots(stock)
        refs = s2d.name_refs(stock, cls.slots)
        words = s2d.label_table_refs(stock)
        cls.labeled = [i for i in range(len(cls.slots))
                       if s2d.label_refs(refs, i, words)]
        cls.unlabeled = [i for i in range(len(cls.slots))
                         if not s2d.label_refs(refs, i, words)]
        cls.refs = refs
        cls.words = words

    def run_queue(self, slot, text):
        start = self.slots[slot][0]
        gen = [{'id': '0', 'pos': hex(start - s2d.B),
                'psp': 'EBOOT:1', 'en': text}]
        calls = []
        with patch.object(s2d.toolbelt, 'read_generated', return_value=gen), \
                patch.object(s2d.toolbelt, 'read_manual', return_value=[]), \
                patch.object(s2d.toolbelt, 'route_over',
                             side_effect=lambda *a: calls.append(a)):
            s2d.route_label_drafts()
        return calls

    def test_over_limit_label_is_queued_at_a_label_word(self):
        slot = self.labeled[0]
        text = 'M'
        while vwf_wrap.text_width(text) <= s2d.LABEL_LIMIT:
            text += 'M'
        calls = self.run_queue(slot, text)
        self.assertEqual(len(calls), 1)
        _rel, pos, psp, draft, reason = calls[0]
        self.assertEqual(pos, hex(s2d.label_refs(self.refs, slot,
                                                 self.words)[0] - s2d.B))
        self.assertEqual(draft, text)
        self.assertEqual(reason, s2d.toolbelt.note_over(
            vwf_wrap.text_width(text), s2d.LABEL_LIMIT))
        self.assertEqual(psp, 'EBOOT:1')

    def test_fitting_label_and_banner_only_names_are_not_queued(self):
        slot = self.labeled[0]
        fits = 'M'
        while vwf_wrap.text_width(fits + 'M') <= s2d.LABEL_LIMIT:
            fits += 'M'
        self.assertEqual(self.run_queue(slot, fits), [])
        # A slot no map label points at is the banner only: the banner's
        # wider strip owns its cap, so it is never queued here.
        if self.unlabeled:
            longer = 'M'
            while vwf_wrap.text_width(longer) <= s2d.LABEL_LIMIT:
                longer += 'M'
            self.assertEqual(self.run_queue(self.unlabeled[0], longer), [])


if __name__ == '__main__':
    unittest.main()
