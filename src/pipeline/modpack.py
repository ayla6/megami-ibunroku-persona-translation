"""Patch layers: file edits, merged in memory, written to the disc once.

The release format of the mod engine (docs/MOD_ENGINE.md). A layer is the
change one patch makes to the disc's FILES, not to its raw sectors: the
engine, the translation and every mod are layers, and a disc is the retail
disc with the selected layers applied in order. The layout (relocating a
file that grows, the ISO records, the game's FNAME / FSECT / FSIZE tables)
and the EDC/ECC are worked out once, after the merge, by build_disc.build_to
- so layers never carry checksums and never depend on each other's sectors.

This module is the reference implementation; the browser patcher
(webpatcher/modpack.js) follows it. Typed Python (AGENTS.md).

  python src/pipeline/modpack.py make <out.p1mod> --name NAME [--from-tree DIR] [--to-tree DIR] [--check-source]
      the layer that turns retail (+ --from-tree's disc files) into retail
      (+ --to-tree's disc files, default build/)
  python src/pipeline/modpack.py apply <out.bin> [--source DISC] [--choose 'LABEL(GROUP=KEY)'] <layer.p1mod> ...
      the disc (default: retail Rev 0, build.py's image) with the layers
      applied in order, each mod at its defaults unless --choose names its
      choices (its label, the picked tokens in parentheses)
  python src/pipeline/modpack.py show <layer.p1mod>

Layer file (reproducible: the same mod always writes the same bytes). One
file per mod; its PARTS are what is applied, each under a condition:
    P1MOD<TAB>1<LF>
    the readable manifest, plain UTF-8 TSV (`head` shows it), so a layer
    found on its own says what it is:
      kind         path  before  after   the header
      name         NAME  -       -       the mod's label
      title        TEXT  -       -       what it is called
      description  TEXT  -       -       what it does
      author       TEXT  -       -       optional author credit
      version      TEXT  -       -       the release it belongs to: written by
                                         tools/publish_patches.py when the
                                         release is published (mods have no
                                         version of their own)
      commit       TEXT  -       -       the source it was built from: the short
                                         commit hash, `-dirty` when the tree had
                                         uncommitted changes (git describe)
      requires     LABEL -       -       a mod it needs; one row each
      option       GROUP=KEY NAME -      an option of the mod: one KEY of a
                                         GROUP is on at a time, the group's
                                         first by default
      extra        KEY   NAME    -       an additive part of the mod, off by
                                         default
      part         COND  -       -       a part: its file rows follow
      file   PATH  BEFORE  AFTER     a file the part edits, its length before
                                     and after the part
      raw    PATH  BEFORE  AFTER     the same for a movie, edited as raw
                                     2352-byte sectors (build_disc writes it
                                     in place, sector for sector)
    COND says when the part is applied: `-` whenever the mod is on, else
    mods written as a build names them (mods.parse_mods), all of which must
    hold - `LABEL` (that mod is on) or `LABEL(TOKEN,...)` (on, with those
    choices: `english-translation(font=small)`); the mod's own label names its own
    choices. A selection is {label: the set of its picked tokens}.
    --<TAB>ROWS<TAB>PAYLOAD<LF>
    one raw LZMA1 stream (lc 3, lp 0, pb 2, end marker; webpatcher/lzma.js
    decodes it) of ROWS bytes of TSV, then PAYLOAD bytes of data:
      part   N                       the rows after it belong to part N
                                     (0-based, manifest order)
      check  PATH  SHA1            the SHA-1 the file must have before
                                     the part edits it (a movie's: each
                                     sector from the subheader on, the address
                                     being the disc's); a file without one is
                                     unchecked
      bytes  PATH  OFFSET  LENGTH    LENGTH bytes at OFFSET, taken in order
                                     from the payload
      twins  PATH  PATH ...          files of the disc this layer was made
                                     against that are sector for sector the
                                     same (the base layer carries them for the
                                     retail disc): the layout may point one
                                     at another to free room, and with this
                                     list it never has to read them to find
                                     out (build_disc.duplicate_files)
All parts share the one stream, so what two options have in common (the two
font editions of the translation) is stored once in effect.
The payload is every `bytes` row's data, in row order; `check` and `bytes`
rows belong to the `file` / `raw` row with their path. LZMA finds repeats
anywhere in the payload, which gzip's 32 KB window cannot (Mark's walk
sheets: 7.6 MB gzip, 0.2 MB LZMA), and the rows - thousands for the base,
mostly the same paths - compress to a tenth inside the same stream.
A part applies to the files as the parts before it left them (retail for the
first): the mods in apply order, each mod's parts in file order.

GROWTH IS NOT AN EDIT. A layer that makes a file longer records only the
data it puts past the old end, never the zero padding up to it; and a
layer's length combines with the others': growing (AFTER > BEFORE) extends
the file to AFTER only when it is shorter, shrinking (AFTER < BEFORE)
truncates it to AFTER. Two options that each grow a file to reach their own
code therefore never cut off or zero out each other's. The layers
that are made against the retail disc (the base translation) check every
file they edit, which is how a player's disc is
verified; an option's input depends on which other options are on, so its
files are unchecked and the release manifest's hash of the layer file covers
it. FNAME / FSECT / FSIZE.DAT belong to the layout (build_disc updates them by
name for every file it moves; the game looks files up by name,
CdSearchFileLoc), so no layer may carry them.
"""
from __future__ import annotations

