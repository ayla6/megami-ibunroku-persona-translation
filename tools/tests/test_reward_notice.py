"""Reward notice pairs require source identity, frame proof and unique anchors."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'), str(ROOT / 'src/injection_tools')]
import reward_notice as rn
import port_derive
import btlp
import btlmsg
import etext
import toolbelt


class RewardNotice(unittest.TestCase):
    def setUp(self):
        self.messages = [('0x10', '乙を得た'), ('0x20', '丙を得た')]
        self.names = [('乙', 'Bitem'), ('丙', 'Citem')]
        self.jp = [{'pos': '0x200', 'text': '乙を得た<FF02><FF01>'},
                   {'pos': '0x240', 'text': '丙を得た<FF02><FF01>'}]
        self.us = [{'pos': '0x300', 'text': 'Received Bitem<FF02><FF01>'},
                   {'pos': '0x340', 'text': 'Received Citem<FF02><FF01>'}]
        self.anchors = [(0x100, 0x200), (0x300, 0x400)]
        self.story = [('"<FF19><0300><FF18><0500>甲<FF18><0000>"を得た<FF02><FF01>',
                       'Received <FF19><0300><FF18><0500>Aitem<FF18><0000><FF02><FF01>')]

    def choose(self):
        return rn.candidates(self.messages, self.names, self.jp, self.us,
                             self.anchors, rn.story_frames(self.story))

    def test_independently_paired_frame_accepts_exact_item(self):
        self.assertEqual(self.choose(), [('0x10', '乙を得た', self.us[0]),
                                         ('0x20', '丙を得た', self.us[1])])

    def test_negative_conditional_and_mismatched_frames_are_not_accepted(self):
        for english in ('Did not receive Bitem', 'If received Bitem', 'Lost Bitem', 'Received Bitem - 1'):
            with self.subTest(english=english):
                self.us[0]['text'] = english + '<FF02><FF01>'
                self.assertEqual(self.choose(), [])
        self.us[0]['text'] = 'Received Bitem<FF02><FF01>'
        self.messages[0] = ('0x10', '乙を得なかった')
        self.assertEqual(self.choose(), [])

    def test_duplicate_item_names_or_source_messages_refuse(self):
        self.names.append(('乙', 'Other'))
        self.assertEqual(self.choose(), [])
        self.names = [('乙', 'Bitem'), ('丙', 'Citem'), ('丁', 'Bitem')]
        self.assertEqual(self.choose(), [])
        self.names = [('乙', 'Bitem'), ('丙', 'Citem')]
        self.jp.append({'pos': '0x220', 'text': self.jp[0]['text']})
        self.assertEqual(self.choose(), [])
        self.jp.pop()
        self.us.append({'pos': '0x320', 'text': 'Received Bitem<FF08><FF02><FF01>'})
        self.assertEqual(self.choose(), [])

    def test_unsupported_controls_overlapping_records_and_missing_proof_refuse(self):
        self.us[0]['text'] = 'Received Bitem<FF02>again<FF02><FF01>'
        self.assertEqual(self.choose(), [])
        self.us[0]['text'] = 'Received Bitem<FF02><FF01>'
        self.jp.insert(0, {'pos': '0x1fe', 'text': 'nested overlap<FF01>'})
        self.assertEqual(self.choose(), [])
        self.jp.pop(0)
        self.anchors.append((0x100, 0x210))
        self.assertEqual(self.choose(), [])
        self.anchors = [(0x100, 0x400), (0x300, 0x200)]
        self.assertEqual(self.choose(), [])
        self.anchors = [(0x100, 0x200), (0x300, 0x400)]
        self.story = []
        self.assertEqual(self.choose(), [])

    def test_assembled_code_references_full_reward_text(self):
        built = ROOT / 'build/BTLP.BIN'
        if not built.exists():
            self.skipTest('requires assembled BTLP.BIN')
        data = built.read_bytes()
        references = btlmsg.refs(btlmsg.data())
        generated = {r['pos']: r for r in toolbelt.merged_rows('BTLP')}
        for pos, _ja, _source in rn.derive():
            expected = etext.encode(btlp.msg_script(generated[pos]['en']), end=btlp.END)
            found = references.get(btlp.B + int(pos, 16), [])
            self.assertTrue(found, pos)
            for kind, address in found:
                if kind == 'addiu':
                    immediate = struct.unpack_from('<h', data, address - btlp.B)[0]
                    pointer = (0x800D0000 + immediate) & 0xffffffff
                else:
                    pointer = struct.unpack_from('<I', data, address - btlp.B)[0]
                self.assertEqual(data[pointer - btlp.B:pointer - btlp.B + len(expected)],
                                 expected, pos)

    def test_item_reader_is_serialized_with_slps_writers(self):
        import port
        steps = [('first', (), ('SLPS_005.00',)),
                 ('second', (), ('SLPS_005.00',)),
                 ('message', (), ('BTLP', 'SLPS_005.00'))]
        waves = port.waves(steps)
        self.assertEqual([[step[0] for step in wave] for wave in waves],
                         [['first'], ['second'], ['message']])

    def test_real_corpus_candidates_and_destination_dialect(self):
        actual = rn.derive()
        self.assertEqual({r[0] for r in actual}, {'0x6dd54', '0x6dd60'})
        for pos, ja, source in actual:
            text, reason = port_derive.derive(source['text'], ja, 'BTLP', pos)
            self.assertFalse(reason)
            self.assertTrue(text.endswith('<FF02>'))
            encoded = etext.encode(btlp.msg_script(text), end=btlp.END)
            self.assertNotIn(bytes.fromhex('ff02'), encoded)
            self.assertTrue(encoded.endswith(btlp.END))


if __name__ == '__main__':
    unittest.main()
