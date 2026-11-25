#!/usr/bin/env python3
"""Loopback-only analytics viewer over local SQLite or Cloudflare D1 (via Wrangler)."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from typing import Final
from urllib.parse import parse_qs, urlsplit

from collector_local import DEFAULT_DATABASE, create_schema

HERE: Final = Path(__file__).resolve().parent
WRANGLER: Final = ['npx', '--no-install', 'wrangler@4.168.0', 'd1', 'execute',
                   'persona-patcher-analytics', '--remote', '--json', '--command']

# {period} is replaced by the date-bounded visits CTE; b = builds in those visits.
REPORT: Final = {
    'totals': """SELECT count(*) visits, count(DISTINCT visitor) visitors,
      (SELECT count(DISTINCT visit) FROM b) build_visits,
      (SELECT count(DISTINCT visitor) FROM b) builders,
      (SELECT count(*) FROM b) builds FROM v""",
    'daily': """SELECT v.day, count(*) visits, count(DISTINCT v.visitor) visitors,
      count(DISTINCT b.visit) build_visits, count(DISTINCT b.visitor) builders
      FROM v LEFT JOIN (SELECT DISTINCT visit, visitor FROM b) b USING (visit)
      GROUP BY v.day ORDER BY v.day""",
    'releases': """SELECT release, output, count(*) builds FROM b
      GROUP BY release, output ORDER BY release DESC""",
    'updates': """SELECT previous, release, count(*) builds FROM b WHERE previous <> ''
      GROUP BY previous, release ORDER BY builds DESC""",
    'setup': """SELECT output, source, folder, count(*) builds FROM b
      GROUP BY output, source, folder ORDER BY builds DESC""",
    'options': """SELECT m.mod, m.options, count(*) builds FROM b JOIN build_mods m USING (build)
      WHERE m.options IS NOT NULL GROUP BY m.mod, m.options ORDER BY builds DESC""",
    'pairs': """SELECT x.mod a, y.mod b, count(*) builds FROM b
      JOIN build_mods x USING (build) JOIN build_mods y USING (build)
      WHERE x.options IS NOT NULL AND y.options IS NOT NULL GROUP BY x.mod, y.mod""",
    'changes': """SELECT m.mod, CASE WHEN m.was IS NULL THEN 'added' WHEN m.options IS NULL
      THEN 'removed' ELSE 'changed' END change, count(*) builds
      FROM b JOIN build_mods m USING (build)
      WHERE b.known AND m.options IS NOT m.was GROUP BY m.mod, change""",
    'referrers': """SELECT referrer, count(*) visits, count(DISTINCT visitor) visitors,
      count(DISTINCT b.visit) build_visits
      FROM v LEFT JOIN (SELECT DISTINCT visit FROM b) b USING (visit)
      GROUP BY referrer ORDER BY visits DESC""",
}


@dataclass(frozen=True)
class Settings:
    database: Path
    remote: bool
    label: str


def queries(start: str, end: str) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)  # validates before SQL
    if first > last:
        raise ValueError('Start is after end.')
    period = (f"WITH v AS (SELECT * FROM visits WHERE day BETWEEN '{first}' AND '{last}'), "
              "b AS (SELECT builds.*, v.visitor FROM builds JOIN v USING (visit)) ")
    return [period + sql for sql in REPORT.values()]


def read_report(settings: Settings, start: str, end: str) -> dict[str, object]:
    sql = queries(start, end)
    if settings.remote:
        result = subprocess.run(WRANGLER + [';\n'.join(sql)], cwd=HERE, capture_output=True,
                                text=True, timeout=60, check=False)
        if result.returncode:
            raise RuntimeError('Wrangler query failed (login / database_id in wrangler.toml).')
        try:
            batches = json.loads(result.stdout)
            if len(batches) != len(sql) or not all(item.get('success') for item in batches):
                raise ValueError
            rows = [item['results'] for item in batches]
        except (ValueError, KeyError, TypeError) as error:
            raise RuntimeError('Unexpected Wrangler output.') from error
    else:
        with sqlite3.connect(settings.database) as connection:
            connection.row_factory = sqlite3.Row
            rows = [[dict(row) for row in connection.execute(query)] for query in sql]
    return dict(zip(REPORT, rows)) | {'source': settings.label, 'start': start, 'end': end}


def seed_demo(database: Path) -> None:
    """Synthetic placeholder labels only (demo-mod-N), never real mod names."""
    import random
    rng = random.Random(1)
    mods = [f'demo-mod-{n}' for n in range(1, 11)]
    releases = ['2026-11-20', '2026-11-22', '2026-11-25']
    with sqlite3.connect(database) as connection:
        n = 0
        for offset in range(30):
            day = (date.today() - timedelta(days=29 - offset)).isoformat()
            for _ in range(rng.randint(10, 40)):
                n += 1
                visitor = f'u{rng.randint(1, 400)}'
                visit = f'v{n}'
                connection.execute('INSERT INTO visits VALUES (?,?,?,?)', (visit, visitor, day,
                                   rng.choice(['', '', 'https://forum.example', 'https://chat.example'])))
                if rng.random() < .45:
                    release = releases[min(2, offset // 10 + (rng.random() < .3))]
                    previous = rng.choice(['', '', releases[0]]) if release != releases[0] else ''
                    known = int(bool(previous))
                    connection.execute('INSERT INTO builds VALUES (?,?,?,?,?,?,?,?)', (
                        visit, visit, release, previous, rng.choice(['ppf', 'ppf', 'disc']),
                        rng.choice(['bin', 'bin', 'chd']), int(rng.random() < .3), known))
                    for i, mod in enumerate(mods):
                        on = rng.random() < 0.9 - i * 0.08
                        was = rng.random() < 0.9 - i * 0.08 if known else False
                        options = f'speed={rng.randint(1, 3)}' if i % 3 == 0 else ''
                        if on or was:
                            connection.execute('INSERT INTO build_mods VALUES (?,?,?,?)', (
                                visit, mod, options if on else None,
                                (f'speed={rng.randint(1, 3)}' if i % 3 == 0 else '') if was else None))


def handler_for(settings: Settings) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline';"
                             " style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            # Loopback + Host/Origin checks: no DNS-rebinding access to the D1 credentials.
            port = self.server.server_address[1]
            hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
            origin = self.headers.get('Origin')
            if (self.headers.get('Host') not in hosts or (origin and urlsplit(origin).netloc not in hosts)
                    or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                self.reply(403, b'Forbidden', 'text/plain')
                return
            url = urlsplit(self.path)
            if url.path == '/':
                self.reply(200, (HERE / 'dashboard.html').read_bytes(), 'text/html; charset=utf-8')
            elif url.path == '/api/report':
                args = parse_qs(url.query)
                try:
                    data = read_report(settings, args.get('start', ['2000-01-01'])[0],
                                       args.get('end', [date.today().isoformat()])[0])
                    self.reply(200, json.dumps(data).encode(), 'application/json')
                except ValueError as error:
                    self.reply(400, json.dumps({'error': str(error)}).encode(), 'application/json')
                except (RuntimeError, sqlite3.Error, subprocess.TimeoutExpired) as error:
                    message = str(error) if isinstance(error, RuntimeError) else 'Database error.'
                    self.reply(502, json.dumps({'error': message}).encode(), 'application/json')
            else:
                self.reply(404, b'Not found', 'text/plain')

        def log_message(self, format: str, *args: object) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--local', action='store_true', help='read a local SQLite instead of Cloudflare D1')
    mode.add_argument('--demo', action='store_true', help='synthetic throwaway data')
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE, help='SQLite for --local')
    parser.add_argument('--port', type=int, default=8790)
    args = parser.parse_args()
    args.remote = not (args.local or args.demo)
    with tempfile.TemporaryDirectory(prefix='patcher-analytics-') as temporary:
        database = Path(temporary) / 'demo.sqlite' if args.demo else args.database
        if not args.remote:
            create_schema(database)
            if args.demo:
                seed_demo(database)
        label = 'demo' if args.demo else 'D1' if args.remote else 'local'
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(Settings(database, args.remote, label)))
        print(f'analytics: http://127.0.0.1:{server.server_port} ({label})', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