import hashlib
import lzma
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import Final, TYPE_CHECKING

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import numpy as np                       # noqa: E402
import numpy.typing as npt               # noqa: E402
import build_disc                        # noqa: E402
from build_disc import Disc, SECTOR, is_raw_file  # noqa: E402

ROOT: Final = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAGIC: Final = b'P1MOD\t1\n'
LZMA_PROPS: Final = {'lc': 3, 'lp': 0, 'pb': 2}
HEADER: Final = 'kind\tpath\tbefore\tafter'
LAYOUT_FILES: Final = frozenset({'FNAME.DAT', 'FSECT.DAT', 'FSIZE.DAT'})
RUN_GAP: Final = 16   # unchanged bytes a run may bridge before a new row pays off

DiscPath = str        # upper-case path on the disc, '/'-separated: 'EXE/END.BIN'
Run = tuple[int, int]  # [start, end) of changed bytes in a file


from range_parameters import RangeSetting, Scale
from format_edits import EntryEdit, replace_mes, mes_changes, prepared_mes_changes, registry as file_formats

if TYPE_CHECKING:
    import mods


@dataclass(frozen=True)
class Span:
    """Bytes a layer writes at one offset of a file."""
    offset: int
    data: bytes


@dataclass
class FileEdit:
    """One file of a layer: its length before and after, and the bytes written."""
    path: DiscPath
    raw: bool                     # a movie, edited as raw 2352-byte sectors
    before: int                   # the file's length the layer was made from
    length: int                   # its length after the layer
    source: str | None = None     # SHA-1 the file must have before the edit
    spans: list[Span] = field(default_factory=list)
    scales: list[Scale] = field(default_factory=list)
    entries: list[EntryEdit] = field(default_factory=list)


@dataclass
class Layer:
    """What is applied as one step: a mod's part (or a whole one-part mod)."""
    name: str
    files: list[FileEdit]
    title: str = ''
    description: str = ''
    version: str = ''             # the release (stamped when published)
    commit: str = ''              # the source it was built from (git describe)
    requires: list[str] = field(default_factory=list)
    twins: list[list[DiscPath]] = field(default_factory=list)   # identical files, extent order


@dataclass
class Part:
    """Edits a mod applies when `when` holds (COND in the file: '' = always)."""
    when: str
    files: list[FileEdit]


@dataclass
class Pack:
    """A mod's layer file: its parts and what they need."""
    name: str
    parts: list[Part]
    title: str = ''
    description: str = ''
    version: str = ''
    commit: str = ''
    requires: list[str] = field(default_factory=list)
    choices: list[tuple[str, str]] = field(default_factory=list)   # (token, name)
    twins: list[list[DiscPath]] = field(default_factory=list)

    ranges: list[RangeSetting] = field(default_factory=list)
    author: str = ''

    def defaults(self) -> frozenset[str]:
        """Each option group's first token (the extras are off)."""
        first: dict[str, str] = {}
        for token, _name in self.choices:
            if '=' in token:
                first.setdefault(token.split('=', 1)[0], token)
        return frozenset(first.values()) | frozenset(f"{r.key}={r.default}" for r in self.ranges)


Selection = dict[str, frozenset[str]]   # mod label -> its picked choice tokens


def holds(when: str, selection: Selection) -> bool:
    """Whether a part's condition holds in `selection`."""
    import mods
    for label, picked in mods.parse_mods(when):
        if label not in selection:
            return False
        if not {t.strip() for t in picked.split(',') if t.strip()} <= selection[label]:
            return False
    return True


def parts_for(pack: Pack, selection: Selection) -> list[Layer]:
    """The pack's parts that apply to `selection`, as layers, in file order."""
    return [Layer(pack.name + (f'[{part.when}]' if part.when else ''), part.files,
                  twins=pack.twins)
            for part in pack.parts if holds(part.when, selection)]


