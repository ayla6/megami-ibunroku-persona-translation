"""The resident text scratch must stay beyond every live CD path entry."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
from build_disc import check_path_cache, CD_PATH_CACHE_BASE, CD_PATH_CACHE_STRIDE, RESIDENT_SCRATCH_START


class FakeDisc:
    def __init__(self, count):
        self.data = b''.join(b'\x01\x00' + bytes(6) + b'A\x00' for _ in range(count))

    def user(self, lba):
        return self.data.ljust(2048, b'\x00')


def pvd_for(disc):
    pvd = bytearray(2048)
    struct.pack_into('<I', pvd, 132, len(disc.data))
    struct.pack_into('<I', pvd, 140, 18)
    return pvd


class PathCacheBounds(unittest.TestCase):
    def test_boundary(self):
        limit = (RESIDENT_SCRATCH_START - CD_PATH_CACHE_BASE) // CD_PATH_CACHE_STRIDE
        disc = FakeDisc(limit)
        self.assertEqual(check_path_cache(disc, pvd_for(disc)), limit)
        disc = FakeDisc(limit + 1)
        with self.assertRaisesRegex(ValueError, 'overlapping text scratch'):
            check_path_cache(disc, pvd_for(disc))

    def test_rejects_truncated_record(self):
        disc = FakeDisc(1)
        pvd = pvd_for(disc)
        struct.pack_into('<I', pvd, 132, len(disc.data) - 1)
        with self.assertRaisesRegex(ValueError, 'malformed'):
            check_path_cache(disc, pvd)


if __name__ == '__main__':
    unittest.main()
