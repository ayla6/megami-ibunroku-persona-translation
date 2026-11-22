"""The mods: one folder each under src/mods/, described by its mod.tsv.

A mod's folder holds everything that is only that mod's: its assembly (one
file per overlay it patches, placed by its asm.tsv: asm_main.py writes
build/main.asm from the mods that are on), the
generators it alone uses, its files that are not code in assets/, its
README, and mod.tsv - two columns,
key and value:

    name         what it is called. Its slug (`Unified save menu` ->
                 `unified-save-menu`) is the mod's one identifier everywhere:
                 its folder (src/mods/unified-save-menu/), its release layer
                 (`unified-save-menu.p1mod`), its `--mods` name, `requires`
                 rows and part conditions, the release manifest, the web
                 patcher's remembered selections, and its armips define
                 (MOD_UNIFIED_SAVE_MENU)
    description  what it does, for players (the web patcher, the release
                 README, the layer)
    author       optional author credit, shown in the patcher and stored in the layer
    requires     a mod's slug, one row per mod it needs (a mod that only replaces
                 files, like Black Mark or the dub, needs none). A mod has no version of its own: a
                 release is one build of all of them, and publishing stamps
                 the release's tag into its manifest and every layer
                 (tools/publish_patches.py).
    default      yes: ticked on the web patcher until the player unticks it,
                 and part of a bare `--mods`
    always       yes: always applied, never an option (base, alphabet, fmv, english)
    release      yes: shipped as a release layer
    marker       yes: a dependency only, never picked: it does nothing useful
                 on its own (the movie subtitle renderer without subtitles to
                 show), so it is on exactly when a mod or a picked choice
                 requires it. Optional (no by default).
    translation  yes: the language (english). An engine-only build
                 (PERSONA_ENGINE_ONLY, build.py --engine-only) runs its tools
                 with no English, so its choices are off and require
                 nothing. Optional (no by default).
    warning      what the web patcher says when the mod is turned off.
                 Optional.
    integrates   SLUG or SLUG(TOKEN), TEXT: something the mod genuinely does
                 with that mod or choice on (not a compatibility part); the
                 web patcher offers it in the mod's settings.
    option       GROUP, KEY, NAME, DESCRIPTION (tab-separated), one row per
                 choice: within a GROUP one KEY is on at a time, the group's
                 first by default. english's `font` group is the font
                 editions (KEY = toolpath.FONT_EDITIONS).
    extra        KEY, NAME, DESCRIPTION: an additive part of the mod, off
                 unless picked.
                 Either may end with a `requires=SLUG,...` cell: the mods
                 that choice needs (English's subtitles need fmv-translation).

A build names a mod's choices on the mod: `--mods=english-translation(font=small)`,
`--mods=some-mod(KEY)` for an extra, several joined by commas inside the
parentheses. A mod picks up what it needs from the OTHER mods that are on by
itself (its `when` parts, in the release); those are never named.

There is no typed order: a mod is applied after the mods it requires, and
mods at the same depth go by name (ordered).

base is the language-neutral engine, alphabet what an alphabet needs (the
variable-width text, the longer-text mechanics, the Latin name entry),
fmv the movie subtitle and frame engine, english the translation on top of
them. Base, alphabet and English have separate release layers.

This is the single source of mod names and wording: build.py, the release
builder and the web patcher's features.js all read it. Typed Python
(AGENTS.md).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Final

ROOT: Final = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODS_DIR: Final = os.path.join(ROOT, 'src', 'mods')
KEYS: Final = ('name', 'description', 'default', 'always', 'release')
OPTIONAL: Final = {'marker': 'no', 'warning': '', 'translation': 'no', 'author': ''}
REPEATED: Final = ('requires', 'option', 'extra', 'integrates')


from range_parameters import RangeSetting


@dataclass(frozen=True)
class Choice:
    """One of a mod's choices: an option of a group (one on at a time, the
    group's first by default) or, with no group, an extra (off by default)."""
    group: str                    # '' for an extra
    key: str
    name: str
    description: str
    requires: tuple[str, ...] = ()   # the mods this choice needs

    @property
    def token(self) -> str:
        """How a selection and a part's condition name it: `font=small`, or
        an extra's KEY."""
        return f'{self.group}={self.key}' if self.group else self.key


