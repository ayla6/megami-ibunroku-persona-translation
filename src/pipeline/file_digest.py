"""Reuse file hashes across build processes only while full stat identity matches."""
from __future__ import annotations

import atexit
import csv
import hashlib
import os
from pathlib import Path
import tempfile
from dataclasses import dataclass
from typing import Final

CACHE: Final = Path(__file__).resolve().parents[2] / 'build/step_cache/file-digests.tsv'
FIELDS: Final = ('path', 'device', 'inode', 'size', 'mtime_ns', 'ctime_ns', 'sha1')


@dataclass(frozen=True)
class Record:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    sha1: str


_records: dict[str, Record] | None = None
_dirty = False


def records() -> dict[str, Record]:
    global _records
    if _records is None:
        _records = {}
        try:
            with CACHE.open(newline='') as stream:
                reader = csv.DictReader(stream, delimiter='\t')
                if reader.fieldnames != list(FIELDS):
                    return _records
                for row in reader:
                    value = row['sha1']
                    if len(value) == 40 and all(c in '0123456789abcdef' for c in value):
                        _records[row['path']] = Record(*(int(row[k]) for k in FIELDS[1:-1]), value)
        except (OSError, ValueError, KeyError, TypeError):
            _records.clear()
    return _records


def signature(path: Path) -> tuple[int, int, int, int, int]:
    st = path.stat()
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def digest(path: Path) -> str:
    global _dirty
    path = path.resolve()
    stamp = signature(path)
    old = records().get(str(path))
    if old and (old.device, old.inode, old.size, old.mtime_ns, old.ctime_ns) == stamp:
        return old.sha1
    value = hashlib.sha1()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    if signature(path) != stamp:
        raise RuntimeError(f'file changed while hashing: {path}')
    result = value.hexdigest()
    records()[str(path)] = Record(*stamp, result)
    _dirty = True
    return result


def flush() -> None:
    global _dirty
    if not _dirty:
        return
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=CACHE.parent, delete=False, newline='') as out:
        writer = csv.writer(out, delimiter='\t', lineterminator='\n')
        writer.writerow(FIELDS)
        for path, record in sorted(records().items()):
            writer.writerow((path, record.device, record.inode, record.size,
                             record.mtime_ns, record.ctime_ns, record.sha1))
        temporary = out.name
    os.replace(temporary, CACHE)
    _dirty = False


atexit.register(flush)
