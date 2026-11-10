"""Stamp the deployed page with the release named by its patch manifest."""
import csv
import html
from pathlib import Path
import sys


def stamp(page, manifest):
    page, manifest = Path(page), Path(manifest)
    with manifest.open(encoding='utf-8', newline='') as source:
        reader = csv.DictReader(source, delimiter='\t')
        if 'release' not in (reader.fieldnames or ()):
            raise ValueError('patch manifest has no release column')
        releases = [(row.get('release') or '').strip() for row in reader]
    if not releases or not all(releases) or len(set(releases)) != 1:
        raise ValueError('patch manifest must name one release on every row')
    text = page.read_text(encoding='utf-8')
    if '$VERSION' not in text:
        raise ValueError('page has no $VERSION placeholder')
    page.write_text(text.replace('$VERSION', html.escape(releases[0], quote=True)),
                    encoding='utf-8')
    return releases[0]


if __name__ == '__main__':
    try:
        print('web patcher release:', stamp(sys.argv[1], sys.argv[2]))
    except (IndexError, OSError, ValueError) as error:
        raise SystemExit(f'web patcher version: {error}') from error
