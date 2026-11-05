"""Source and geometry evidence only; this does not enable personality VWF."""
from pathlib import Path
import struct
import sys
import unittest

from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import btlcmd
import btlmsg
import btlui
import personality_source
import smallfont_vwf
import tables


class PersonalityEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.psx = btlmsg.data()
        cls.jp = tables.jp_boot()
        cls.us = tables.us_boot()
        cls.names = btlcmd.pointer_text(cls.us, 0x2acbdc, 8)

    def test_profile_masks_establish_distinct_bit_positions(self):
        masks = [[], [], []]
        for i in range(1, 194):
            ptr = struct.unpack_from('<I', self.psx, 0x800caf30 - btlmsg.B + 4 * i)[0]
            offset = ptr - btlmsg.B
            self.assertGreaterEqual(offset, 0)
            self.assertLessEqual(offset + 20, len(self.psx))
            masks[0].append(self.psx[offset + 2])
            masks[1].append(self.jp[0x295ac4 - (i - 1) * 20 + 2])
            masks[2].append(self.us[0x2a7ce0 - (i - 1) * 20 + 2])
        self.assertEqual(masks[0], masks[1])
        self.assertEqual(masks[0], masks[2])
        vectors = {tuple((m >> bit) & 1 for m in masks[0]) for bit in range(8)}
        self.assertEqual(len(vectors), 8)

    def test_mechanical_source_proof_and_falsifiers(self):
        self.assertEqual(personality_source.prove(self.psx, self.jp, self.us), self.names)
        jp = bytearray(self.jp)
        jp[personality_source.JP_PROFILE_ONE + 2] ^= 1
        with self.assertRaisesRegex(ValueError, 'profile bit mismatch'):
            personality_source.prove(self.psx, jp, self.us)
        us = bytearray(self.us)
        us[0xb7260] ^= 1
        with self.assertRaisesRegex(ValueError, 'consumer changed'):
            personality_source.prove(self.psx, self.jp, us)
        psx = bytearray(self.psx)
        psx[0x80075290 - btlmsg.B] ^= 1
        with self.assertRaisesRegex(ValueError, 'consumer changed'):
            personality_source.prove(psx, self.jp, self.us)
        us = bytearray(self.us)
        at = personality_source.US_TABLE
        us[at + 4:at + 8] = us[at:at + 4]
        with self.assertRaisesRegex(ValueError, 'aliased'):
            personality_source.prove(self.psx, self.jp, us)

    def test_retail_guard_rejects_new_private_bank_and_helper_references(self):
        for target in (0x800c87ec, 0x800b9f58):
            altered = bytearray(self.psx)
            struct.pack_into('<I', altered, 0, target)
            with self.assertRaisesRegex(ValueError, 'reference|consumer'):
                btlui.guard_offer_retail(altered)

    def test_psp_consumers_increment_pointer_and_test_same_bit_index(self):
        md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
        for blob, start, pointer, flags in ((self.jp, 0xb5ecc, '$s4', '$s6'),
                                            (self.us, 0xb7254, '$s2', '$s7')):
            instructions = [(i.mnemonic, i.op_str)
                            for i in md.disasm(blob[start:start + 32], start)]
            self.assertEqual(instructions[1], ('addiu', f'{pointer}, {pointer}, 4'))
            self.assertEqual(instructions[2][0], 'lhu')
            self.assertIn(flags, instructions[2][1])
            self.assertIn(('srav', '$v0, $v0, $s1'), instructions)
            self.assertIn(('andi', '$v0, $v0, 1'), instructions)
            self.assertIn(('addiu', '$s1, $s1, 1'), instructions)

    def test_full_glyph_quads_fit_original_four_column_offer_frame(self):
        table = ROOT / 'build/sf_width.bin'
        if not table.exists():
            self.skipTest('requires built small-font metrics')
        widths = table.read_bytes()
        columns = [[] for _ in range(4)]
        for i, text in enumerate(self.names):
            pen = 0
            left, right = 1000, -1
            for char in text:
                packed = widths[smallfont_vwf.char_code(char)]
                origin = pen - (packed >> 4)
                left = min(left, origin)
                right = max(right, origin + 8)
                pen += packed & 15
            x = 16 + (i >> 1) * 48
            columns[i >> 1].append((x + left, x + right))
            self.assertGreaterEqual(x + left, 0)
            self.assertLessEqual(x + right, 208)
        for left, right in zip(columns, columns[1:]):
            self.assertLess(max(end for _start, end in left),
                            min(start for start, _end in right))

    def test_personality_quads_alone_fit_one_ui_packet_half(self):
        # BtlDrawGlyphs emits one 40-byte POLY_FT4 per character, while
        # BtlDrawUi gives each of its two buffers 0x2800 bytes. Other UI and
        # effect rows share this arena: this is NOT a whole-frame bound.
        glyphs = sum(len(text) for text in self.names)
        self.assertLessEqual(glyphs * 40, 0x2800)

    def test_one_byte_terminators_fit_the_existing_personality_bank(self):
        encoded = [bytes(smallfont_vwf.char_code(c) for c in text) + b'\xff'
                   for text in self.names]
        self.assertLessEqual(sum(map(len, encoded)), 0x40)
        # This is capacity evidence only: FF-only use is not enabled until
        # every consumer and the effect renderer have been verified.


if __name__ == '__main__':
    unittest.main()
