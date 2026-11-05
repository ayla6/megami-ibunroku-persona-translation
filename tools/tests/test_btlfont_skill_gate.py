"""Battle VWF must fail closed on font/metric/geometry disagreements."""
from pathlib import Path
import sys,unittest,struct
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/injection_tools'))
import btlfont,skills,slps,toolbelt

class BattleFontSkillGate(unittest.TestCase):
 def test_incompatible_skill_glyph_is_rejected(self):
  first=slps.SK_FIRST-slps.BASE
  row=next(r for r in toolbelt.merged_rows(slps.REL)
           if r['en'].strip() and first<=int(r['pos'],16)<first+slps.SK_STRIDE*slps.SK_COUNT
           and (int(r['pos'],16)-first)%slps.SK_STRIDE==0)
  code=skills.encode(0,row['en'].strip())[0]; x=(code%31)*8;y=(code//31)*12
  altered=bytearray(btlfont.SHEET);at=y*256+x;altered[at]^=1
  with patch.object(btlfont,'SHEET',altered):
   with self.assertRaisesRegex(SystemExit,'battle font page|ink footprint'):
    btlfont.verify_skill_vwf()

 def test_unverified_buffer_reference_and_descriptor_change_are_rejected(self):
  original=Path.read_bytes
  filename=Path(btlfont.ROOT)/'build'/'BTLP.BIN'
  built=original(filename)
  base=0x800643C4
  descriptor=toolbelt.asm_equ('BTLP_SKILL_DESC_A')-base
  for at,value,message in ((0,toolbelt.asm_equ('SKILL_MENU_BUF'),'unverified battle skill-buffer pointer'),
                           (descriptor+4,toolbelt.asm_equ('SKILL_MENU_BUF')+16,'changed battle skill slot descriptor'),
                           (descriptor,0,'changed battle skill slot descriptor')):
   altered=bytearray(built);struct.pack_into('<I',altered,at,value)
   def read(path):
    return bytes(altered) if path==filename else original(path)
   with self.subTest(message=message), patch.object(Path,'read_bytes',read):
    with self.assertRaisesRegex(SystemExit,message): btlfont.verify_skill_vwf()

if __name__=='__main__':unittest.main()
