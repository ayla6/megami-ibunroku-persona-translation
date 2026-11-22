"""Build and verify the release: P1MOD layers (docs/MOD_ENGINE.md).

Only the original Rev 0 disc is patched. A release is one layer file per
mod, named after it in src/mods/*/mod.tsv, all made from build trees - no
disc image is assembled per variant:

  base.p1mod       retail Rev 0 -> language-neutral base
  latin-alphabet.p1mod
                   base -> alphabet engines and fonts, without English
  english-translation.p1mod
                   alphabet -> English at its defaults, with a part per
                   other choice. Each tier checks its preceding input files
  <name>.p1mod     one per release mod (`unified-save-menu.p1mod`): its
                   parts, applied in apply order, each under the condition
                   its row names (mods written as a build names them) -
                     -                  the lowest supported tier
                                        -> this mod at its defaults; higher
                                        tiers have conditional parts
                     slug(token)        what that choice of the mod changes
                                        over its defaults (`english-translation(font=small)`,
                                        `english-translation(subtitles=off)`)
                     slug(t1,t2)        what two of its choices change together
                                        beyond their own parts, when they do
                     other              what this mod and an earlier one built
                                        together change beyond both alone (a
                                        pair whose layers write the same
                                        bytes; the later mod carries it)
                     other(token)       what this mod changes beyond its own
                                        layer while another mod has that
                                        choice (the small font)

Markers (mod.tsv `marker`: the movie renderer) are never picked: a build
turns one on when a mod or a picked choice requires it (mods.with_needs),
and without a layer of its own its bytes ride in the parts of whatever
turned it on.

Production builds only native trees needed to make layers and compatibility
parts. Intermediates remain uncompressed; each finished P1MOD is compressed
once. Known higher-order interactions are declared by the owning mod's
compatibility.tsv. Release verification runs native combined comparisons,
interaction discovery and browser/standalone disc/PPF parity by default,
then marks files `verified`. `--no-verify-release` writes production output
with state `untested`.
`--recheck` also bypasses native variant snapshots. Native snapshots are reused
only when their input keys and inventories match.

manifest.tsv has one row per layer: layer, kind (base / option), label,
choices (the mod's choice tokens, each group's default first), requires,
version (the
release tag, stamped by publish_patches.py with the release column - a mod
has no version of its own), bytes, sha1, build_key; the base row also has
the original disc's source_bytes and source_chd_sha1 (the raw SHA-1 a CHD
of it carries in its header), which the web patcher identifies a disc by.
A release whose build inputs are unchanged (build_key) is reused.

    python tools/build_patches.py                    # dist/patches
    python tools/build_patches.py --no-verify-release # production only
    python tools/build_patches.py --publish-release  # verify, then upload
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from collections import OrderedDict
import functools
from itertools import combinations
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
# build sets the tier's environment before toolpath freezes its paths.
sys.path.insert(0, str(ROOT / 'src' / 'pipeline'))
import build                # noqa: E402
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import build_disc           # noqa: E402
import build_step_cache     # noqa: E402
import image_check          # noqa: E402
import modpack              # noqa: E402
import mods                 # noqa: E402

# The released mods, in apply order (src/mods/*/mod.tsv, read by mods.py -
# the single source of their names and wording). Each is one layer.
CHOICE_ORDER: Final = [mod.label for mod in mods.released()]
# Dependency-ordered foundations, then English (the reference for optional mods).
ROOT_MOD: Final = mods.by_label()['base']
ALPHABET_MOD: Final = mods.by_label()['latin-alphabet']
BASE_MOD: Final = mods.by_label()['english-translation']
FOUNDATIONS: Final = (ROOT_MOD, ALPHABET_MOD)
BASE_LAYER: Final = ROOT_MOD.slug + '.p1mod'
TRANSLATION_LAYERS: Final = ' '.join(mod.slug + '.p1mod' for mod in (*FOUNDATIONS, BASE_MOD))
BASE_TREE: Final = ROOT / 'build' / 'release-base-tree'
TREES: Final = ROOT / 'build' / 'release-trees'
MANIFEST: Final = 'manifest.tsv'
PATCHER: Final = 'persona-patch.py'     # the standalone applier, shipped beside the layers
PATCHER_SOURCE: Final = ROOT / 'src' / 'pipeline' / 'persona_patch.py'
INPROGRESS: Final = '.inprogress'    # an older run's in-progress layer names, cleared on start
MANIFEST_FIELDS: Final = ('layer', 'kind', 'label', 'state', 'choices', 'requires', 'version', 'bytes',
                           'sha1', 'build_key', 'source_bytes', 'source_chd_sha1', 'release')


@dataclass(frozen=True)
class Variant:
    """One build.py patch set the release builds, and why."""
    name: str                     # 'base', a mod's slug, 'a+b', 'all'
    labels: tuple[str, ...]       # release labels, in CHOICE_ORDER
    role: str                     # 'base', 'option', 'compat' or 'check'


@dataclass(frozen=True)
class CompatibilityRecipe:
    owner: str
    tier: str
    when: str


def compatibility_recipes() -> list[CompatibilityRecipe]:
    result: list[CompatibilityRecipe] = []
    for mod in mods.released():
        path = Path(mod.folder) / 'compatibility.tsv'
        if not path.exists():
            continue
        with path.open(newline='') as stream:
            reader = csv.DictReader(stream, delimiter='\t')
            if reader.fieldnames != ['tier', 'when']:
                raise ValueError(f'{path}: invalid compatibility columns')
            for row in reader:
                if row['tier'] not in ('base', 'alphabet', 'english'):
                    raise ValueError(f'{path}: invalid compatibility tier')
                for label, picked in mods.parse_mods(row['when']):
                    if label not in mods.by_label():
                        raise ValueError(f'{path}: unknown mod {label}')
                    mods.by_label()[label].pick(picked)
                result.append(CompatibilityRecipe(mod.label, row['tier'], row['when']))
    return result


def produce_recipe(source: modpack.Source, packs: dict[str, modpack.Pack], rev0: Path,
                   recipe: CompatibilityRecipe, number: int) -> None:
    if any(part.when == recipe.when for part in packs[recipe.owner].parts):
        return
    conditions = mods.parse_mods(recipe.when)
    labels = {recipe.owner, *(label for label, _ in conditions)}
    optional = tuple(label for label in CHOICE_ORDER if label in labels)
    tier_labels = ['base'] + (['latin-alphabet'] if recipe.tier != 'base' else [])
    if recipe.tier == 'english':
        tier_labels.append('english-translation')
    selected = {label: mods.by_label()[label].defaults() for label in [*tier_labels, *optional]}
    for label, picked in conditions:
        selected[label] = mods.by_label()[label].pick(picked)
    name = f'compatibility-{recipe.owner}-{number}'
    flags = {'base': ['--base-only'], 'alphabet': ['--engine-only'], 'english': []}[recipe.tier]
    # the tiers are named: build.py turns on only the tiers a --mods list
    # names or requires
    configured = ','.join([*(mods.by_label()[label].slug for label in tier_labels
                             if not any(label == l for l, _p in conditions)),
                           recipe.owner, *(
        condition(mods.by_label()[label], mods.by_label()[label].pick(picked))
        if picked else label
        for label, picked in conditions
        if picked or not mods.by_label()[label].always)])
    subprocess.run([sys.executable, str(Path(__file__)), *flags, '--rev0', str(rev0),
                    '--mods=' + configured, '--trees', name + ':' + ','.join(optional)],
                   check=True, cwd=ROOT)
    if not add_part(source, packs, recipe.owner, recipe.when, selected,
                    kept_tree(source, TREES / name)):
        packs[recipe.owner].parts.append(modpack.Part(recipe.when, []))


def release_selection(labels: tuple[str, ...]) -> list[str]:
    """The build.py mod labels for a set of release labels, in build order."""
    return [name for name in build.MODS if name in labels]


def wording(label: str) -> tuple[str, str]:
    """A mod's name and description (its mod.tsv)."""
    mod = mods.by_label()[label]
    return mod.name, mod.description


