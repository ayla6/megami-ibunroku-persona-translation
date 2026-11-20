"""Configuration-specific preparation and ending products; never disc snapshots."""
from __future__ import annotations

import csv
from importlib.metadata import distributions
from collections.abc import Callable
from pathlib import Path
from typing import Final

import file_digest
import materialized_cache
import toolpath

ROOT: Final = Path(toolpath.ROOT)
BUILD: Final = ROOT / 'build'
GENERATED: Final = tuple(
    Path(toolpath.font_path(kind, edition))
    for edition in toolpath.FONT_EDITIONS for kind in ('font', 'width', 'index', 'glyphs')
) + tuple(ROOT / 'src/mods/base/asm/common' / name
          for name in ('persona.tbl', 'persona_vwf.tbl'))


def source_inputs() -> list[Path]:
    generated = {p.resolve() for p in GENERATED}
    # Declared image assets belong to the post-assembly image compiler. They
    # carry their own source/output checks and cannot change prepared text.
    image_inputs: set[Path] = set()
    for manifest in (ROOT / 'src/mods').glob('*/images.tsv'):
        image_inputs.add(manifest.resolve())
        with manifest.open(newline='') as stream:
            for row in csv.DictReader(stream, delimiter='\t'):
                image_inputs.add((manifest.parent / 'assets' / row['image']).resolve())
    return [p for p in sorted((ROOT / 'src').rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'
            and p.resolve() not in generated | image_inputs
            and not (p.name.startswith('test_') and p.suffix == '.py')
            and not p.name.startswith('vwf_preview')]


def versions() -> tuple[str, ...]:
    from PIL import features
    return (*sorted(f'{d.metadata["Name"]}=={d.version}' for d in distributions()
                    if d.metadata.get('Name')), str(features.version_module('freetype2')))


def inputs() -> list[Path]:
    import build
    translations = list(dict.fromkeys((Path(toolpath.TRANSLATION),
                                       Path(toolpath.DEFAULT_TRANSLATION))))
    return source_inputs() + [Path(build.ARMIPS), *translations, ROOT / 'data/psx',
                              ROOT / 'data/cache', ROOT / 'data/extracted_text']


def candidates() -> list[Path]:
    # Preparation can write root assembly/data, graphics and game-file folders.
    # Diagnostic, snapshot, movie and voice caches are owned by other stages.
    folders = ('ADV', 'B', 'D00', 'D01', 'D02', 'D03', 'D04', '2D', 'TALK', 'EXE', 'gfx')
    return [p for p in BUILD.iterdir() if p.is_file()] + [
        p for folder in folders for p in (BUILD / folder).rglob('*') if p.is_file()
    ] + [p for p in GENERATED if p.is_file()]


def prepare(action: Callable[[], None], font: str, gates: dict[str, bool],
            reuse: bool, verify: bool = True) -> None:
    products: list[Path] = []

    def generate() -> None:
        before = {p: file_digest.signature(p) for p in candidates()}
        action()
        # Only files actually written by preparation belong to this cache.
        # Include declared products of the smaller caches even on their hits.
        # Inner caches can leave outputs untouched on a preparation miss.
        for name in ('character-tables', 'dialogue-font'):
            manifest = BUILD / 'step_cache' / (name + '.tsv')
            if manifest.exists():
                with manifest.open(newline='') as stream:
                    products.extend(Path(row['path']) for row in csv.DictReader(stream, delimiter='\t')
                                    if row['kind'] == 'output' and Path(row['path']).is_file())
        products.extend(p for p in candidates()
                        if p in GENERATED or before.get(p) != file_digest.signature(p))

    materialized_cache.run('text/font preparation', inputs(), lambda: products,
                           generate, BUILD / 'step_cache/preparation',
                           context=(font, f'verify={verify}', *versions(), *(
                               f'{key}={value}' for key, value in sorted(gates.items()))),
                           reuse=reuse)


def movies(action: Callable[[], None], font: str, reuse: bool) -> None:
    import build
    import os
    os.environ['PERSONA_FMV_PARTS'] = ','.join(build.fmv_parts())
    materialized_cache.run(
        'movie preparation', inputs(),
        lambda: [*BUILD.glob('movie_subs*.bin'), BUILD / 'movie_subs.sym',
                 BUILD / 'armips-subs.lst'], action, BUILD / 'step_cache/movies',
        context=(font, os.environ['PERSONA_FMV_PARTS'], *versions()), reuse=reuse)


def ending(action: Callable[[], None], font: str, arguments: tuple[str, ...], reuse: bool) -> None:
    materialized_cache.run(
        'ending pages', inputs(), lambda: [BUILD / 'EXE/END.BIN', BUILD / 'end_roll.asm'],
        action, BUILD / 'step_cache/ending', context=(font, *arguments, *versions()), reuse=reuse)
