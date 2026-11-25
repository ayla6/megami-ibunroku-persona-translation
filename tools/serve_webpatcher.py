"""Serve the web patcher from this machine, offline, over the tailnet.

  python tools/serve_webpatcher.py                # localhost + tailscale serve
  python tools/serve_webpatcher.py --no-tailscale # localhost only
  python tools/serve_webpatcher.py --patches DIR  # serve that patch set
  python tools/serve_webpatcher.py --port 8137
  python tools/serve_webpatcher.py --debug        # with the debug log
  python tools/serve_webpatcher.py --analytics    # usage events to local SQLite

This is the offline stand-in for the Pages deploy: the same static page,
served from webpatcher/ on this machine, with the patch set and the option
wording it needs put in place first:

- webpatcher/features.js is generated from the mods' src/mods/*/mod.tsv (the
  Pages workflow does this in production; locally it is this script, so an
  edited JSON is testable without pushing).
- webpatcher/patches/ is synced from the given directory (default
  dist/patches, the release build's output) and then verified against its
  own manifest: every row's patch file must exist and match the manifest's
  SHA-1, so the page is served only with a set it can actually apply. A
  release still `building` or `testing` (the manifest's state column) is
  served as it stands - that is what local serving is for - and the page says
  it is not a finished release; only a `verified` one is ever published.

tailscale serve publishes the local server at this node's tailnet URL, so
any device on the tailnet (a phone, a handheld, the console-adjacent
laptop) opens the patcher without a deploy. The serve entry is removed on
Ctrl-C; with --no-tailscale nothing touches tailscale at all.

--debug loads tools/webpatcher_debug.js into the page and into every patch
worker (worker.js, chdblocks.js): a log panel at the bottom of the page,
mirrored to build/webpatcher-debug.log on this machine, so a device without
dev tools can still show what its workers did. The Pages site never has it.
"""
import argparse
import contextlib
import functools
import hashlib
import http.server
import io
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import publish_patches  # noqa: E402  (sync_local_patches + completeness rules)
import stamp_webpatcher  # noqa: E402

sys.path.insert(0, str(ROOT / 'tools' / 'patcher-analytics'))
from collector_local import LocalCollector, DEFAULT_DATABASE, EVENT_PATH, MAX_EVENT_BYTES, configure_page


SITE = ROOT / 'webpatcher'
DEBUG_SCRIPT = ROOT / 'tools' / 'webpatcher_debug.js'
DEBUG_LOG = ROOT / 'build' / 'webpatcher-debug.log'
# the debug script runs last in these workers, after their own imports
DEBUG_WORKERS = ('/worker.js', '/chdblocks.js')


def sha1(path):
    digest = hashlib.sha1()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_patches(directory):
    """(ok, problems): the manifest's every row names a present layer whose
    SHA-1 matches, and no stray .p1mod hides outside it. The page plans
    its selections from this manifest, so a set that fails here would fail
    mid-apply in the browser. A release still building or testing is served
    as it stands (local serving is for trying it): only publishing needs a
    finished, verified one."""
    manifest = directory / 'manifest.tsv'
    if not manifest.is_file():
        return False, [f'{manifest} is missing']
    problems, seen = [], set()
    with open(manifest, encoding='utf-8', newline='') as source:
        import csv
        rows = [row for row in csv.DictReader(source, delimiter='\t')
                if row.get('layer')]
    for row in rows:
        name = row['layer']
        seen.add(name)
        path = directory / name
        if not path.is_file():
            problems.append(f'{name}: missing')
            continue
        want = row.get('sha1', '')
        got = sha1(path)
        if want and got != want:
            problems.append(f'{name}: sha1 {got} != manifest {want}')
    stray = sorted(p.name for p in directory.glob('*.p1mod')
                   if p.name not in seen)
    if stray:
        problems.append('not in the manifest: ' + ', '.join(stray))
    states = sorted({row.get('state') or 'unknown' for row in rows})
    if states != ['verified']:
        print(f'serve_webpatcher: serving a release that is {"/".join(states)}:'
              f' {len(rows)} of {publish_patches.complete_release_size()} layers,'
              ' not published until the release build verifies it', flush=True)
    return not problems, problems


def tailscale_publish(port):
    """The tailnet URL tailscale serve answers on, or None."""
    if not shutil.which('tailscale'):
        print('serve_webpatcher: no tailscale on PATH - serving on localhost'
              ' only')
        return None
    subprocess.run(['tailscale', 'serve', '--bg',
                    f'http://127.0.0.1:{port}'],
                   check=True, capture_output=True, text=True)
    status = subprocess.run(['tailscale', 'serve', 'status', '--json'],
                            check=True, capture_output=True, text=True)
    out = status.stdout
    # The URL is this node's tailnet name; serve status echoes it, but the
    # node name is cheaper and stable: `morgana.tailnet.ts.net`.
    who = subprocess.run(['tailscale', 'status', '--json'],
                         check=True, capture_output=True, text=True).stdout
    import json
    name = json.loads(who).get('Self', {}).get('DNSName', '').rstrip('.')
    return f'https://{name}' if name else None


