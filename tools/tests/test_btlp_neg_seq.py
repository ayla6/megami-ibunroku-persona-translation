"""Sequencer messages must not be packed through the text-window-only hook."""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import btlp
import etext
import toolbelt


class NegotiationData(unittest.TestCase):
    """The zone also holds debug material whose bytes decode as text (the
    name-entry keyboard pages, padded kana fields, glyph tables and the
    page-scroll test). Those runs are not messages, so no wording is owed."""

    DEBUG_RUNS = (0x65914, 0x69620, 0x69718, 0x69efc)

    def test_debug_material_is_not_a_text_row(self):
        stock = btlp.data()
        spans = {a - btlp.B: (a, e) for a, e in btlp.neg_strings(stock)}
        slots = {off for off, _f in btlp.families(stock)}
        for off in self.DEBUG_RUNS:
            self.assertIn(off, spans)
            self.assertTrue(btlp.neg_is_data(stock, *spans[off]), hex(off))
            self.assertNotIn(off, slots)

    def test_ordinary_lines_are_language(self):
        self.assertFalse(btlp._not_language(
            '＞<FFF3>の、<FFF6>\u3000スペルカードを手に入れた。'))
        self.assertFalse(btlp._not_language('いいえ'))


class NegotiationSequencer(unittest.TestCase):
    def test_all_sequencer_table_entries_are_plain(self):
        stock = btlp.data()
        built = (ROOT / 'build/BTLP.BIN').read_bytes()
        strings = btlp.neg_strings(stock)
        refs = btlp._zone_refs(stock, btlp.NEG_ZONE)
        rows = {row['pos']: row for row in toolbelt.merged_rows(btlp.REL)}
        seq = btlp.neg_seq_indices(strings, refs)
        self.assertEqual(len(seq), 11)
        for index in sorted(seq):
            address, _ = strings[index]
            text = (rows.get(hex(address - btlp.B), {}).get('en') or '').strip()
            if not text:
                continue
            expected = etext.encode(btlp.laid(text), end=btlp.END)
            for kind, where in refs[address]:
                self.assertEqual(kind, 'word')
                pointer = struct.unpack_from('<I', built, where - btlp.B)[0]
                self.assertEqual(built[pointer-btlp.B:pointer-btlp.B+len(expected)], expected, index)


if __name__ == '__main__':
    unittest.main()
