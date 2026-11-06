"""An ADV system message is drawn by the message engine, not a textbox.

Its call site opens a map-layer viewport with no label row, so a PSP-US
`<FF1B>name<FF03>` there is UI decoration and never wording. The same rule
decides the autoport: a parked queue row re-derives from its `psp` source on
every apply, so an over-limit wording keeps the standard draft shape and a
wording that now fits ships. The note is never parsed - the source is the
truth.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for _p in ('src/injection_tools', 'src/extraction_tools/matching',
           'src/extraction_tools/psp'):
    sys.path.insert(0, str(ROOT / _p))

import port_caps
import port_derive
import port_lastresort as net

# The Velvet Room Persona-delete prompt: one 240 px row.
DELETE_POS = '0x56df2'
DELETE_JA = '\u3000\u3000このペルソナを消すのだね？<FF01>'
DELETE_US = (' <FF1B>Igor<FF03>Are you certain that you wish to<FF03>'
             'delete this Persona?<FF02><FF0E> <FF01>')
DELETE_DRAFT = 'Are you certain that you wish to delete this Persona?<FF01>'
DELETE_REASON = 'over limit 342px/240px'

# A message that fits its one line.
FITS_POS = '0x56db6'
FITS_JA = '\u3000このペルソナで良いですかな？<FF01>'
FITS_US = ("<FF1B>Igor<FF03>Is this the Persona you'd like?<FF02>"
           "<FF0E> <FF01>")


class NoLabelRow(unittest.TestCase):
    def test_adv_message_geometry_has_no_label_row(self):
        self.assertFalse(port_caps.has_label_row('ADV', DELETE_POS))
        self.assertFalse(port_caps.has_label_row('ADV', '0x56d3e'))
        # an ordinary story box and every other family can draw a label
        self.assertTrue(port_caps.has_label_row('ADV', '0x0'))
        self.assertTrue(port_caps.has_label_row('BTLP', '0x0'))

    def test_the_psp_nameplate_is_not_wording_here(self):
        laid, why = port_derive.derive(DELETE_US, DELETE_JA, 'ADV', DELETE_POS)
        self.assertNotIn('Igor', laid)
        self.assertEqual(laid, DELETE_DRAFT)
        self.assertEqual(why, DELETE_REASON)

    def test_a_label_row_keeps_its_speaker(self):
        laid, why = port_derive.derive(
            '<FF1B>Igor<FF03>Hello there.<FF01>',
            '<FF1B>イゴール<FF03>こんにちは<FF01>', 'ADV', '0x0')
        self.assertEqual(laid, 'Igor: Hello there.<FF01>')
        self.assertEqual(why, '')

    def test_a_japanese_nameplate_keeps_the_label(self):
        # the build's own Japanese spells a nameplate: it is structure the
        # destination expects, so the US name stays
        laid, why = port_derive.derive(
            DELETE_US, '<FF1B>イゴール<FF03>このペルソナを消すのだね？<FF01>',
            'ADV', DELETE_POS)
        self.assertIn('Igor', laid)
        self.assertIn('over limit ', why)


def run_redraft(manual, generated, wording, ja):
    """redraft() against a fake table: every write is captured."""
    routed, shipped, gaps = [], [], []
    with patch.object(net, 'tables', return_value=['ADV']), \
         patch.object(net, 'psx_text_of', return_value=ja), \
         patch.object(net, 'psp_wording', return_value=wording), \
         patch.object(net.toolbelt, 'read_manual', return_value=manual), \
         patch.object(net.toolbelt, 'read_generated', return_value=generated), \
         patch.object(net.toolbelt, 'route_to_manual'), \
         patch.object(net.toolbelt, 'write_generated'), \
         patch.object(net.toolbelt, 'route_over',
                      side_effect=lambda *a: routed.append(a)), \
         patch.object(net.toolbelt, 'upsert_generated',
                      side_effect=lambda rel, rows: shipped.extend(rows)), \
         patch.object(net.toolbelt, 'route_gaps',
                      side_effect=lambda rel, rows: gaps.append(rows)):
        n, withdrawn = net.redraft()
    return n, withdrawn, routed, shipped


def parked(pos, psp, note='unpaired; ja source'):
    return {'id': '7', 'pos': pos, 'psp': psp, 'en': '', 'note': note}


class RedraftParkedRows(unittest.TestCase):
    def test_an_over_limit_source_keeps_the_standard_draft(self):
        n, withdrawn, routed, shipped = run_redraft(
            [parked(DELETE_POS, 'EBOOT:2d4b02')], [],
            DELETE_US, {DELETE_POS: DELETE_JA})
        self.assertEqual((n, withdrawn, shipped), (1, 0, []))
        rel, pos, psp, draft, why = routed[0]
        self.assertEqual((rel, pos, psp), ('ADV', DELETE_POS, 'EBOOT:2d4b02'))
        self.assertEqual(draft, DELETE_DRAFT)
        self.assertEqual(why, DELETE_REASON)

    def test_the_note_is_not_parsed_the_source_is_the_truth(self):
        stale = parked(DELETE_POS, 'EBOOT:2d4b02',
                       'over limit 999px/999px; old words')
        _n, _w, routed, shipped = run_redraft(
            [stale], [], DELETE_US, {DELETE_POS: DELETE_JA})
        self.assertEqual(routed[0][3], DELETE_DRAFT)
        self.assertEqual(routed[0][4], DELETE_REASON)
        self.assertEqual(shipped, [])

    def test_a_source_that_now_fits_ships(self):
        n, withdrawn, routed, shipped = run_redraft(
            [parked(FITS_POS, 'EBOOT:2d4c58')], [],
            FITS_US, {FITS_POS: FITS_JA})
        self.assertEqual((n, withdrawn, routed), (1, 0, []))
        self.assertEqual(shipped, [{
            'pos': FITS_POS, 'psp': 'EBOOT:2d4c58',
            'en': "Is this the Persona you'd like?<FF01>"}])

    def test_a_human_row_or_an_unclaimed_row_is_left_alone(self):
        human = dict(parked(DELETE_POS, 'EBOOT:2d4b02'), en='Human words')
        unclaimed = parked('0x56d24', '', 'unpaired; ja')
        n, _w, routed, shipped = run_redraft(
            [human, unclaimed], [], DELETE_US, {DELETE_POS: DELETE_JA})
        self.assertEqual((n, routed, shipped), (0, [], []))


if __name__ == '__main__':
    unittest.main()
