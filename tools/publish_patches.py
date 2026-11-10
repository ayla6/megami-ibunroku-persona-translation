"""Upload the patch release the web patcher serves.

The page itself is deployed by .github/workflows/pages.yml, which unpacks
the latest release's patch zip into webpatcher/patches before publishing
the artifact, so the page reads the patches same-origin (release downloads
carry no CORS headers, so a browser cannot fetch them directly). This
script handles the release asset that mirror unpacks:

- upload one persona-patches.zip (gh CLI, --no-release to skip) holding
  the manifest, the README and every patch: the tag defaults to
  patches-YYYY-MM-DD, with -2, -3, ... appended when that day already has
  releases. The stamp is written into the manifest's release column before
  upload, and the web patcher uses it in the result filenames. Individual
  files stay in the zip so the page can fetch only the patches along the
  chosen chain. The upload targets the repository named by
  webpatcher/app.js (RELEASE_REPO), not origin, which is not GitHub.

    python tools/publish_patches.py               # release upload
    python tools/publish_patches.py --no-release  # local copy only

A finished build can upload the release directly:

    python tools/build_patches.py --publish-release
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'webpatcher'
DIST = ROOT / 'dist' / 'patches'
ARCHIVE_NAME = 'persona-patches.zip'
RELEASE_PREFIX = 'patches-'


def release_date(now=None):
    """The day part of a default release tag, in local time."""
    return (now or time.localtime()).strftime('%Y-%m-%d')


def next_release_tag(existing=(), today=None):
    """The first free patches-YYYY-MM-DD[-N] tag for a day.

    A second release on the same day becomes -2, then -3, so the result
    filenames stamped by the web patcher stay distinct."""
    base = RELEASE_PREFIX + (today or release_date())
    if base not in existing:
        return base
    number = 2
    while f'{base}-{number}' in existing:
        number += 1
    return f'{base}-{number}'


def existing_release_tags():
    """Tags already on the release repository, so a same-day upload gets
    its own release instead of clobbering the previous one."""
    try:
        output = run('gh', 'release', 'list', '--repo', GITHUB_REPO,
                     '--limit', '1000', '--json', 'tagName', capture=True)
    except subprocess.CalledProcessError:
        raise SystemExit(
            f'cannot list releases on {GITHUB_REPO} with gh - create that'
            ' GitHub repository and push main first, then run this again'
        ) from None
    try:
        return {item['tagName'] for item in json.loads(output or '[]')}
    except (KeyError, TypeError, ValueError):
        raise SystemExit('gh returned an unrecognized release list') from None


def stamp_manifest(tag, directory=None):
    """Write the release tag into the manifest's release column.

    The tag is only known when publishing, after the release was built, so
    this is the one place that stamps it. Older manifests gain the column;
    every existing column and row is preserved."""
    directory = Path(directory) if directory else DIST
    manifest = directory / 'manifest.tsv'
    if not manifest.is_file():
        raise SystemExit(f'{manifest} does not exist - build the release first')
    with open(manifest, encoding='utf-8', newline='') as source:
        reader = csv.DictReader(source, delimiter='\t')
        fields = list(reader.fieldnames or ())
        if not fields:
            raise SystemExit(f'{manifest} has no header')
        rows = list(reader)
    if 'release' not in fields:
        fields.append('release')
    for row in rows:
        row['release'] = tag
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', newline='', dir=manifest.parent,
                delete=False) as out:
            temporary = Path(out.name)
            writer = csv.DictWriter(out, fieldnames=fields, delimiter='\t',
                                    lineterminator='\n', extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, manifest)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return tag


def complete_release_size():
    """How many patch files a complete release has.

    The count is derived from the release graph, never typed: one rev
    conversion per original revision, one file per in-place option, and one
    file per size-changer anchor."""
    sys.path.insert(0, str(ROOT / 'tools'))
    import build_patches
    return len(build_patches.release_file_names())


def release_repo():
    """The GitHub owner/repo the page reads releases from and we upload to.

    webpatcher/app.js is the one definition: the page needs that value at
    runtime, so deriving it here keeps the upload from drifting to another
    repository.
    """
    source = (SITE / 'app.js').read_text(encoding='utf-8')
    match = re.search(r"^const RELEASE_REPO = '([^']+)';", source, re.M)
    if not match:
        raise SystemExit(f'{SITE / "app.js"} has no RELEASE_REPO')
    return match.group(1)


GITHUB_REPO = release_repo()


def run(*cmd, capture=False):
    result = subprocess.run(cmd, cwd=ROOT, check=True,
                            text=True, capture_output=capture)
    return result.stdout.strip() if capture else None


def release_is_complete(directory=None):
    """A complete release has one manifest row per patch file.

    The old per-combination manifest repeats patch names; that is not a
    complete release of this layout and must not be uploaded over it.
    """
    directory = Path(directory) if directory else DIST
    manifest = directory / 'manifest.tsv'
    if not manifest.is_file():
        return False
    with open(manifest, encoding='utf-8', newline='') as source:
        reader = csv.DictReader(source, delimiter='\t')
        fields = set(reader.fieldnames or ())
        rows = [row for row in reader if row.get('patch')]
    # One row per patch file, with the graph columns a chain needs. The
    # `verified` column records the sampled selections that exercised each
    # step; it is part of the layout even when a particular step has none.
    if not {'adds', 'anchor', 'order', 'choices', 'verified'} <= fields:
        return False
    names = {row['patch'] for row in rows}
    return (len(names) == complete_release_size()
            and len(rows) == len(names))


def sync_local_patches(directory=None):
    """Refresh webpatcher/features.js and webpatcher/patches for local
    serving (both git-ignored).

    A symlink to dist/patches is a valid setup for the patches: local
    serving then always sees the current release, so there is nothing to
    copy."""
    sys.path.insert(0, str(ROOT / 'tools'))
    import generate_features
    generate_features.generate(target=SITE / 'features.js')
    directory = Path(directory) if directory else DIST
    local = SITE / 'patches'
    local.mkdir(exist_ok=True)
    if local.resolve() == directory.resolve():
        return
    for stale in local.glob('*.xdelta'):
        if not (directory / stale.name).is_file():
            stale.unlink()
    for path in directory.iterdir():
        if path.is_file():
            shutil.copy2(path, local / path.name)


def release_files(directory=None):
    """Everything that belongs in a release: the manifest, the manual
    README and every patch."""
    directory = directory or DIST
    return sorted(path for path in directory.iterdir()
                  if path.is_file() and path.name != ARCHIVE_NAME)


def write_archive(destination, directory=None):
    """One zip with the same files, for people applying xdelta by hand.

    The web patcher does not use this: it reads manifest.tsv and then only
    the patches along the chosen chain, which a zip would make impossible
    without downloading and unpacking all of them in the browser.
    """
    directory = directory or DIST
    destination = Path(destination)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in release_files(directory):
            info = zipfile.ZipInfo(
                path.name, date_time=time.localtime(path.stat().st_mtime)[:6])
            info.external_attr = 0o100644 << 16  # readable after extraction
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return destination


def require_release_repo():
    """Fail before the archive is built when gh cannot reach the repository.

    origin is not GitHub, so a missing repository or a stale login would
    otherwise only surface as a failed release creation at the very end.
    """
    try:
        run('gh', 'repo', 'view', GITHUB_REPO, '--json', 'name',
            capture=True)
    except subprocess.CalledProcessError:
        raise SystemExit(
            f'cannot reach {GITHUB_REPO} with gh - create that GitHub'
            ' repository and push main first (the Pages workflow deploys'
            ' from it), then run this again') from None


def upload_release(tag, directory=None):
    directory = Path(directory) if directory else DIST
    if not shutil.which('gh'):
        raise SystemExit('gh is required to upload the release - install it'
                         ' from https://cli.github.com or pass --no-release')
    require_release_repo()
    with tempfile.TemporaryDirectory() as tmp:
        archive = write_archive(Path(tmp) / ARCHIVE_NAME, directory)
        assets = [str(archive)]
        try:
            run('gh', 'release', 'view', '--repo', GITHUB_REPO, tag,
                capture=True)
            run('gh', 'release', 'upload', '--repo', GITHUB_REPO,
                tag, '--clobber', *assets)
            print(f'release {tag} assets updated on {GITHUB_REPO}')
            return 'updated'
        except subprocess.CalledProcessError:
            label = tag.removeprefix(RELEASE_PREFIX)
            run('gh', 'release', 'create', '--repo', GITHUB_REPO, tag, *assets,
                '--title', f'Persona translation patches ({label})',
                '--notes', 'One zip: the patch files, manifest.tsv (every'
                           ' chain, with the hashes to verify each step) and'
                           ' README.txt (apply order). The manifest release'
                           f' column is {tag}.')
            print(f'release {tag} created on {GITHUB_REPO}')
            return 'created'


def deploy_site():
    """Redeploy the Pages site so its mirror picks up a replaced release.

    A new release deploys the site through the workflow's
    `release: published` trigger. Clobbering the assets of a release that
    already exists fires nothing, so that case dispatches the workflow
    itself. Either way the site keeps serving patches from its own origin.
    """
    try:
        run('gh', 'workflow', 'run', 'pages.yml', '--repo', GITHUB_REPO,
            '--ref', 'main', capture=True)
        print(f'Pages deploy triggered on {GITHUB_REPO}')
    except subprocess.CalledProcessError:
        print('warning: could not trigger the Pages deploy - run'
              ' "Deploy web patcher" from the Actions tab')


def publish(tag=None, *, directory=None, release=True,
            allow_incomplete=False):
    """Upload the release and refresh the local copy of the patches.

    This is the single entry point used by the CLI and by
    build_patches.py --publish-release, so a finished build cannot
    half-publish through a different code path. The site then redeploys to
    mirror the release it serves.
    """
    directory = Path(directory) if directory else DIST
    if tag is None:
        tag = next_release_tag(
            existing_release_tags() if release else ())
    if release:
        if not release_is_complete(directory) and not allow_incomplete:
            raise SystemExit(
                f'{directory / "manifest.tsv"} does not list a complete'
                f' release ({complete_release_size()} patch files) - rerun'
                ' the release build, or pass --allow-incomplete')
    stamp_manifest(tag, directory)
    if release:
        if upload_release(tag, directory) == 'updated':
            deploy_site()
    sync_local_patches(directory)
    owner, project = GITHUB_REPO.split('/')
    print(f'site: https://{owner}.github.io/{project}/'
          ' (GitHub Actions mirrors this release into the page)')
    return tag


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--no-release', dest='release', action='store_false',
                        help="don't upload the release; only refresh"
                             ' webpatcher/patches for local serving')
    parser.add_argument('--allow-incomplete', action='store_true',
                        help='upload the release even if it is not complete')
    parser.add_argument('--tag', default=None,
                        help='release tag (default: patches-YYYY-MM-DD,'
                             ' then -2, -3, ... for another release that day)')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    publish(tag=args.tag, release=args.release,
            allow_incomplete=args.allow_incomplete)


if __name__ == '__main__':
    main()
