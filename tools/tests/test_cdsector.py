"""Batched Form 1 sector generation and deferred disc writes must match the
single-sector builders byte for byte, so a run can amortize EDC/ECC work
without changing a single byte of the image."""
import os
import random
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import build_disc
import cdsector

SECTOR = 2352


def random_entries(count, rng):
    entries = []
    for _ in range(count):
        lba = rng.randint(0, 400000)
        sub = bytes(rng.getrandbits(8) for _ in range(4))
        size = rng.choice([0, 1, 100, 2047, 2048])
        entries.append((lba, sub, bytes(rng.getrandbits(8) for _ in range(size))))
    return entries


class Form1Batch(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(7)

    def test_batch_matches_single_sector_builder(self):
        for _ in range(10):
            entries = random_entries(self.rng.randint(1, 20), self.rng)
            expected = [cdsector.make_form1(lba, sub, data)
                        for lba, sub, data in entries]
            self.assertEqual(cdsector.make_form1_many(entries), expected)

    def test_scalar_fallback_matches(self):
        entries = random_entries(3, self.rng)
        expected = [cdsector.make_form1(lba, sub, data)
                    for lba, sub, data in entries]
        saved = cdsector._np
        try:
            cdsector._np = None
            self.assertEqual(cdsector.make_form1_many(entries), expected)
        finally:
            cdsector._np = saved

    def test_empty_batch(self):
        self.assertEqual(cdsector.make_form1_many([]), [])


class DeferredWrites(unittest.TestCase):
    def test_flush_writes_contiguous_runs_like_write_user(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'disc.bin'
            blank = bytes(SECTOR * 20)
            path.write_bytes(blank)
            disc = build_disc.Disc(path)
            data = bytes(range(256)) * 10
            disc.write_file(2, data)
            disc.write_file(8, b'x')                    # single-sector file
            disc.write_file(3, data[:2048])             # overlaps first file
            disc.write_user(15, b'pvd!', b'\x00\x00\x08\x00')
            disc.flush()
            disc.f.close()

            written = path.read_bytes()
            rebuilt = bytearray(blank)
            rebuilt[2 * SECTOR:2 * SECTOR + SECTOR] = cdsector.make_form1(
                2, build_disc.SUB_DATA, data[:2048])
            rebuilt[3 * SECTOR:3 * SECTOR + SECTOR] = cdsector.make_form1(
                3, build_disc.SUB_LAST, data[:2048])
            rebuilt[8 * SECTOR:8 * SECTOR + SECTOR] = cdsector.make_form1(
                8, build_disc.SUB_LAST, b'x'.ljust(2048, b'\x00'))
            rebuilt[15 * SECTOR:15 * SECTOR + SECTOR] = cdsector.make_form1(
                15, b'\x00\x00\x08\x00', b'pvd!'.ljust(2048, b'\x00'))
            self.assertEqual(written, bytes(rebuilt))

    def test_pending_sector_is_visible_to_reads_before_flush(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'disc.bin'
            path.write_bytes(bytes(SECTOR * 4))
            disc = build_disc.Disc(path)
            disc.write_file(1, b'abc')
            self.assertEqual(disc.user(1)[:3], b'abc')
            disc.f.close()


if __name__ == '__main__':
    unittest.main()