def requirements(mod: mods.Mod) -> list[str]:
    """A mod's requirements as layer rows. Mods without a layer of their own
    (the FMV marker) are left out."""
    return [need for need in mod.requires if mods.by_label()[need].release]


slug = mods.slug


def option_layer(label: str) -> str:
    """A mod's layer file, named after it like its folder
    (`label` stays its identifier in the manifest, the page and history)."""
    return mods.by_label()[label].slug + '.p1mod'


def release_labels() -> list[str]:
    """Every layer in apply order: base, alphabet, English, then optional mods."""
    return [mod.label for mod in FOUNDATIONS] + [BASE_MOD.label] + CHOICE_ORDER


def release_file_names() -> list[str]:
    return [option_layer(label) for label in release_labels()]


def check_choices() -> None:
    """Fail before any work when two layers would share a file name (the
    mods themselves are checked by mods.load: unique labels and names)."""
    names = release_file_names()
    if len(set(names)) != len(names):
        raise ValueError('two release mods make the same layer file name: '
                         + ', '.join(sorted({n for n in names if names.count(n) > 1})))


def new_pack(mod: mods.Mod) -> modpack.Pack:
    return modpack.Pack(mod.label, [], mod.name, mod.description, requires=requirements(mod),
                        choices=[(c.token, c.name) for c in mod.choices], author=mod.author)


def default_selection(labels: tuple[str, ...] | list[str]) -> modpack.Selection:
    """Base, alphabet, English and `labels` on, each at its defaults."""
    return {label: mods.by_label()[label].defaults() for label in [*(mod.label for mod in FOUNDATIONS), BASE_MOD.label, *labels]}


def condition(mod: mods.Mod, tokens: frozenset[str] | set[str] | list[str]) -> str:
    """A part condition: the mod with those choices (`english-translation(font=small)`)."""
    return f'{mod.label}({",".join(sorted(tokens))})' if tokens else ''


def other_choices() -> list[tuple[mods.Mod, mods.Choice]]:
    """Every released mod's choices past its defaults: each is built in a child."""
    return [(mod, choice) for mod in [*FOUNDATIONS, BASE_MOD, *mods.released()] for choice in mod.choices
            if choice.token not in mod.defaults()]


def choice_pairs() -> list[tuple[mods.Mod, mods.Choice, mods.Choice]]:
    """Two non-default choices of one mod from different groups (or extras):
    built together to check their parts add up."""
    out = []
    for mod in [*FOUNDATIONS, BASE_MOD, *mods.released()]:
        others = [c for c in mod.choices if c.token not in mod.defaults()]
        for i, a in enumerate(others):
            for b in others[i + 1:]:
                if not (a.group and a.group == b.group):
                    out.append((mod, a, b))
    return out


_HASHED: dict[tuple[str, int, int], str] = {}    # (path, size, mtime_ns) -> digest


def sha1(path: Path) -> str:
    """SHA-1 of a file; a file whose size and mtime did not move since it
    was hashed is not read again (the manifest is rewritten at every step)."""
    st = os.stat(path)
    ident = (os.fspath(path), st.st_size, st.st_mtime_ns)
    if ident not in _HASHED:
        _HASHED[ident] = _sha1(path)
    return _HASHED[ident]


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


@functools.lru_cache(maxsize=None)
def chd_raw_sha1(path: Path) -> str:
    """The raw SHA-1 a CHD of this single-track image carries in its header.

    chdman stores each 2352-byte sector as a 2448-byte frame (96 subcode
    bytes, zero for a .bin) and pads the track to a multiple of 4 frames;
    the header's raw SHA-1 covers exactly those bytes. The web patcher
    identifies a CHD by it without unpacking anything."""
    digest = hashlib.sha1()
    subcode = bytes(96)
    frames = 0
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(2352 * 1024), b''):
            for at in range(0, len(chunk), 2352):
                digest.update(chunk[at:at + 2352])
                digest.update(subcode)
                frames += 1
    for _ in range(-frames % 4):
        digest.update(bytes(2448))
    return digest.hexdigest()


def release_fingerprint(rev0: Path) -> str:
    """What feeds the built layers: sources, tables, extracted data, the
    tools that build them and their library versions."""
    from PIL import features as pil_features
    dependencies = sorted(f'{d.metadata["Name"]}=={d.version}' for d in metadata.distributions()
                          if d.metadata.get('Name'))
    paths = [ROOT / 'src', ROOT / 'translation', ROOT / 'data/psx',
             ROOT / 'data/cache', ROOT / 'data/extracted_text',
             ROOT / 'tools/build_patches.py',
             rev0, Path(sys.executable)]
    if build.ARMIPS:
        paths.append(Path(build.ARMIPS))
    # Editions and language-free tiers rewrite these generated products.
    # Their sources and generator are already in paths; products are not inputs.
    generated = {Path(toolpath.font_path(kind, edition)).resolve()
                 for edition in ('large', 'small')
                 for kind in ('font', 'width', 'index', 'glyphs')}
    inputs = [child for path in paths for child in
              (path.rglob('*') if path.is_dir() else (path,))
              if child.is_file() and child.resolve() not in generated
              and '__pycache__' not in child.parts and child.suffix != '.pyc']
    key: str = build_step_cache.fingerprint(inputs, context=(
        *dependencies, pil_features.version_module('freetype2'), 'release-layers-v1-ranges'))
    return key


