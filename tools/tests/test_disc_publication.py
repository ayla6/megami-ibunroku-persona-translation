"""Publishing a new disc must not mutate an already-open image."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import build_disc


class DiscPublication(unittest.TestCase):
    def test_replacement_keeps_old_open_image_and_publishes_complete_new_image(self):
        with TemporaryDirectory() as d:
            root = Path(d); src = root / 'source.bin'; dst = root / 'Persona-TL.bin'
            src.write_bytes(b'source'); dst.write_bytes(b'old-image')
            def construct(source, target, build, placement=None):
                self.assertEqual(Path(source), src)
                self.assertNotEqual(Path(target), dst)
                self.assertIsNone(placement)
                self.assertEqual(dst.read_bytes(), b'old-image')
                Path(target).write_bytes(b'complete-new-image')
                return 1, 42
            with dst.open('rb') as existing, patch.object(build_disc, 'build_to', side_effect=construct), \
                 patch.object(sys, 'argv', ['build_disc.py', str(src), str(dst), 'build']):
                build_disc.main()
                self.assertEqual(existing.read(), b'old-image')
            self.assertEqual(dst.read_bytes(), b'complete-new-image')
            self.assertIn('FILE "Persona-TL.bin" BINARY', (root / 'Persona-TL.cue').read_text())
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             ['Persona-TL.bin', 'Persona-TL.cue', 'source.bin'])

    def test_failed_construction_leaves_old_disc_and_cue_untouched(self):
        with TemporaryDirectory() as d:
            root = Path(d); src = root / 'source.bin'; dst = root / 'Persona-TL.bin'
            cue = root / 'Persona-TL.cue'
            src.write_bytes(b'source'); dst.write_bytes(b'old-image'); cue.write_text('old-cue')
            def fail(source, target, build, placement=None):
                Path(target).write_bytes(b'incomplete')
                raise RuntimeError('forced builder failure')
            with patch.object(build_disc, 'build_to', side_effect=fail), \
                 patch.object(sys, 'argv', ['build_disc.py', str(src), str(dst), 'build']):
                with self.assertRaisesRegex(RuntimeError, 'forced builder failure'):
                    build_disc.main()
            self.assertEqual(dst.read_bytes(), b'old-image')
            self.assertEqual(cue.read_text(), 'old-cue')
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             ['Persona-TL.bin', 'Persona-TL.cue', 'source.bin'])

    def test_placement_record_is_published_with_the_image(self):
        with TemporaryDirectory() as d:
            root = Path(d); src = root / 'source.bin'; dst = root / 'Persona-TL.bin'
            record = root / 'Persona-TL.bin.placement.tsv'
            src.write_bytes(b'source')
            def construct(source, target, build, placement=None):
                self.assertTrue(placement.endswith('.placement.tsv'))
                Path(target).write_bytes(b'complete-new-image')
                Path(placement).write_text('path\textent\tsize\tsha256\n',
                                           encoding='utf-8', newline='\n')
                return 1, 42
            with patch.object(build_disc, 'build_to', side_effect=construct), \
                 patch.object(sys, 'argv', ['build_disc.py', str(src), str(dst), 'build',
                                            str(record)]):
                build_disc.main()
            self.assertEqual(record.read_text(), 'path\textent\tsize\tsha256\n')
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             ['Persona-TL.bin', 'Persona-TL.bin.placement.tsv',
                              'Persona-TL.cue', 'source.bin'])

    def test_failed_construction_publishes_no_placement_record(self):
        with TemporaryDirectory() as d:
            root = Path(d); src = root / 'source.bin'; dst = root / 'Persona-TL.bin'
            record = root / 'Persona-TL.bin.placement.tsv'
            src.write_bytes(b'source')
            def fail(source, target, build, placement=None):
                Path(placement).write_text('partial\n')
                raise RuntimeError('forced builder failure')
            with patch.object(build_disc, 'build_to', side_effect=fail), \
                 patch.object(sys, 'argv', ['build_disc.py', str(src), str(dst), 'build',
                                            str(record)]):
                with self.assertRaisesRegex(RuntimeError, 'forced builder failure'):
                    build_disc.main()
            self.assertFalse(record.exists())
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             ['source.bin'])


if __name__ == '__main__':
    unittest.main()
