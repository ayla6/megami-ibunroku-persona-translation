"""Persona names require proven atlas cells, frame geometry and owned descriptors."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import btlfont
import toolbelt

class BattleFontPersonaGate(unittest.TestCase):
    def test_persona_only_glyph_is_checked_against_battle_atlas(self):
        # J is used by a canonical Persona but by no currently written skill.
        import personas, skills, slps
        first = slps.SK_FIRST - slps.BASE
        skill_codes = {code for row in toolbelt.merged_rows('SLPS_005.00')
                       if row['en'].strip() and first <= int(row['pos'],16) < first + slps.SK_COUNT*slps.SK_STRIDE
                       and (int(row['pos'],16)-first) % slps.SK_STRIDE == 0
                       for code in skills.encode(0,row['en'].strip())}
        persona_codes = {code for text in personas.record_en().values() if text.strip()
                         for code in skills.encode_glyphs(0,text.strip())}
        unique = sorted(persona_codes - skill_codes)
        self.assertTrue(unique, 'fixture needs a source-derived Persona-only glyph')
        code = unique[0]
        altered = bytearray(btlfont.SHEET)
        altered[(code//31)*12*256 + (code%31)*8] ^= 1
        with patch.object(btlfont,'SHEET',altered):
            with self.assertRaisesRegex(SystemExit,'battle font page|Persona'):
                btlfont.verify_skill_vwf()

    def test_graph_geometry_and_unowned_slot_references_fail_closed(self):
        original = Path.read_bytes
        filename = ROOT/'build/BTLP.BIN'
        built = original(filename)
        base = 0x800643c4
        header = toolbelt.asm_equ('BTLP_HDR_NAME_DESC')
        skill_buf = toolbelt.asm_equ('SKILL_MENU_BUF')
        stride = toolbelt.asm_equ('SKILL_MENU_STRIDE')
        mutations = (
            (0x800e2288-base, '<I', 0, 'board graph'),
            (0x800ddbE4-base, '<h', -300, 'board graph'),
            (toolbelt.asm_equ('BTLP_PRSCHG_DESC')-base, '<h', -300, 'Persona row geometry'),
            (header-base, '<h', 500, 'overlaps the header label'),
            (header-base+8, '<B', 0, 'owned slot'),
            (0, '<I', skill_buf + stride, 'unverified battle skill-buffer pointer'),
        )
        for at,fmt,value,message in mutations:
            altered = bytearray(built)
            struct.pack_into(fmt,altered,at,value)
            def read(path):
                return bytes(altered) if path == filename else original(path)
            with self.subTest(address=hex(base+at)), patch.object(Path,'read_bytes',read):
                with self.assertRaisesRegex(SystemExit,message):
                    btlfont.verify_skill_vwf()

if __name__ == '__main__':
    unittest.main()
