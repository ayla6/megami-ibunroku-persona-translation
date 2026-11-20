"""build/main.asm: the armips entry point, written from the mods that are on.

There is no hand-written main.asm. Each mod says what it assembles in its own
`asm.tsv` (TSV, one row per line it adds):

    file    the disc file's block it goes in: a key of
            src/mods/base/asm/files.tsv (SLPS, ADV, BTLP, ...), or `-` for the
            definitions before the first block (tables, macros, constants)
    order   numeric priority among rows whose prerequisite mods have already
            emitted their rows in this block; dependencies take precedence
    line    the armips line. In `.include "PATH"`, PATH is relative to the
            mod's own folder, or starts with `build/` for a generated file
            of the build directory; any other line is written as it is
    if      an armips condition the line needs (SF_VWF, a feature gate of
            build/features.inc), or empty
    unless  a mod's slug: the line is left out while that mod is on (Fast
            forward's BtlDrawFrame rewrite replaces Battle speedup's)
    note    the comment written after it

src/mods/base/asm/files.tsv lists the blocks in order: key, the `.open`
line, a title. A mod that is off adds nothing - the file is written without
it - so no mod is gated by an `.ifdef` around its includes. The MOD_<LABEL>
defines are still passed to armips (build.py), so a mod's own files can ask
whether another mod is on (western-controls' DNG layout asks for run).

armips runs from src/mods/base/asm, where every path written here is
relative to. Typed Python (AGENTS.md).

    python src/pipeline/asm_main.py [LABEL ...]    write it for those mods (with the always-on ones)
"""
from __future__ import annotations

import csv
from collections import Counter
import os
import re
import sys
from dataclasses import dataclass
from typing import Final

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import mods  # noqa: E402

ROOT: Final = mods.ROOT
ASM_ROOT: Final = os.path.join(ROOT, 'src', 'mods', 'base', 'asm')
FILES: Final = os.path.join(ASM_ROOT, 'files.tsv')
OUT: Final = os.path.join(ROOT, 'build', 'main.asm')
COLUMNS: Final = ('file', 'order', 'line', 'if', 'unless', 'note')
INCLUDE: Final = re.compile(r'\.include\s+"([^"]+)"')


@dataclass(frozen=True)
class Block:
    """One disc file armips opens."""
    key: str
    open: str            # the `.open` line
    title: str


@dataclass(frozen=True)
class Row:
    """A line a mod adds to a block."""
    mod: str             # the label of the mod it belongs to
    file: str            # a block key, or '-'
    order: int
    line: str            # as written: paths still relative to the mod
    condition: str
    unless: str          # a mod slug, or ''
    note: str


def blocks() -> list[Block]:
    with open(FILES, encoding='utf-8', newline='') as source:
        return [Block(r['file'], r['open'], r['title'])
                for r in csv.DictReader(source, delimiter='\t')]


def rows(mod: mods.Mod) -> list[Row]:
    """The mod's asm.tsv rows ([] when it assembles nothing)."""
    path = os.path.join(mod.folder, 'asm.tsv')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8', newline='') as source:
        reader = csv.DictReader(source, delimiter='\t')
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f'{path}: the columns are {", ".join(COLUMNS)}')
        return [Row(mod.label, r['file'], int(r['order']), r['line'], r['if'] or '',
                    r['unless'] or '', r['note'] or '') for r in reader]


def resolved(mod: mods.Mod, line: str) -> str:
    """The line with its include path made relative to ASM_ROOT."""
    def path(match: re.Match[str]) -> str:
        target = match.group(1)
        full = (os.path.join(ROOT, target) if target.startswith('build/')
                else os.path.join(mod.folder, target))
        return f'.include "{os.path.relpath(full, ASM_ROOT).replace(os.sep, "/")}"'
    return INCLUDE.sub(path, line)


def dependency_rows(rows_in: list[Row], requirements: dict[str, set[str]],
                    rank: dict[str, int]) -> list[Row]:
    """Prerequisites first; numeric priority selects among ready rows.

    Dependency-only nodes with no rows still carry their prerequisites.
    No ordering choice depends on set iteration.
    """
    memo: dict[str, set[str]] = {}

    def before(label: str, trail: tuple[str, ...] = ()) -> set[str]:
        if label in trail:
            raise ValueError('cyclic assembly dependencies: ' + ' -> '.join((*trail, label)))
        if label not in memo:
            direct = requirements.get(label, set())
            memo[label] = direct | set().union(*(before(need, (*trail, label)) for need in direct))
        return memo[label]

    pending = sorted(rows_in, key=lambda row: (row.order, rank[row.mod]))
    remaining = Counter(row.mod for row in pending)
    result: list[Row] = []
    while pending:
        for index, row in enumerate(pending):
            if any(remaining[need] for need in before(row.mod)):
                continue
            result.append(pending.pop(index))
            remaining[row.mod] -= 1
            break
        else:
            raise ValueError('assembly rows cannot satisfy their mod dependencies')
    return result


def text(labels: list[str], outputs: dict[str, str] | None = None) -> str:
    """main.asm for the always-on mods and `labels` (mod labels)."""
    by = mods.by_label()
    slugs = {mod.slug: mod.label for mod in mods.load()}
    on = [mod for mod in mods.load() if mod.always or mod.label in labels]
    if os.environ.get('PERSONA_BASE_ONLY'):
        on = [mod for mod in on if mod.label != 'latin-alphabet']
    known = {block.key for block in blocks()}
    picked: list[Row] = []
    for mod in on:
        for row in rows(mod):
            if row.file != '-' and row.file not in known:
                raise ValueError(f'{mod.slug}/asm.tsv: no block {row.file} (base/asm/files.tsv)')
            if row.unless and row.unless not in slugs:
                raise ValueError(f'{mod.slug}/asm.tsv: unless names no mod: {row.unless}')
            if row.unless and slugs[row.unless] in [m.label for m in on]:
                continue
            picked.append(row)
    rank = {mod.label: n for n, mod in enumerate(on)}
    requirements = {mod.label: set(mods.every_need(mod)) for mod in mods.load()}
    out = [';; Generated by src/pipeline/asm_main.py from each mod\'s asm.tsv - edit those.',
           ';; Mods: ' + (', '.join(m.label for m in on)), '']

    def emit(rows_in: list[Row]) -> None:
        for row in dependency_rows(rows_in, requirements, rank):
            line = resolved(by[row.mod], row.line)
            if row.note:
                line = f'{line}   ; {row.note}'
            if row.condition:
                out.extend((f'.if {row.condition}', line, '.endif'))
            else:
                out.append(line)

    emit([row for row in picked if row.file == '-'])
    for block in blocks():
        opening = block.open
        if outputs:
            source, output, address = opening.split(',')
            if output.strip() in outputs:
                opening = f'{source}, "{outputs[output.strip()]}",{address}'
        out += ['', f';; --- {block.title} ---', opening]
        emit([row for row in picked if row.file == block.key])
        out.append('.close')
    return '\n'.join(out) + '\n'


def write(labels: list[str], path: str = OUT,
          outputs: dict[str, str] | None = None) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.islink(path):        # a mirrored tree's link to the real build/ file
        os.unlink(path)
    with open(path, 'w', encoding='utf-8', newline='\n') as out:
        out.write(text(labels, outputs))
    return path


if __name__ == '__main__':
    print(write(sys.argv[1:]))
