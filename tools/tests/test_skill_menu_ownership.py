"""Battle skill slots inherit source-derived VWF ownership without changing copied glyphs."""
from pathlib import Path
import re,sys,unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src/injection_tools'),str(ROOT/'tools/tests')]
import skills,toolbelt
from mips_cpu import CPU,REG

class SkillMenuOwnership(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.slps=(ROOT/'build/SLPS_005.00').read_bytes()
  cls.btlp=(ROOT/'build/BTLP.BIN').read_bytes()
  cls.sym={m.group(2):int(m.group(1),16) for line in (ROOT/'build/persona.sym').read_text().splitlines()
           if (m:=re.fullmatch(r'([0-9A-Fa-f]{8})\s+(\S+)',line))}
  cls.flags=toolbelt.asm_equ('SKILL_VWF_FLAGS_ADDR');cls.slots=toolbelt.asm_equ('SKILL_VWF_SLOTS_ADDR')
  cls.dest=toolbelt.asm_equ('SKILL_MENU_BUF');cls.stride=toolbelt.asm_equ('SKILL_MENU_STRIDE')
  cls.bit0=toolbelt.asm_equ('SKILL_BIT_OFFSET')
 def cpu(self):
  c=CPU();c.load(0x80010000,self.slps[0x800:]);c.load(0x800643c4,self.btlp)
  for i in range(1,32):c.r[i]=0x11100000+i*0x101
  c.r[REG['sp']]=0x801ff000;c.r[REG['ra']]=0x8000fff0
  return c
 def until(self,c,start,end):
  c.start(start)
  for _ in range(1000):
   if c.pc==end:return
   c.step()
  self.fail('skill copier did not return')
 def test_all_ids_and_slots_update_only_the_expected_bit(self):
  c=self.cpu();flag_bytes=bytes(c.read(self.flags+i,1) for i in range(31))
  for ident in range(1,skills.COUNT+1):
   c.r[REG['a0']]=self.dest;c.r[REG['a1']]=ident
   self.until(c,self.sym['skill_name_copy'],0x8000fff0)
   expected=bytes(c.read(self.dest+i,1) for i in range(skills.MAXLEN))
   for slot in range(7):
    for initial in (0,0xFFFF):
     c=self.cpu();c.write(self.slots,initial,2)
     c.r[REG['a0']]=self.dest+slot*self.stride;c.r[REG['a1']]=ident;c.r[REG['a2']]=slot
     before=c.r.copy();self.until(c,self.sym['skill_menu_copy'],0x8000fff0)
     en=(flag_bytes[ident>>3]>>(ident&7))&1; bit=self.bit0+slot; mask=1<<bit
     self.assertEqual(c.read(self.slots,2),(initial&~mask)|(en<<bit),(ident,slot))
     self.assertEqual(self.written(bytes(c.read(self.dest+slot*self.stride+i,1) for i in range(skills.MAXLEN))),self.written(expected))
     for reg in ('t0','t1','t2','t3','t4','t5','t6','t7','t8','t9','a3','s0','s1','s2','s3','s4','s5','s6','s7','sp'):
      self.assertEqual(c.r[REG[reg]],before[REG[reg]],(ident,slot,reg))
 def test_all_three_real_loops_forward_the_correct_slot(self):
  for entry,end,slotreg,adjust in ((0x800ac978,0x800aca44,'t3',1),(0x800a5654,0x800a5694,'a3',0),(0x800acc60,0x800acca0,'a3',0)):
   for slot in range(7):
    c=self.cpu();c.write(self.slots,0,2);c.r[REG['v1']]=1;c.r[REG[slotreg]]=slot+adjust
    self.until(c,entry,end)
    en=(c.read(self.flags,1)>>1)&1
    self.assertEqual(c.read(self.slots,2),en<<(self.bit0+slot),(hex(entry),slot))
    self.assertEqual(self.written(bytes(c.read(self.dest+slot*self.stride+i,1) for i in range(skills.MAXLEN))),self.written(self.expected_one()))
 def test_menu_build_preserves_empty_skill_marker(self):
  for slot in range(7):
   c=self.cpu();c.write(self.dest+slot*self.stride,0x42,1)
   c.r[REG['v1']]=0;c.r[REG['t3']]=slot+1
   self.until(c,0x800ac978,0x800aca44)
   self.assertEqual(c.read(self.dest+slot*self.stride,1),0xff,slot)
 def written(self,buf):
  """The name and its FF terminator; bytes past the terminator are stale."""
  end=buf.find(b'\xff')
  return buf if end<0 else buf[:end+1]
 def expected_one(self):
  c=self.cpu();c.r[REG['a0']]=self.dest;c.r[REG['a1']]=1
  self.until(c,self.sym['skill_name_copy'],0x8000fff0)
  return bytes(c.read(self.dest+i,1) for i in range(skills.MAXLEN))

if __name__=='__main__':unittest.main()
