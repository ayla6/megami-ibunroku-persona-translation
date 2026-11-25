"""Patcher server -> worker.mjs (one Node process) -> SQLite -> dashboard report."""
from __future__ import annotations

import functools
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve_webpatcher
from collector_local import EVENT_PATH, LocalCollector, configure_page
from dashboard import Settings, handler_for, queries, read_report


def serve(handler: object) -> tuple[ThreadingHTTPServer, HTTPConnection]:
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, HTTPConnection('127.0.0.1', server.server_port)


class LocalTests(unittest.TestCase):
    def test_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'events.sqlite'
            collector = LocalCollector.open(database)
            page = configure_page((serve_webpatcher.SITE / 'index.html').read_text())
            server, client = serve(functools.partial(serve_webpatcher.Handler,
                directory=str(serve_webpatcher.SITE), page=page.encode(), analytics=collector))

            def post(data: object, origin: str | None = None) -> int:
                headers = {'Content-Type': 'text/plain'} | ({'Origin': origin} if origin else {})
                client.request('POST', EVENT_PATH, json.dumps(data), headers)
                response = client.getresponse()
                response.read()
                return response.status
            try:
                browser, visit = str(uuid4()), str(uuid4())
                self.assertEqual(post({'t': 'visit', 'b': browser, 'v': visit, 'r': 'https://r.example/x?y'}), 204)
                build = {'t': 'build', 'b': browser, 'v': visit, 'id': str(uuid4()), 'rel': '2026-11-25',
                         'prev': '2026-11-24', 'out': 'ppf', 'src': 'bin', 'dir': True,
                         'mods': {'one': 'speed=2', 'two': ''}, 'was': {'one': 'speed=1'}}
                self.assertEqual(post(build), 204)
                self.assertEqual(post(build), 204)  # resend is deduplicated
                self.assertEqual(post(build, 'https://other.example'), 403)
                self.assertEqual(post({'t': 'nope'}), 400)
                settings = Settings(database, False, 'local')
                report = read_report(settings, '2000-01-01', '2099-01-01')
                self.assertEqual(report['totals'][0], dict(visits=1, visitors=1, build_visits=1, builders=1, builds=1))
                self.assertEqual(report['referrers'][0]['referrer'], 'https://r.example')
                self.assertEqual({(r['mod'], r['change']) for r in report['changes']},
                                 {('one', 'changed'), ('two', 'added')})
                self.assertEqual(len(report['pairs']), 4)
                self.assertEqual(Path(str(database) + '.key').stat().st_mode & 0o777, 0o600)
                with self.assertRaises(ValueError):
                    queries("2000-01-01' OR 1=1", '2026-01-01')
                dash, dash_client = serve(handler_for(settings))
                dash_client.request('GET', '/api/report', headers={'Host': 'evil.example'})
                self.assertEqual(dash_client.getresponse().status, 403)
                dash.shutdown()
            finally:
                client.close()
                server.shutdown()
                collector.close()


if __name__ == '__main__':
    unittest.main()
