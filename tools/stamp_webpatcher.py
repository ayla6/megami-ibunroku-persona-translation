"""Stamp the deployed page with its manifest version and release notes."""
import csv
import html
from pathlib import Path
import sys


def render(page, manifest, notes=None, *, local=False):
    """Return (release, stamped HTML), without changing the source page.

    An entirely unstamped manifest is accepted only for local testing.
    Partially stamped or inconsistent manifests are always rejected.
    """
    page, manifest = Path(page), Path(manifest)
    notes = Path(notes) if notes is not None else Path(__file__).resolve().parents[1] / 'RELEASE_NOTES.md'
    with manifest.open(encoding='utf-8', newline='') as source:
        reader = csv.DictReader(source, delimiter='\t')
        if 'release' not in (reader.fieldnames or ()) and not local:
            raise ValueError('patch manifest has no release column')
        releases = [(row.get('release') or '').strip() for row in reader]
    if local and releases and not any(releases):
        releases = ['local'] * len(releases)
    if not releases or not all(releases) or len(set(releases)) != 1:
        raise ValueError('patch manifest must name one release on every row')
    text = page.read_text(encoding='utf-8')
    if '$VERSION' not in text:
        raise ValueError('page has no $VERSION placeholder')
    if '$RELEASE_NOTES' not in text:
        raise ValueError('page has no $RELEASE_NOTES placeholder')
    version = releases[0].removeprefix('patches-')
    content = notes.read_text(encoding='utf-8')
    return releases[0], (text.replace('$VERSION', html.escape(version, quote=True))
                         .replace('$RELEASE_NOTES', html.escape(content)))


def stamp(page, manifest, notes=None):
    release, text = render(page, manifest, notes)
    Path(page).write_text(text, encoding='utf-8')
    return release


if __name__ == '__main__':
    try:
        print('web patcher release:', stamp(sys.argv[1], sys.argv[2]))
    except (IndexError, OSError, ValueError) as error:
        raise SystemExit(f'web patcher version: {error}') from error
