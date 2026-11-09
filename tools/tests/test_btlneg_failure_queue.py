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


if __name__ == '__main__':
    unittest.main()