def single(layer: Layer) -> Pack:
    """A one-part pack applied whenever its mod is on."""
    return Pack(layer.name, [Part('', layer.files)], layer.title, layer.description,
                layer.version, layer.commit, list(layer.requires), [], list(layer.twins))


def one_line(text: str) -> str:
    """A readable-manifest cell: tabs and line breaks become spaces."""
    return ' '.join(text.split())


def source_version() -> str:
    """The short commit hash of the checkout, `-dirty` with uncommitted
    changes; '' outside a git checkout."""
    import subprocess
    try:
        done = subprocess.run(['git', 'describe', '--always', '--dirty'], cwd=ROOT,
                              capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return ''
    return done.stdout.strip()


Clashes = dict[tuple[str, str, DiscPath], int]   # (earlier, later, file) -> bytes


def source_digest(data: bytes, raw: bool) -> str:
    """The SHA-1 a `file`/`raw` row checks: a movie's sectors from the
    subheader on (the sync and address belong to where the disc put it)."""
    if raw:
        data = build_disc.raw_body(data)
    return hashlib.sha1(data).hexdigest()


def retail_image() -> str:
    import build
    image: str = build.ORIGINAL_IMAGE
    return image


class Source:
    """The files of a disc image, read-only."""

    def __init__(self, path: str) -> None:
        self.disc: Disc = Disc.__new__(Disc)
        self.disc.f = open(path, 'rb')
        self.disc.f.seek(0, 2)
        self.disc.sectors = self.disc.f.tell() // SECTOR
        self.disc.pending = {}
        pvd: bytes = self.disc.user(16)
        root_lba: int = struct.unpack_from('<I', pvd, 156 + 2)[0]
        root_size: int = struct.unpack_from('<I', pvd, 156 + 10)[0]
        self.files: dict[tuple[DiscPath, bool], bytes] = {}   # read once (read)
        self.entries: dict[DiscPath, tuple[int, int]] = {
            p.upper(): (ext, size)
            for p, ext, size, _rl, _ro in self.disc.walk(root_lba, root_size)}

    def read(self, path: DiscPath, raw: bool = False) -> bytes:
        """A file of the disc (a movie as raw sectors). The disc never
        changes, so each file is read once and kept."""
        cached = self.files.get((path, raw))
        if cached is not None:
            return cached
        ext, size = self.entries[path]
        sectors = (size + 2047) // 2048
        if raw:
            data = b''.join(self.disc.raw(ext + n) for n in range(sectors))
        else:
            data = b''.join(self.disc.user(ext + n) for n in range(sectors))[:size]
        self.files[(path, raw)] = data
        return data

    def close(self) -> None:
        self.disc.f.close()


def tree(directory: str, source: Source) -> dict[DiscPath, str]:
    """{DISC/PATH: local path} of the disc files a build tree holds."""
    out: dict[DiscPath, str] = {}
    for r, _dirs, files in os.walk(directory):
        for f in files:
            local = os.path.join(r, f)
            key = os.path.relpath(local, directory).replace(os.sep, '/').upper()
            if key in source.entries:
                out[key] = local
    return out


def same_file_data(first: bytes, second: bytes, raw: bool = False) -> bool:
    """Compare movie sector bodies without copying whole movie streams.

    Raw files ignore the first 16 bytes of each sector, exactly as raw_body
    does. Bounded views keep temporary comparison memory below one MiB.
    """
    if first is second:
        return True
    if not raw:
        return first == second
    if len(first) % SECTOR or len(second) % SECTOR:
        return build_disc.raw_body(first) == build_disc.raw_body(second)
    if len(first) != len(second):
        return False
    a = np.frombuffer(first, np.uint8).reshape(-1, SECTOR)
    b = np.frombuffer(second, np.uint8).reshape(-1, SECTOR)
    chunk = max(1, (1 << 20) // SECTOR)
    return all(np.array_equal(a[i:i+chunk, 16:], b[i:i+chunk, 16:])
               for i in range(0, len(a), chunk))


def runs(old: bytes, new: bytes) -> list[Run]:
    """[(offset, end)] of `new` where it differs from `old`, and past the end
    of `old` where it is not zero (growth padding is not an edit); runs closer
    than RUN_GAP are joined."""
    n = min(len(old), len(new))
    a: npt.NDArray[np.uint8] = np.frombuffer(old, np.uint8, n)
    b: npt.NDArray[np.uint8] = np.frombuffer(new, np.uint8, n)
    tail: npt.NDArray[np.uint8] = np.frombuffer(new, np.uint8)[n:]
    diff = np.concatenate((np.flatnonzero(a != b), np.flatnonzero(tail) + n))
    if not diff.size:
        return []
    breaks = np.flatnonzero(np.diff(diff) > RUN_GAP)
    starts = np.concatenate(([diff[0]], diff[breaks + 1]))
    ends = np.concatenate((diff[breaks], [diff[-1]])) + 1
    return [(int(s), int(e)) for s, e in zip(starts, ends)]


def pack_payload(payload: bytes) -> bytes:
    """One raw LZMA1 stream; the dictionary covers all of it."""
    dict_size = 1 << max(16, min(26, (len(payload) - 1).bit_length()))
    return lzma.compress(payload, format=lzma.FORMAT_RAW, filters=[{
        'id': lzma.FILTER_LZMA1, 'preset': 6,
        'dict_size': dict_size, **LZMA_PROPS}])


def unpack_payload(packed: bytes, size: int) -> bytes:
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{
        'id': lzma.FILTER_LZMA1, 'dict_size': 1 << 26, **LZMA_PROPS}])
    return decoder.decompress(packed, max_length=size)


