"""Bounded movie comparisons preserve the established sector-body semantics."""
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import toolpath
import modpack
import build_disc


class MovieComparison(unittest.TestCase):
    def test_headers_are_ignored_but_every_body_byte_matters(self):
        original = bytes(modpack.SECTOR*900)
        changed = bytearray(original)
        for i in range(0, len(changed), modpack.SECTOR):
            changed[i:i+16] = bytes([7])*16
        with patch.object(build_disc, 'raw_body', side_effect=AssertionError('whole movie copy')):
            self.assertTrue(modpack.same_file_data(original, bytes(changed), True))
            for at in (16, 2351, 2352+16, 449*2352+16, len(changed)-1):
                changed[at] ^= 1
                self.assertFalse(modpack.same_file_data(original, bytes(changed), True))
                changed[at] ^= 1
        self.assertFalse(modpack.same_file_data(original, bytes(changed)))
        self.assertFalse(modpack.same_file_data(original, changed[:-2352], True))

    def test_partial_and_empty_inputs_match_existing_semantics(self):
        rng = random.Random(17)
        for size in (0, 1, 15, 16, 17, 2351, 2352, 2353, 4710):
            a = rng.randbytes(size)
            for b in (a, bytes(size), a+b'header'):
                self.assertEqual(modpack.same_file_data(a,b,True),
                                 build_disc.raw_body(a)==build_disc.raw_body(b))