def tailscale_withdraw():
    for off in (['tailscale', 'serve', 'reset'],
                ['tailscale', 'serve', '--https=443', 'off']):
        try:
            subprocess.run(off, capture_output=True, text=True, check=False)
            return
        except FileNotFoundError:
            return


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serves webpatcher/ with no caching (a re-test must never see a
    stale manifest) and the one MIME map entry Python < 3.13 lacks."""

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        '.wasm': 'application/wasm',
        '.js': 'text/javascript',
    }

    def __init__(self, *args, page=None, debug=False, analytics: LocalCollector | None = None, **kwargs):
        self.page = page
        self.debug = debug
        self.analytics = analytics
        super().__init__(*args, **kwargs)

    def send_bytes(self, body, content_type):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        return io.BytesIO(body)

    def send_head(self):
        path = urlsplit(self.path).path
        if self.page is not None and path in ('/', '/index.html'):
            return self.send_bytes(self.page, 'text/html; charset=utf-8')
        if self.debug and path == '/debug.js':
            return self.send_bytes(DEBUG_SCRIPT.read_bytes(), 'text/javascript')
        if self.debug and path in DEBUG_WORKERS:
            body = ((SITE / path.lstrip('/')).read_bytes()
                    + b"\nimportScripts('debug.js');\n")
            return self.send_bytes(body, 'text/javascript')
        return super().send_head()

    def do_POST(self):
        if self.analytics and urlsplit(self.path).path == EVENT_PATH:
            origin = self.headers.get('Origin')
            if (origin and urlsplit(origin).netloc != self.headers.get('Host')) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                status = 403
            elif not self.headers.get('Content-Type', '').startswith('text/plain'):
                status = 415
            else:
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    length = 0
                if length <= 0:
                    status = 411
                elif length > MAX_EVENT_BYTES:
                    status = 413
                else:
                    self.connection.settimeout(10)
                    status = self.analytics.ingest(self.rfile.read(length))
            self.send_response(status)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if not (self.debug and urlsplit(self.path).path == '/__debug/log'):
            self.send_error(404)
            return
        text = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        text = text.decode('utf-8', 'replace')
        with open(DEBUG_LOG, 'a', encoding='utf-8') as out:
            out.write(text)
        for line in text.splitlines():
            print(f'debug: {line}')
        self.send_response(204)
        self.end_headers()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_message(self, fmt, *args):
        if urlsplit(self.path).path == EVENT_PATH:
            return  # Do not log addresses or event payloads.
        print(f'webpatcher: {self.address_string()} {fmt % args}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--patches', default=None,
                        help='a complete dist/patches-style set to serve '
                             '(default: dist/patches)')
    parser.add_argument('--no-tailscale', action='store_true',
                        help='serve on localhost only; do not run tailscale serve')
    parser.add_argument('--debug', action='store_true',
                        help='add the debug log panel, mirrored to '
                             'build/webpatcher-debug.log')
    parser.add_argument('--analytics', nargs='?', type=Path, const=DEFAULT_DATABASE,
                        metavar='DATABASE', help='record usage events to this SQLite (default build/patcher-analytics.sqlite)')
    args = parser.parse_args(argv)

    source = Path(args.patches) if args.patches else publish_patches.DIST
    # any state the release build left it in is served (it says which);
    # what must hold is that the set matches its own manifest
    ok, problems = verify_patches(source)
    if not ok:
        raise SystemExit('the patch set does not match its manifest:\n  '
                         + '\n  '.join(problems))

    # features.js from the mods' mod.tsv + webpatcher/patches/ synced
    # (publish_patches owns both rules; local serving is its --no-release
    # path without the upload).
    publish_patches.sync_local_patches(source)
    local = SITE / 'patches'
    if local.resolve() != source.resolve():
        ok, problems = verify_patches(local)
        if not ok:
            raise SystemExit('the synced copy does not match its manifest:\n  '
                             + '\n  '.join(problems))

    try:
        release, page = stamp_webpatcher.render(SITE / 'index.html',
                                                local / 'manifest.tsv', local=True)
    except (OSError, ValueError) as error:
        raise SystemExit(f'web patcher version: {error}') from error
    if args.debug:
        tag = '<script src="app.js"></script>'
        if tag not in page:
            raise SystemExit(f'web patcher page has no {tag} to load the debug log before')
        page = page.replace(tag, '<script src="debug.js"></script>\n' + tag)
        DEBUG_LOG.parent.mkdir(exist_ok=True)
        with open(DEBUG_LOG, 'a', encoding='utf-8') as out:
            out.write(f'--- serve_webpatcher --debug {time.strftime("%Y-%m-%d %H:%M:%S")}\n')
    analytics = LocalCollector.open(args.analytics) if args.analytics is not None else None
    if analytics:
        page = configure_page(page)
        print(f'webpatcher: analytics to {analytics.database}')
    handler = functools.partial(Handler, directory=str(SITE), page=page.encode('utf-8'),
                                debug=args.debug, analytics=analytics)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    url = f'http://127.0.0.1:{args.port}'
    print(f'webpatcher: serving {SITE.name}/ at {url} '
          f'({len(list(local.glob("*.p1mod")))} layers, '
          f'mods from src/mods, version {release})')
    if args.debug:
        print(f'webpatcher: debug log on the page and in {DEBUG_LOG.relative_to(ROOT)}')
    published = None if args.no_tailscale else tailscale_publish(args.port)
    if published:
        print(f'webpatcher: tailnet URL {published} (Ctrl-C withdraws it)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if published:
            tailscale_withdraw()
            print('webpatcher: tailscale serve entry removed')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