def readable_rows(pack: Pack) -> list[str]:
    """The readable manifest's rows, header first."""
    rows = [HEADER, f'name\t{pack.name}\t-\t-']
    for kind, text in (('title', pack.title), ('description', pack.description), ('author', pack.author),
                       ('version', pack.version), ('commit', pack.commit)):
        if text:
            rows.append(f'{kind}\t{one_line(text)}\t-\t-')
    rows += [f'requires\t{label}\t-\t-' for label in pack.requires]
    rows += [f"{'option' if '=' in token else 'extra'}\t{token}\t{one_line(name)}\t-"
             for token, name in pack.choices]
    rows += [f"range\t{r.key}\t{r.bounds()}\t{one_line(r.name)}" for r in pack.ranges]
    for part in pack.parts:
        rows.append(f'part\t{part.when or "-"}\t-\t-')
        for edit in part.files:
            if edit.path in LAYOUT_FILES:
                raise ValueError(f'{pack.name}: {edit.path} belongs to the layout')
            rows.append(f"{'raw' if edit.raw else 'file'}\t{edit.path}\t{edit.before}"
                        f"\t{edit.length}")
    return rows


def write_layer(path: str, pack: Pack | Layer) -> None:
    if isinstance(pack, Layer):
        pack = single(pack)
    runs_rows: list[str] = ['twins\t' + '\t'.join(group) for group in pack.twins]
    payload: list[bytes] = []
    for number, part in enumerate(pack.parts):
        runs_rows.append(f'part\t{number}')
        for edit in part.files:
            if edit.source:
                runs_rows.append(f'check\t{edit.path}\t{edit.source}')
            for scale in edit.scales:
                runs_rows.append(f"scale\t{edit.path}\t{scale.offset}\t{scale.parameter}\t{scale.original}")
            for entry in edit.entries:
                runs_rows.append(f'mes-entry\t{edit.path}\t{entry.index}\t{len(entry.data)}\t{entry.source}')
                payload.append(entry.data)
            for span in edit.spans:
                runs_rows.append(f'bytes\t{edit.path}\t{span.offset}\t{len(span.data)}')
                payload.append(span.data)
    readable = ('\n'.join(readable_rows(pack)) + '\n').encode('utf-8')
    packed_rows = ''.join(row + '\n' for row in runs_rows).encode('ascii')
    data = b''.join(payload)
    stream = pack_payload(packed_rows + data)      # before the file is touched
    # written whole, then swapped in: a reader never sees a half-written layer
    with open(path + '.tmp', 'wb') as out:
        out.write(MAGIC)
        out.write(readable)
        out.write(f'--\t{len(packed_rows)}\t{len(data)}\n'.encode('ascii'))
        out.write(stream)
    os.replace(path + '.tmp', path)


def split_layer(blob: bytes, path: str = 'layer') -> tuple[list[str], bytes]:
    """(the readable manifest's lines, everything from the `--` line on)."""
    if not blob.startswith(MAGIC):
        raise ValueError(f'{path}: not a P1MOD 1 layer')
    at = blob.find(b'\n--\t', len(MAGIC) - 1)
    if at < 0:
        raise ValueError(f'{path}: no `--` line')
    return blob[len(MAGIC):at].decode('utf-8').split('\n'), blob[at + 1:]


def stamp(path: str, version: str) -> None:
    """Set a layer's version row (the release it belongs to) in place: the
    readable manifest is plain text before the stream, nothing recompresses."""
    with open(path, 'rb') as f:
        blob = f.read()
    lines, rest = split_layer(blob, path)
    lines = [line for line in lines if not line.startswith('version\t')]
    lines.insert(next((i for i, line in enumerate(lines)
                       if line.split('\t')[0] not in ('kind', 'name', 'title', 'description', 'author')),
                      len(lines)), f'version\t{one_line(version)}\t-\t-')
    with open(path + '.tmp', 'wb') as out:
        out.write(MAGIC + ('\n'.join(lines) + '\n').encode('utf-8') + rest)
    os.replace(path + '.tmp', path)


