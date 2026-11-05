"""CONTACT names must be exact indexed PSP-US data, not authored abbreviations."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import btlcmd
import btlmsg
import etext
import tables


class ContactCommandSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.psx = btlmsg.data()
        cls.jp = tables.jp_boot()
        cls.us = tables.us_boot()

    def test_all_psx_japanese_slots_match_psp_and_us_text_is_source(self):
        rows = btlcmd.source_commands(self.psx, self.jp, self.us)
        self.assertEqual(len(rows), 36)
        self.assertEqual([s for _, s in rows], btlcmd.pointer_text(self.us, btlcmd.US_TABLE))
        self.assertTrue(all(text for _pointer, text in rows))

    def test_reordered_or_aliased_slots_fail_closed(self):
        data = bytearray(self.jp)
        off = btlcmd.JP_TABLE
        a, b = data[off:off + 4], data[off + 16:off + 20]
        data[off:off + 4], data[off + 16:off + 20] = b, a
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            btlcmd.source_commands(self.psx, data, self.us)
        data = bytearray(self.us)
        off = btlcmd.US_TABLE
        a, b = data[off:off + 4], data[off + 4:off + 8]
        data[off:off + 4], data[off + 4:off + 8] = b, a
        with self.assertRaisesRegex(ValueError, 'inconsistent regional duplicate'):
            btlcmd.source_commands(self.psx, self.jp, data)
        data = bytearray(self.us)
        off = btlcmd.US_TABLE
        data[off + 4:off + 8] = data[off:off + 4]
        with self.assertRaisesRegex(ValueError, 'aliased'):
            btlcmd.source_commands(self.psx, self.jp, data)

    def test_invalid_pointer_control_and_missing_terminator_fail_closed(self):
        data = bytearray(self.us)
        struct.pack_into('<I', data, btlcmd.US_TABLE, 0xffffffff)
        with self.assertRaisesRegex(ValueError, 'outside'):
            btlcmd.source_commands(self.psx, self.jp, data)
        data = bytearray(self.us)
        base, _ = btlcmd.data_segment(data)
        pointer = base + struct.unpack_from('<I', data, btlcmd.US_TABLE)[0]
        data[pointer:pointer + 2] = b'\xff\x03'
        with self.assertRaisesRegex(ValueError, 'controlled'):
            btlcmd.source_commands(self.psx, self.jp, data)
        data = bytearray(self.us)
        data[pointer:pointer + 128] = b'\x01\x01' * 64
        with self.assertRaisesRegex(ValueError, 'unterminated'):
            btlcmd.source_commands(self.psx, self.jp, data)

    def test_production_readback_rejects_pointer_and_text_corruption(self):
        built = ROOT / 'build/BTLP.BIN'
        if not built.exists():
            self.skipTest('requires assembled BTLP')
        original = built.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'BTLP.BIN'
            path.write_bytes(original)
            btlcmd.verify(str(path))
            data = bytearray(original)
            slot = btlcmd.PSX_TABLE - btlcmd.B
            ptr = struct.unpack_from('<I', data, slot)[0]
            data[ptr - btlcmd.B] ^= 1
            path.write_bytes(data)
            with self.assertRaisesRegex(SystemExit, 'text mismatch'):
                btlcmd.verify(str(path))
            data = bytearray(original)
            struct.pack_into('<I', data, slot, btlcmd.B)
            path.write_bytes(data)
            with self.assertRaisesRegex(SystemExit, 'pointer outside'):
                btlcmd.verify(str(path))

    def test_assembled_psx_pointer_slots_read_back_full_psp_text(self):
        path = ROOT / 'build/BTLP.BIN'
        if not path.exists():
            self.skipTest('requires assembled BTLP')
        built = path.read_bytes()
        for i, (_original, text) in enumerate(btlcmd.source_commands(self.psx, self.jp, self.us)):
            ptr = struct.unpack_from('<I', built, btlcmd.PSX_TABLE - btlcmd.B + 4 * i)[0]
            expected = etext.encode(text, end=btlmsg.END)
            self.assertEqual(built[ptr - btlcmd.B:ptr - btlcmd.B + len(expected)], expected, i)


if __name__ == '__main__':
    unittest.main()
