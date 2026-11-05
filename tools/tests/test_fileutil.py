"""Disc image copies: share extents where possible, stay correct where not."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import fileutil


class CloneFileTest(unittest.TestCase):

    def test_copy_preserves_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 'src.bin', Path(tmp) / 'dst.bin'
            payload = b'persona' * 100000
            src.write_bytes(payload)
            fileutil.clone_file(src, dst)
            self.assertEqual(dst.read_bytes(), payload)

    def test_reflink_preserves_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 'src.bin', Path(tmp) / 'dst.bin'
            payload = b'reflink' * 100000
            src.write_bytes(payload)
            if not fileutil.reflink(src, dst):
                self.skipTest('filesystem does not support reflink')
            self.assertEqual(dst.read_bytes(), payload)

    def test_unsupported_reflink_falls_back_to_a_byte_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 'src.bin', Path(tmp) / 'dst.bin'
            src.write_bytes(b'source')
            with patch.object(fileutil, 'reflink', return_value=False), \
                    patch.object(fileutil.shutil, 'copyfile') as copy:
                fileutil.clone_file(src, dst)
            copy.assert_called_once_with(src, dst)

    def test_supported_reflink_is_not_followed_by_a_byte_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 'src.bin', Path(tmp) / 'dst.bin'
            src.write_bytes(b'source')
            with patch.object(fileutil, 'reflink', return_value=True), \
                    patch.object(fileutil.shutil, 'copyfile') as copy:
                fileutil.clone_file(src, dst)
            copy.assert_not_called()


if __name__ == '__main__':
    unittest.main()
