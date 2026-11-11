"""Serve the web patcher from this machine, offline, over the tailnet.

  python tools/serve_webpatcher.py                # localhost + tailscale serve
  python tools/serve_webpatcher.py --no-tailscale # localhost only
  python tools/serve_webpatcher.py --patches DIR  # serve that patch set
  python tools/serve_webpatcher.py --port 8137

This is the offline stand-in for the Pages deploy: the same static page,
served from webpatcher/ on this machine, with the patch set and the option
wording it needs put in place first:

- webpatcher/features.js is generated from tools/release_options.json (the
  Pages workflow does this in production; locally it is this script, so an
  edited JSON is testable without pushing).
- webpatcher/patches/ is synced from the given directory (default
  dist/patches, the release build's output) and then verified against its
  own manifest: every row's patch file must exist and match the manifest's
  SHA-256, so the page is served only with a set it can actually apply.

tailscale serve publishes the local server at this node's tailnet URL, so
any device on the tailnet (a phone, a handheld, the console-adjacent
laptop) opens the patcher without a deploy. The serve entry is removed on
Ctrl-C; with --no-tailscale nothing touches tailscale at all.
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
sys.path.insert(0, str(ROOT / 'tools'))
import publish_patches  # noqa: E402  (sync_local_patches + completeness rules)
import stamp_webpatcher  # noqa: E402

SITE = ROOT / 'webpatcher'


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_patches(directory):
    """(ok, problems): the manifest's every row names a present file whose
    SHA-256 matches, and no stray .xdelta hides outside it. The page plans
    its chains from this manifest, so a set that fails here would fail
    mid-apply in the browser."""
    manifest = directory / 'manifest.tsv'
    if not manifest.is_file():
        return False, [f'{manifest} is missing']
    problems, seen = [], set()
    with open(manifest, encoding='utf-8', newline='') as source:
        import csv
        rows = [row for row in csv.DictReader(source, delimiter='\t')
                if row.get('patch')]
    for row in rows:
        name = row['patch']
        seen.add(name)
        path = directory / name
        if not path.is_file():
            problems.append(f'{name}: missing')
            continue
        want = row.get('patch_sha256', '')
        got = sha256(path)
        if want and got != want:
            problems.append(f'{name}: sha256 {got} != manifest {want}')
    stray = sorted(p.name for p in directory.glob('*.xdelta')
                   if p.name not in seen)
    if stray:
        problems.append('not in the manifest: ' + ', '.join(stray))
    if not publish_patches.release_is_complete(directory):
        problems.append(f'incomplete release: {len(rows)} manifest rows, '
                        f'{publish_patches.complete_release_size()} expected'
                        ' - rerun `python tools/build_patches.py`')
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

    def __init__(self, *args, page=None, **kwargs):
        self.page = page
        super().__init__(*args, **kwargs)

    def send_head(self):
        if self.page is not None and urlsplit(self.path).path in ('/', '/index.html'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(self.page)))
            self.end_headers()
            return io.BytesIO(self.page)
        return super().send_head()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_message(self, fmt, *args):
        print(f'webpatcher: {self.address_string()} {fmt % args}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--patches', default=None,
                        help='a complete dist/patches-style set to serve '
                             '(default: dist/patches)')
    parser.add_argument('--no-tailscale', action='store_true',
                        help='serve on localhost only; do not run tailscale serve')
    args = parser.parse_args(argv)

    source = Path(args.patches) if args.patches else publish_patches.DIST
    if not publish_patches.release_is_complete(source):
        raise SystemExit(
            f'{source} does not hold a complete patch set - build it with '
            '`python tools/build_patches.py`, or point --patches at one '
            'that does')
    ok, problems = verify_patches(source)
    if not ok:
        raise SystemExit('the patch set does not match its manifest:\n  '
                         + '\n  '.join(problems))

    # features.js from release_options.json + webpatcher/patches/ synced
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
    handler = functools.partial(Handler, directory=str(SITE), page=page.encode('utf-8'))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    url = f'http://127.0.0.1:{args.port}'
    print(f'webpatcher: serving {SITE.name}/ at {url} '
          f'({len(list(local.glob("*.xdelta")))} patches, '
          f'options from tools/release_options.json, version {release})')
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
