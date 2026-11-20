"""Mod-owned build.tsv lifecycle steps; no shell commands or implicit previews."""
from __future__ import annotations
from collections.abc import Callable
import csv
from dataclasses import dataclass
import importlib
from pathlib import Path
from pathlib import PurePosixPath
import shlex
from string import Formatter
from typing import Final
import mods

COLUMNS: Final = ('phase', 'action', 'target', 'arguments')
INPUT_COLUMNS: Final = ('path',)


def inputs(mod: mods.Mod, root: Path) -> list[Path]:
    """External source files used by this mod, relative to the project root."""
    manifest = Path(mod.folder) / 'inputs.tsv'
    if not manifest.exists():
        return []
    result: list[Path] = []
    with manifest.open(newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if reader.fieldnames != list(INPUT_COLUMNS):
            raise ValueError(f'{manifest}: invalid input columns')
        for row in reader:
            value = row['path']
            path = PurePosixPath(value)
            if not path.parts or path.is_absolute() or '..' in path.parts or '\\' in value:
                raise ValueError(f'{manifest}: inputs must be project-relative paths')
            result.append(root / path)
    return result


@dataclass(frozen=True)
class Hook:
    phase: str
    action: str
    target: Path | None
    function: str
    arguments: tuple[str, ...]


def hooks(mod: mods.Mod) -> list[Hook]:
    path = Path(mod.folder)/'build.tsv'
    if not path.exists():
        return []
    result: list[Hook] = []
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f'{path}: invalid build hook columns')
        for row in reader:
            if row['phase'] not in ('restore', 'restore-disabled', 'build', 'verify', 'ending') or row['action'] not in ('call', 'run', 'arguments'):
                raise ValueError(f'{path}: invalid build hook phase/action')
            arguments = tuple(shlex.split(row['arguments']))
            if row['phase'] == 'ending':
                if row['action'] != 'arguments' or row['target'] not in ('', '-'):
                    raise ValueError(f'{path}: ending contributions contain arguments only')
                result.append(Hook('ending', 'arguments', None, '', arguments))
                continue
            if row['action'] == 'arguments':
                raise ValueError(f'{path}: argument contributions need a named preparation phase')
            script, _, function = row['target'].partition(':')
            target = (Path(mod.folder)/script).resolve()
            if not target.is_relative_to(Path(mod.folder).resolve()) or not target.is_file():
                raise ValueError(f'{path}: hook must name a tool inside its mod')
            if row['action'] == 'call' and (row['phase'] not in ('restore', 'restore-disabled') or arguments or not function.isidentifier()):
                raise ValueError(f'{path}: restore calls take a named function and no arguments')
            if row['action'] == 'run' and function:
                raise ValueError(f'{path}: command hooks cannot name a function')
            result.append(Hook(row['phase'], row['action'], target, function, arguments))
    return result


def restore(selected: list[mods.Mod] | None = None, *,
            enabled: frozenset[str] = frozenset()) -> None:
    for mod in mods.load() if selected is None else selected:
        for hook in hooks(mod):
            if hook.phase not in ('restore', 'restore-disabled'):
                continue
            if hook.phase == 'restore-disabled' and mod.label in enabled:
                continue
            if hook.action != 'call':
                raise ValueError('restore hooks must be in-process calls')
            assert hook.target is not None
            module = importlib.import_module(hook.target.stem)
            if Path(module.__file__).resolve() != hook.target:
                raise ValueError('mod tool name resolves outside its declared folder')
            getattr(module, hook.function)()


def render_arguments(mod: mods.Mod, hook: Hook,
                     value: Callable[[str, str], str]) -> tuple[str, ...]:
    result: list[str] = []
    for argument in hook.arguments:
        fields = [name for _, name, _, _ in Formatter().parse(argument) if name is not None]
        if any(not field.isidentifier() for field in fields):
            raise ValueError('hook parameters must be option keys')
        result.append(argument.format_map({field: value(mod.label,field) for field in fields}))
    return tuple(result)


def arguments(selected: list[mods.Mod], phase: str,
              value: Callable[[str, str], str]) -> tuple[str, ...]:
    return tuple(argument for mod in selected for hook in hooks(mod)
                 if hook.phase == phase and hook.action == 'arguments'
                 for argument in render_arguments(mod, hook, value))


def commands(mod: mods.Mod, verify: bool,
             value: Callable[[str, str], str]) -> list[tuple[str, ...]]:
    result: list[tuple[str, ...]] = []
    for hook in hooks(mod):
        if hook.phase not in ('build', 'verify') or (hook.phase == 'verify' and not verify):
            continue
        if hook.action != 'run':
            raise ValueError('build/verify hooks must be commands')
        assert hook.target is not None
        result.append((str(hook.target), *render_arguments(mod, hook, value)))
    return result
