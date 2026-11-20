"""Native snapshots survive interruption, detect damage and share immutable data."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from variant_cache import VariantCache


class VariantCacheTests(unittest.TestCase):
    def test_reuse_damage_inventory_and_shared_blobs(self):
        with TemporaryDirectory() as tmp:
            cache = VariantCache(Path(tmp)/'variants')
            key = 'a'*40
            files = {'ADV/E0.BIN': b'event', 'DNG.BIN': b'dungeon'}
            tree = cache.store(key, files)
            self.assertEqual(cache.find(key), tree)
            second = cache.store('b'*40, files)
            self.assertEqual((tree/'DNG.BIN').stat().st_ino,
                             (second/'DNG.BIN').stat().st_ino)
            (tree/'extra.bin').write_bytes(b'extra')
            self.assertIsNone(cache.find(key))
            (tree/'extra.bin').unlink()
            (tree/'DNG.BIN').write_bytes(b'tampered')
            self.assertIsNone(cache.find(key))
            self.assertEqual((cache.store(key, files)/'DNG.BIN').read_bytes(), b'dungeon')

    def test_incomplete_and_unsafe_manifests_are_not_hits(self):
        with TemporaryDirectory() as tmp:
            cache = VariantCache(Path(tmp)/'variants')
            entry = cache.entry('a'*40)
            (entry/'files').mkdir(parents=True)
            self.assertIsNone(cache.find('a'*40))
            (entry/'manifest.tsv').write_text('path\tsha1\n../outside\tbad\n')
            self.assertIsNone(cache.find('a'*40))
            with self.assertRaises(ValueError):
                cache.store('b'*40, {'../outside': b'bad'})
            self.assertIsNone(cache.find('b'*40))
            self.assertEqual(list(cache.root.glob('.variant-*')), [])

    def test_generated_range_maps_are_verified_and_restored_without_source_writes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = VariantCache(root/'build/step_cache/variants')
            name = 'build/step_cache/sounds/values.tsv'
            data = b'path\toffset\tparameter\toriginal\n'
            key = 'c'*40
            cache.store(key, {'DNG.BIN': b'game'}, {name: data})
            cache.restore_auxiliary(key, root)
            self.assertEqual((root/name).read_bytes(), data)
            (root/name).write_bytes(b'changed live output')
            self.assertIsNotNone(cache.find(key))
            cache.restore_auxiliary(key, root)
            self.assertEqual((root/name).read_bytes(), data)
            (cache.entry(key)/'auxiliary'/name).write_bytes(b'damaged cache')
            self.assertIsNone(cache.find(key))
            with self.assertRaises(ValueError):
                cache.store('d'*40, {}, {'src/source.py': b'must not restore source'})
