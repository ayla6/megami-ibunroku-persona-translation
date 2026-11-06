"""Read back the live name hooks and overlay-owned storage from assembled files."""
import re
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = 0x800643C4


class OverlayStorage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / 'build/persona.sym'
        if not path.exists():
            raise unittest.SkipTest('requires assembled game files')
        cls.sym = {}
        for line in path.read_text().splitlines():
            match = re.fullmatch(r'([0-9a-fA-F]{8}) (\w+)', line)
            if match:
                cls.sym[match[2]] = int(match[1], 16)

    def test_name_hooks_and_recorder_use_their_own_scratch(self):
        for ovl in ('adv', 'dng', 's2d'):
            with self.subTest(overlay=ovl):
                data = (ROOT / f'build/{ovl.upper()}.BIN').read_bytes()
                scratch = self.sym[f'sf_name_scratch_{ovl}']
                hook = self.sym[f'item_hook_{ovl}']
                recorder = self.sym[f'sf_record_{ovl}']
                rec_end = self.sym[f'sf_record_end_{ovl}']
                copy = self.sym[f'item_name_copy_{ovl}']
                words = struct.unpack_from('<14I', data, hook - BASE)
                hi = ((scratch + 0x8000) >> 16) & 0xFFFF
                lo = scratch & 0xFFFF
                self.assertEqual(words[2:4], (0x3C040000 | hi, 0x24840000 | lo))
                self.assertEqual(words[9:11], (0x3C040000 | hi, 0x24840000 | lo))
                self.assertEqual(words[5], 0x0C000000 | ((copy >> 2) & 0x03FFFFFF))
                instructions = struct.unpack_from(f'<{(rec_end - recorder) // 4}I', data, recorder - BASE)
                self.assertTrue(any(instructions[i:i+2] == (0x3C0B0000 | hi, 0x256B0000 | lo)
                                    for i in range(len(instructions) - 1)),
                                'recorder must recognize the very same full-name scratch')

    def test_tables_are_distinct_overlay_owned_zero_filled_regions(self):
        for ovl in ('adv', 'dng', 's2d'):
            with self.subTest(overlay=ovl):
                data = (ROOT / f'build/{ovl.upper()}.BIN').read_bytes()
                table = self.sym[f'sf_table_{ovl}']
                end = self.sym[f'sf_table_end_{ovl}']
                scratch = self.sym[f'sf_name_scratch_{ovl}']
                cfg = self.sym[f'sf_cfg_{ovl}']
                self.assertEqual(end - table, 64 * 56)
                # The scratch sits at or after the table: overlay code (the
                # MsgStep full-name stubs) may own the run between them, but
                # it must never share bytes with the table or the scratch.
                self.assertGreaterEqual(scratch, end)
                self.assertEqual(struct.unpack_from('<I', data, cfg - BASE + 8)[0], table)
                self.assertEqual(data[table-BASE:end-BASE], bytes(64 * 56))
                self.assertEqual(data[scratch-BASE:scratch-BASE+21], bytes(21))
                self.assertGreaterEqual(table, self.sym[f'sf_data_end_{ovl}'])
                self.assertLessEqual(scratch + 21, BASE + len(data))


if __name__ == '__main__':
    unittest.main()
