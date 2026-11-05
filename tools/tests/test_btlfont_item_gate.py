"""Item VWF rejects altered numeric geometry, stale ownership and source clipping."""
from pathlib import Path
import re
import struct
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/injection_tools'))
import btlfont,items,toolbelt

class ItemFontGate(unittest.TestCase):
    def test_full_name_is_marked_as_owned(self):
        pos=hex(toolbelt.asm_equ('ITEM_NAME_BASE')+items.STRIDE-items.BASE)
        with patch.object(toolbelt,'merged_rows',return_value=[{'pos':pos,'en':'A'*11}]):
            self.assertEqual(btlfont.item_vwf_records(),{1: items.encode('A'*11)})
            self.assertTrue(btlfont.item_vwf_flags()[0] & 2)

    def test_descriptor_numeric_and_generation_mutations_fail_closed(self):
        original=Path.read_bytes
        battle=ROOT/'build/BTLP.BIN';resident=ROOT/'build/SLPS_005.00'
        images={battle:original(battle),resident:original(resident)}
        sym={m.group(2):int(m.group(1),16) for line in (ROOT/'build/persona.sym').read_text().splitlines()
             if (m:=re.fullmatch(r'([0-9A-Fa-f]{8}) (\S+)',line))}
        desc=toolbelt.asm_equ('BTLP_ITEM_DESC')
        samples=((battle,desc-0x800643c4+8,'<B',10,'item name descriptor'),
                 (battle,desc+12*12-0x800643c4,'<h',-120,'item numeric descriptor'),
                 (battle,0x800acf0c-0x800643c4,'<I',0,'producer ownership hook'),
                 (resident,sym['btl_item_owner']-items.BASE,'<B',1,'semantic name directory'),
                 (resident,sym['btl_name_ranges']-items.BASE+56+8,'<I',0,'semantic name directory'))
        # +56: the directory's third entry (Persona, skill, item) - its IDs
        # word is the item source table, so zeroing it must fail the verify.
        for filename,at,fmt,value,message in samples:
            altered=bytearray(images[filename]);struct.pack_into(fmt,altered,at,value)
            def read(path):return bytes(altered) if path==filename else original(path)
            with self.subTest(message=message),patch.object(Path,'read_bytes',read):
                with self.assertRaisesRegex(SystemExit,message):btlfont.verify_skill_vwf()

if __name__=='__main__':unittest.main()
