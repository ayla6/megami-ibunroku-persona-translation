"""Per-record control-message proofs reject altered calls and positional ambiguity."""
from pathlib import Path
import struct
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src/extraction_tools/matching'),str(ROOT/'src/injection_tools')]
import control_consumer as proof
import notice_consumer as notice
import tables
import toolbelt

class ControlConsumerProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jp=tables.jp_boot();cls.us=tables.us_boot()
        cls.jr=toolbelt.read_extracted('psp_jp','EBOOT')
        cls.ur=toolbelt.read_extracted('psp_us','EBOOT')
        cls.messages=[(int(r['pos'],16),r['text']) for r in toolbelt.read_extracted('psx','BTLP')
                      if r['pos'] in ('0x64668','0x64698')]
        cls.pairs=notice.proven_pairs()

    def prove(self,us=None,jr=None,pairs=None,messages=None):
        return proof.candidates(self.messages if messages is None else messages,self.jp,
                                self.us if us is None else us,self.jr if jr is None else jr,
                                self.ur,self.pairs if pairs is None else pairs)

    def test_real_records_use_verbatim_source_wording(self):
        result=self.prove()
        self.assertEqual([(hex(idx),row['pos']) for idx,row in result],
                         [('0x64668','0x2a58ec'),('0x64698','0x2a58a6')])
        self.assertEqual(result[1][1]['text'],' ＞ Gained <FFF8> EXP.<FF01>')

    def test_no_independent_anchor_proves_nothing(self):
        self.assertFalse(self.prove(pairs={}))

    def test_redirected_consuming_call_is_not_normalized_into_a_match(self):
        us=bytearray(self.us)
        struct.pack_into('<I',us,0xbba54,0x0c000400)
        self.assertEqual([hex(idx) for idx,_row in self.prove(us=us)],['0x64668'])

    def test_wrong_delay_slot_register_fails(self):
        us=bytearray(self.us)
        word=struct.unpack_from('<I',us,0xbba58)[0]
        struct.pack_into('<I',us,0xbba58,(word&~(31<<21))|(3<<21))
        self.assertEqual([hex(idx) for idx,_row in self.prove(us=us)],['0x64668'])

    def test_duplicate_candidate_or_anchor_consumer_fails_unique_gate(self):
        lo=notice.elf(self.us)[0][0][0]
        for source,expected in ((0xbba50,['0x64668']),(0xc26d0,[])):
            us=bytearray(self.us)
            us[lo+0x1000:lo+0x1000+4*proof.SPAN]=us[source:source+4*proof.SPAN]
            with self.subTest(source=hex(source)):
                self.assertEqual([hex(idx) for idx,_row in self.prove(us=us)],expected)

    def test_reordered_or_missing_pointer_path_is_rejected(self):
        for operation in ('swap','duplicate','invalid'):
            us=bytearray(self.us)
            a,b=struct.unpack_from('<II',us,0x2a5760)
            if operation=='swap':struct.pack_into('<II',us,0x2a5760,b,a)
            elif operation=='duplicate':struct.pack_into('<II',us,0x2a5760,a,a)
            else:struct.pack_into('<I',us,0x2a5764,0xffffffff)
            with self.subTest(operation=operation):self.assertFalse(self.prove(us=us))

    def test_pointer_without_loader_relocation_is_not_evidence(self):
        us=bytearray(self.us)
        data_lo=notice.elf(self.us)[0][1][0]
        record=struct.pack('<II',0x2a5760-data_lo,notice.RELOC_POINTER)
        at=us.find(record)
        self.assertGreaterEqual(at,0)
        self.assertEqual(us.find(record,at+1),-1)
        struct.pack_into('<I',us,at+4,0)
        self.assertFalse(self.prove(us=us))

    def test_conflicting_independent_callee_maps_are_not_anchors(self):
        j={1:[(0,10,100,1)],2:[(4,14,100,2)]}
        u={3:[(8,18,200,3)],4:[(12,22,300,4)]}
        self.assertFalse(proof.anchored_calls(j,u,{1:{3},2:{4}}))

    def test_duplicate_source_wording_or_message_is_ambiguous(self):
        row=next(r for r in self.jr if r['pos']=='0x293916')
        self.assertEqual([hex(idx) for idx,_r in self.prove(jr=[*self.jr,dict(row,pos='0x1')])],['0x64668'])
        self.assertFalse(self.prove(messages=self.messages*2))

if __name__=='__main__':unittest.main()