@dataclass(frozen=True)
class Integration:
    """Something a mod genuinely does with another mod on (not a
    compatibility part): the page offers that mod in this one's settings."""
    other: str                    # the other mod's slug, or `slug(token)` for one of its choices
    text: str                     # what the two do together


@dataclass(frozen=True)
class Mod:
    name: str
    description: str
    requires: tuple[str, ...]     # the labels of the mods it needs
    default: bool
    always: bool                  # always applied: base, alphabet, fmv, english
    release: bool
    folder: str
    marker: bool = False          # a dependency only: on when required, never picked                   # absolute path of its src/mods/<slug>/ folder
    choices: tuple[Choice, ...] = ()   # its options (by group) and extras
    warning: str = ''             # what the page says against turning it off
    integrates: tuple[Integration, ...] = ()   # what it does together with other mods
    translation: bool = False     # the language: its choices are off in an engine-only build

    ranges: tuple[RangeSetting, ...] = ()
    author: str = ''

    def needs(self, tokens: frozenset[str] | set[str]) -> tuple[str, ...]:
        """The mods it requires with those choices picked."""
        return self.requires + tuple(n for c in self.choices if c.token in tokens
                                     for n in c.requires)

    def groups(self) -> dict[str, list[Choice]]:
        """{group: its options, the default first}."""
        out: dict[str, list[Choice]] = {}
        for choice in self.choices:
            if choice.group:
                out.setdefault(choice.group, []).append(choice)
        return out

    def defaults(self) -> frozenset[str]:
        """The tokens on when nothing is picked: each group's first option."""
        return frozenset(options[0].token for options in self.groups().values()) | frozenset(
            f"{r.key}={r.default}" for r in self.ranges)

    def pick(self, picked: str) -> frozenset[str]:
        """The tokens of `GROUP=KEY,KEY` (what a build names in the mod's
        parentheses) on top of the defaults; an unknown name is refused."""
        out = dict((c.group, c.token) for c in self.choices
                   if c.group and c.token in self.defaults())
        out.update({r.key: f"{r.key}={r.default}" for r in self.ranges})
        extras: set[str] = set()
        known = {c.token for c in self.choices}
        values = {r.key: r.default for r in self.ranges}
        named: set[str] = set()
        for name in filter(None, (n.strip() for n in picked.split(','))):
            parameter, sep, value = name.partition("=")
            setting = next((r for r in self.ranges if r.key == parameter), None)
            if setting and sep:
                values[parameter] = setting.validate(value)
                named.add(parameter)
                out[parameter] = f"{parameter}={values[parameter]}"
                continue
            if name not in known:
                raise ValueError(f'{self.slug} has no choice {name}; it has '
                                 + (', '.join(sorted(known)) or 'none'))
            group = name.partition('=')[0] if '=' in name else ''
            if group:
                out[group] = name
            else:
                extras.add(name)
        for r in self.ranges:              # a range not named takes the one it follows
            if r.follows and r.key not in named:
                out[r.key] = f"{r.key}={r.nearest(values[r.follows])}"
        return frozenset(out.values()) | frozenset(extras)

    @property
    def label(self) -> str:
        """Its identifier: the slug of its name (there is no other)."""
        return slug(self.name)

    @property
    def define(self) -> str:
        """The armips define that says it is on: MOD_<SLUG> (dashes as _)."""
        return 'MOD_' + self.label.upper().replace('-', '_')

    @property
    def slug(self) -> str:
        return slug(self.name)


