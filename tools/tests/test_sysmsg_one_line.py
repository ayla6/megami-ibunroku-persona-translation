"""ADV system messages whose own call site proves a one-row viewport.

The height is read from the code that opens the message (BgMapInit's
g_bg_layers[4].h), never from a per-message table: a proven 16 px viewport is
one 240 px line, so a line/page move is a space and the wording is measured
on that one line. An unproven call site stays an ordinary box.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
sys.path.insert(0, str(ROOT / 'src/extraction_tools/matching'))

import port_caps
import port_derive
import sysmsg
import tstatus
import vwf_wrap


# The Velvet Room Persona-delete prompt: the PSP wording carries a break,
# but the call site sets h = 0x10 (one visible row).
DELETE_POS = '0x56df2'
DELETE_EN = 'Are you certain that you wish to<FF03>delete this Persona?<FF01>'
DELETE_JA = '\u3000\u3000このペルソナを消すのだね？<FF01>'

# The memory-card "no card" message is drawn by a pointer-table loop, so no
# single call site proves its height: it must stay a textbox.
MEMCARD_POS = '0x56e5b'

# The coin shop's notice is drawn into an 11-cell layer: its own proven line
# is 176 px, not the 240 px of the full 15-cell row.
COIN_POS = '0x56d3e'
COIN_JA = '\u3000枚数を指定して下さい<FF01>'
COIN_EN = 'Select the number of coins.<FF01>'
COIN_LONG = 'Select the number of coins, please.<FF01>'   # 219 px


class DisplayRows(unittest.TestCase):
    def test_one_row_call_site_is_structural(self):
        rows = sysmsg.display_rows()
        self.assertEqual(rows.get(0x56df2), 1)
        self.assertEqual(rows.get(0x56e06), 2)   # two-row save prompt
        self.assertEqual(rows.get(0x56e2a), 3)   # three-row power prompt
        self.assertNotIn(0x56e5b, rows)          # pointer-table loop
        self.assertNotIn(0x56d24, rows)          # inherited height

    def test_viewport_width_is_the_layer_it_draws_into(self):
        self.assertEqual(sysmsg.display_size()[0x56d3e], (176, 16))
        self.assertEqual(sysmsg.display_size()[0x56df2], (240, 16))
        self.assertEqual(sysmsg.display_size()[0x56e06], (240, 32))
        self.assertIsNone(sysmsg.line_px(0x56e5b))

    def test_the_line_limit_is_the_proven_width(self):
        self.assertEqual(port_caps.dest_line_px('ADV', COIN_POS), 176)
        self.assertEqual(port_caps.dest_line_px('ADV', DELETE_POS), 240)
        self.assertIsNone(port_caps.dest_line_px('ADV', MEMCARD_POS))
        # 219 px fits the 240 px box but not the coin shop's 176 px layer
        self.assertEqual(port_caps.dest_note(COIN_EN, 'ADV', COIN_POS, COIN_JA),
                         '')
        self.assertEqual(port_caps.dest_note(COIN_LONG, 'ADV', COIN_POS,
                                             COIN_JA),
                         'over limit 219px/176px')
        self.assertEqual(port_caps.dest_note(COIN_LONG, 'ADV', DELETE_POS,
                                             DELETE_JA), '')
        err = tstatus.check(COIN_JA, COIN_LONG, line_px=176)
        self.assertEqual(err[0][0], 'width')
        self.assertTrue(err[0][1].startswith(
            '219 px over 176: Select the number of coins, please.'))
        self.assertEqual(tstatus.check(COIN_JA, COIN_LONG), [])

    def test_the_japanese_agrees_with_the_proven_rows(self):
        # Cross-check only: a textbox needs a line/page move, so a message
        # whose Japanese carries one was never a one-row viewport. The rule
        # stays the call site's geometry; this fails if the two ever
        # disagree (a new message shape, or a detection bug).
        d = sysmsg.adv()
        ja = {a - sysmsg.B: sysmsg.dec(d, a, e)
              for a, e in sysmsg.messages(d)}
        moves = ('<FF03>', '<FF04>', '<FFF6>')
        sizes = sysmsg.display_size()
        for off, (_w, h) in sizes.items():
            if h // 16 == 1:
                self.assertFalse([c for c in moves if c in ja[off]],
                                 f'{hex(off)}: one-row viewport with a move')
            else:
                self.assertTrue([c for c in moves if c in ja[off]],
                                f'{hex(off)}: {h // 16}-row viewport with no '
                                f'move in its Japanese')

    def test_dest_cap_reports_a_fixed_line_only_for_proven_rows(self):
        self.assertEqual(port_caps.dest_cap('ADV', DELETE_POS), (None, None, 1))
        self.assertTrue(port_caps.is_fixed_field('ADV', DELETE_POS))
        self.assertEqual(port_caps.dest_cap('ADV', MEMCARD_POS),
                         (None, None, None))
        self.assertFalse(port_caps.is_fixed_field('ADV', MEMCARD_POS))
        # a two-row viewport still scrolls (PAGE_LINES), so it is not a cap
        self.assertEqual(port_caps.dest_cap('ADV', '0x56e06'),
                         (None, None, None))


class OneLineLayout(unittest.TestCase):
    def test_break_becomes_the_word_gap(self):
        self.assertEqual(vwf_wrap.one_line(DELETE_EN),
                         'Are you certain that you wish to delete this Persona?<FF01>')
        # a wait is not a move: it stays on the same line
        self.assertEqual(vwf_wrap.one_line('Wait<FF02>here<FF01>'),
                         'Wait<FF02>here<FF01>')

    def test_lay_out_does_not_reflow_a_proven_one_row_message(self):
        laid = port_derive.lay_out(DELETE_EN, 'ADV', DELETE_JA, DELETE_POS)
        self.assertNotIn('<FF03>', laid)
        self.assertNotIn('<FFF6>', laid)
        self.assertEqual(laid, vwf_wrap.one_line(DELETE_EN))
        # the same wording in a pointer-only textbox row still reflows
        self.assertIn('<FF03>',
                      port_derive.lay_out(DELETE_EN, 'ADV', DELETE_JA,
                                          MEMCARD_POS))

    def test_width_is_measured_on_the_line_that_is_drawn(self):
        px, lines = port_caps.widest(vwf_wrap.one_line(DELETE_EN))
        self.assertEqual(lines, 1)
        self.assertGreater(px, port_caps.PEN_MAX)
        note = port_caps.dest_note(DELETE_EN, 'ADV', DELETE_POS, DELETE_JA)
        self.assertRegex(note, r'over limit \d+px/240px')
        self.assertNotIn('lines', note)


if __name__ == '__main__':
    unittest.main()
