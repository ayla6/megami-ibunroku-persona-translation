"""xdelta downloads are platform-specific, verified and safely installed."""
import hashlib
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import setup_external_tools as setup


def tar_asset(name='folder/xdelta3', content=b'executable'):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        item = tarfile.TarInfo(name)
        item.size = len(content)
        archive.addfile(item, io.BytesIO(content))
    return buffer.getvalue()


class XdeltaSetup(unittest.TestCase):
    def test_supported_platforms_and_architecture_aliases(self):
        for system, machine, suffix in (
                ('linux', 'x86_64', 'linux-x86_64.tar.gz'),
                ('linux', 'aarch64', 'linux-arm64.tar.gz'),
                ('darwin', 'arm64', 'macos-arm64.tar.gz'),
                ('darwin', 'x86_64', 'macos-x86_64.tar.gz'),
                ('win32', 'AMD64', 'windows-x86_64.zip'),
                ('win32', 'ARM64', 'windows-arm64.zip'),
                ('win32', 'i686', 'windows-x86.zip')):
            with self.subTest(system=system, machine=machine):
                asset, checksum = setup.xdelta_asset(system, machine)
                self.assertTrue(asset.endswith(suffix))
                self.assertEqual(len(checksum), 64)
        with self.assertRaisesRegex(RuntimeError, 'no xdelta3'):
            setup.xdelta_asset('linux', 'riscv64')

    def test_install_and_refuse_bad_checksum_without_overwriting(self):
        asset = tar_asset()
        checksum = hashlib.sha256(asset).hexdigest()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(setup, 'EXTERNAL', Path(tmp)), \
                patch.object(setup, 'xdelta_asset', return_value=('x.tar.gz', checksum)), \
                patch.object(setup, 'fetch', return_value=asset) as fetch:
            setup.install_xdelta3()
            target = Path(tmp) / 'xdelta3/xdelta3'
            self.assertEqual(target.read_bytes(), b'executable')
            self.assertTrue(target.stat().st_mode & 0o111)
            setup.install_xdelta3()
            self.assertEqual(fetch.call_count, 1)
            with patch.object(setup, 'fetch', return_value=b'bad'):
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    setup.install_xdelta3(force=True)
            self.assertEqual(target.read_bytes(), b'executable')

    def test_zip_executable_is_extracted_without_archive_paths(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('../nested/xdelta3.exe', b'windows executable')
        data = buffer.getvalue()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(setup, 'EXTERNAL', Path(tmp)), \
                patch.object(setup.sys, 'platform', 'win32'), \
                patch.object(setup, 'xdelta_asset', return_value=('x.zip', hashlib.sha256(data).hexdigest())), \
                patch.object(setup, 'fetch', return_value=data):
            setup.install_xdelta3()
            self.assertEqual((Path(tmp) / 'xdelta3/xdelta3.exe').read_bytes(), b'windows executable')
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['xdelta3'])

    def test_archive_without_unique_executable_fails(self):
        asset = tar_asset('other')
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(setup, 'EXTERNAL', Path(tmp)), \
                patch.object(setup, 'xdelta_asset', return_value=('x.tar.gz', hashlib.sha256(asset).hexdigest())), \
                patch.object(setup, 'fetch', return_value=asset):
            with self.assertRaisesRegex(RuntimeError, 'exactly one'):
                setup.install_xdelta3()
            self.assertFalse((Path(tmp) / 'xdelta3').exists())


if __name__ == '__main__':
    unittest.main()
