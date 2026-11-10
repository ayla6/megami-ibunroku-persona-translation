"""The deployed title follows the patch manifest, not the workflow ref."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import stamp_webpatcher


class StampWebpatcher(unittest.TestCase):
    def test_stamps_every_placeholder_and_escapes_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / 'index.html'
            manifest = Path(tmp) / 'manifest.tsv'
            page.write_text('<title>$VERSION</title><h1>$VERSION</h1>')
            manifest.write_text('patch\trelease\na\tpatches-&test\nb\tpatches-&test\n')
            self.assertEqual(stamp_webpatcher.stamp(page, manifest), 'patches-&test')
            self.assertEqual(page.read_text(),
                             '<title>&amp;test</title><h1>&amp;test</h1>')

    def test_display_version_omits_release_tag_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / 'index.html'
            manifest = Path(tmp) / 'manifest.tsv'
            page.write_text('<h1>Persona 1 Translation Patcher (beta $VERSION)</h1>')
            manifest.write_text('patch\trelease\na\tpatches-2026-11-10-2\n')
            stamp_webpatcher.stamp(page, manifest)
            self.assertEqual(page.read_text(),
                             '<h1>Persona 1 Translation Patcher (beta 2026-11-10-2)</h1>')

    def test_rejects_missing_or_inconsistent_release_without_writing(self):
        for content in ('patch\na\n', 'patch\trelease\na\t\n',
                        'patch\trelease\na\tv1\nb\tv2\n'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                page = Path(tmp) / 'index.html'
                manifest = Path(tmp) / 'manifest.tsv'
                page.write_text('$VERSION')
                manifest.write_text(content)
                with self.assertRaises(ValueError):
                    stamp_webpatcher.stamp(page, manifest)
                self.assertEqual(page.read_text(), '$VERSION')


if __name__ == '__main__':
    unittest.main()
