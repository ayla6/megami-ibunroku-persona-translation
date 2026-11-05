"""Executable-consumer proofs must survive independent anchors and fail closed."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/injection_tools')]
import notice_consumer as notice
import btlmsg
import btlneg
import tables
import toolbelt


class ConsumerProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jp = tables.jp_boot()
        cls.us = tables.us_boot()
        cls.jp_rows = sorted(toolbelt.read_extracted('psp_jp', 'EBOOT'), key=lambda r: int(r['pos'], 16))
        cls.us_rows = sorted(toolbelt.read_extracted('psp_us', 'EBOOT'), key=lambda r: int(r['pos'], 16))
        row = next(r for r in toolbelt.read_extracted('psx', 'BTLP') if r['pos'] == '0x6473c')
        cls.messages = [(810, row['text'])]
        cls.pairs = notice.proven_pairs()

    def prove(self, jp=None, us=None, jr=None, ur=None, pairs=None, messages=None):
        return notice.candidates(self.messages if messages is None else messages,
            self.jp if jp is None else jp, self.us if us is None else us,
            self.jp_rows if jr is None else jr, self.us_rows if ur is None else ur,
            self.pairs if pairs is None else pairs)

    def test_real_pair_and_raw_pointer_vs_extract_offset(self):
        result = self.prove()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1]['pos'], '0x2a5776')
        self.assertEqual(result[0][1]['text'], '＞ The demon spoke to you!<FF01>')
        seg, rel = notice.elf(self.us)
        pointed = notice.pointed(self.us, seg, 0x2a5778)
        self.assertEqual(pointed, (0x2a577c, result[0][1]['text']))
        self.assertIn(0x2a5778, rel)

    def test_whole_negotiation_family_has_only_proven_candidate(self):
        previous = btlmsg.ZONE
        try:
            btlmsg.ZONE = btlneg.ZONE
            data = btlmsg.data()
            refs = btlmsg.refs(data)
            messages = [(i, btlmsg.dec(data, a, end))
                        for i, (a, end) in enumerate(btlneg.strings(data, refs))]
            proofs = self.prove(messages=messages)
            self.assertEqual([(idx, row['pos']) for idx, row in proofs], [(33, '0x2a5776')])
        finally:
            btlmsg.ZONE = previous

    def test_no_anchor_or_conflicting_anchor_never_proves(self):
        self.assertFalse(self.prove(pairs={}))
        pairs = dict(self.pairs)
        pairs[0x29387c] = {0x2a57b2}
        self.assertFalse(self.prove(pairs=pairs))

    def test_instruction_flow_change_invalidates_consumer(self):
        us = bytearray(self.us)
        us[0xbdd34:0xbdd38] = b'\x01\x00\x00\x00'  # former nop
        self.assertFalse(self.prove(us=us))

    def test_duplicate_consumer_fingerprint_is_ambiguous(self):
        us = bytearray(self.us)
        code, _ = notice.elf(self.us)
        other = code[0][0] + 0x1000
        us[other:other + 4 * notice.SPAN] = us[0xbdd1c:0xbdd1c + 4 * notice.SPAN]
        self.assertFalse(self.prove(us=us))

    def test_duplicated_source_or_destination_is_ambiguous(self):
        row = next(r for r in self.jp_rows if r['pos'] == '0x29385a')
        duplicate = dict(row, pos='0x1')
        jr = sorted([*self.jp_rows, duplicate], key=lambda r: int(r['pos'], 16))
        self.assertFalse(self.prove(jr=jr))
        self.assertFalse(self.prove(messages=self.messages * 2))

    def test_unrecognized_control_and_bad_relocation_do_not_pair(self):
        us = bytearray(self.us)
        us[0x2a577c:0x2a577e] = b'\xff\x03'
        self.assertFalse(self.prove(us=us))
        us = bytearray(self.us)
        # The consumer's target slot is no longer relocated.
        off = 0x396d28 + 2443 * 8 + 4
        us[off:off + 4] = b'\0' * 4
        self.assertFalse(self.prove(us=us))


if __name__ == '__main__':
    unittest.main()
