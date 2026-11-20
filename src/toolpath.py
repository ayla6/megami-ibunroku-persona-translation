"""Every tool folder on sys.path, so any tool imports any other by its name.

The tools are grouped by job (src/pipeline, src/extraction, src/porting,
src/injection/<area>, src/research, each mod's own folder under src/mods,
tools/), but their module names are unique across all of them, so imports
stay flat: `import btlp`, not `import injection.battle.btlp`. A module only
puts src/ on sys.path and imports this:

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    import toolpath  # noqa: E402,F401

A folder is a tool folder when it holds a .py file; assets/ and __pycache__
are never searched. Two modules with one name stop every import, since one
would hide the other.
"""
from __future__ import annotations

import os
import sys
from typing import Final

ROOT: Final = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The one place translation/ is named. PERSONA_TRANSLATION points every tool
# at another tree laid out the same way: the engine build uses a copy whose
# every `en` is empty, so each row keeps its Japanese (build.py --engine-only).
DEFAULT_TRANSLATION: Final = os.path.join(ROOT, 'translation')
TRANSLATION: Final = os.environ.get('PERSONA_TRANSLATION') or DEFAULT_TRANSLATION
# The dialogue font's edition: `large` (sheet.png, the release) or `small`
# (small_serif.png). Each has its own generated files, vwf_<kind>_<edition>.*
# in latin-alphabet/assets/fonts; PERSONA_FONT picks the one a build and every tool it
# runs measures and draws with (build.py --mods='english-translation(font=small)').
FONT_EDITIONS: Final = ('large', 'small')
# the edition build/ was last assembled in (build.py writes it)
BUILT_EDITION_FILE: Final = os.path.join(ROOT, 'build', 'font_edition')
FONT_EDITION: Final = os.environ.get('PERSONA_FONT') or 'large'
FONT_DIR: Final = os.path.join(ROOT, 'src', 'mods', 'latin-alphabet', 'assets', 'fonts')
if FONT_EDITION not in FONT_EDITIONS:
    raise ImportError(f'toolpath: PERSONA_FONT is {FONT_EDITION!r}; the editions are {FONT_EDITIONS}')


def font_path(kind: str, edition: str = FONT_EDITION) -> str:
    """One generated dialogue-font file: `font`, `width`, `index` (.bin),
    `glyphs` (.asm) or `preview` (.png), of an edition (the current one)."""
    ext = {'glyphs': 'asm', 'preview': 'png'}.get(kind, 'bin')
    return os.path.join(FONT_DIR, f'vwf_{kind}_{edition}.{ext}')
SKIP: Final = frozenset(('__pycache__', 'assets', 'node_modules'))


def folders() -> list[str]:
    """Every folder under src/ and tools/ that holds a .py file, sorted."""
    found: list[str] = []
    seen: dict[str, str] = {}
    for top in ('src', 'tools'):
        for parent, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs[:] = sorted(d for d in dirs if d not in SKIP)
            modules = [f for f in files if f.endswith('.py')]
            if not modules:
                continue
            found.append(parent)
            for name in modules:
                if name in seen and name != 'toolpath.py':
                    raise ImportError(f'toolpath: two tools are called {name}:'
                                      f' {seen[name]} and {parent}')
                seen[name] = parent
    return found


def script(name: str) -> str:
    """The path of the tool called `name` (`btlp.py`), wherever its folder
    is: scripts are run by name, never by a typed folder."""
    for folder in folders():
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(f'toolpath: no tool called {name}')


for _folder in reversed(folders()):
    if _folder not in sys.path:
        sys.path.insert(0, _folder)
