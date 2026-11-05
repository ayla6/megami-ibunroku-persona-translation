"""Shared TSV format for text-free source correspondence plans."""
import csv
import hashlib
import os
from pathlib import Path

COLUMNS = ('kind', 'key', 'value', 'rel', 'pos', 'us_sub', 'us_pos', 'us_hi_pos',
           'mode', 'split', 'speaker')
MATCH_COLUMNS = COLUMNS[3:]


def matches_digest(matches):
    h = hashlib.sha1()
    for row in matches:
        for key in MATCH_COLUMNS:
            h.update(row.get(key, '').encode('utf-8') + b'\0')
    return h.hexdigest()


def write(path, metadata, matches):
    """Atomically write metadata and ordered source matches; no wording."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    metadata = dict(metadata, matches_sha1=matches_digest(matches))
    with temporary.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        for key, value in sorted(metadata.items()):
            writer.writerow({'kind': 'meta', 'key': key, 'value': value})
        for row in matches:
            writer.writerow(dict(row, kind='match'))
    os.replace(temporary, path)


def read(path):
    """Validate structure and match completeness before returning any rows."""
    try:
        with Path(path).open(encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f, delimiter='\t')
            if tuple(reader.fieldnames or ()) != COLUMNS:
                raise ValueError('invalid column header')
            metadata, matches = {}, []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError('malformed row')
                if row['kind'] == 'meta':
                    if not row['key'] or row['key'] in metadata or any(row[k] for k in MATCH_COLUMNS):
                        raise ValueError('invalid metadata')
                    metadata[row['key']] = row['value']
                elif row['kind'] == 'match':
                    if row['key'] or row['value']:
                        raise ValueError('invalid match')
                    matches.append({k: row[k] for k in MATCH_COLUMNS if row[k]})
                else:
                    raise ValueError('unknown row kind')
    except (OSError, csv.Error) as exc:
        raise ValueError(f'correspondence plan unavailable: {path}') from exc
    if metadata.pop('matches_sha1', None) != matches_digest(matches):
        raise ValueError('correspondence plan has missing or damaged matches')
    return metadata, matches
