"""Unaligned retail copies merge bytes and respect the R3000 load delay."""
import unittest
from mips_cpu import CPU, REG

class UnalignedMemory(unittest.TestCase):
    def test_all_source_and_destination_alignments_preserve_neighbors(self):
        for source_offset in range(4):
            for destination_offset in range(4):
                for reverse in (False,True):
                    with self.subTest(source=source_offset,dest=destination_offset,reverse=reverse):
                        c=CPU();source=0x80001000+source_offset;dest=0x80002000+destination_offset
                        c.load(0x80001000,bytes(range(16)));c.load(0x80002000,b'\xee'*16)
                        c.r[REG['t0']]=source;c.r[REG['t1']]=dest;c.r[REG['v0']]=0x12345678
                        def instruction(op,base,offset):return (op<<26)|(REG[base]<<21)|(REG['v0']<<16)|offset
                        loads=[instruction(34,'t0',3),instruction(38,'t0',0)]
                        if reverse:loads.reverse()
                        program=loads+[0,instruction(42,'t1',3),instruction(46,'t1',0)]
                        c.load(0x80003000,b''.join(w.to_bytes(4,'little') for w in program));c.start(0x80003000)
                        c.step();self.assertEqual(c.r[REG['v0']],0x12345678)
                        for _ in program[1:]:c.step()
                        got=bytes(c.read(0x80002000+i,1) for i in range(16))
                        expected=bytearray(b'\xee'*16);expected[destination_offset:destination_offset+4]=bytes(range(source_offset,source_offset+4))
                        self.assertEqual(got,expected)

if __name__=='__main__':unittest.main()
