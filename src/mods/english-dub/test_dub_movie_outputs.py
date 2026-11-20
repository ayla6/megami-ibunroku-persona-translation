"""Reusing cached movie outputs must retain bytes and reject changed outputs."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import toolpath
import fmv_dub


class MovieOutputs(unittest.TestCase):
    def test_retains_identical_movies_repairs_tampering_and_removes_dropped_movies(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'cached.STR'
            source.write_bytes(b'cached movie')
            dest = root / 'build/STR1/A.STR'
            dest.parent.mkdir(parents=True)
            dest.write_bytes(source.read_bytes())
            dropped = dest.with_name('B.STR')
            dropped.write_bytes(b'old dub')
            stamp = dest.stat()
            index = {'A': ('STR1/A.STR', 0, 1), 'B': ('STR1/B.STR', 1, 1)}
            with patch.object(fmv_dub, 'BUILD', str(root/'build')), \
                    patch.object(fmv_dub.disc_data, 'resolve_psx', return_value='source'), \
                    patch.object(fmv_dub, 'str_index', return_value=index), \
                    patch.object(fmv_dub, 'read_map', return_value={'A': ('track', [])}), \
                    patch.object(fmv_dub, 'copies', return_value=[]), \
                    patch.object(fmv_dub, 'psp_track'), \
                    patch.object(fmv_dub, 'retail_sha1', return_value='digest'), \
                    patch.object(fmv_dub, 'movie_key', return_value='key'), \
                    patch.object(fmv_dub, 'cached', return_value=(str(source), 'cached')):
                fmv_dub.build()
                self.assertEqual(dest.stat().st_ino, stamp.st_ino)
                self.assertEqual(dest.stat().st_mtime_ns, stamp.st_mtime_ns)
                self.assertFalse(dropped.exists())
                dest.write_bytes(b'tampered dub')
                fmv_dub.build()
                self.assertEqual(dest.read_bytes(), source.read_bytes())


class MovieTwins(unittest.TestCase):
    def test_reuses_twin_map_and_rediscovers_changed_image(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / 'retail.bin'
            image.write_bytes(b'retail identity')
            a = bytes(16) + b'A' * (2352 - 16)
            twin = b'header differs!!' + a[16:]
            other = bytes(16) + b'B' * (2352 - 16)
            index = {'A': ('STR/A.STR', 0, 1), 'B': ('STR/B.STR', 1, 1),
                     'C': ('STR/C.STR', 2, 1), 'D': ('STR/D.STR', 3, 2)}
            raw = {0: a, 1: twin, 2: other}
            fmv_dub._copy_map.cache_clear()
            with patch.object(fmv_dub, 'CACHE', str(root/'cache')), patch.object(
                    fmv_dub, 'str_sectors', side_effect=lambda image, lba, count: raw[lba]) as read:
                self.assertEqual(fmv_dub.copies(str(image), index, 'A'), ['STR/B.STR'])
                self.assertEqual(fmv_dub.copies(str(image), index, 'B'), ['STR/A.STR'])
                self.assertEqual(fmv_dub.copies(str(image), index, 'C'), [])
                self.assertEqual(read.call_count, 3)
                # A fresh process reuses the verified disk map too.
                fmv_dub._copy_map.cache_clear()
                self.assertEqual(fmv_dub.copies(str(image), index, 'A'), ['STR/B.STR'])
                self.assertEqual(read.call_count, 3)
                image.write_bytes(b'changed identity')
                raw[1] = other
                self.assertEqual(fmv_dub.copies(str(image), index, 'A'), [])
                self.assertEqual(read.call_count, 6)
            fmv_dub._copy_map.cache_clear()
