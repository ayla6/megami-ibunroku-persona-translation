"""The RAM workspace must preserve byte results, unchanged files and rollback."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import toolpath  # noqa: E402,F401
import armips_products as products


@unittest.skipUnless(products.RAM.is_dir(), 'requires a RAM filesystem')
class ArmipsProducts(unittest.TestCase):
    def test_real_assembler_changed_unchanged_and_listing_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build = root / 'build'
            build.mkdir()
            original = root / 'original.bin'
            original.write_bytes(bytes(32))
            target = build / 'out.bin'
            target.write_bytes(bytes(32))
            source, listing = root / 'main.asm', build / 'main.lst'

            plan = products.AssemblyProducts((target,), 64, ('OUT',))
            for repeat in range(2):
                before = target.stat()
                with products.memory_outputs(plan, build) as outputs:
                    staged = Path(outputs['OUT'])
                    source.write_text(f'.psx\n.open "{original}", "{staged}", 0x80000000\n'
                                      '.org 0x80000004\n.byte 0x12, 0x34\n.close\n')
                    subprocess.run([str(ROOT / 'external_tools/armips/armips'),
                                    '-erroronwarning', str(source), '-temp', str(listing)],
                                   check=True, capture_output=True)
                    self.assertTrue(staged.resolve().is_relative_to(products.RAM))
                    self.assertEqual(target.read_bytes(), (bytes(32) if not repeat else
                                     bytes(4) + b'\x12\x34' + bytes(26)))
                self.assertEqual(staged.resolve(), target)
                self.assertFalse(target.is_symlink())
                self.assertEqual(target.read_bytes(), bytes(4) + b'\x12\x34' + bytes(26))
                self.assertIn(str(staged), listing.read_text())
                if repeat:
                    self.assertEqual(target.stat().st_ino, before.st_ino)
                    self.assertEqual(target.stat().st_mtime_ns, before.st_mtime_ns)
            before = target.read_bytes()
            new = build / 'new.bin'
            plan = products.AssemblyProducts((target, new), 128)
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                with products.memory_outputs(plan, build) as outputs:
                    Path(outputs['0']).write_bytes(b'partial')
                    Path(outputs['1']).write_bytes(b'partial')
                    raise RuntimeError('failed')
            self.assertEqual(target.read_bytes(), before)
            self.assertFalse(target.is_symlink())
            self.assertFalse(new.exists())
            self.assertFalse(list(build.glob('.armips-previous-*')))
