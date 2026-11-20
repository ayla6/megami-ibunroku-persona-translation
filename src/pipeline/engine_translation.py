"""The engine's translation: translation/ with every English cell empty.

The engine (the base mod) is the patch without the English mod. Building it
means building with a translation that says nothing: the same files, rows,
ids, positions and correspondence mappings as translation/, but no English,
so every row falls back to its Japanese - the way an untranslated row ships
today. Where that build fails or the game misbehaves, an engine piece
assumes English: the line docs/MOD_ENGINE.md says to fix.

    python src/pipeline/engine_translation.py [OUT]   (default build/engine-translation)

`build.py --engine-only` makes it and points every tool at it
(PERSONA_TRANSLATION, src/toolpath.py). English lives in three kinds of
cells, all emptied:

  en      every row table's wording column
  note    provenance - an over-limit row's draft is English that ships
  text    the ending pages and the movie subtitles (ending/, fmv/)

Everything else is copied as it is, so the tree stays a valid translation.
Typed Python (AGENTS.md).
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import Final

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)

SOURCE: Final = toolpath.DEFAULT_TRANSLATION
OUT: Final = os.path.join(toolpath.ROOT, 'build', 'engine-translation')
ENGLISH_COLUMNS: Final = frozenset(('en', 'note'))
# folders whose `text` column is English (pages, subtitles, the opening quote)
TEXT_FOLDERS: Final = ('ending', 'fmv')


def english_columns(rel: str, header: list[str]) -> set[int]:
    """The columns of one table (its path under translation/) that hold English."""
    out = {k for k, name in enumerate(header) if name in ENGLISH_COLUMNS}
    parts = rel.split(os.sep)
    if len(parts) > 1 and parts[1] in TEXT_FOLDERS:
        out |= {k for k, name in enumerate(header) if name == 'text'}
    return out


def blank(text: str, rel: str) -> str:
    """A table with its English cells emptied; the header and every other
    cell kept byte for byte."""
    lines = text.split('\n')
    header = lines[0].split('\t')
    columns = english_columns(rel, header)
    if not columns:
        return text
    out = [lines[0]]
    for line in lines[1:]:
        cells = line.split('\t')
        out.append('\t'.join('' if k in columns else cell for k, cell in enumerate(cells)))
    return '\n'.join(out)


def make(out: str = OUT, source: str = SOURCE) -> str:
    """Write the engine's translation to `out` (replacing it); return `out`."""
    if os.path.abspath(out) == os.path.abspath(source):
        raise ValueError('engine_translation: the output would overwrite translation/')
    shutil.rmtree(out, ignore_errors=True)
    for parent, _dirs, files in os.walk(source):
        rel_dir = os.path.relpath(parent, source)
        os.makedirs(os.path.join(out, rel_dir), exist_ok=True)
        for name in files:
            rel = os.path.normpath(os.path.join(rel_dir, name))
            src, dest = os.path.join(source, rel), os.path.join(out, rel)
            if name.endswith('.tsv'):
                with open(src, encoding='utf-8', newline='') as f:
                    text = f.read()
                with open(dest, 'w', encoding='utf-8', newline='') as f:
                    f.write(blank(text, rel))
            else:
                shutil.copy2(src, dest)
    return out


if __name__ == '__main__':
    print(f'engine translation: {make(sys.argv[1] if len(sys.argv) > 1 else OUT)}')
