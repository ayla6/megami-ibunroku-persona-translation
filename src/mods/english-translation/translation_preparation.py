"""English translation compilation recipe and its native-row fallback.

The format encoders are shared tools. This mod owns their preparation order,
porting, movie text and source QA.
The early font-kit step supplies widths; the final one rebuilds the affinity
pool after the text encoders have finalized its input. Font pages are applied
after container rebuilds so neither operation erases the other. Native tiers run the same recipe against the engine's
blank-English provider, so empty rows retain their Japanese bytes.
"""
from __future__ import annotations

from collections.abc import Callable
import csv
import os
from dataclasses import dataclass
from pathlib import Path
import shlex
from typing import Final

import toolpath

RECIPE: Final = Path(__file__).with_name('preparation.tsv')
COLUMNS: Final = ('when', 'action', 'target', 'arguments')
CONDITIONS: Final = frozenset(('always', 'port', 'verify', 'SF_VWF'))
ACTIONS: Final = frozenset(('run', 'mkdir', 'tables', 'font'))


@dataclass(frozen=True)
class PreparationStep:
    when: str
    action: str
    target: str
    arguments: tuple[str, ...]


def steps(path: Path = RECIPE) -> list[PreparationStep]:
    result: list[PreparationStep] = []
    with path.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f'{path}: invalid preparation columns')
        for row in reader:
            step = PreparationStep(row['when'], row['action'], row['target'],
                                   tuple(shlex.split(row['arguments'])))
            if step.when not in CONDITIONS or step.action not in ACTIONS:
                raise ValueError(f'{path}: invalid preparation condition/action')
            if step.action == 'run':
                if Path(step.target).name != step.target or not step.target.endswith('.py'):
                    raise ValueError(f'{path}: commands name a shared tool, not a shell command')
                toolpath.script(step.target)  # reject missing tools before executing any steps
            elif step.action == 'mkdir':
                target = Path(step.target)
                if target.is_absolute() or '..' in target.parts or not target.parts:
                    raise ValueError(f'{path}: build directories must be relative')
                if step.arguments:
                    raise ValueError(f'{path}: mkdir takes no arguments')
            elif step.target != '-' or step.arguments:
                raise ValueError(f'{path}: generator adapters take no target or arguments')
            result.append(step)
    return result


def prepare(root: Path, python: str, run: Callable[..., None], *, port: bool,
            gates: dict[str, bool], verify: bool, tables: Callable[[], None],
            font: Callable[[], None]) -> None:
    enabled = {'always': True, 'port': port, 'verify': verify,
               'SF_VWF': gates.get('SF_VWF', False)}
    for step in steps():
        if not enabled[step.when]:
            continue
        if step.action == 'run':
            run(python, step.target, *step.arguments)
        elif step.action == 'mkdir':
            (root / 'build' / step.target).mkdir(parents=True, exist_ok=True)
        elif step.action == 'tables':
            tables()
        elif step.action == 'font':
            font()


def fmv_parts(subtitles: str) -> list[str]:
    """What the movie renderer shows: 'movie-text' (the opening quote, the
    ending poems) whenever it is on - it is English text - and 'subtitles'
    (the spoken lines) when the English mod's subtitles are on."""
    return ['movie-text'] + (['subtitles'] if subtitles == 'on'
                             else [])


def prepare_fmv_data(py: str, incremental: bool = False, *,
                     subtitles: str, run: Callable[..., None]) -> None:
    """Generate subtitle assets, or reuse byte-verified unchanged outputs."""
    os.environ['PERSONA_FMV_PARTS'] = ','.join(fmv_parts(subtitles))
    command = lambda: run(py, 'fmv_subgen.py', 'data')
    from importlib.metadata import version
    from PIL import features as pil_features
    import build_step_cache
    # Conservative inputs: a source or translation edit costs a rebuild
    # rather than risking a stale subtitle asset.
    build_step_cache.run(
        'FMV subtitle data', [os.path.join(toolpath.ROOT, 'src'), os.path.join(toolpath.TRANSLATION)],
        [os.path.join(toolpath.ROOT, 'build', f'movie_subs{suffix}.bin') for suffix in
         ('_data', '_dub_data', '_open_data', '_end_data', '_tex', '_dub_tex', '_open_tex',
          '_end_tex', '_zoom', '_dub_zoom', '_open_zoom', '_end_zoom')],
        command, os.path.join(toolpath.ROOT, 'build', 'step_cache', 'fmv-data.tsv'),
        context=(version('Pillow'), pil_features.version_module('freetype2'),
                 'parts=' + os.environ['PERSONA_FMV_PARTS']),
        reuse=incremental)

