"""Item-name ownership follows the real producer; number/label buffers remain retail."""
from pathlib import Path
import re
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src/injection_tools'),str(ROOT/'tools/tests')]
import btlfont
import toolbelt
from mips_cpu import CPU,REG

class BattleItemOwnership(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resident=(ROOT/'build/SLPS_005.00').read_bytes()[0x800:]
        cls.battle=(ROOT/'build/BTLP.BIN').read_bytes()
        cls.sym={m.group(2):int(m.group(1),16) for line in (ROOT/'build/persona.sym').read_text().splitlines()
                 if (m:=re.fullmatch(r'([0-9A-Fa-f]{8}) (\S+)',line))}

    def cpu(self):
        c=CPU();c.load(0x80010000,self.resident);c.load(0x800643c4,self.battle)
        c.r[REG['sp']]=0x801ff000;c.r[REG['ra']]=0x8000fff0
        return c

    def until(self,c,start,stop,limit=20000):
        c.start(start)
        for _ in range(limit):
            if c.pc==stop:return
            # Numeric formatting is unmodified retail code, not the VWF patch.
            if c.pc==0x800ae4f0:
                c.start(c.r[REG['ra']]);continue
            c.step()
        self.fail(f'no return at {c.pc:#x}')

    def test_all_ids_rows_and_invalid_generation(self):
        flags=btlfont.item_vwf_flags()
        for ident in range(512):
            for row in range(12):
                c=self.cpu();c.write(self.sym['btl_item_owner'],1,1)
                c.write(toolbelt.asm_equ('BTLP_ITEM_IDS_ADDR')+row*2,ident|(17<<9),2)
                c.r[REG['a0']]=toolbelt.asm_equ('BTLP_ITEM_FULL_ADDR')+row*toolbelt.asm_equ('BTLP_ITEM_FULL_STRIDE')
                self.until(c,self.sym['btl_name_lookup'],0x8000fff0,400)
                expected=(flags[ident>>3]>>(ident&7))&1 if ident<86 else 0
                self.assertEqual(c.r[REG['v0']],expected,(ident,row))
        for pointer in (toolbelt.asm_equ('BTLP_ITEM_FULL_ADDR')+1,
                        toolbelt.asm_equ('BTLP_ITEM_COUNT_ADDR'),
                        0x800dd744):
            c=self.cpu();c.write(self.sym['btl_item_owner'],1,1);c.r[REG['a0']]=pointer
            self.until(c,self.sym['btl_name_lookup'],0x8000fff0,400)
            self.assertEqual(c.r[REG['v0']],0)

    def test_real_item_writer_commits_only_complete_source_bytes(self):
        records=btlfont.item_vwf_records()
        c=self.cpu()
        ident=next(i for i in records if c.read(toolbelt.asm_equ('ITEM_NAME_BASE')+i*32-2,2)&0x80)
        inventory=0x801f267c
        c.write(inventory,ident|(1<<9),2);c.r[REG['a0']]=inventory
        c.write(self.sym['btl_item_owner'],1,1)
        self.until(c,0x800acf0c,0x800acf14)
        self.assertEqual(c.read(self.sym['btl_item_owner'],1),0)
        self.until(c,c.pc,0x8000fff0)
        self.assertEqual(c.read(self.sym['btl_item_owner'],1),1)
        buf=toolbelt.asm_equ('BTLP_ITEM_FULL_ADDR')
        actual=bytes(c.read(buf+i,1) for i in range(toolbelt.asm_equ('BTLP_ITEM_FULL_STRIDE'))).split(b'\xff')[0]
        self.assertEqual(actual,records[ident])
        c.r[REG['a0']]=buf;self.until(c,self.sym['btl_name_lookup'],0x8000fff0,400)
        self.assertEqual(c.r[REG['v0']],1)
        # The alternate skill producer invalidates this same buffer before reuse.
        self.until(c,0x800ad41c,0x800ad424,100)
        self.assertEqual(c.read(self.sym['btl_item_owner'],1),0)
        c.r[REG['a0']]=buf;self.until(c,self.sym['btl_name_lookup'],0x8000fff0,400)
        self.assertEqual(c.r[REG['v0']],0)

if __name__=='__main__':unittest.main()