def read_layer(path: str) -> Pack:
    with open(path, 'rb') as f:
        blob: bytes = f.read()
    lines, rest = split_layer(blob, path)
    end = rest.find(b'\n')
    _dash, runs_size, size = rest[:end].decode('ascii').split('\t')
    total = int(runs_size) + int(size)
    both = unpack_payload(rest[end + 1:], total)
    if len(both) != total:
        raise ValueError(f'{path}: the stream holds {len(both)} bytes, not {total}')
    if lines[0] != HEADER:
        raise ValueError(f'{path}: unknown manifest header {lines[0]!r}')
    run_lines = both[:int(runs_size)].decode('ascii').splitlines()
    payload = both[int(runs_size):]
    name: str | None = None
    about = {'title': '', 'description': '', 'version': '', 'commit': '', 'author': ''}
    requires: list[str] = []
    choices: list[tuple[str, str]] = []
    ranges: list[RangeSetting] = []
    parts: list[Part] = []
    by_path: list[dict[DiscPath, FileEdit]] = []
    for line in lines[1:]:
        kind, cell, before, after = line.split('\t')
        if kind == 'name':
            name = cell
        elif kind in about:
            about[kind] = cell
        elif kind == 'requires':
            requires.append(cell)
        elif kind == 'range':
            ranges.append(RangeSetting(cell, *(int(x) for x in before.split(',')), after))
        elif kind in ('option', 'extra'):
            choices.append((cell, before))
        elif kind == 'part':
            parts.append(Part('' if cell == '-' else cell, []))
            by_path.append({})
        elif kind in ('file', 'raw'):
            if not parts:
                raise ValueError(f'{path}: a file row before any part')
            if cell in LAYOUT_FILES:
                raise ValueError(f'{path}: {cell} belongs to the layout')
            edit = FileEdit(cell, kind == 'raw', int(before), int(after))
            parts[-1].files.append(edit)
            by_path[-1][cell] = edit
        else:
            raise ValueError(f'{path}: unknown row kind {kind!r}')
    pos = 0
    twins: list[list[DiscPath]] = []
    current: dict[DiscPath, FileEdit] | None = None
    for line in run_lines:
        kind, cell, *cells = line.split('\t')
        if kind == 'twins':
            twins.append([cell, *cells])
            continue
        if kind == 'part':
            current = by_path[int(cell)]
            continue
        if current is None or cell not in current:
            raise ValueError(f'{path}: a {kind} row for {cell} has no file row in its part')
        if kind == 'check':
            current[cell].source = cells[0]
        elif kind == 'scale':
            current[cell].scales.append(Scale(int(cells[0]), cells[1], int(cells[2])))
        elif kind == 'mes-entry':
            n = int(cells[1])
            current[cell].entries.append(EntryEdit(int(cells[0]), payload[pos:pos + n], cells[2]))
            pos += n
        elif kind == 'bytes':
            n = int(cells[1])
            current[cell].spans.append(Span(int(cells[0]), payload[pos:pos + n]))
            pos += n
        else:
            raise ValueError(f'{path}: unknown row kind {kind!r}')
    if pos != len(payload):
        raise ValueError(f'{path}: {len(payload) - pos} payload bytes left over')
    if name is None:
        raise ValueError(f'{path}: no name row')
    return Pack(name, parts, about['title'], about['description'], about['version'],
                about['commit'], requires, choices, twins, ranges, author=about['author'])


def bind_ranges(pack: Pack, mod: 'mods.Mod') -> None:
    """Attach declared byte transforms from a builder's TSV product."""
    import csv
    from pathlib import Path
    import mods
    pack.ranges = [RangeSetting(r.key, r.minimum, r.maximum, r.step, r.default, r.name)
                   for r in mod.ranges]
    for setting in mod.ranges:
        with (Path(mods.ROOT) / setting.edits).open(newline='') as stream:
            reader = csv.DictReader(stream, delimiter='\t')
            if reader.fieldnames != ['path', 'offset', 'parameter', 'original']:
                raise ValueError('invalid range edit map')
            for row in reader:
                if row['parameter'] != setting.key:
                    continue
                target = next((e for p in pack.parts for e in p.files if e.path == row['path']), None)
                if target is None:
                    raise ValueError(f"{pack.name}: parameter file {row['path']} is absent")
                target.scales.append(Scale(int(row['offset']), setting.key, int(row['original'])))


