"""Execute the assembled dungeon FF0A name insertion up to its VWF printer."""
from pathlib import Path
import re
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src/injection_tools'),str(ROOT/'tools/tests')]
import skills
from mips_cpu import CPU,REG

class DungeonSkillInsert(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resident=(ROOT/'build/SLPS_005.00').read_bytes()
        cls.overlay=(ROOT/'build/DNG.BIN').read_bytes()
        cls.sym={m.group(2):int(m.group(1),16) for line in (ROOT/'build/persona.sym').read_text().splitlines()
                 if (m:=re.fullmatch(r'([0-9A-Fa-f]{8})\s+(\S+)',line))}
    def test_inserts_complete_skill_name_and_does_not_touch_config(self):
        for name in ('A','ABCDEFGHIJKLMNO','ABCDEFGHIJKLMNOPQRS','ABCDEFGHIJKLMNOPQRSTUVW'):
            with self.subTest(name=name):
                text=skills.encode_glyphs(0,name);tail=text[10:]
                head=text[:10]
                if len(head)<10:head+=b'\xff'
                head=head.ljust(10,b'\0')
                bank,offsets=skills.pack_tails([tail] if len(tail)>3 else [])
                spare=bytes([0xfe,offsets[tail],0]) if len(tail)>3 else (tail+b'\xff\0\0')[:3]
                cpu=CPU();cpu.load(0x80010000,self.resident[0x800:]);cpu.load(0x800643c4,self.overlay)
                cpu.load(0x80047d58,head+bytes(7)+spare);cpu.load(0x8004ce6f,bank)
                cpu.r[REG['sp']]=0x801ff000;cpu.r[REG['s5']]=0x801f0000;cpu.write(0x801f0000,1,1)
                config=self.sym['dng_txt_cfg'];before=bytes(cpu.read(config+i,1) for i in range(48))
                cpu.start(self.sym['dng_skill_name'])
                for _ in range(2000):
                    if cpu.pc==0x800753ac:break
                    cpu.step()
                else:self.fail('dungeon skill insert did not call its printer')
                ptr=cpu.r[REG['a0']]; self.assertEqual(ptr,self.sym['dng_skill_buf'])
                self.assertEqual(cpu.r[REG['a1']],skills.MAXLEN)
                shown=text[:skills.MAXLEN]          # a slot cannot hold more glyphs
                self.assertEqual(bytes(cpu.read(ptr+i,1) for i in range(len(shown)+1)),shown+b'\xff')
                self.assertEqual(bytes(cpu.read(config+i,1) for i in range(48)),before)
                glyphs=[]; frames=0
                for _ in range(5000):
                    if cpu.pc==0x8007423c:break
                    if cpu.pc==self.sym['dng_txt_put_name']:
                        glyphs.append(cpu.r[REG['a0']]); cpu.start(cpu.r[REG['ra']]); continue
                    if cpu.pc==0x800659b4:
                        frames+=1; cpu.start(cpu.r[REG['ra']]); continue
                    cpu.step()
                else:self.fail('dungeon insert did not return to the original script continuation')
                self.assertEqual(glyphs,list(shown))
                self.assertEqual(frames,len(shown))
                self.assertEqual(cpu.r[REG['sp']],0x801ff000)

if __name__=='__main__':unittest.main()