def read_manifest(path: Path) -> dict[str, dict[str, str]]:
    """Rows keyed by layer file; an older (xdelta) manifest counts as none."""
    if not path.exists():
        return {}
    with open(path, encoding='utf-8', newline='') as source:
        reader = csv.DictReader(source, delimiter='\t')
        if not reader.fieldnames or 'layer' not in reader.fieldnames:
            return {}
        return {row['layer']: row for row in reader}


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                     dir=path.parent, delete=False) as out:
        writer = csv.DictWriter(out, fieldnames=MANIFEST_FIELDS, delimiter='\t',
                                lineterminator='\n', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    os.chmod(out.name, 0o644)      # a temporary file starts private; the manifest is published
    os.replace(out.name, path)


_TREE_SOURCE: modpack.Source | None = None
FileStamp = tuple[int, int, int, int, int]
# Live entries include the retail comparison for a particular disc path.
# Snapshot entries hold raw file bytes and can share across hard links.
_TREE_READS: OrderedDict[tuple[str | None, FileStamp], bytes | None] = OrderedDict()
_TREE_BYTES = 0
# Hold the changed-file working set, including dubbed movies, across variants.
# A cache smaller than that set evicts each movie before the next scan reaches
# it. This remains a hard cap; retail bytes are owned by Source separately.
_TREE_LIMIT: Final = 512 * 1024 * 1024


def read_tree_file(source: modpack.Source, path: Path, disc_path: str | None) -> bytes | None:
    """Read a snapshot, or omit a live file that matches its retail counterpart."""
    global _TREE_SOURCE, _TREE_BYTES
    import file_digest
    if _TREE_SOURCE is not source:
        _TREE_READS.clear()
        _TREE_BYTES = 0
        _TREE_SOURCE = source
    stamp = file_digest.signature(path)
    key = (disc_path, stamp)
    if key in _TREE_READS:
        _TREE_READS.move_to_end(key)
        return _TREE_READS[key]
    data = path.read_bytes()
    if file_digest.signature(path) != stamp:
        raise RuntimeError(f'{path}: tree file changed while reading')
    value: bytes | None = data
    if disc_path is not None:
        raw = build_disc.is_raw_file(disc_path, data)
        if modpack.same_file_data(data, source.read(disc_path, raw), raw):
            value = None
    _TREE_READS[key] = value
    _TREE_BYTES += len(value) if value is not None else 0
    while _TREE_BYTES > _TREE_LIMIT or len(_TREE_READS) > 1024:
        _, removed = _TREE_READS.popitem(last=False)
        _TREE_BYTES -= len(removed) if removed is not None else 0
    return value


def tree_files(source: modpack.Source, directory: Path) -> dict[str, bytes]:
    """{DISC/PATH: bytes} of a build tree's disc files that differ from retail."""
    out: dict[str, bytes] = {}
    for disc_path, local in modpack.tree(str(directory), source).items():
        if disc_path not in modpack.LAYOUT_FILES:
            changed = read_tree_file(source, Path(local), disc_path)
            if changed is not None:
                out[disc_path] = changed
    return out


def variant_files(source: modpack.Source, directory: Path) -> dict[str, bytes]:
    """A live build needs retail comparison; a verified snapshot already omits retail."""
    return (tree_files(source, directory) if directory == ROOT / 'build'
            else kept_tree(source, directory))


def save_tree(source: modpack.Source, directory: Path, from_tree: Path | None = None) -> None:
    """Keep changed game files in shared immutable blobs, without retail copies."""
    shutil.rmtree(directory, ignore_errors=True)
    import file_digest
    blobs = ROOT / 'build/step_cache/tree-blobs'
    blobs.mkdir(parents=True, exist_ok=True)
    from_tree = from_tree or ROOT / 'build'
    for disc_path, data in variant_files(source, from_tree).items():
        value = hashlib.sha1(data).hexdigest()
        blob = blobs / value
        if not blob.is_file() or file_digest.digest(blob) != value:
            build_step_cache.clone(from_tree / disc_path, blob)
        if file_digest.digest(blob) != value:
            raise RuntimeError(f'{disc_path}: snapshot differs from build output')
        copy = directory / disc_path
        copy.parent.mkdir(parents=True, exist_ok=True)
        # Only immutable snapshots share an inode. Live build products remain
        # independent, so the next assembly cannot modify a saved variant.
        try:
            os.link(blob, copy)
        except OSError:
            build_step_cache.clone(blob, copy)


def kept_tree(source: modpack.Source, directory: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for disc_path, local in modpack.tree(str(directory), source).items():
        data = read_tree_file(source, Path(local), None)
        assert data is not None
        out[disc_path] = data
    return out


def selection_packs(packs: dict[str, modpack.Pack], selection: modpack.Selection) -> list[modpack.Pack]:
    """The packs a selection applies, in apply order."""
    return [packs[label] for label in release_labels() if label in selection and label in packs]


def check_range_values(source: modpack.Source, packs: dict[str, modpack.Pack]) -> None:
    """Every mod at once, each range at its maximum: every range byte holds
    the player's value in the merged files, whatever a later mod's part
    (built at the defaults) wrote there. The layer comparisons only see the
    defaults, where a lost value looks right."""
    import csv
    selection = default_selection(CHOICE_ORDER)
    expected: dict[tuple[str, int], int] = {}
    for label, pack in packs.items():
        mod = mods.by_label()[label]
        if not mod.ranges:
            continue
        selection[label] = frozenset({t for t in selection[label]
                                      if t.split('=')[0] not in {r.key for r in mod.ranges}}
                                     | {f'{r.key}={r.maximum}' for r in mod.ranges})
        for setting in mod.ranges:
            with (Path(mods.ROOT) / setting.edits).open(newline='') as stream:
                for row in csv.DictReader(stream, delimiter='\t'):
                    if row['parameter'] == setting.key:
                        scale = modpack.Scale(int(row['offset']), setting.key, int(row['original']))
                        expected[(row['path'], scale.offset)] = scale.value(setting.maximum)
    files = merged_files(source, packs, selection)
    wrong = [f'{path}+{offset:#x}: {files[path][offset]} (want {value})'
             for (path, offset), value in sorted(expected.items())
             if path in files and files[path][offset] != value]
    if wrong:
        raise RuntimeError('release: a range value is lost after its layer: ' + '; '.join(wrong))
    print(f'release: {len(expected)} range byte(s) hold their maximum with every mod on', flush=True)


def merged_files(source: modpack.Source, packs: dict[str, modpack.Pack],
                 selection: modpack.Selection) -> dict[str, bytes]:
    # strict=False: the release merges a choice before it has built that
    # choice's part - that difference is what it is about to find
    files, _clashes = modpack.merge(source, selection_packs(packs, selection), selection,
                                    strict=False, track_clashes=False)
    return {path: bytes(data) for path, data in files.items()}


def differing(source: modpack.Source, expect: dict[str, bytes],
              actual: dict[str, bytes]) -> list[str]:
    """The disc paths where two {DISC/PATH: bytes} maps disagree (a missing
    path is the retail file; a movie is compared from each subheader on)."""
    wrong = []
    for disc_path in sorted(set(expect) | set(actual)):
        raw = disc_path.endswith('.STR')
        a = expect[disc_path] if disc_path in expect else source.read(disc_path, raw)
        b = actual[disc_path] if disc_path in actual else source.read(disc_path, raw)
        if not modpack.same_file_data(a, b, raw):
            wrong.append(disc_path)
    return wrong


def guard_retail_inputs(source: modpack.Source, root: modpack.Pack,
                        layer: modpack.Layer) -> None:
    """Validate original files in Base before any configurable layers edit them."""
    guarded = {edit.path for edit in root.parts[0].files}
    for edit in layer.files:
        if edit.path in guarded:
            continue
        data = source.read(edit.path, edit.raw)
        root.parts[0].files.append(modpack.FileEdit(
            edit.path, edit.raw, len(data), len(data),
            source=modpack.source_digest(data, edit.raw)))
        guarded.add(edit.path)


def add_part(source: modpack.Source, packs: dict[str, modpack.Pack], label: str, when: str,
             selection: modpack.Selection, built: dict[str, bytes]) -> bool:
    """Give `label`'s pack a part under `when`: what `built` (the selection's
    build) changes beyond the selection's layers merged. -> whether it did."""
    merged = merged_files(source, packs, selection)
    if not differing(source, merged, built):
        return False
    part = modpack.layer_from(label, source, merged, built)
    packs[label].parts.append(modpack.Part(when, part.files))
    print(f'release: {label}: a part for {when}', flush=True)
    return True


def overlapping_pairs(packs: dict[str, modpack.Pack]) -> list[tuple[str, ...]]:
    """Mod pairs whose parts write the same bytes of a file - the only
    pairs whose combined build can differ from the two layers merged."""
    written: dict[str, list[tuple[str, int, int]]] = {}
    for label in CHOICE_ORDER:
        for part in packs[label].parts:
            for edit in part.files:
                for span in edit.spans:
                    written.setdefault(edit.path, []).append(
                        (label, span.offset, span.offset + len(span.data)))
    semantic: dict[str,dict[str,set[int]]]={}
    byte_writers: dict[str,set[str]]={}
    for label in CHOICE_ORDER:
        for part in packs[label].parts:
            for edit in part.files:
                if edit.entries:
                    semantic.setdefault(edit.path,{}).setdefault(label,set()).update(e.index for e in edit.entries)
                if edit.spans: byte_writers.setdefault(edit.path,set()).add(label)
    pairs: set[tuple[str, ...]] = set()
    for path,writers in semantic.items():
        labels=list(writers)
        for i,a in enumerate(labels):
            for b in labels[i+1:]:
                if writers[a]&writers[b]: pairs.add(tuple(sorted((a,b),key=CHOICE_ORDER.index)))
            for b in byte_writers.get(path,set())-{a}:
                pairs.add(tuple(sorted((a,b),key=CHOICE_ORDER.index)))
    for spans in written.values():
        spans.sort(key=lambda s: s[1])
        for i, (a, start, end) in enumerate(spans):
            for b, other_start, _other_end in spans[i + 1:]:
                if other_start >= end:
                    break
                if a != b:
                    pairs.add(tuple(sorted((a, b), key=CHOICE_ORDER.index)))
    return sorted(pairs, key=lambda pair: [CHOICE_ORDER.index(label) for label in pair])


def check_combination(source: modpack.Source, packs: dict[str, modpack.Pack], name: str,
                      selection: modpack.Selection, built: dict[str, bytes]) -> None:
    """A variant's build tree must be its layers merged."""
    wrong = differing(source, merged_files(source, packs, selection), built)
    if wrong:
        raise RuntimeError(f'{name}: the build differs from its layers merged in '
                           + ', '.join(wrong[:8]) + ' - an interaction between three or more'
                           ' mods or options, which no part explains')
    print(f'release: {name}: build == its layers merged', flush=True)


def ppf_gives(ppf: Path, source: Path, expected: Path) -> bool:
    """Whether `source` with the PPF 3.0 `ppf` applied is byte for byte
    `expected` - patched in memory a chunk at a time, nothing written."""
    import struct
    data = ppf.read_bytes()
    if data[:5] != b'PPF30':
        raise RuntimeError(f'{ppf} is not a PPF 3.0')
    pos = 60 + (1024 if data[57] else 0)
    records: list[tuple[int, bytes]] = []
    while pos < len(data):
        offset, = struct.unpack_from('<Q', data, pos)
        n = data[pos + 8]
        records.append((offset, data[pos + 9:pos + 9 + n]))
        pos += 9 + n
    records.sort(key=lambda r: r[0])
    if source.stat().st_size != expected.stat().st_size:
        return False
    chunk = 64 << 20
    at = 0
    k = 0
    with open(source, 'rb') as a, open(expected, 'rb') as b:
        while True:
            block = bytearray(a.read(chunk))
            if not block:
                return True
            end = at + len(block)
            while k < len(records) and records[k][0] < end:
                offset, bytes_ = records[k]
                lo = max(offset, at)
                hi = min(offset + len(bytes_), end)
                block[lo - at:hi - at] = bytes_[lo - offset:hi - offset]
                if offset + len(bytes_) > end:
                    break                   # the rest lands in the next chunk
                k += 1
            if bytes(block) != b.read(len(block)):
                return False
            at = end


def layout_workspace(rev0: Path, ram: Path = Path('/dev/shm')) -> Path:
    """Reserve bounded scratch for one native image and the two PPFs."""
    fallback = ROOT / 'build'
    fallback.mkdir(parents=True, exist_ok=True)
    parent = fallback
    if (ram.is_dir() and os.access(ram, os.W_OK)
            and shutil.disk_usage(ram).free >= rev0.stat().st_size * 3):
        parent = ram
    return Path(tempfile.mkdtemp(prefix='persona-release-check-', dir=parent))


def check_browser_layout(rev0: Path, layers: list[Path], name: str,
                         directory: Path | None = None) -> None:
    """The browser's applier lays the disc out exactly as build_disc.py does
    (every layer at its first option: build/ holds that variant)."""
    work = layout_workspace(rev0)
    try:
        expected = work / 'build_disc.bin'
        build_disc.build_to(str(rev0), str(expected), str(directory or ROOT / 'build'))
        ppf = work / 'modpack_js.ppf'
        subprocess.run(['node', '--max-old-space-size=3072',
                        str(ROOT / 'tools/tests/webpatcher_modpack.js'),
                        str(ROOT / 'webpatcher/modpack.js'), str(rev0), str(expected),
                        '--compare', '--ppf', str(ppf), *map(str, layers)],
                       check=True)
        # the PPF over the original must give the same disc (applied while
        # comparing: no third image is written)
        if not ppf_gives(ppf, rev0, expected):
            raise RuntimeError(f'{name}: the web patcher\'s Build PPF does not give'
                               ' build_disc.py\'s disc')
        # the standalone Python applier shipped with the release, the same way
        py_ppf = work / 'persona_patch.ppf'
        subprocess.run([sys.executable, str(PATCHER_SOURCE), str(rev0), str(py_ppf),
                        *map(str, layers)], check=True)
        if not ppf_gives(py_ppf, rev0, expected):
            raise RuntimeError(f'{name}: {PATCHER} does not give build_disc.py\'s disc')
        print(f'release: {name}: the web patcher\'s disc and PPF and {PATCHER}\'s PPF all'
              ' match build_disc.py', flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_variants(rev0: Path, port: bool, variants: list[Variant],
                 finished: Callable[[Variant, Path], None], *, verify: bool = False) -> None:
    """Prepare once; build misses and pass each native tree's explicit directory.

    Cache hits never pretend that the mutable build/ tree holds that variant.
    """
    queue = list(variants)
    import features
    import variant_cache
    import variant_inputs
    cache = variant_cache.VariantCache(ROOT / 'build/step_cache/variants')
    source = modpack.Source(str(rev0))
    profile: variant_inputs.VariantInputs | None = None
    initialized = False
    pending_key: str | None = None

    def before(patches: list[str], _path: str) -> bool:
        nonlocal initialized, profile, pending_key
        if port or os.environ.get('PERSONA_RECHECK_VARIANTS'):
            return True
        if not initialized:
            initialized = True
            try:
                movie_prepared = any('fmv-translation' in mods.with_needs(
                    release_selection(v.labels), build.OPTIONS) for v in variants)
                profile = variant_inputs.VariantInputs(
                    ROOT, rev0, mods.load(), build.OPTIONS, font=build.FONT,
                    base_only=build.BASE_ONLY, engine_only=build.ENGINE_ONLY,
                    verify=verify, movie_prepared=movie_prepared,
                    tool=Path(build.ARMIPS), gates=features.from_argv(sys.argv))
            except (OSError, ValueError) as error:
                print(f'release: native cache unavailable: {error}', flush=True)
        if profile is None:
            return True
        pending_key = profile.key(patches)
        cached = cache.find(pending_key)
        if cached is None:
            print(f'release: native build needed: {queue[0].name}', flush=True)
            return True
        variant = queue.pop(0)
        print(f'release: native tree reused: {variant.name}', flush=True)
        cache.restore_auxiliary(pending_key, ROOT)
        finished(variant, cached)
        pending_key = None
        return False

    def after(patches: list[str], _path: str) -> None:
        nonlocal pending_key
        directory = ROOT / 'build'
        if profile is not None and pending_key is not None:
            if profile.key(patches) == pending_key:
                auxiliary: dict[str, bytes] = {}
                for mod in mods.load():
                    if not mod.always and mod.label not in patches:
                        continue
                    for setting in mod.ranges:
                        path = ROOT / setting.edits
                        if path.resolve().is_relative_to((ROOT/'build').resolve()):
                            auxiliary[path.relative_to(ROOT).as_posix()] = path.read_bytes()
                directory = cache.store(pending_key, tree_files(source, directory), auxiliary)
            else:
                print('release: variant inputs changed; native result not cached', flush=True)
        pending_key = None
        finished(queue.pop(0), directory)

    previous_argv, previous_image = sys.argv, build.ORIGINAL_IMAGE
    try:
        sys.argv = ['build.py', '--no-disc'] + ([] if verify else ['--no-verify']) + (['--port'] if port else [])
        if build.BASE_ONLY:
            sys.argv += ['--base-only', '--no-sf-vwf', '--no-sf-latin']
        elif build.ENGINE_ONLY:
            sys.argv += ['--engine-only']
        build.ORIGINAL_IMAGE = str(rev0)
        build.main(variants_override=[(release_selection(v.labels), v.name) for v in variants],
                   before_variant=before, after_variant=after)
    finally:
        source.close()
        sys.argv, build.ORIGINAL_IMAGE = previous_argv, previous_image


def child_trees(rev0: Path, mod: mods.Mod, tokens: list[str],
                variants: list[Variant]) -> None:
    """Build `variants` with the mod's choices `tokens` on, in a child
    process (a build's choices are fixed when it starts); each tree lands in
    TREES/<name>."""
    # every tier named, as before: build.py turns on only the tiers a --mods
    # list names or requires
    tiers = [m.slug for m in mods.load() if m.always and m.label != mod.label]
    subprocess.run([sys.executable, str(Path(__file__)),
                    '--mods=' + ','.join([*tiers, f'{mod.slug}({",".join(tokens)})']),
                    '--rev0', str(rev0), '--trees',
                    ';'.join(f'{v.name}:{",".join(v.labels)}' for v in variants)],
                   check=True, cwd=ROOT)


def trees_main(rev0: Path, spec: str, *, verify: bool = False) -> None:
    """The child side of child_trees."""
    variants = [Variant(name, tuple(filter(None, labels.split(','))), 'check')
                for name, _colon, labels in (item.partition(':') for item in spec.split(';'))]
    source = modpack.Source(str(rev0))
    try:
        run_variants(rev0, False, variants,
                     lambda variant, directory: save_tree(source, TREES / variant.name, directory),
                     verify=verify)
    finally:
        source.close()


def build_release(rev0_in: str, output_in: str, *, port: bool = False, verify: bool = False) -> None:
    rev0, output = Path(rev0_in).resolve(), Path(output_in).absolute()
    image_check.require(str(rev0))
    check_choices()
    output.mkdir(parents=True, exist_ok=True)
    key = release_fingerprint(rev0)
    rows = read_manifest(output / MANIFEST)

    def reusable(name: str) -> bool:
        row = rows.get(name)
        path = output / name
        return bool(row and row['build_key'] == key and row.get('state') in ({'verified'} if verify else {'untested', 'verified'})
                    and path.is_file()
                    and sha1(path) == row['sha1'])

    def compare(source: modpack.Source, packs: dict[str, modpack.Pack], name: str,
                selected: modpack.Selection, built: dict[str, bytes]) -> None:
        if verify:
            check_combination(source, packs, name, selected, built)

    print('release: ' + ('production and full verification' if verify else
                           'production only; complete files will be marked untested'), flush=True)
    if port or os.environ.get('PERSONA_RECHECK_VARIANTS') or not all(reusable(name) for name in release_file_names()):
        shutil.rmtree(TREES, ignore_errors=True)       # an earlier run's, stopped midway
        for name in output.glob('*' + INPROGRESS):      # the old in-progress naming
            name.unlink()
        packs = {label: new_pack(mods.by_label()[label]) for label in release_labels()}
        source = modpack.Source(str(rev0))
        packs[ROOT_MOD.label].twins = modpack.cached_retail_twins(source)
        base_files: dict[str, bytes] = {}   # the base tree's changed files, read once

        # Packs stay uncompressed in memory until all compatibility parts exist.
        # An interrupted run cannot advertise an old package as this release.
        write_manifest(output / MANIFEST, [])
        own_io = [own_disk_io()]

        def stage(what: str) -> None:
            now = own_disk_io()
            read, wrote = (b - a for a, b in zip(own_io[0], now))
            own_io[0] = now
            print(f'release: staged {what}; '
                  f'{sum(len(pack.parts) for pack in packs.values())} uncompressed parts;'
                  f' disk read {read >> 20} MB, wrote {wrote >> 20} MB', flush=True)

        try:
            # PRODUCE - every build here makes a layer or a part

            def native_mods(component: mods.Mod, flag: str,
                            reference: dict[str, bytes]) -> None:
                tiers = {ROOT_MOD.label}
                if component is ALPHABET_MOD:
                    tiers.add(ALPHABET_MOD.label)

                def supported(label: str, seen: set[str] | None = None) -> bool:
                    visited = set() if seen is None else seen
                    if label in visited:
                        return True
                    visited.add(label)
                    mod = mods.by_label()[label]
                    if mod.always and label not in tiers:
                        return False
                    return all(supported(need, visited)
                               for need in mod.needs(mod.defaults()))

                labels = [label for label in CHOICE_ORDER if supported(label)]
                native_selection = {label: mods.by_label()[label].defaults() for label in tiers}

                def trees(variants: list[Variant]) -> None:
                    if variants:
                        subprocess.run([sys.executable, str(Path(__file__)), flag,
                                        '--rev0', str(rev0), '--trees',
                                        ';'.join(f'{v.name}:{",".join(v.labels)}' for v in variants)],
                                       check=True, cwd=ROOT)

                singles = [Variant(f'{component.label}-{label}', (label,), 'option')
                           for label in labels]
                trees(singles)
                for variant in singles:
                    label = variant.labels[0]
                    built = kept_tree(source, TREES / variant.name)
                    selected = native_selection | {label: mods.by_label()[label].defaults()}
                    if not packs[label].parts:
                        part = modpack.layer_from(label, source, reference, built)
                        packs[label].parts.append(modpack.Part('', part.files))
                    else:
                        add_part(source, packs, label, component.label, selected, built)
                    compare(source, packs, variant.name, selected, built)
                stage(f'{component.label} mods')
                pairs = [pair for pair in overlapping_pairs(packs)
                         if all(label in labels for label in pair)]
                pair_variants = [Variant(f'{component.label}-{a}+{b}', (a, b), 'compat')
                                 for a, b in pairs]
                trees(pair_variants)
                for variant in pair_variants:
                    first, later = variant.labels
                    selected = native_selection | {
                        label: mods.by_label()[label].defaults() for label in variant.labels}
                    when = first if component is ROOT_MOD else f'{first},{component.label}'
                    built = kept_tree(source, TREES / variant.name)
                    add_part(source, packs, later, when, selected, built)
                    compare(source, packs, variant.name, selected, built)
                stage(f'{component.label} mod pairs')
                if labels and verify:
                    combined = Variant(f'{component.label}-all', tuple(labels), 'check')
                    trees([combined])
                    compare(source, packs, combined.name,
                                      native_selection | {label: mods.by_label()[label].defaults()
                                                          for label in labels},
                                      kept_tree(source, TREES / combined.name))

            # Build the two language-free foundations in isolated processes:
            # toolpath and feature choices are fixed when Python imports them.
            foundation_files: dict[str, bytes] = {}
            for component, flag in ((ROOT_MOD, '--base-only'), (ALPHABET_MOD, '--engine-only')):
                name = 'foundation-' + component.label
                subprocess.run([sys.executable, str(Path(__file__)),
                                flag, '--rev0', str(rev0), '--trees', name + ':',
                                *(['--verify-tree'] if verify else [])],
                               check=True, cwd=ROOT)
                built = kept_tree(source, TREES / name)
                part = modpack.layer_from(component.label, source, foundation_files, built,
                                          check_source=component is ROOT_MOD)
                if component is not ROOT_MOD:
                    guard_retail_inputs(source, packs[ROOT_MOD.label], part)
                packs[component.label].parts.append(modpack.Part('', part.files))
                foundation_files = built
                selected = {ROOT_MOD.label: frozenset()}
                if component is ALPHABET_MOD:
                    selected[ALPHABET_MOD.label] = frozenset()
                compare(source, packs, component.label, selected, built)
                stage(component.label)
                native_mods(component, flag, built)

            # 1. the base and each mod on its own, every mod at its defaults
            def layer(variant: Variant, directory: Path) -> None:
                built = variant_files(source, directory)
                if variant.role == 'base':
                    save_tree(source, BASE_TREE, directory)
                    part = modpack.layer_from(BASE_MOD.label, source, foundation_files, built)
                    guard_retail_inputs(source, packs[ROOT_MOD.label], part)
                    packs[BASE_MOD.label].parts.append(modpack.Part('', part.files))
                    base_files.update(built)        # every mod is diffed against it
                else:
                    if packs[variant.name].parts:
                        add_part(source, packs, variant.name, BASE_MOD.label,
                                 default_selection(variant.labels), built)
                    else:
                        part = modpack.layer_from(variant.name, source, base_files, built)
                        packs[variant.name].parts.append(modpack.Part('', part.files))
                stage(variant.name)
            run_variants(rev0, port, [Variant('base', (), 'base')]
                         + [Variant(label, (label,), 'option') for label in CHOICE_ORDER], layer)

            # 2. the pairs that write the same bytes: a part of the later mod
            #    where the built pair differs from the two merged
            pairs = overlapping_pairs(packs)
            print('release: overlapping pairs: '
                  + (', '.join('+'.join(pair) for pair in pairs) or 'none'), flush=True)

            def compat(variant: Variant, directory: Path) -> None:
                first, later = variant.labels
                if add_part(source, packs, later, first, default_selection(variant.labels),
                            variant_files(source, directory)):
                    stage(variant.name)
            if pairs:
                run_variants(rev0, False, [Variant('+'.join(pair), pair, 'compat')
                                           for pair in pairs], compat)

            # 3. every other choice: what it changes over the mod's defaults,
            #    then the mods that write a file it changes, built with it
            #    (no other mod can see it): a part where a layer no longer fits
            for number, (mod, choice) in enumerate(other_choices(), 1):
                alone = () if mod.always else (mod.label,)
                tokens = mod.pick(choice.token)
                when = condition(mod, {choice.token})
                print(f'release: choice {number}/{len(other_choices())}: {when}', flush=True)
                child_trees(rev0, mod, [choice.token], [Variant('alone', alone, 'check')])
                if not add_part(source, packs, mod.label, when,
                                default_selection(alone) | {mod.label: tokens},
                                kept_tree(source, TREES / 'alone')):
                    # nothing to change, but the release still offers it
                    packs[mod.label].parts.append(modpack.Part(when, []))
                stage(when)
                changed = {edit.path for part in packs[mod.label].parts if part.when == when
                           for edit in part.files}
                touching = [label for label in CHOICE_ORDER if label != mod.label and any(
                    edit.path in changed for part in packs[label].parts for edit in part.files)]
                print(f'release: {when} changes {len(changed)} file(s); mods that write them: '
                      + (', '.join(touching) or 'none'), flush=True)
                if touching:
                    child_trees(rev0, mod, [choice.token], [Variant(label, tuple(sorted(
                        {label, *alone}, key=release_labels().index)), 'check')
                        for label in touching])
                    for label in touching:
                        add_part(source, packs, label, when,
                                 default_selection((label, *alone)) | {mod.label: tokens},
                                 kept_tree(source, TREES / label))
                    stage(f'mods with {when}')

            # 4. two of a mod's choices together: a part where they interact
            for mod, a, b in choice_pairs():
                alone = () if mod.always else (mod.label,)
                when = condition(mod, {a.token, b.token})
                print(f'release: {when}', flush=True)
                child_trees(rev0, mod, [a.token, b.token], [Variant('pair', alone, 'check')])
                if add_part(source, packs, mod.label, when,
                            default_selection(alone) | {mod.label: mod.pick(f'{a.token},{b.token}')},
                            kept_tree(source, TREES / 'pair')):
                    stage(when)

            # Known interactions are production inputs, not rediscovered by a
            # full matrix on every release. Recipes live with their owning mod.
            for number, recipe in enumerate(compatibility_recipes()):
                produce_recipe(source, packs, rev0, recipe, number)

            if verify:
                # Verify uncompressed packs, including any compatibility parts found
                # by combined choices. Compression happens only once all parts exist.
                def check_all(variant: Variant, directory: Path) -> None:
                    compare(source, packs, variant.name,
                                      default_selection(variant.labels),
                                      variant_files(source, directory))
                    save_tree(source, TREES / 'browser-all', directory)
                run_variants(rev0, False, [Variant('all', tuple(CHOICE_ORDER), 'check')], check_all)
                for mod, choice in other_choices():
                    alone = () if mod.always else (mod.label,)
                    tokens = mod.pick(choice.token)
                    when = condition(mod, {choice.token})
                    child_trees(rev0, mod, [choice.token],
                                [Variant('all', tuple(CHOICE_ORDER), 'check')])
                    every = default_selection(CHOICE_ORDER) | {mod.label: tokens}
                    built_all = kept_tree(source, TREES / 'all')
                    # mods that still interact in a file while the choice is on:
                    # each pair of them that writes that file is built with it,
                    # and the later one carries what the pair adds (`a,mod(choice)`)
                    wrong = differing(source, merged_files(source, packs, every), built_all)
                    if wrong:
                        both = [label for label in CHOICE_ORDER if label != mod.label and any(
                            edit.path in wrong for part in packs[label].parts for edit in part.files)]
                        pairs_in = [(x, y) for i, x in enumerate(both) for y in both[i + 1:]]
                        print(f'release: with {when}, {", ".join(wrong)}: building '
                              + ', '.join('+'.join(p) for p in pairs_in), flush=True)
                        child_trees(rev0, mod, [choice.token], [Variant(
                            f'{x}+{y}', tuple(sorted({x, y, *alone}, key=release_labels().index)),
                            'check') for x, y in pairs_in])
                        for x, y in pairs_in:
                            add_part(source, packs, y, f'{x},{when}',
                                     default_selection((x, y, *alone)) | {mod.label: tokens},
                                     kept_tree(source, TREES / f'{x}+{y}'))
                        stage(f'pairs with {when}')
                    # Positive conditions also apply to supersets. Pair corrections
                    # can therefore expose a higher-order interaction (for example,
                    # several mods independently enabling the same renderer).
                    wrong = differing(source, merged_files(source, packs, every), built_all)
                    members = [label for label in CHOICE_ORDER if label != mod.label and any(
                        edit.path in wrong for part in packs[label].parts for edit in part.files)]
                    for size in range(3, len(members) + 1):
                        if not wrong:
                            break
                        if size == len(members):
                            # The full build is already available. Only these mods
                            # write the remaining files; unrelated mods need no part.
                            condition_labels = [*members[:-1], when]
                            add_part(source, packs, members[-1], ','.join(condition_labels),
                                     every, built_all)
                        else:
                            groups = list(combinations(members, size))
                            variants = [Variant('+'.join(group), tuple(sorted(
                                {*group, *alone}, key=release_labels().index)), 'check')
                                for group in groups]
                            child_trees(rev0, mod, [choice.token], variants)
                            for group, variant in zip(groups, variants):
                                selected = default_selection(variant.labels) | {mod.label: tokens}
                                built = kept_tree(source, TREES / variant.name)
                                add_part(source, packs, group[-1], ','.join([*group[:-1], when]),
                                         selected, built)
                                compare(source, packs, variant.name, selected, built)
                        stage(f'{size}-mod interactions with {when}')
                        wrong = differing(source, merged_files(source, packs, every), built_all)
                    compare(source, packs, f'all with {when}', every, built_all)
            for label, pack in packs.items():
                target = output / option_layer(label)
                if mods.by_label()[label].ranges:
                    modpack.bind_ranges(pack, mods.by_label()[label])
                modpack.save(str(target), pack)
                if modpack.read_layer(str(target)) != pack:
                    raise RuntimeError(f'{label}: compressed layer differs from its staged parts')
            if verify:
                check_range_values(source, packs)
                write_outputs(output, rev0, key, 'testing')
                check_browser_layout(rev0, [output / option_layer(label)
                                       for label in release_labels()], 'all',
                                 TREES / 'browser-all')
            shutil.rmtree(TREES, ignore_errors=True)
        finally:
            source.close()
        if release_fingerprint(rev0) != key:
            raise RuntimeError('build inputs changed during the release; rerun it')
        write_outputs(output, rev0, key, 'verified' if verify else 'untested')
    else:
        print('release: every layer is current; reused', flush=True)


def own_disk_io() -> tuple[int, int]:
    """(bytes read, bytes written) on disk by this process (/proc/self/io;
    page-cache reads are not disk reads). (0, 0) where it is unavailable."""
    try:
        fields = dict(line.split(': ') for line in
                      Path('/proc/self/io').read_text().splitlines())
        return int(fields['read_bytes']), int(fields['write_bytes'])
    except (OSError, KeyError, ValueError):
        return 0, 0


def write_outputs(output: Path, rev0: Path, key: str, state: str) -> None:
    """The manifest and the README of the layers in `output` (a layer not
    written yet is left out); anything else there (an older release's files)
    is removed. state: `untested` for complete production output, `testing`
    while explicit checks run, `verified` once every check passed -
    only a verified release is published; a local server serves any."""
    manifest = []
    for label in release_labels():
        name = option_layer(label)
        path = output / name
        if not path.is_file():
            continue
        mod = mods.by_label()[label]
        row = {'layer': name, 'kind': 'base' if mod is ROOT_MOD else 'option', 'label': label,
               'state': state,
               'choices': ','.join(c.token for c in mod.choices),
               'requires': ','.join(requirements(mod)), 'version': '',
               'bytes': str(path.stat().st_size), 'sha1': sha1(path),
               'build_key': key, 'release': ''}
        if mod is ROOT_MOD:
            row.update(source_bytes=str(rev0.stat().st_size), source_chd_sha1=chd_raw_sha1(rev0))
        manifest.append(row)
    write_manifest(output / MANIFEST, manifest)
    patcher = output / PATCHER
    if not patcher.exists() or patcher.read_bytes() != PATCHER_SOURCE.read_bytes():
        shutil.copyfile(PATCHER_SOURCE, patcher)
    keep = set(release_file_names()) | {MANIFEST, 'README.txt', PATCHER}
    for path in output.iterdir():
        if path.name not in keep:
            print(f'release: removing {path.name}', flush=True)
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    write_readme(output)
    total = sum(int(row['bytes']) for row in manifest)
    print(f'release: {len(manifest)} layers, {total} bytes in {output}', flush=True)


def write_readme(output: Path) -> None:
    """Generated, never hand-typed: names from the mods' mod.tsv."""
    entries = []
    for label in release_labels():
        mod = mods.by_label()[label]
        choices = ' (choices: ' + ', '.join(f'{c.token} = {c.name}' for c in mod.choices) + ')' \
            if mod.choices else ''
        if mod.ranges:
            choices += ' (ranges: ' + ', '.join(
                f'{r.key}={r.minimum}..{r.maximum}, step {r.step}, default {r.default}'
                for r in mod.ranges) + ')'
        entries.append((option_layer(label), mod.name + choices))
    width = max(len(name) for name, _comment in entries)
    listing = '\n'.join(f'  {name.ljust(width)}  {comment}' for name, comment in entries)
    readme = (
        'Persona translation patches\n'
        '===========================\n'
        '\n'
        'Use the web patcher:\n'
        'https://ayla6.github.io/megami-ibunroku-persona-translation\n'
        'It applies these layers to your disc and writes a patched disc or a\n'
        'PPF. Only the original Rev 0 disc is patched.\n'
        '\n'
        "Each file is a P1MOD layer: one mod's changes to the disc's files, in\n"
        'parts the patcher picks from what else is on (an option of the mod,\n'
        'another mod beside it). Applied in this order (leave out the mods\n'
        "you don't want):\n"
        '\n'
        f'{listing}\n'
        '\n'
        'Without a browser, with Python 3.9 or later (persona-patch.py is here;\n'
        'nothing to install):\n'
        '\n'
        f'    python {PATCHER} your.bin out.bin {TRANSLATION_LAYERS} <mods>.p1mod\n'
        f'    python {PATCHER} your.bin out.ppf {TRANSLATION_LAYERS} <mods>.p1mod\n'
        "    (--choose 'english-translation(font=small)' picks a mod's choices)\n"
        '\n'
        'From a checkout of the project:\n'
        '\n'
        '    python src/pipeline/modpack.py apply out.bin --source your.bin \\\n'
        f"        [--choose 'english-translation(font=small)'] {TRANSLATION_LAYERS} <mods>.p1mod\n"
        '\n'
        'The base layer checks every file it changes, so a wrong disc is\n'
        'refused. manifest.tsv lists every layer with its size, SHA-1 and state.\n'
        'Untested means release combination checks have not been run.\n'
    )
    target = output / 'README.txt'
    if not target.exists() or target.read_text(encoding='utf-8') != readme:
        target.write_text(readme, encoding='utf-8')


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0])
    parser.add_argument('--rev0', default=build.ORIGINAL_IMAGE, help='original Rev 0 BIN')
    parser.add_argument('--output', default=str(ROOT / 'dist' / 'patches'),
                        help='directory for the release (an unchanged one is reused)')
    parser.add_argument('--no-sf-vwf', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--no-sf-latin', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--base-only', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--engine-only', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--port', action='store_true', help='regenerate translation tables first')
    parser.add_argument('--trees', help=argparse.SUPPRESS)       # child_trees
    parser.add_argument('--verify-tree', action='store_true', help=argparse.SUPPRESS)
    verification = parser.add_mutually_exclusive_group()
    verification.add_argument('--verify-release', dest='verify_release', action='store_true',
                        default=True,
                        help='run combined native comparisons and disc/PPF parity after producing layers')
    verification.add_argument('--no-verify-release', dest='verify_release', action='store_false',
                        help='produce release files without full release verification')
    parser.add_argument('--recheck', action='store_true',
                        help='rebuild every native verification variant (slow)')
    parser.add_argument('--mods', help=argparse.SUPPRESS)        # the child's choice
    parser.add_argument('--publish-release', '--publish-web',
                        dest='publish_release', action='store_true',
                        help='upload the release and refresh the local web patcher copy afterwards')
    args = parser.parse_args(argv)
    if args.recheck:
        os.environ['PERSONA_RECHECK_VARIANTS'] = '1'
    if args.trees:
        trees_main(Path(args.rev0).resolve(), args.trees, verify=args.verify_tree)
        return
    try:
        build_release(args.rev0, args.output, port=args.port,
                      verify=args.verify_release or args.recheck or args.publish_release)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'build_patches.py: {error}\n')
    if args.publish_release:
        import publish_patches
        publish_patches.publish(directory=args.output)


if __name__ == '__main__':
    main()
