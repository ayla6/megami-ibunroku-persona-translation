"""Verified preparation products, restored with reflinks across build configurations.

Manifests are TSV. A manifest is committed only after every stored product is
hashed and inputs are rechecked. Cached bytes are verified before restoration.
"""
from __future__ import annotations

import csv
import os
import io
from pathlib import Path
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

import build_step_cache as steps

FIELDS: Final = ('path', 'sha1', 'blob')


@dataclass(frozen=True)
class Product:
    path: Path
    sha1: str
    blob: str


def load(path: Path) -> list[Product]:
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if reader.fieldnames != list(FIELDS):
            raise ValueError('invalid materialized cache manifest')
        return [Product(Path(row['path']), row['sha1'], row['blob']) for row in reader]


def write(path: Path, products: list[Product]) -> None:
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
    writer.writerow(FIELDS)
    writer.writerows((str(p.path), p.sha1, p.blob) for p in products)
    content = stream.getvalue()
    if path.exists() and path.read_text() == content:
        return
    temporary = path.with_suffix('.tmp')
    temporary.write_text(content)
    os.replace(temporary, path)


def run(name: str, inputs: Iterable[Path], owned: Callable[[], list[Path]],
        action: Callable[[], None], cache: Path, context: tuple[str, ...] = (),
        reuse: bool = True) -> bool:
    inputs = list(inputs)
    key = steps.fingerprint(inputs, context)
    entry = cache / key
    manifest = entry / 'manifest.tsv'
    if reuse:
        try:
            products = load(manifest)
            if not all((entry / p.blob).is_file() and steps._digest(entry / p.blob) == p.sha1
                       for p in products):
                raise ValueError('damaged preparation cache')
            active = cache / 'active.tsv'
            previous = load(active) if active.exists() else []
            wanted = {p.path for p in products}
            for p in previous:
                if p.path not in wanted and p.path.exists():
                    p.path.unlink()
            for p in products:
                if not p.path.exists() or steps._digest(p.path) != p.sha1:
                    p.path.parent.mkdir(parents=True, exist_ok=True)
                    steps.clone(entry / p.blob, p.path)
            write(active, products)
            print(f'build: {name}: verified preparation restored ({len(products)} products)', flush=True)
            return False
        except (OSError, ValueError, KeyError):
            pass
    entry.mkdir(parents=True, exist_ok=True)
    manifest.unlink(missing_ok=True)
    action()
    if steps.fingerprint(inputs, context) != key:
        print(f'build: {name} inputs changed during generation; not caching', flush=True)
        return True
    products: list[Product] = []
    for path in sorted(set(owned())):
        value = steps._digest(path)
        blob = '../blobs/' + value
        stored = entry / blob
        if not stored.is_file() or steps._digest(stored) != value:
            steps.clone(path, stored)
        if steps._digest(stored) != value:
            raise RuntimeError(f'{name}: cached copy differs from {path}')
        products.append(Product(path, value, blob))
    write(manifest, products)
    write(cache / 'active.tsv', products)
    return True
