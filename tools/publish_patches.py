"""Upload the patch release the web patcher reads.

The page itself is deployed by .github/workflows/pages.yml, which publishes
the webpatcher/ directory as the Pages artifact. This script only handles
the release assets that page reads at runtime:

- upload the release directory (dist/patches/ by default) as release assets
  (gh CLI, --no-release to skip): the tag defaults to patches-YYYYMMDD;
  re-running the same day clobbers the existing release's assets. The files
  stay individual because the page fetches manifest.tsv and then only the
  patches along the chosen chain; a persona-patches.zip with the same files
  is uploaded too, for people applying xdelta by hand. The upload targets
  the repository named by webpatcher/app.js (RELEASE_REPO), not origin,
  which is not GitHub.

    python tools/publish_patches.py               # release upload
    python tools/publish_patches.py --no-release  # local copy only

A finished build can upload the release directly:

    python tools/build_patches.py --publish-release
"""

import argparse
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'webpatcher'
DIST = ROOT / 'dist' / 'patches'
ARCHIVE_NAME = 'persona-patches.zip'
COMPLETE_RELEASE = 33  # 2 conversions + 31 combinations


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
    directory = Path(directory) if directory else DIST
    manifest = directory / 'manifest.tsv'
    if not manifest.is_file():
        return False
    rows = manifest.read_text(encoding='utf-8').splitlines()
    return len([row for row in rows if row]) - 1 >= COMPLETE_RELEASE


def sync_local_patches(directory=None):
    """Refresh webpatcher/patches for local serving (git-ignored).

    A symlink to dist/patches is a valid setup: local serving then always
    sees the current release, so there is nothing to copy."""
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
        assets = [str(path) for path in release_files(directory)]
        assets.append(str(archive))
        try:
            run('gh', 'release', 'view', '--repo', GITHUB_REPO, tag,
                capture=True)
            run('gh', 'release', 'upload', '--repo', GITHUB_REPO,
                tag, '--clobber', *assets)
            print(f'release {tag} assets updated on {GITHUB_REPO}')
        except subprocess.CalledProcessError:
            run('gh', 'release', 'create', '--repo', GITHUB_REPO, tag, *assets,
                '--title', f'Persona translation patches ({time.strftime("%Y-%m-%d")})',
                '--notes', 'Apply with the web patcher, or manually in the order'
                           ' described in manifest.tsv and README.txt.'
                           f' {ARCHIVE_NAME} bundles the same files for offline use.')
            print(f'release {tag} created on {GITHUB_REPO}')


def publish(tag=None, *, directory=None, release=True,
            allow_incomplete=False):
    """Upload the release and refresh the local copy of the patches.

    This is the single entry point used by the CLI and by
    build_patches.py --publish-release, so a finished build cannot
    half-publish through a different code path. The site itself is deployed
    by GitHub Actions on the next push.
    """
    directory = Path(directory) if directory else DIST
    tag = tag or f'patches-{time.strftime("%Y%m%d")}'
    if release:
        if not release_is_complete(directory) and not allow_incomplete:
            raise SystemExit(
                f'{directory / "manifest.tsv"} does not list a complete'
                f' release ({COMPLETE_RELEASE} patches) - rerun the release'
                ' build, or pass --allow-incomplete')
        upload_release(tag, directory)
    sync_local_patches(directory)
    owner, project = GITHUB_REPO.split('/')
    print(f'site: https://{owner}.github.io/{project}/'
          ' (GitHub Actions deploys it on push to main)')
    return tag


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--no-release', dest='release', action='store_false',
                        help="don't upload the release; only refresh"
                             ' webpatcher/patches for local serving')
    parser.add_argument('--allow-incomplete', action='store_true',
                        help='upload the release even if it is not complete')
    parser.add_argument('--tag', default=None,
                        help='release tag (default: patches-YYYYMMDD)')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    publish(tag=args.tag, release=args.release,
            allow_incomplete=args.allow_incomplete)


if __name__ == '__main__':
    main()
