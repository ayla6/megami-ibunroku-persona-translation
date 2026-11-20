"""Retail twins preserve extent order and inspect only possible duplicates."""
from types import SimpleNamespace
import unittest

import modpack


class RetailTwins(unittest.TestCase):
    def test_unique_lengths_and_first_bodies_skip_full_reads(self):
        reads = []
        def raw(lba):
            reads.append(lba)
            if lba == 40:
                raise AssertionError('unique-length file was read')
            if lba in (31, 32, 33):
                raise AssertionError('different-first-sector file was scanned')
            # Identical sector bodies, with differing address headers.
            return bytes([lba])*16 + b'\0'*2352
        source = SimpleNamespace(entries={
            'LATER': (20, 4096), 'FIRST': (10, 4096),
            'SAME_EXTENT': (10, 4096), 'UNIQUE': (40, 8192),
            'OTHER': (30, 4096),
        })
        def sectors(lba):
            result = raw(lba)
            if lba == 30:
                return result[:24] + b'different' + result[33:]
            return result
        source.disc = SimpleNamespace(raw=sectors)
        self.assertEqual(modpack.retail_twins(source), [['FIRST', 'LATER']])
        self.assertEqual(set(reads), {10, 11, 20, 21, 30})

    def test_persistent_groups_require_matching_image_and_intact_output(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root/'retail.bin'
            image.write_bytes(b'first')
            source = SimpleNamespace(entries={'FIRST': (1, 2048), 'SECOND': (2, 2048)},
                                     disc=SimpleNamespace(f=SimpleNamespace(name=str(image))))
            with patch.object(modpack, 'ROOT', str(root)), patch.object(
                    modpack, 'retail_twins', return_value=[['FIRST', 'SECOND']]) as discover:
                expected = modpack.cached_retail_twins(source)
                self.assertEqual(modpack.cached_retail_twins(source), expected)
                self.assertEqual(discover.call_count, 1)
                (root/'build/step_cache/retail-twins/groups.tsv').write_text('damaged')
                self.assertEqual(modpack.cached_retail_twins(source), expected)
                self.assertEqual(discover.call_count, 2)
                image.write_bytes(b'other')
                self.assertEqual(modpack.cached_retail_twins(source), expected)
                self.assertEqual(discover.call_count, 3)