def layer_from(name: str, source: Source, before: dict[DiscPath, bytes],
               after: dict[DiscPath, bytes], check_source: bool = False) -> Layer:
    """The layer that turns `before` into `after`: {DISC/PATH: bytes} maps of
    the files that differ from the disc `source` (a path missing from a map is
    the disc's own file)."""
    layer = Layer(name, [])
    for disc_path in sorted((set(before) | set(after)) - LAYOUT_FILES):
        new = after.get(disc_path)
        old = before.get(disc_path)
        shape = new if new is not None else old
        assert shape is not None   # the path came from one of the two maps
        raw = is_raw_file(disc_path, shape)
        if old is None:
            old = source.read(disc_path, raw)
        if new is None:
            new = source.read(disc_path, raw)
        if old == new:
            continue
        if file_formats().get(disc_path)=='mes':
            layer.files.append(FileEdit(disc_path,False,len(old),len(new),entries=prepared_mes_changes(old,new)))
            continue
        spans = [Span(a, new[a:b]) for a, b in runs(old, new)]
        layer.files.append(FileEdit(disc_path, raw, len(old), len(new),
                                    source_digest(old, raw) if check_source else None,
                                    spans))
    return layer


def compact_mes_edit(edit: FileEdit, before: bytes, after: bytes) -> FileEdit:
    """Prefer entry semantics only when they reproduce the complete result."""
    from dataclasses import replace
    entries = mes_changes(before, after)
    if replace_mes(before, entries) != after:
        raise ValueError('MES entry edits do not reproduce the supplied archive')
    return replace(edit, source=None, spans=[], entries=entries)


def save(out: str, pack: Pack | Layer) -> None:
    """Write a layer, stamped with the source it came from."""
    if isinstance(pack, Layer):
        pack = single(pack)
    pack.commit = pack.commit or source_version()
    write_layer(out, pack)
    changed = sum(sum(len(s.data) for s in edit.spans) + sum(len(e.data) for e in edit.entries)
                  for part in pack.parts for edit in part.files)
    print(f'modpack: {pack.name}: {len(pack.parts)} part(s), {changed} changed bytes'
          f' -> {out} ({os.path.getsize(out)} bytes)')


def read_tree(directory: str, source: Source) -> dict[DiscPath, bytes]:
    return {path: open(local, 'rb').read() for path, local in tree(directory, source).items()}


def retail_twins(source: Source) -> list[list[DiscPath]]:
    """The groups of files that are sector for sector the same on the disc
    (each sector from the subheader on, as build_disc.sector_body compares),
    one path per extent, in extent order - what build_disc.duplicate_files
    searches for, computed once."""
    by_extent: dict[int, DiscPath] = {}
    for path, (ext, size) in sorted(source.entries.items(), key=lambda e: e[1][0]):
        if size:
            by_extent.setdefault(ext, path)
    lengths: dict[int, list[tuple[int, DiscPath]]] = {}
    for ext, path in sorted(by_extent.items()):
        sectors = (source.entries[path][1] + 2047) // 2048
        lengths.setdefault(sectors, []).append((ext, path))
    classes: dict[tuple[int, bytes], list[DiscPath]] = {}
    for sectors, members in lengths.items():
        if len(members) < 2:
            continue
        firsts: dict[bytes, list[tuple[int, DiscPath]]] = {}
        for ext, path in members:
            first = build_disc.sector_body(source.disc.raw(ext))
            firsts.setdefault(first, []).append((ext, path))
        for first, candidates in firsts.items():
            if len(candidates) < 2:
                continue
            for ext, path in candidates:
                digest = hashlib.sha1(first)
                for n in range(1, sectors):
                    digest.update(build_disc.sector_body(source.disc.raw(ext + n)))
                classes.setdefault((sectors, digest.digest()), []).append(path)
    # Keep the existing extent order, independent of the candidate buckets.
    return sorted((group for group in classes.values() if len(group) > 1),
                  key=lambda group: source.entries[group[0]][0])


