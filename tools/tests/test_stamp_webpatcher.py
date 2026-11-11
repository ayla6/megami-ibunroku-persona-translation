"""The deployed title follows the patch manifest, not the workflow ref."""
from pathlib import Path
import functools
import http.client
import http.server
import sys
import tempfile
import threading
import unittest
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import stamp_webpatcher
import serve_webpatcher


class StampWebpatcher(unittest.TestCase):
    def test_actual_page_embeds_full_notes_under_version_disclosure(self):
        class Page(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack = []
                self.summary = ''
                self.notes = ''
                self.links_in_summary = 0

            def handle_starttag(self, tag, attrs):
                self.stack.append(tag)
                if tag == 'a' and 'summary' in self.stack:
                    self.links_in_summary += 1

            def handle_endtag(self, tag):
                if tag in self.stack:
                    self.stack = self.stack[:len(self.stack) - 1 - self.stack[::-1].index(tag)]

            def handle_data(self, data):
                if 'summary' in self.stack and 'details' in self.stack:
                    self.summary += data
                if 'pre' in self.stack and 'details' in self.stack:
                    self.notes += data

        with tempfile.TemporaryDirectory() as tmp:
            page, manifest = Path(tmp) / 'index.html', Path(tmp) / 'manifest.tsv'
            page.write_text((ROOT / 'webpatcher/index.html').read_text())
            manifest.write_text('patch\trelease\na\tpatches-2026-11-10-3\n')
            stamp_webpatcher.stamp(page, manifest)
            parsed = Page()
            parsed.feed(page.read_text())
            self.assertEqual(parsed.summary, '(beta 2026-11-10-3)')
            self.assertEqual(parsed.notes, (ROOT / 'RELEASE_NOTES.md').read_text())
            self.assertEqual(parsed.links_in_summary, 0)

    def test_stamps_every_placeholder_and_escapes_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / 'index.html'
            manifest = Path(tmp) / 'manifest.tsv'
            notes = Path(tmp) / 'notes.md'
            notes.write_text('# Notes\n<unsafe> & $VERSION\n')
            page.write_text('<title>$VERSION</title><h1>$VERSION</h1><pre>$RELEASE_NOTES</pre>')
            manifest.write_text('patch\trelease\na\tpatches-&test\nb\tpatches-&test\n')
            self.assertEqual(stamp_webpatcher.stamp(page, manifest, notes), 'patches-&test')
            self.assertEqual(page.read_text(),
                             '<title>&amp;test</title><h1>&amp;test</h1>'
                             '<pre># Notes\n&lt;unsafe&gt; &amp; $VERSION\n</pre>')

    def test_display_version_omits_release_tag_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / 'index.html'
            manifest = Path(tmp) / 'manifest.tsv'
            notes = Path(tmp) / 'notes.md'
            notes.write_text('# 2026-11-10-2\n- Text\n')
            page.write_text('<details><summary>(beta $VERSION)</summary><pre>$RELEASE_NOTES</pre></details>')
            manifest.write_text('patch\trelease\na\tpatches-2026-11-10-2\n')
            stamp_webpatcher.stamp(page, manifest, notes)
            self.assertEqual(page.read_text(),
                             '<details><summary>(beta 2026-11-10-2)</summary>'
                             '<pre># 2026-11-10-2\n- Text\n</pre></details>')

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

    def test_missing_notes_or_placeholder_leaves_page_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            page, manifest = Path(tmp) / 'index.html', Path(tmp) / 'manifest.tsv'
            manifest.write_text('patch\trelease\na\tpatches-test\n')
            for template in ('$VERSION', '$VERSION $RELEASE_NOTES'):
                page.write_text(template)
                with self.assertRaises((OSError, ValueError)):
                    stamp_webpatcher.stamp(page, manifest, Path(tmp) / 'missing')
                self.assertEqual(page.read_text(), template)

    def test_local_unstamped_manifest_has_local_version_but_partial_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            page, manifest, notes = (Path(tmp) / name for name in ('index.html', 'manifest.tsv', 'notes.md'))
            page.write_text('$VERSION $RELEASE_NOTES')
            notes.write_text('notes')
            for content in ('patch\na\n', 'patch\trelease\na\t\nb\t\n'):
                manifest.write_text(content)
                self.assertEqual(stamp_webpatcher.render(page, manifest, notes, local=True),
                                 ('local', 'local notes'))
                with self.assertRaises(ValueError):
                    stamp_webpatcher.render(page, manifest, notes)
            manifest.write_text('patch\trelease\na\tpatches-one\nb\t\n')
            with self.assertRaises(ValueError):
                stamp_webpatcher.render(page, manifest, notes, local=True)

    def test_local_server_serves_stamped_page_and_original_static_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = '<details><summary>(beta $VERSION)</summary><pre>$RELEASE_NOTES</pre></details>'
            (root / 'index.html').write_text(template)
            (root / 'manifest.tsv').write_text('patch\trelease\na\tpatches-test\n')
            (root / 'notes.md').write_text('<hello>')
            (root / 'app.js').write_text('static')
            _, page = stamp_webpatcher.render(root / 'index.html', root / 'manifest.tsv', root / 'notes.md', local=True)
            handler = functools.partial(serve_webpatcher.Handler, directory=str(root), page=page.encode())
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
                for path in ('/', '/index.html?test=1'):
                    conn.request('GET', path)
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read().decode(), page)
                conn.request('HEAD', '/')
                response = conn.getresponse()
                self.assertEqual(int(response.getheader('Content-Length')), len(page.encode()))
                self.assertEqual(response.read(), b'')
                conn.request('GET', '/app.js')
                response = conn.getresponse()
                self.assertEqual(response.read(), b'static')
                conn.close()
                self.assertEqual((root / 'index.html').read_text(), template)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()
