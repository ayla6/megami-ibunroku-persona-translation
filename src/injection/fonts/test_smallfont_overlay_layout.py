"""Read back the live name hooks and overlay-owned storage from assembled files."""
import re
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
from smallfont_vwf import SCRATCH_TABLE_OVERLAYS as SCRATCH_TABLES  # noqa: E402
from toolbelt import asm_equ  # noqa: E402

BASE = 0x800643C4
ROWS = asm_equ('SF_ROWS', str(ROOT / 'src/mods/latin-alphabet/asm/vwf/smallfont_defs.asm'))


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
                self.assertEqual(end - table, ROWS * 56)
                self.assertEqual(struct.unpack_from('<I', data, cfg - BASE + 8)[0], table)
                self.assertEqual(data[scratch-BASE:scratch-BASE+21], bytes(21))
                self.assertLessEqual(scratch + 21, BASE + len(data))
                if ovl in SCRATCH_TABLES:
                    # runtime scratch outside the image (ADV: above the game's
                    # globals; DNG: the top of its image room); the recorder
                    # clears it on a fresh load
                    limit = asm_equ(f'{ovl.upper()}_SF_TABLE_LIMIT')
                    self.assertEqual(table, asm_equ(f'{ovl.upper()}_SF_TABLE_ADDR'))
                    self.assertLessEqual(end, limit)
                    self.assertTrue(end <= BASE or table >= BASE + len(data),
                                    'the scratch table overlaps the image')
                    continue
                # The scratch sits at or after the table: overlay code (the
                # MsgStep full-name stubs) may own the run between them, but
                # it must never share bytes with the table or the scratch.
                self.assertGreaterEqual(scratch, end)
                self.assertEqual(data[table-BASE:end-BASE], bytes(ROWS * 56))
                self.assertGreaterEqual(table, self.sym[f'sf_data_end_{ovl}'])


if __name__ == '__main__':
    unittest.main()
