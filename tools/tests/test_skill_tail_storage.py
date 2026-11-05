"""The skill tail bank must never overlap the next resident code allocation."""
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/injection_tools'))
import skills
import slps
import toolbelt

class SkillTailStorage(unittest.TestCase):
    def test_last_owned_byte_and_overflow(self):
        cap = toolbelt.asm_equ('SKILL_TAILS_SIZE')
        self.assertEqual(toolbelt.asm_equ('SKILL_TAILS_ADDR') + cap,
                         toolbelt.asm_equ('AFF_FREE2_ADDR'))
        bank = bytearray(cap - 3)
        self.assertEqual(skills.append_tail(bank, b'AB'), cap - 3)
        self.assertEqual(len(bank), cap)
        self.assertEqual(bank[-3:], b'AB\xff')
        before = bytes(bank)
        with self.assertRaises(SystemExit):
            skills.append_tail(bank, b'C')
        self.assertEqual(bank, before)

    def test_full_builder_refuses_overlap_without_writing_outputs(self):
        start = slps.SK_FIRST - slps.BASE
        rows = [{'id': str(i), 'pos': hex(start + i * slps.SK_STRIDE),
                 'en': 'A' * 13 + chr(65 + i // 26) + chr(65 + i % 26), 'psp': ''} for i in range(30)]
        with tempfile.TemporaryDirectory() as tmp:
            out, tails = Path(tmp, 'slps.asm'), Path(tmp, 'tails.asm')
            out.write_text('old output'); tails.write_text('old tails')
            with patch.object(slps, 'OUT', str(out)), \
                 patch.object(slps, 'OUT_TAILS', str(tails)), \
                 patch.object(toolbelt, 'merged_rows', return_value=rows):
                with self.assertRaisesRegex(SystemExit, 'owned before the next resident code'):
                    slps.build()
            self.assertEqual(out.read_text(), 'old output')
            self.assertEqual(tails.read_text(), 'old tails')

    def test_identical_and_suffix_tails_share_exact_terminated_bytes(self):
        bank = bytearray()
        self.assertEqual(skills.append_tail(bank, b'ABCDE'), 0)
        self.assertEqual(skills.append_tail(bank, b'ABCDE'), 0)
        self.assertEqual(skills.append_tail(bank, b'CDE'), 2)
        self.assertEqual(bank, bytearray(b'ABCDE\xff'))
        self.assertEqual(skills.append_tail(bank, b'ABC'), 6)
        self.assertEqual(bank, bytearray(b'ABCDE\xffABC\xff'))

    def test_standalone_builder_uses_longest_first_suffix_plan(self):
        entries=[(0,0x80047d58,''),(1,0x80047d6c,'')]
        wording={0:('A'*10+'BCDE',''),1:('A'*10+'ABCDE','')}
        with tempfile.TemporaryDirectory() as tmp:
            out,tails=Path(tmp,'skills.asm'),Path(tmp,'tails.asm')
            with patch.object(skills,'records',return_value=entries), \
                 patch.object(skills,'read_tsv',return_value=wording), \
                 patch.object(skills,'OUT',str(out)),patch.object(skills,'OUT_X',str(tails)):
                skills.build()
            self.assertIn('0xFE, 0x01, 0x00',out.read_text())
            self.assertIn('0xFE, 0x00, 0x00',out.read_text())
            expected=skills.encode_glyphs(0,'ABCDE')+b'\xff'
            self.assertIn(', '.join(f'0x{c:02X}' for c in expected),tails.read_text())

    def test_standalone_overflow_preserves_existing_outputs(self):
        entries=[(i,0x80047d58+i*20,'') for i in range(30)]
        wording={i:('A'*13+chr(65+i//26)+chr(65+i%26),'') for i in range(30)}
        with tempfile.TemporaryDirectory() as tmp:
            out,tails=Path(tmp,'skills.asm'),Path(tmp,'tails.asm')
            out.write_text('old');tails.write_text('old tails')
            with patch.object(skills,'records',return_value=entries), \
                 patch.object(skills,'read_tsv',return_value=wording), \
                 patch.object(skills,'OUT',str(out)),patch.object(skills,'OUT_X',str(tails)):
                with self.assertRaises(SystemExit):skills.build()
            self.assertEqual(out.read_text(),'old');self.assertEqual(tails.read_text(),'old tails')

    def test_misdeclared_owner_boundary_fails_closed(self):
        original = toolbelt.asm_equ
        def broken(name, *args):
            value = original(name, *args)
            return value + 1 if name == 'AFF_FREE2_ADDR' else value
        bank = bytearray()
        with patch.object(toolbelt, 'asm_equ', side_effect=broken):
            with self.assertRaises(SystemExit):
                skills.append_tail(bank, b'A')
        self.assertEqual(bank, bytearray())

if __name__ == '__main__':
    unittest.main()
