"""Assemble in RAM and publish changed binaries without rewriting live files.

Stable output aliases let listings remain usable after the RAM workspace is
released. Outside assembly each alias resolves to the ordinary build file.
The assembler and all write guards still run for every selected variant.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Final

import build_step_cache

RAM: Final = Path('/dev/shm')
EQU: Final = re.compile(r'^(\w+)\s+equ\s+"([^"]+)"', re.MULTILINE)


@dataclass(frozen=True)
class AssemblyProducts:
    paths: tuple[Path, ...]
    reserve: int
    names: tuple[str, ...] = ()


def main_products(root: Path) -> AssemblyProducts:
    import asm_main
    base = root / 'src/mods/base/asm'
    definitions = dict(EQU.findall((base / 'common/addresses.inc').read_text()))
    paths: list[Path] = []
    names: list[str] = []
    size = 0
    for block in asm_main.blocks():
        source, output, _address = block.open.removeprefix('.open ').split(',')
        paths.append(Path(os.path.abspath(base / definitions[output.strip()])))
        names.append(output.strip())
        size += (base / definitions[source.strip()]).stat().st_size
    return AssemblyProducts(tuple(paths), size * 2, tuple(names))


def digest(path: Path) -> bytes:
    # Ephemeral RAM names must not fill the persistent digest index.
    value = hashlib.sha1()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.digest()


def point(link: Path, target: Path) -> None:
    temporary = link.with_name(link.name + '.tmp')
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, link)


@contextmanager
def memory_outputs(products: AssemblyProducts, build: Path,
                   ram: Path = RAM) -> Iterator[dict[str, str]]:
    alias = build / '.armips-output'
    if (not ram.is_dir() or not os.access(ram, os.W_OK)
            or shutil.disk_usage(ram).free < products.reserve
            or (alias.exists() and not alias.is_symlink())
            or any(path.is_symlink() for path in products.paths)):
        yield {}
        return
    build.mkdir(parents=True, exist_ok=True)
    if any(not path.parent.resolve().is_relative_to(build.resolve()) for path in products.paths):
        raise ValueError('assembler output is outside build/')
    names = products.names or tuple(str(i) for i in range(len(products.paths)))
    if len(names) != len(products.paths) or any(not re.fullmatch(r'\w+', name) for name in names):
        raise ValueError('invalid assembler output names')
    links = build / '.armips-product-links'
    links.mkdir(exist_ok=True)
    for name, target in zip(names, products.paths):
        target.parent.mkdir(parents=True, exist_ok=True)
        point(links / name, target)
    with tempfile.TemporaryDirectory(prefix='persona-armips-', dir=ram) as work:
        workspace = Path(work)
        point(alias, workspace)
        try:
            yield {name: str(alias / name) for name in names}
            for name in names:
                if not (workspace / name).is_file():
                    raise RuntimeError(f'assembler did not produce {name}')
            changed = 0
            for name, target in zip(names, products.paths):
                result = workspace / name
                same = (target.is_file() and result.stat().st_size == target.stat().st_size
                        and digest(result) == digest(target))
                if not same:
                    build_step_cache.clone(result, target)
                    changed += 1
            print(f'build: assembler products: {changed} changed, '
                  f'{len(names) - changed} unchanged; RAM workspace released', flush=True)
        finally:
            point(alias, links)
