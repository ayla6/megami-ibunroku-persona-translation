"""All action banners point to dialogue-encoded PSP names or intact JP bytes."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import btlp
import etext
import toolbelt


class BannerReadback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = [ROOT / 'build' / 'BTLP.BIN', ROOT / 'build' / 'SLPS_005.00']
        if not all(p.exists() for p in required):
            raise unittest.SkipTest('requires assembled build/')
        cls.overlay, cls.slps = (p.read_bytes() for p in required)
        cls.base, cls.size = struct.unpack_from('<II', cls.slps, 0x18)
        cls.original = btlp.data()
        cls.rows = {r['pos']: r for r in toolbelt.merged_rows('BTLP')}

    def data_at(self, address, count):
        if btlp.B <= address and address + count <= btlp.B + len(self.overlay):
            offset = address - btlp.B
            return self.overlay[offset:offset + count]
        if self.base <= address and address + count <= self.base + self.size:
            offset = 0x800 + address - self.base
            return self.slps[offset:offset + count]
        self.fail(f'banner pointer {address:#x} is not in an assembled owner')

    def test_every_pointer_reads_exact_canonical_wording_and_terminator(self):
        records = list(btlp.ban_records(self.original))
        self.assertTrue(records, 'no action banner records were found')
        for index, original, japanese in records:
            with self.subTest(index=index, japanese=japanese):
                row = self.rows.get(hex(original - btlp.B), {})
                text = (row.get('en') or '').strip()
                if text:
                    expected = etext.encode(text, end=btlp.END)
                else:
                    start = original - btlp.B
                    end = self.original.index(btlp.END, start) + len(btlp.END)
                    expected = self.original[start:end]
                pointer = struct.unpack_from('<I', self.overlay,
                                             btlp.BAN_TABLE - btlp.B + 4 * index)[0]
                self.assertEqual(self.data_at(pointer, len(expected)), expected)

    def test_popup_encoding_is_battle_dialogue_not_small_font(self):
        wording = btlp.banner_wording()[80][0]
        self.assertEqual(btlp.ban_encode(wording), etext.encode(wording, end=None))
        self.assertNotEqual(btlp.ban_encode(wording), bytes.fromhex('ad233823'))


if __name__ == '__main__':
    unittest.main()