def slug(text: str) -> str:
    """A file or folder name from a mod's name: lowercase words joined by dashes."""
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def _read(folder: str) -> Mod:
    path = os.path.join(folder, 'mod.tsv')
    values: dict[str, str] = {}
    requires: list[str] = []
    choices: list[Choice] = []
    integrates: list[Integration] = []
    ranges: list[RangeSetting] = []
    with open(path, encoding='utf-8') as source:
        for number, line in enumerate(source, 1):
            line = line.rstrip('\n')
            if not line:
                continue
            key, sep, value = line.partition('\t')
            if key == 'range' and sep:
                cells = value.split('\t')
                if len(cells) not in (7, 8) or len(cells) == 8 and not cells[7].startswith('follows='):
                    raise ValueError(f'{path}:{number}: range is KEY MIN MAX STEP DEFAULT NAME EDITS [follows=KEY]')
                follows = cells[7].removeprefix('follows=') if len(cells) == 8 else ''
                if follows and not any(r.key == follows and not r.follows for r in ranges):
                    raise ValueError(f'{path}:{number}: follows names no earlier range of its own')
                setting = RangeSetting(cells[0], *(int(x) for x in cells[1:5]), cells[5], cells[6],
                                       follows)
                if setting.step <= 0 or setting.minimum > setting.maximum:
                    raise ValueError(f'{path}:{number}: invalid range bounds')
                setting.validate(str(setting.default))
                if any(r.key == setting.key for r in ranges) or any(c.group == setting.key for c in choices):
                    raise ValueError(f'{path}:{number}: duplicate range key')
                ranges.append(setting)
                continue
            if key == 'requires' and sep:
                if '\t' in value:
                    raise ValueError(f'{path}:{number}: requires is one LABEL (mods have no'
                                     ' versions: the release is the version)')
                requires.append(value)
                continue
            if key == 'integrates' and sep:
                other, tab, text = value.partition('\t')
                if not tab or not other or not text or '\t' in text:
                    raise ValueError(f'{path}:{number}: integrates is SLUG, TEXT')
                integrates.append(Integration(other, text))
                continue
            if key in ('option', 'extra') and sep:
                cells = value.split('\t')
                needs: tuple[str, ...] = ()
                if cells and cells[-1].startswith('requires='):
                    needs = tuple(filter(None, cells.pop()[len('requires='):].split(',')))
                width = 4 if key == 'option' else 3
                if len(cells) != width or not all(cells):
                    raise ValueError(f'{path}:{number}: ' + (
                        'option is GROUP, KEY, NAME, DESCRIPTION' if key == 'option'
                        else 'extra is KEY, NAME, DESCRIPTION') + ' [requires=LABEL,...]')
                choices.append(Choice(*([] if key == 'option' else ['']), *cells,
                                      requires=needs))
                continue
            if not sep or (key not in KEYS and key not in OPTIONAL) or key in values:
                raise ValueError(f'{path}:{number}: expected one of {", ".join(KEYS)}'
                                 ' once (or requires / option / extra / integrates, any number of times), a tab, then'
                                 ' its value')
            values[key] = value
    missing = [key for key in KEYS if key not in values]
    if missing:
        raise ValueError(f'{path}: missing {", ".join(missing)}')
    for key, fallback in OPTIONAL.items():
        values.setdefault(key, fallback)
    for key in ('default', 'always', 'release', 'marker', 'translation'):
        if values[key] not in ('yes', 'no'):
            raise ValueError(f'{path}: {key} is yes or no')
    mod = Mod(values['name'], values['description'],
              tuple(requires), values['default'] == 'yes',
              values['always'] == 'yes', values['release'] == 'yes', folder, values['marker'] == 'yes',
              tuple(choices), values['warning'], tuple(integrates),
              values['translation'] == 'yes', author=values['author'], ranges=tuple(ranges))
    if os.path.basename(folder) != mod.slug:
        raise ValueError(f'{path}: the folder of "{mod.name}" is named {mod.slug}')
    return mod


_LOADED: list[Mod] | None = None


def load() -> list[Mod]:
    """Every mod, in apply order (ordered); the labels and names are unique."""
    global _LOADED
    if _LOADED is None:
        found = [_read(os.path.join(MODS_DIR, name)) for name in sorted(os.listdir(MODS_DIR))
                 if os.path.isfile(os.path.join(MODS_DIR, name, 'mod.tsv'))]
        for field in ('label', 'name'):
            values = [getattr(mod, field) for mod in found]
            if len(set(values)) != len(values):
                raise ValueError(f'src/mods: two mods share a {field}')
        _LOADED = ordered(found)
        check_requirements(_LOADED)
    return _LOADED


