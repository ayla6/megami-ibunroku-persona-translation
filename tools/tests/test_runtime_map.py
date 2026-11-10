"""Indexed runtime references are leads, not inferred array extents."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import runtime_map


class RuntimeMap(unittest.TestCase):
    def test_indexed_store_and_reader(self):
        # lui at,0x8010; addiu at,at,-0x7c44; addu at,at,v0; sw v1,0(at)
        code = struct.pack('<4I', 0x3c018010, 0x242183bc, 0x00220821, 0xac230000)
        self.assertEqual(list(runtime_map.candidates(code, 0x80010000)),
                         [(0x8001000c, 0x800f83bc, 'sw', 2)])

    def test_real_graphics_pointer_array_is_found(self):
        if not runtime_map.DEFAULT.exists():
            self.skipTest('requires extracted rev-0 BTLP')
        hits = list(runtime_map.candidates(runtime_map.DEFAULT.read_bytes()))
        self.assertIn((0x80081b84, 0x800f83bc, 'sw', 2), hits)


if __name__ == '__main__':
    unittest.main()
