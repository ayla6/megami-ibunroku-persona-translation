"""Battle negotiation failures retain their complete source for review."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/extraction_tools/psp'),
                str(ROOT / 'src/injection_tools')]
import btlmsg
import port_btlneg
import port_derive


class NegotiationFailureQueue(unittest.TestCase):
    def test_source_fragments_do_not_invent_page_turns(self):
        boot = [(0x10, '', 'Speaker<FF03>Is this '),
                (0x20, '', 'word'),
                (0x30, '', ' here?<FF01>')]
        self.assertEqual(port_btlneg.source_message(boot, [0x10, 0x20, 0x30]),
                         ('Speaker', 'Is this word here?'))

    def test_source_page_turn_survives_without_duplicate(self):
        boot = [(0x10, '', 'Speaker<FF03>First<FF02><FF04>'),
                (0x20, '', 'Speaker<FF03>Second<FF01>')]
        self.assertEqual(port_btlneg.source_message(boot, [0x10, 0x20]),
                         ('Speaker', 'First<FF02><FF04>Second'))

    def test_fragment_head_marker_is_not_glued_to_prior_word(self):
        boot = [(0x10, '', 'First'), (0x20, '', '＞ Second<FF01>')]
        self.assertEqual(port_btlneg.source_message(boot, [0x10, 0x20]),
                         ('', 'First ＞ Second'))

    def test_hidden_terminator_is_recovered_from_source_bytes(self):
        boot = [(0x10, '', 'First'), (0x20, '', '＞ Second<FF01>')]
        raw = bytearray(0x40)
        raw[0x1e:0x20] = b'\xff\x01'
        self.assertEqual(port_btlneg.source_message(boot, [0x10, 0x20], raw),
                         ('', 'First<FF01> ＞ Second'))

    def test_negotiation_layout_reflows_source_newlines(self):
        # A PSP prose newline is where its 16 px glyphs ran out, not a break.
        text, reason = port_derive.derive('First<FF03>Second', '例', 'BTLP')
        self.assertEqual((text, reason), ('First Second', ''))

    def test_source_span_rejects_missing_or_empty_units(self):
        boot = [(0x1230, '', 'A<FF03>First<FF01>'), (0x1250, '', '')]
        for addresses in ([0x1230, 0x1260], [0x1230, 0x1250], []):
            with self.subTest(addresses=addresses), self.assertRaisesRegex(
                    ValueError, 'missing or empty PSP source'):
                port_btlneg.source_message(boot, addresses)

    def test_psp_nameplates_convert_before_battle_line_controls(self):
        source = ' <FF1B>Speaker<FF03>Example!<FF01>'
        text, reason = port_derive.derive(source, '', 'BTLP')
        self.assertEqual((text, reason), ('Speaker: Example!', ''))

    @unittest.skipUnless((ROOT / 'data/extracted_text/psp_us/EBOOT.tsv').exists(),
                         'requires extracted PSP-US text')
    def test_real_source_nameplate_preserves_the_extracted_wording(self):
        source = port_btlneg.toolbelt.psp_wording('EBOOT:2a95fe')
        label, body = port_derive.label_head(source)
        self.assertTrue(label)
        text, reason = port_derive.derive(source, '', 'BTLP')
        self.assertEqual(reason, '')
        self.assertEqual(text, label + ': ' + body.replace('<FF01>', '').strip())

    def test_all_failures_queue_full_drafts_and_sources_once(self):
        msgs = [(btlmsg.B + 0x100, 0), (btlmsg.B + 0x200, 0),
                (btlmsg.B + 0x300, 0), (btlmsg.B + 0x400, 0)]
        draft = 'A' * 200 + '<FFF8> after'
        failures = [(0, 'unsupported destination control codes', draft, (0x1234, 0x5678)),
                    (0, 'duplicate', 'ignored', ()),
                    (1, 'source mapping does not match destination', '', (0x9999,)),
                    (2, 'failed but later succeeded', 'ignored', ()),
                    (3, 'human wording', 'ignored', ())]
        successes = [(2, 'good', 'source', ())]
        with patch.object(port_btlneg.toolbelt, 'route_over') as route:
            count = port_btlneg.route_failures(failures, successes, msgs, {'0x400'})
        self.assertEqual(count, 2)
        self.assertEqual(route.call_args_list[0].args,
                         ('BTLP', '0x100', 'EBOOT:1234,EBOOT:5678', draft,
                          'unsupported destination control codes'))
        self.assertEqual(route.call_args_list[1].args,
                         ('BTLP', '0x200', 'EBOOT:9999', '',
                          'source mapping does not match destination'))

    def test_emit_keeps_the_full_failed_draft(self):
        draft = 'Long ' * 80
        ok, fail = [], []
        with patch.object(port_derive, 'derive', return_value=(draft, 'over limit')):
            port_btlneg.emit(0, draft, 'source', {'0': ['', '', 'ja']}, ok, fail,
                             srcs=(0x1234,))
        self.assertEqual(fail, [(0, 'over limit', draft, (0x1234,))])

    def test_emit_never_combines_independent_source_messages(self):
        source = '＞ First<FF01> ＞ Second<FFEF>'
        ok, fail = [], []
        port_btlneg.emit(0, source, 'source', {'0': ['', '', 'ja']}, ok, fail,
                         srcs=(0x1234, 0x5678))
        self.assertFalse(ok)
        self.assertEqual(fail, [(0, 'multiple PSP messages require destination alignment',
                                 source, (0x1234, 0x5678))])

    def test_sequential_messages_follow_proven_destination_order(self):
        raw = bytearray(0x40)
        raw[0x1e:0x20] = b'\xff\x01'
        sources = [(0x10, 'First!<FF01>'), (0x20, 'Second!<FF01>')]
        with patch.object(port_btlneg.toolbelt, 'read_eboot', return_value=sources), \
                patch.object(port_btlneg.eboot_twin_plan, 'exact_us',
                             return_value={'7:0': 0x20, '7:1': None}):
            text = port_btlneg.sequential_source(7, '甲<FFEF>乙', (0x10, 0x20), raw)
        self.assertEqual(text, 'Second!<FFEF>First!')

    def test_sequential_messages_without_a_proven_pair_are_rejected(self):
        raw = bytearray(0x40)
        raw[0x1e:0x20] = b'\xff\x01'
        with patch.object(port_btlneg.toolbelt, 'read_eboot',
                          return_value=[(0x10, 'First'), (0x20, 'Second')]), \
                patch.object(port_btlneg.eboot_twin_plan, 'exact_us', return_value={}):
            with self.assertRaisesRegex(ValueError, 'require destination alignment'):
                port_btlneg.sequential_source(7, '甲<FFEF>乙', (0x10, 0x20), raw)


if __name__ == '__main__':
    unittest.main()