def cached_retail_twins(source: Source) -> list[list[DiscPath]]:
    """Reuse verified retail groups while image, index and discovery code agree."""
    import csv
    from pathlib import Path
    import build_step_cache
    cache = Path(ROOT) / 'build/step_cache/retail-twins'
    table = cache / 'groups.tsv'

    def discover() -> None:
        cache.mkdir(parents=True, exist_ok=True)
        with table.open('w', newline='') as stream:
            writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
            writer.writerow(('group', 'path'))
            for number, group in enumerate(retail_twins(source)):
                writer.writerows((number, path) for path in group)

    build_step_cache.run('retail duplicate groups',
                         [Path(source.disc.f.name), Path(__file__), Path(build_disc.__file__)],
                         [table], discover, cache / 'inputs.tsv',
                         context=(repr(sorted(source.entries.items())),))
    groups: dict[int, list[DiscPath]] = {}
    with table.open(newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if reader.fieldnames != ['group', 'path']:
            raise ValueError('invalid retail twin map')
        for row in reader:
            if row['path'] not in source.entries:
                raise ValueError('retail twin map references an absent file')
            groups.setdefault(int(row['group']), []).append(row['path'])
    if sorted(groups) != list(range(len(groups))) or any(len(g) < 2 for g in groups.values()):
        raise ValueError('invalid retail twin groups')
    return [groups[number] for number in range(len(groups))]


def make(out: str, name: str, from_tree: str | None = None, to_tree: str | None = None,
         check_source: bool = False, title: str = '', description: str = '',
         twins: bool = False, requires: list[str] | None = None) -> None:
    source = Source(retail_image())
    try:
        before = read_tree(from_tree, source) if from_tree else {}
        after = read_tree(to_tree or os.path.join(ROOT, 'build'), source)
        layer = layer_from(name, source, before, after, check_source)
        layer.title, layer.description = title, description
        layer.requires = list(requires or [])
        if twins:
            layer.twins = retail_twins(source)
        save(out, layer)
    finally:
        source.close()


def default_selection(packs: list[Pack]) -> Selection:
    """Every pack on, each at its defaults."""
    return {pack.name: pack.defaults() for pack in packs}


def selected(layers: list[str | Pack | Layer],
             selection: Selection | None = None, strict: bool = True) -> list[Layer]:
    """The layers to apply, in order: every part of each pack whose condition
    holds (a pack `selection` leaves out is on at its defaults)."""
    packs = [read_layer(item) if isinstance(item, str) else
             single(item) if isinstance(item, Layer) else item for item in layers]
    chosen = default_selection(packs) | (selection or {})
    import mods
    for pack in packs if strict else ():
        # a choice past the defaults needs a part that names it, or the layer
        # would patch the default and say nothing
        named = {token.strip() for part in pack.parts for label, picked in mods.parse_mods(part.when)
                 if label == pack.name for token in picked.split(',') if token.strip()}
        parameters = set()
        for token in chosen[pack.name]:
            key, sep, value = token.partition('=')
            setting = next((r for r in pack.ranges if r.key == key), None)
            if setting and sep:
                setting.validate(value)
                parameters.add(token)
        missing = sorted(chosen[pack.name] - pack.defaults() - named - parameters)
        if missing:
            raise ValueError(f'{pack.title or pack.name}: this release has no '
                             f'{", ".join(missing)} - its layer was built without it')
    from dataclasses import replace
    layers = []
    for pack in packs:
        values = {r.key: r.default for r in pack.ranges}
        for token in chosen[pack.name]:
            key, _sep, value = token.partition('=')
            if key in values:
                values[key] = next(r for r in pack.ranges if r.key == key).validate(value)
        for layer in parts_for(pack, chosen):
            layer.files = [replace(edit, spans=[*edit.spans, *(
                Span(scale.offset, bytes([scale.value(values[scale.parameter])]))
                for scale in edit.scales)], scales=[]) for edit in layer.files]
            layers.append(layer)
    return layers


def merge(source: Source, layers: list[str | Pack | Layer],
          selection: Selection | None = None,
          strict: bool = True, track_clashes: bool = True
          ) -> tuple[dict[DiscPath, bytearray], Clashes]:
    """{DISC/PATH: bytes} of every file the layers touch, applied in order,
    and {(earlier, later, DISC/PATH): bytes} where a later layer rewrites
    bytes an earlier one wrote with different values (a later layer that
    writes the same values agrees with it and is not counted). Release byte
    comparisons disable diagnostic tracking; source and span checks remain."""
    files: dict[DiscPath, bytearray] = {}
    owner: dict[DiscPath, npt.NDArray[np.uint8]] = {}  # 1 + index of the last layer per byte
    names: list[str] = []
    clashes: Clashes = {}
    for index, layer in enumerate(selected(layers, selection, strict)):
        names.append(layer.name)
        for edit in layer.files:
            if edit.path not in source.entries:
                raise ValueError(f'{layer.name}: {edit.path} is not on the disc')
            if edit.path in LAYOUT_FILES:
                raise ValueError(f'{layer.name}: {edit.path} belongs to the layout')
            data = files.get(edit.path)
            if data is None:
                data = bytearray(source.read(edit.path, edit.raw))
            if edit.source and source_digest(bytes(data), edit.raw) != edit.source:
                raise ValueError(f'{layer.name}: {edit.path} is not the file this layer'
                                 ' was made for (wrong disc, or a layer missing before it)')
            if edit.entries:
                if edit.spans or edit.raw or edit.scales:
                    raise ValueError('MES entries cannot share a file edit with byte edits')
                data = bytearray(replace_mes(bytes(data), edit.entries))
                files[edit.path] = data
                if track_clashes:
                    owner[edit.path] = np.full(len(data), index + 1, np.uint8)
                continue
            # An in-place edit whose bytes all land inside the file leaves
            # its length: the recorded size may include an extension another
            # part leaves out. One that writes past the end grows the file to
            # its whole recorded length, trailing zero padding included.
            reach = max((span.offset + len(span.data) for span in edit.spans), default=0)
            minimum = (reach if edit.length == edit.before and not edit.raw and not edit.scales
                       and reach <= len(data) else edit.length)
            if edit.length < edit.before:
                del data[edit.length:]
            elif len(data) < minimum:
                data.extend(b'\0' * (minimum - len(data)))
            own = owner.get(edit.path, np.zeros(0, np.uint8)) if track_clashes else None
            if own is not None:
                if len(own) > len(data):
                    own = own[:len(data)].copy()
                elif len(own) < len(data):
                    own = np.concatenate((own, np.zeros(len(data) - len(own), np.uint8)))
            for span in edit.spans:
                end = span.offset + len(span.data)
                if span.offset < 0 or end > len(data):
                    raise ValueError(f'{layer.name}: span outside {edit.path}')
                if own is not None:
                    had = own[span.offset:end]
                    new = np.frombuffer(span.data, np.uint8)
                    old = np.frombuffer(bytes(data[span.offset:end]), np.uint8)
                    hit = (had != 0) & (old != new)
                    for prev in np.unique(had[hit]).tolist():
                        key = (names[prev - 1], layer.name, edit.path)
                        clashes[key] = clashes.get(key, 0) + int(np.count_nonzero(had[hit] == prev))
                    own[span.offset:end] = index + 1
                data[span.offset:end] = span.data
            files[edit.path] = data
            if own is not None:
                owner[edit.path] = own
    return files, clashes


def apply(out: str, layers: list[str], image: str | None = None,
          selection: Selection | None = None) -> None:
    image = image or retail_image()
    source = Source(image)
    try:
        files, clashes = merge(source, layers, selection)
    finally:
        source.close()
    for (a, b, disc_path), n in sorted(clashes.items()):
        print(f'modpack: {b} rewrites {n} byte(s) of {disc_path} that {a} wrote')
    changed, volume = build_disc.build_to(image, out, {p: bytes(d) for p, d in files.items()})
    with open(os.path.splitext(out)[0] + '.cue', 'w', newline='\r\n') as c:
        c.write(f'FILE "{os.path.basename(out)}" BINARY\n  TRACK 01 MODE2/2352\n'
                '    INDEX 01 00:00:00\n')
    print(f'modpack: {len(layers)} layer(s), {changed} file(s) written; volume {volume}'
          f' sectors -> {out}')


def show(path: str) -> None:
    pack = read_layer(path)
    print(f'{pack.name} {pack.version or "(unpublished)"}: {pack.title or "-"}'
          f' ({pack.commit or "no commit"}) - {len(pack.parts)} part(s)')
    for label in pack.requires:
        print(f'  requires {label}')
    for token, name in pack.choices:
        print(f'  {"option" if "=" in token else "extra"} {token}: {name}')
    if pack.description:
        print(f'  {pack.description}')
    for part in pack.parts:
        print(f'  part {part.when or "(always)"}')
        for edit in part.files:
            print(f"    {edit.path:28} {'raw ' if edit.raw else ''}{edit.length:>10} bytes,"
                  f" {len(edit.spans)} run(s), {sum(len(s.data) for s in edit.spans)} bytes")


def main(argv: list[str]) -> int:
    if argv[:1] == ['make'] and len(argv) >= 2:
        args = [a for a in argv[2:] if a != '--check-source']
        opts = dict(zip(args[::2], args[1::2]))
        make(argv[1], opts.get('--name', os.path.splitext(os.path.basename(argv[1]))[0]),
             opts.get('--from-tree'), opts.get('--to-tree'), '--check-source' in argv[2:])
    elif argv[:1] == ['apply'] and len(argv) >= 3:
        rest = argv[2:]
        image = None
        choice: Selection = {}
        while rest[:1] in (['--source'], ['--choose']):
            if rest[0] == '--source':
                image = rest[1]
            else:
                import mods
                for label, picked in mods.parse_mods(rest[1]):
                    choice[label] = frozenset(t.strip() for t in picked.split(',') if t.strip())
            rest = rest[2:]
        apply(argv[1], rest, image, choice)
    elif argv[:1] == ['show'] and len(argv) == 2:
        show(argv[1])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
