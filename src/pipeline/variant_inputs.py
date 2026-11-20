"""Native variant dependencies: shared preparation, selected mods and cleanup.

Preparation products are verified before the first variant and fingerprinted by
content. This preserves dependencies on shared generators that read optional
mod declarations without treating every optional mod's source as selected.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import importlib
from pathlib import Path
from typing import Final

import build_step_cache
import file_digest
import materialized_cache
import mod_build
import mods
import preparation_cache
import render_inputs

METADATA: Final = frozenset({'images.tsv'})


@dataclass(frozen=True)
class PreparedStage:
    name: str
    products: tuple[materialized_cache.Product, ...]


def prepared_stage(root: Path, name: str) -> PreparedStage:
    records = materialized_cache.load(root / 'build/step_cache' / name / 'active.tsv')
    if not records or any(file_digest.digest(record.path) != record.sha1 for record in records):
        raise ValueError('preparation has no verified product set')
    return PreparedStage(name, tuple(sorted(records, key=lambda r: str(r.path))))


class VariantInputs:
    def __init__(self, root: Path, image: Path, catalog: Sequence[mods.Mod],
                 options: Mapping[str, frozenset[str]], *, font: str,
                 base_only: bool, engine_only: bool, verify: bool,
                 movie_prepared: bool, tool: Path, gates: Mapping[str, bool]) -> None:
        self.root = root
        self.image = image
        self.catalog = tuple(catalog)
        self.options = options
        self.base_only = base_only
        self.engine_only = engine_only
        self.verify = verify
        self.prepared = prepared_stage(root, 'preparation')
        self.movies = prepared_stage(root, 'movies') if movie_prepared else None
        self.generated = {path.resolve() for path in preparation_cache.GENERATED}
        self.context = (font, str(base_only), str(engine_only), str(verify),
                        repr(sorted(gates.items())), *preparation_cache.versions())
        # Shared code and retail/translation inputs affect every variant.
        self.common = [root/'tools/build_patches.py', root/'tools/run_tests.py', tool,
                        root/'translation', root/'data/psx', root/'data/cache',
                        root/'data/extracted_text', image]
        if verify:
            self.common += [p for p in (root/'src/mods').rglob('test_*.py')]
        self.metadata = tuple(replace(m, description='', warning='', integrates=(),
                              choices=tuple(replace(c, name='', description='') for c in m.choices),
                              ranges=tuple(replace(r, name='') for r in m.ranges))
                              for m in self.catalog)

    def source_file(self, path: Path) -> bool:
        return ('__pycache__' not in path.parts and path.suffix != '.pyc'
                and path.resolve() not in self.generated
                and (self.verify or not (path.name.startswith('test_') and path.suffix == '.py')))

    def selected(self, labels: Sequence[str]) -> set[str]:
        by = {mod.label: mod for mod in self.catalog}
        on = set(labels) | {mod.label for mod in self.catalog if mod.always}
        if self.base_only:
            on.discard('latin-alphabet')
        todo = list(on)
        while todo:
            mod = by[todo.pop()]
            tokens = (frozenset() if self.engine_only and mod.translation
                      else self.options.get(mod.label, mod.defaults()))
            for need in mod.needs(tokens):
                if need not in on:
                    on.add(need)
                    todo.append(need)
        if self.base_only:
            on.discard('latin-alphabet')
        return on

    def key(self, labels: Sequence[str]) -> str:
        on = self.selected(labels)
        paths = list(self.common)
        paths.extend(p for p in (self.root/'src').rglob('*') if p.is_file()
                     and not p.is_relative_to(self.root/'src/mods') and self.source_file(p))
        cleanup: list[str] = []
        for mod in self.catalog:
            folder = Path(mod.folder)
            if mod.label in on:
                paths.extend(p for p in folder.rglob('*') if p.is_file() and self.source_file(p))
                paths.extend(mod_build.inputs(mod, self.root))
                paths.extend(self.root / setting.edits for setting in mod.ranges
                             if not (self.root / setting.edits).resolve().is_relative_to(
                                 (self.root/'build').resolve()))
            else:
                # Image cleanup reads declarations even for disabled mods.
                paths.extend(p for p in folder.iterdir() if p.is_file() and p.name in METADATA)
            for hook in mod_build.hooks(mod):
                if hook.phase not in ('restore', 'restore-disabled'):
                    continue
                if hook.phase == 'restore-disabled' and mod.label in on:
                    continue
                assert hook.target is not None
                module = importlib.import_module(hook.target.stem)
                if Path(module.__file__).resolve() != hook.target:
                    raise ValueError('cleanup tool resolves outside its declared mod')
                cleanup.append(render_inputs.fingerprint(getattr(module, hook.function)))
        stages = [self.prepared]
        if 'fmv-translation' in on:
            if self.movies is None:
                raise ValueError('variant requires unprepared movie products')
            stages.append(self.movies)
        selected_options = tuple((label, tuple(sorted(self.options.get(label,
                                  next(m for m in self.catalog if m.label == label).defaults()))))
                                 for label in sorted(on))
        return build_step_cache.fingerprint(sorted(set(paths)), context=(
            *self.context, repr(self.metadata), repr(stages), repr(selected_options), *cleanup))