def ordered(found: list[Mod]) -> list[Mod]:
    """Each mod after every mod it requires: by depth (base 0, a mod one more
    than the deepest mod it requires), then by name."""
    by = {mod.label: mod for mod in found}
    for mod in found:
        for need in every_need(mod):
            if need not in by:
                raise ValueError(f'{mod.label} requires {need}, which is not a mod')
        for integration in mod.integrates:
            if integration.other.partition('(')[0] not in by:
                raise ValueError(f'{mod.label} integrates {integration.other}, which is not a mod')
    depth: dict[str, int] = {}

    def depth_of(mod: Mod, path: tuple[str, ...] = ()) -> int:
        if mod.label in path:
            raise ValueError('src/mods: these mods require each other in a circle: '
                             + ' -> '.join(path + (mod.label,)))
        if mod.label not in depth:
            depth[mod.label] = 1 + max((depth_of(by[need], path + (mod.label,))
                                        for need in every_need(mod)), default=-1)
        return depth[mod.label]

    return sorted(found, key=lambda mod: (depth_of(mod), mod.name.lower()))


def every_need(mod: Mod) -> tuple[str, ...]:
    """What the mod or any of its choices can require."""
    return mod.requires + tuple(n for c in mod.choices for n in c.requires)


def with_needs(labels: list[str], picked: dict[str, frozenset[str]]) -> list[str]:
    """`labels` and every mod they (and the always-on mods), with their
    picked choices (default: their defaults), require, transitively - how a
    marker comes to be on. Apply order."""
    by = by_label()
    on = set(labels) | {mod.label for mod in load() if mod.always}
    engine = bool(os.environ.get('PERSONA_ENGINE_ONLY'))
    todo = list(on)
    while todo:
        mod = by[todo.pop()]
        # an engine-only build has no English: the translation's choices
        # (its movie subtitles) need nothing
        tokens = frozenset() if engine and mod.translation else picked.get(mod.label, mod.defaults())
        for need in mod.needs(tokens):
            if need not in on:
                on.add(need)
                todo.append(need)
    return [mod.label for mod in load() if mod.label in on and not mod.always]


def by_name() -> dict[str, Mod]:
    """Every mod by its slug (`unified-save-menu`), what a build names."""
    return {mod.slug: mod for mod in load()}


def parse_mods(text: str) -> list[tuple[str, str]]:
    """`a,b(font=small,x),c` -> [(a, ''), (b, 'font=small,x'), (c, '')]: the
    names a --mods list gives, each with what its parentheses pick."""
    items: list[str] = []
    depth, start = 0, 0
    for at, char in enumerate(text + ','):
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif char == ',' and depth == 0:
            items.append(text[start:at])
            start = at + 1
        if depth not in (0, 1):
            break
    out: list[tuple[str, str]] = []
    for item in filter(None, (i.strip() for i in items + ([text[start:]] if depth else []))):
        match = re.fullmatch(r'([^(),\s]+)\s*(?:\(([^()]*)\))?', item)
        if depth or not match:
            raise ValueError(f'cannot read the mod list {text!r}: names joined by commas,'
                             ' a mod\'s choices in parentheses after it')
        out.append((match.group(1), match.group(2) or ''))
    return out


def check_requirements(found: list[Mod]) -> None:
    """Every requirement names a mod that comes before it (a mod can only
    need what is applied under it)."""
    seen: set[str] = set()
    for mod in found:
        for need in every_need(mod):
            if need not in seen:
                raise ValueError(f'{mod.label} requires {need}, which is not a mod'
                                 ' that comes before it')
        seen.add(mod.label)


def options() -> list[Mod]:
    """The mods a build or a player can turn on or off (not the always-on ones)."""
    return [mod for mod in load() if not mod.always]


def by_label() -> dict[str, Mod]:
    return {mod.label: mod for mod in load()}


def released() -> list[Mod]:
    """The released mods that are options (each one layer); a marker with a
    layer is among them, applied when something requires it."""
    return [mod for mod in options() if mod.release]


def pickable() -> list[Mod]:
    """What a player or a build can turn on by name: not the markers."""
    return [mod for mod in options() if not mod.marker]
