"""Verified native variant trees, shared across release attempts.

Trees contain changed game files only. Immutable content-addressed blobs are
shared with release snapshots; a manifest is published after all files exist.
"""
from __future__ import annotations

from collections.abc import Mapping
import csv
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Final

import file_digest

FIELDS: Final = ('path', 'sha1')


@dataclass(frozen=True)
class CachedFile:
    path: str
    sha1: str


def safe_path(text: str) -> PurePosixPath:
    path = PurePosixPath(text)
    if path.is_absolute() or not path.parts or '..' in path.parts or '\\' in text:
        raise ValueError('invalid cached game path')
    return path


class VariantCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.blobs = root.parent / 'tree-blobs'

    def entry(self, key: str) -> Path:
        if len(key) != 40 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('invalid variant fingerprint')
        return self.root / key

    def find(self, key: str) -> Path | None:
        entry = self.entry(key)
        if not self.valid_tree(entry / 'auxiliary', entry / 'auxiliary.tsv', auxiliary=True):
            return None
        return entry / 'files' if self.valid_tree(entry / 'files', entry / 'manifest.tsv') else None

    def valid_tree(self, files: Path, manifest: Path, *, auxiliary: bool = False) -> bool:
        try:
            with manifest.open(newline='') as stream:
                reader = csv.DictReader(stream, delimiter='\t')
                if reader.fieldnames != list(FIELDS):
                    return False
                records = [CachedFile(row['path'], row['sha1']) for row in reader]
            names = {record.path for record in records}
            if len(names) != len(records) or not files.is_dir():
                return False
            actual = {p.relative_to(files).as_posix() for p in files.rglob('*') if p.is_file()}
            if actual != names:
                return False
            for record in records:
                relative = safe_path(record.path)
                if auxiliary and relative.parts[0] != 'build':
                    return False
                path = files / relative
                if (not path.resolve().is_relative_to(files.resolve())
                        or file_digest.digest(path) != record.sha1):
                    return False
            return True
        except (OSError, ValueError, KeyError, TypeError, csv.Error):
            return False

    def restore_auxiliary(self, key: str, root: Path) -> None:
        import build_step_cache
        entry = self.entry(key)
        with (entry / 'auxiliary.tsv').open(newline='') as stream:
            for row in csv.DictReader(stream, delimiter='\t'):
                relative = safe_path(row['path'])
                target = root / relative
                if relative.parts[0] != 'build' or not target.resolve().is_relative_to((root/'build').resolve()):
                    raise ValueError('cached auxiliary output is outside build/')
                if not target.is_file() or file_digest.digest(target) != row['sha1']:
                    build_step_cache.clone(entry / 'auxiliary' / relative, target)

    def store(self, key: str, files: Mapping[str, bytes],
              auxiliary: Mapping[str, bytes] | None = None) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs.mkdir(parents=True, exist_ok=True)
        existing = self.find(key)
        if existing is not None:
            return existing
        with tempfile.TemporaryDirectory(prefix='.variant-', dir=self.root) as temporary:
            work = Path(temporary) / 'entry'
            tree = work / 'files'
            tree.mkdir(parents=True)
            records: list[CachedFile] = []
            for name, data in sorted(files.items()):
                relative = safe_path(name)
                value = hashlib.sha1(data).hexdigest()
                blob = self.blobs / value
                if not blob.is_file() or file_digest.digest(blob) != value:
                    with tempfile.NamedTemporaryFile(dir=self.blobs, delete=False) as stream:
                        stream.write(data)
                        pending = Path(stream.name)
                    os.replace(pending, blob)
                if file_digest.digest(blob) != value:
                    raise RuntimeError('cached variant blob differs from its native output')
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(blob, target)
                except OSError:
                    shutil.copyfile(blob, target)
                records.append(CachedFile(name, value))
            with (work / 'manifest.tsv').open('w', newline='') as stream:
                writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
                writer.writerow(FIELDS)
                writer.writerows((r.path, r.sha1) for r in records)
            side = work / 'auxiliary'
            side.mkdir()
            with (work / 'auxiliary.tsv').open('w', newline='') as stream:
                writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
                writer.writerow(FIELDS)
                for name, data in sorted((auxiliary or {}).items()):
                    relative = safe_path(name)
                    if relative.parts[0] != 'build':
                        raise ValueError('auxiliary outputs must live in build/')
                    target = side / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    writer.writerow((name, hashlib.sha1(data).hexdigest()))
            destination = self.entry(key)
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(work, destination)
        result = self.find(key)
        if result is None:
            raise RuntimeError('published variant failed its content checks')
        return result
