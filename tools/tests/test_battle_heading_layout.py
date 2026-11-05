"""Padded literal headings centre using the same metrics as battle VWF."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import battle_text_layout as layout


class HeadingLayout(unittest.TestCase):
    def fixture(self, text=b'\0\0AB\0\0', x=-24, y=-20, bottom=False):
        data = bytearray(0x100)
        struct.pack_into('<II', data, 0, 2 if bottom else 1, layout.BASE + 0x20)
        struct.pack_into('<hhIBBBB', data, 0x20, x, y,
                         layout.BASE + 0x80, len(text), 0x21, 12, 0)
        if bottom:
            struct.pack_into('<hhIBBBB', data, 0x2C, -8, y-12,
                             layout.BASE + 0xA0, 1, 0x21, 12, 0)
            data[0xA0:0xA2] = b'A\xff'
        data[0x80:0x81+len(text)] = text + b'\xff'
        widths = bytearray([0x32] * 256)  # bearing 3, advance 2
        widths[0] = 4
        bits = bytearray(32)
        for c in b'\0AB':
            bits[c // 8] |= 1 << (c % 8)
        return data, widths, bits

    def test_centres_padded_heading_on_object_origin(self):
        self.assertEqual(layout.centred_headings(*self.fixture()), [(0x20, -24)])

    def test_fixed_headings_ignore_proportional_metrics(self):
        data, widths, bits = self.fixture()
        widths[ord('A')] = 0x71
        self.assertEqual(layout.centred_headings(data, widths, bits), [(0x20, -24)])

    def test_ordinary_and_unbalanced_rows_keep_their_alignment(self):
        for text in (b'AB', b'\0AB', b'\0AB\0\0', b'\0\0'):
            self.assertEqual(layout.centred_headings(*self.fixture(text)), [])
        self.assertEqual(layout.centred_headings(*self.fixture(x=10)), [])
        self.assertEqual(layout.centred_headings(*self.fixture(bottom=True)), [])

    def test_nontext_or_early_terminated_runs_stay_retail(self):
        for text in (b'\0A1\0', b'\0A\xffB\0'):
            self.assertEqual(layout.centred_headings(*self.fixture(text)), [])

    def test_descriptor_requires_a_valid_text_list(self):
        data, widths, bits = self.fixture()
        struct.pack_into('<I', data, 0, 0)
        self.assertEqual(layout.centred_headings(data, widths, bits), [])

    def test_readback_checks_position(self):
        data, _, _ = self.fixture()
        with self.assertRaisesRegex(ValueError, 'not centred'):
            layout.verify(data, [(0x20, -10)])
        struct.pack_into('<h', data, 0x20, -10)
        layout.verify(data, [(0x20, -10)])

    def test_retail_heading_is_discovered_without_name_or_address_mapping(self):
        data = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        widths = (ROOT / 'build/sf_width.bin').read_bytes()
        bits = (ROOT / 'build/btl_text_bits.bin').read_bytes()
        rows = layout.centred_headings(data, widths, bits)
        self.assertTrue(rows)
        for off, x in rows:
            pointer = struct.unpack_from('<I', data, off + 4)[0] - layout.BASE
            n = data[off + 8]
            width = n * 8
            self.assertIn(2*x + width, (0, 1))


if __name__ == '__main__':
    unittest.main()
