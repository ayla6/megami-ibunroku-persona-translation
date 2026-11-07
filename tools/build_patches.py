"""Build, verify and incrementally resume the xdelta3 patch set.

The release applies one option at a time in a fixed solver order, so the
number of patch files grows with the options instead of with their
combinations. `rev1-to-rev0.xdelta` and `rev0-to-base.xdelta` convert the
retail disc to the base translation; every option is then an
`add-<option>.xdelta` file that splices its own changes into whatever
variant it is given.

Size-changers come first, because an insertion shifts every offset after
it: an option applied after one is encoded against the accumulated
size-changers (`add-60fps.xdelta` without the save menu,
`add-60fps-saves.xdelta` with it). In-place options come last and are
encoded from the undecorated size-changer layout (`add-mark.xdelta`,
`add-mark-saves.xdelta`, ...): their patches are the same size on both
sides, so a copy is an ordinary same-offset copy that preserves whatever
earlier in-place edits the disc carries. This ordering is what makes the
graph compose: a shifted copy only ever runs against an undecorated
source, so it can never carry a canonical byte over a decorated one. With
m size-changers each in-place option needs 2^m files; growth stays linear
in the options and exponential only in the size-changers.

A patch file is encoded from one canonical state - the base translation,
a size-changer anchor, or that anchor plus one in-place option. When the
applier's disc is exactly that state, xdelta's own per-window checksums
verify the step. Applied over a decorated variant (extra in-place edits
riding along) those checksums describe the canonical target, so the step
decodes with `-n` and its output size is checked; the patch file's own
SHA-256 is checked for integrity. A decorated disc never matches one
canonical hash, so the release claims no per-combination checksums and
proves nothing exhaustively: it is verified by SAMPLING. The popular
combinations and a seeded set of random ones are built as real one-shot
discs, the chain is applied exactly the way the web patcher applies it,
and the result must match the built disc byte for byte. Every add- row
records the selections that exercised it in the manifest's `verified`
column; rows no sample exercised are named in the build summary - that
residual risk is what sampling accepts.

Injection and assembly are the only sequential stage: they own the shared
build/ tree. A variant is written onto a clone of its parent's finished
image, so `build_disc` rewrites only the files the new option changes; a
size-changer added after another size-changer is laid out from retail in
one pass so its bytes match `build.py --qol=...`. Every finished image is
snapshotted (its placement record plus the builder's small report files)
and the audit and delta encode run in a worker pool behind the assembly of
the next variant. The audit reads the snapshot, never the live tree, and
compares the image with the one it was assembled on.

Scratch images live in a private workspace on the fastest filesystem with
room (`PERSONA_BUILD_SCRATCH` to override, the system temp directory by
default, build/ beside the project otherwise). The canonical states are
kept for the run; they are reflink clones and share their unchanged
extents, and the sampled discs are compared and deleted immediately.
Reruns rebuild only what changed: recorded patches are re-verified by
decoding them over the fresh states, and a canonical image not built this
run is reconstructed by decoding its verified patch. A Mark input edited
mid-run stops the run by name, because every variant built so far would
carry the old artwork.
"""
import argparse
import csv
import itertools
import json
import os
import random
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import itertools
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import build
import image_check
import build_step_cache
from fileutil import clone_file, reflink

CHOICES_SOURCE = Path(__file__).resolve().parent / 'release_options.json'
# Option wording (name and description) lives in release_options.json - the
# single source the release README and the web patcher grid are generated
# from; a wrong label here fails the coverage check in check_choices() and
# the wording test, never a release.
with open(CHOICES_SOURCE, encoding='utf-8') as _release_options:
    RELEASE_OPTIONS = json.load(_release_options)
CHOICES = tuple((item['label'], (item['label'],)) for item in RELEASE_OPTIONS)
CHOICE_ORDER = [label for label, _group in CHOICES]
# Options whose build appends bytes. Everything after an insertion shifts,
# so options applied later are encoded against the accumulated size-changers:
# a size-changer against the layout before it, an in-place option against
# every size-changer layout. The build verifies this classification against
# the solo images it assembles.
SIZE_CHANGERS = frozenset(('saves', '60fps'))
REV1_PATCH = 'rev1-to-rev0.xdelta'
BASE_PATCH = 'rev0-to-base.xdelta'
DEFAULT_REV1 = (ROOT / 'data/discs/Megami Ibunroku - Persona - Be Your True Mind (Japan) (Rev 1)' /
                'Megami Ibunroku - Persona - Be Your True Mind (Japan) (Rev 1).bin')
SCRATCH_ENV = 'PERSONA_BUILD_SCRATCH'
SCRATCH_NAME = 'persona-patch-work'
VERIFY_XDELTA = 'xdelta'      # the patch's own per-window checksums decide


def solver_order(labels):
    """The release applies one option at a time, in this order.

    Size-changers first (an insertion shifts every offset after it), then
    in-place options (their patches are the same size on both sides), each
    group in CHOICES order. The whole release graph hangs off this order:
    a variant is always reached by adding its last option to the variant
    without it, and a patch is encoded from the size-changer layout that
    precedes its option."""
    return sorted(labels, key=lambda label: (label not in SIZE_CHANGERS,
                                             CHOICE_ORDER.index(label)))


def patch_file(option, anchor):
    """The file that adds `option` on top of `anchor` (a frozenset of the
    size-changers already applied, never including `option` itself)."""
    suffix = ''.join('-' + label for label in CHOICE_ORDER if label in anchor)
    return f'add-{option}{suffix}.xdelta'


class Edge:
    """How one variant is reached: add `file` to the variant `source`.

    `source` is the canonical state the patch was encoded from, which is
    also the "parent" used to reconstruct the target by decoding. `anchor`
    is the size-changer subset in that source; a decorated chain applies
    the file over its own parent state (the source plus any earlier
    in-place options) with `-n`."""

    __slots__ = ('file', 'parent', 'anchor')

    def __init__(self, file, parent, anchor):
        self.file = file
        self.parent = parent          # encoded source state, solver order
        self.anchor = anchor

    def __repr__(self):
        return (f'Edge({self.file}, parent={self.parent}, '
                f'anchor={sorted(self.anchor)})')


def size_changer_states():
    """Every layout a patch can be encoded against, in build order.

    The empty layout, then each size-changer with every subset of the
    size-changers before it: with m of them that is 2^m states."""
    states = [()]
    sized = tuple(label for label in solver_order(CHOICE_ORDER)
                  if label in SIZE_CHANGERS)
    for index, option in enumerate(sized):
        preceding = sized[:index]
        for bits in itertools.product((False, True), repeat=len(preceding)):
            anchor = [label for label, on in zip(preceding, bits) if on]
            states.append(tuple(solver_order([*anchor, option])))
    return states


def release_edge(labels):
    """The edge to `labels`: its last option's add- file, encoded from the
    size-changer layout that precedes the option. In-place options after it
    ride along inside same-offset copies, so the file serves the decorated
    parent states too."""
    ordered = solver_order(labels)
    last = ordered[-1]
    anchor = frozenset(label for label in ordered[:-1]
                       if label in SIZE_CHANGERS)
    source = tuple(solver_order(anchor))
    return Edge(patch_file(last, anchor), source, anchor)


def release_file_names():
    """Every patch file a complete release can contain: the two revision
    conversions plus every add- edge of the release graph."""
    names = {REV1_PATCH, BASE_PATCH}
    for option, anchor in add_edges():
        names.add(patch_file(option, anchor))
    return names


def feature_names():
    """The display name for each option, from release_options.json: the one
    place option wording lives, so the README cannot drift from the page."""
    return {item['label']: item['name'] for item in RELEASE_OPTIONS}


def in_place_options():
    """The release options whose edits never change the image size."""
    return tuple(label for label in solver_order(CHOICE_ORDER)
                 if label not in SIZE_CHANGERS)


def canonical_states():
    """Every state a patch file is encoded from or to, in build order.

    The base translation, every size-changer layout, and - on each of
    those layouts - each in-place option on its own. In-place options
    compose over one another by same-offset copies, so they do not need a
    file per combination; the size-changer layout is what each one is
    anchored on."""
    anchors = size_changer_states()
    states = list(anchors)
    for option in in_place_options():
        for anchor in anchors:
            states.append(tuple(solver_order([*anchor, option])))
    return states


def add_edges():
    """(option, anchor) for every add- patch file a release can contain."""
    sized = tuple(label for label in solver_order(CHOICE_ORDER)
                  if label in SIZE_CHANGERS)
    for index, option in enumerate(sized):
        preceding = sized[:index]
        for bits in itertools.product((False, True), repeat=len(preceding)):
            yield option, frozenset(
                label for label, on in zip(preceding, bits) if on)
    anchors = size_changer_states()
    for option in in_place_options():
        for anchor in anchors:
            yield option, frozenset(anchor)


SAMPLE_POPULAR = (
    ('saves', 'mark', 'battlespeed', '60fps', 'run', 'skipfmv'),
    ('saves', 'mark', 'battlespeed', '60fps', 'run', 'skipfmv',
     'encounters', 'rewards'),
)


def sample_selections(n, seed):
    """The selections a release verifies end to end: the two expected-
    popular combinations first, then `n` random ones. The seed is part of
    the release's identity - the same seed rebuilds the same release, a
    new seed samples new combinations."""
    rng = random.Random(seed)
    picks = [tuple(solver_order(labels)) for labels in SAMPLE_POPULAR]
    seen = {frozenset(labels) for labels in picks}
    # Canonical states are the release's own encode inputs: applying their
    # own patch over them cannot disagree with the disc it was encoded from.
    # The samples exist to exercise the decorated chains, where in-place
    # options ride along and the add- patch decodes with -n.
    canonical = set(canonical_states())
    combos = []
    for bits in itertools.product((False, True), repeat=len(CHOICE_ORDER)):
        combo = frozenset(label for label, on in zip(CHOICE_ORDER, bits) if on)
        if combo and combo not in seen and combo not in canonical:
            combos.append(combo)
    rng.shuffle(combos)
    for combo in combos[:max(0, n)]:
        picks.append(tuple(solver_order(combo)))
    return picks


def release_selection(labels):
    """The build.py QoL names for a release state."""
    wanted = {label for label in labels}
    selected = {item for label, group in CHOICES if label in wanted for item in group}
    return [name for name in build.QOL_PATCHES if name in selected]


def state_labels(selected):
    """The inverse of release_selection, used by the build callback."""
    chosen = {item for item in selected}
    return tuple(label for label, group in CHOICES if chosen & set(group))


def assembly_parent(labels):
    """The state a variant is assembled on, or None for retail.

    A size-changer added after another size-changer is laid out from
    retail in one pass, so its bytes match a one-shot `build.py --qol=...`
    build. Every other state composes on the size-changer layout that
    precedes it: an in-place state is that layout plus its single option,
    and a lone size-changer is base plus that option."""
    ordered = solver_order(labels)
    if not ordered:
        return ()
    if ordered[-1] in SIZE_CHANGERS:
        parent = tuple(ordered[:-1])
        if any(label in SIZE_CHANGERS for label in parent):
            return None
        return parent
    return tuple(label for label in ordered if label in SIZE_CHANGERS)


def check_choices():
    """Fail before any work when a QoL patch has no release choice."""
    covered = {item for _label, group in CHOICES for item in group}
    if covered | {'debug'} != set(build.QOL_PATCHES):
        raise ValueError('QoL patch list changed; review release choices before publishing')


_HASH_CACHE = {}
_HASH_LOCK = threading.Lock()


def _signature(path):
    status = os.stat(path)
    return (status.st_dev, status.st_ino, status.st_size,
            status.st_mtime_ns, status.st_ctime_ns)


def sha256(path):
    """SHA-256 of a file, remembered for the rest of this run.

    A variant image is ~700 MB and immutable once built. Parent images,
    pending images and hardlinked proof sources are the same inode, and
    the same image is deliberately hashed at several graph edges, so
    rereading it each time is pure disk I/O. The signature includes the
    inode and timestamps, so a rewritten file (including through
    os.replace) never hits a stale digest."""
    signature = _signature(path)
    with _HASH_LOCK:
        digest = _HASH_CACHE.get(signature)
    if digest is not None:
        return digest
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    result = digest.hexdigest()
    with _HASH_LOCK:
        _HASH_CACHE[signature] = result
    return result


def _changed(before, after):
    """Paths whose digest differs between two build_step_cache.digests maps."""
    return [path for path in sorted(set(before) | set(after))
            if before.get(path) != after.get(path)]


def same_bytes(first, second):
    if os.path.getsize(first) != os.path.getsize(second):
        return False
    with open(first, 'rb') as a, open(second, 'rb') as b:
        while True:
            x, y = a.read(4 * 1024 * 1024), b.read(4 * 1024 * 1024)
            if x != y:
                return False
            if not x:
                return True


def run_delta(tool, source, target, output, *, disable_armor):
    """Encode, then verify the patch by decoding it with output disabled.

    `-J` reconstructs every target window and checks its checksum but
    writes nothing. The old round trip decoded another full ~700 MB image
    and read both that image and the target back just to compare them;
    this checks the same property without the two extra disk passes."""
    env = dict(os.environ)
    env.pop('XDELTA', None)
    flags = ['-a'] if disable_armor else []
    output.unlink(missing_ok=True)      # scratch; xdelta3 refuses to overwrite
    subprocess.run([tool, '-e', '-A', *flags, '-s', str(source), str(target), str(output)],
                   check=True, env=env)
    subprocess.run([tool, '-d', '-J', '-s', str(source), str(output)],
                   check=True, env=env)


def run_decode(tool, source, patch, output, *, skip_checksum=False):
    """Decode `patch` over `source` into `output` (scratch; never published)."""
    env = dict(os.environ)
    env.pop('XDELTA', None)
    output.unlink(missing_ok=True)
    command = [tool, '-d', *(['-n'] if skip_checksum else []),
               '-s', str(source), str(patch), str(output)]
    subprocess.run(command, check=True, env=env)


MANIFEST_FIELDS = ('patch', 'adds', 'anchor', 'order', 'choices', 'verify',
                   'source_bytes', 'source_sha256', 'target_bytes',
                   'target_sha256', 'patch_sha256', 'verified', 'build_key')


def write_manifest(path, rows):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                         dir=path.parent, delete=False) as out:
            temporary = Path(out.name)
            writer = csv.DictWriter(out, fieldnames=MANIFEST_FIELDS,
                                    delimiter='\t', lineterminator='\n',
                                    extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_manifest(path):
    """Rows keyed by patch name, one per step.

    Older releases (and the per-combination manifests) are not mistaken for
    this layout: a duplicate patch name means the file was written by the
    old graph, so rebuilding it in place would mix chains."""
    if not path.exists():
        return {}
    with open(path, encoding='utf-8', newline='') as source:
        reader = csv.DictReader(source, delimiter='\t')
        required = {'patch', 'adds', 'anchor', 'order', 'choices', 'verify',
                    'source_bytes', 'source_sha256', 'target_bytes',
                    'target_sha256', 'patch_sha256', 'verified',
                    'build_key'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f'{path}: unrecognized manifest; refusing to replace it')
        rows = {}
        for row in reader:
            name = row['patch']
            if not name or Path(name).name != name:
                raise ValueError(f'{path}: invalid patch name {name!r}')
            verify = row.get('verify') or VERIFY_XDELTA
            if verify != VERIFY_XDELTA:
                raise ValueError(
                    f'{path}: {name} was verified with {verify!r}; this layout'
                    ' only names xdelta checksums - move the release directory'
                    ' away and rerun')
            if name in rows:
                raise ValueError(
                    f'{path}: more than one row for {name} - this is the old'
                    ' per-combination manifest; move the release directory away'
                    ' and rerun')
            rows[name] = {key: row.get(key, '') for key in MANIFEST_FIELDS}
            rows[name]['verify'] = verify
        return rows


def release_fingerprint(rev0, xdelta):
    """Conservative inputs for deciding whether whole game variants can be reused.

    Only what actually feeds the built disc: not the rest of tools/ (those
    are manually-run helpers, and churn there - a test suite, an editor -
    must never invalidate a running release)."""
    from PIL import features as pil_features
    dependencies = sorted(f'{d.metadata["Name"]}=={d.version}' for d in metadata.distributions()
                          if d.metadata.get('Name'))
    paths = [ROOT / 'src', ROOT / 'translation', ROOT / 'data/psx',
             ROOT / 'data/cache', ROOT / 'data/extracted_text',
             ROOT / 'tools/build_patches.py', ROOT / 'tools/verify_disc.py',
             rev0, Path(xdelta), Path(sys.executable)]
    if build.ARMIPS:
        paths.append(Path(build.ARMIPS))
    return build_step_cache.fingerprint(paths, context=(
        *dependencies, pil_features.version_module('freetype2'), 'release-matrix-v5'))


def scratch_root(required_bytes):
    """Pick the filesystem this run keeps its private disc images on.

    The images are the release build's dominant I/O, so keep them off the
    project's data disk when another filesystem has room: an explicit
    $PERSONA_BUILD_SCRATCH first, then the system temp directory (tmpfs on
    most Linux systems), then build/ beside the project. Everything in it
    is scratch that is deleted on exit, so the directory must be
    disposable. The requirement covers the kept parent images too, so a
    small tmpfs is passed over for a real disk rather than filling RAM."""
    override = os.environ.get(SCRATCH_ENV)
    if override:
        root = Path(override).expanduser()
    else:
        root = None
        for candidate in (Path(tempfile.gettempdir()), ROOT / 'build'):
            try:
                if shutil.disk_usage(candidate).free >= required_bytes:
                    root = candidate
                    break
            except OSError:
                continue
        if root is None:
            root = ROOT / 'build'
    root.mkdir(parents=True, exist_ok=True)
    return root


def supports_reflink(root):
    """Whether `root`'s filesystem can share extents between image copies."""
    probe = root / f'.reflink-probe-{os.getpid()}'
    copy = root / f'.reflink-probe-{os.getpid()}-copy'
    try:
        probe.write_bytes(b'persona' * 512)
        return reflink(probe, copy)
    finally:
        probe.unlink(missing_ok=True)
        copy.unlink(missing_ok=True)


@contextmanager
def workspace(required_bytes):
    """Private scratch space for one release run.

    The directory is created with mkdir() (never exist_ok) so a concurrent
    or interrupted run can never be mistaken for ours; everything inside
    it is therefore this run's own work and is deleted wholesale on exit -
    a new scratch artifact must never be able to strand the next run."""
    work = scratch_root(required_bytes) / SCRATCH_NAME
    try:
        work.mkdir()
    except FileExistsError:
        raise RuntimeError(
            f'{work} already exists; another release may be running'
            ' (or was interrupted) - remove it and rerun') from None
    try:
        yield work
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build_release(rev0, rev1, output, xdelta, *, port=False, workers=3,
                  sample_n=3, seed=0):
    """Publish each verified patch and reuse unchanged results on later runs.

    There is one manifest row and one patch file per step, never one per
    combination. The build assembles only the canonical states - the base
    translation, every size-changer layout, and each in-place option on
    every layout - and encodes the add- patches from them. A decorated disc
    (other in-place options riding along) never matches a single canonical
    hash, so the release does not claim per-combination checksums: each step
    carries the patch file's own SHA-256, the output size, and xdelta's
    checksums verify any step applied from its exact canonical state; the
    rest decode with -n.

    The release is verified by sampling: the popular combinations and a
    seeded set of random ones are built as real one-shot discs, the chain is
    applied exactly the way the browser applies it, and the result must
    match the built disc byte for byte. Rows no sample exercised are named
    in the summary - that residual risk is what sampling accepts.
    """
    rev0, rev1, output = Path(rev0).resolve(), Path(rev1).resolve(), Path(output).absolute()
    image_check.require(str(rev0))
    image_check.require_rev1(str(rev1))
    check_choices()
    canonical = canonical_states()
    canonical_set = set(canonical)
    edges = {frozenset(labels): release_edge(labels) for labels in canonical
             if labels}
    samples = sample_selections(sample_n, seed)
    help_text = subprocess.run([xdelta, '-h'], capture_output=True, text=True, check=False)
    help_text = (help_text.stdout + help_text.stderr).lower()
    disable_armor = 'disable armor' in help_text
    if 'disable checksum' not in help_text:
        raise RuntimeError(f'{xdelta} has no -n (disable checksum); the release'
                           ' needs it to apply add- patches over decorated variants')
    output.mkdir(parents=True, exist_ok=True)
    image_bytes = rev0.stat().st_size
    # The canonical states stay for the whole run: children are reflink
    # clones of their parent, and the sample chains decode from the base
    # image. That is ~32 images plus the two chain slots, all sharing their
    # unchanged extents; sample discs are compared and deleted immediately.
    keep_images = len(canonical) + 3 + max(1, workers)
    with workspace(keep_images * image_bytes) as work:
        manifest = output / 'manifest.tsv'
        records = read_manifest(manifest)
        expected_files = release_file_names()
        foreign = sorted(set(records) - expected_files)
        if foreign:
            raise RuntimeError(
                f'{manifest} holds patches outside the current release layout'
                f' (for example {foreign[0]}) - move the old release directory'
                ' away and rerun; mixing layouts would corrupt the chains')
        # Stage the retail image once: every variant is written onto a clone
        # of this scratch copy, so the spinning disc is read once rather than
        # once per variant and each image is the ordinary build's output. The
        # hash is taken here, not from the original, so the bytes the release
        # is built from are the bytes that were staged.
        original = work / 'original.bin'
        clone_file(rev0, original)
        base = work / 'base.bin'
        rev1_hash = sha256(rev1)
        initial_key = release_fingerprint(rev0, xdelta)
        current_key = initial_key
        touched = set()
        records_lock = threading.Lock()
        image_lock = threading.RLock()
        tasks = ThreadPoolExecutor(max_workers=max(1, workers))
        futures = {}
        slots = itertools.count()
        built = {}          # labels -> image assembled or decoded this run
        baselines = {}      # labels -> the image it was assembled on

        def save_records():
            rows = [records[name] for name in sorted(records)]
            write_manifest(manifest, rows)

        def file_matches_row(name, row):
            path = output / name
            if not row or not path.is_file():
                return False
            if sha256(path) != row['patch_sha256']:
                raise RuntimeError(f'{path} was modified; refusing to replace your file')
            return True

        def anchor_text(anchor):
            return ','.join(label for label in solver_order(CHOICE_ORDER)
                            if label in anchor)

        def state_choices(labels):
            return ','.join(solver_order(labels))

        def canonical_row_ok(labels):
            if not labels:
                row = records.get(BASE_PATCH)
                return bool(row and file_matches_row(BASE_PATCH, row)
                            and row.get('build_key') == initial_key)
            ordered = solver_order(labels)
            edge = edges[frozenset(labels)]
            row = records.get(edge.file)
            if not row or not file_matches_row(edge.file, row):
                return False
            return (row.get('build_key') == initial_key
                    and row.get('adds') == ordered[-1]
                    and row.get('anchor') == anchor_text(edge.anchor)
                    and row.get('choices') == state_choices(labels))

        pending_canonical = [labels for labels in canonical
                             if port or not canonical_row_ok(labels)]
        build_states = list(pending_canonical)

        def build_order(labels):
            ordered = tuple(solver_order(labels)) if labels else ()
            return (len(ordered), ordered)

        build_states.sort(key=build_order)
        index = {tuple(release_selection(labels)): labels for labels in build_states}
        state_paths = {labels: work / f'state-{number}.bin'
                       for number, labels in enumerate(build_states)}

        def ensure_image(labels):
            """The canonical image for a state, built this run or decoded
            from its verified patch."""
            labels = tuple(solver_order(labels))
            path = built.get(labels)
            if path and Path(path).is_file():
                return Path(path)
            with image_lock:
                path = built.get(labels)
                if path and Path(path).is_file():
                    return Path(path)
                if not labels:
                    row = records.get(BASE_PATCH)
                    if not row or not file_matches_row(BASE_PATCH, row):
                        raise RuntimeError(
                            'cannot reconstruct the base translation: '
                            f'{BASE_PATCH} is missing from the release')
                    if not base.is_file():
                        run_decode(xdelta, original, output / BASE_PATCH, base)
                    built[labels] = base
                    return base
                edge = edges.get(frozenset(labels))
                if edge is None:
                    raise RuntimeError(
                        f'cannot reconstruct {state_choices(labels)}: it is'
                        ' not a canonical state of this release')
                row = records.get(edge.file)
                if not row or not file_matches_row(edge.file, row):
                    raise RuntimeError(
                        f'cannot reconstruct {edge.file}: it is missing from the release')
                source = ensure_image(edge.parent)
                dest = state_paths.get(labels)
                if dest is None:
                    dest = work / ('image-%s.bin' % '-'.join(labels))
                if not dest.is_file():
                    run_decode(xdelta, source, output / edge.file, dest)
                built[labels] = dest
                return dest

        def assembly_source(labels):
            """The image this variant is written onto.

            That is its parent's finished image, so `build_disc` writes only
            the files the new option changes. A size-changer added after
            another size-changer is laid out from retail in one pass, so its
            bytes match `build.py --qol=...` (the one-shot layout). An
            in-place state is written on its size-changer layout, so the
            patch for it is exactly that one option's edits."""
            labels = tuple(solver_order(labels))
            if not labels:
                return original
            parent = assembly_parent(labels)
            if parent is None:
                return original
            if parent in canonical_set or parent in built:
                return ensure_image(parent)
            return ensure_image(())

        def snapshot_audit(image, slot):
            placement = image.with_name(image.name + '.placement.tsv')
            if not placement.is_file():
                raise RuntimeError(
                    f'{placement.name} is missing - build_disc did not write'
                    ' the placement record this audit requires')
            audit = work / f'audit-{slot}'
            audit.mkdir()
            shutil.copyfile(placement, audit / 'placement.tsv')
            stable_placement = work / f'pend-{slot}.placement.tsv'
            shutil.copyfile(placement, stable_placement)
            for name in SIDE_FILES:
                source = ROOT / 'build' / name
                if source.is_file():
                    shutil.copy2(source, audit / name)
            return stable_placement, audit

        def verify_image(image, placement=None, side_files=None, baseline=None,
                         no_text=False):
            command = [sys.executable, str(ROOT / 'tools/verify_disc.py'), str(image),
                       '--original', str(baseline or original)]
            if placement is not None:
                command += ['--placement', str(placement)]
            if side_files is not None:
                command += ['--side-files', str(side_files)]
            if no_text:
                command.append('--no-text')
            subprocess.run(command, cwd=ROOT, check=True)

        def publish(generated, path):
            """Atomically install the verified patch, across filesystems too."""
            staged = path.with_name(path.name + '.tmp')
            try:
                shutil.copyfile(generated, staged)
                os.replace(staged, path)
            finally:
                staged.unlink(missing_ok=True)

        def record_row(name, source, target, metadata, key, hashes=None):
            """One manifest row. Whole-image SHA-256 columns are filled only
            where a canonical undecorated hash means something - the two
            revision conversions and the base translation. An add- row's
            source is whatever the player's earlier options made it, so its
            hash columns stay empty: the decoder checks sizes, the patch
            file's own hash catches damaged downloads, and the sampled
            chain comparisons are the verification."""
            with records_lock:
                records[name] = {
                    'patch': name,
                    'adds': metadata.get('adds', ''),
                    'anchor': metadata.get('anchor', ''),
                    'order': metadata.get('order', ''),
                    'choices': metadata.get('choices', ''),
                    'verify': VERIFY_XDELTA,
                    'source_bytes': str(source.stat().st_size),
                    'source_sha256': (sha256(source) if hashes and 'source' in hashes
                                      else ''),
                    'target_bytes': str(target.stat().st_size),
                    'target_sha256': (sha256(target) if hashes and 'target' in hashes
                                      else ''),
                    'patch_sha256': sha256(output / name),
                    'verified': metadata.get('verified', ''),
                    'build_key': key,
                }
                touched.add(name)
                save_records()

        def patch(source, target, name, metadata, key='', hashes=None):
            """Encode `name` from source to target, or reuse it if verified.

            Rows with whole-image hashes (the revision conversions and the
            base translation) reuse on the recorded hashes. An add- row has
            no hash columns to compare - its source is whatever the
            player's earlier options made it - so reuse is proven the
            direct way: the stored patch is decoded over this run's fresh
            source and must produce this run's fresh target byte for
            byte."""
            path = output / name
            if hashes == {'source', 'target'}:
                target_hash = sha256(target)
                source_hash = sha256(source)
            else:
                target_hash = source_hash = None
            old = records.get(name)
            if (old and file_matches_row(name, old)
                    and hashes == {'source', 'target'}
                    and old.get('target_sha256') == target_hash
                    and old.get('source_sha256') == source_hash):
                print(f'patch: {name} unchanged; reusing verified patch', flush=True)
                with records_lock:
                    row = records[name]
                    row.update({'adds': metadata.get('adds', ''),
                                'anchor': metadata.get('anchor', ''),
                                'order': metadata.get('order', ''),
                                'choices': metadata.get('choices', ''),
                                'verify': VERIFY_XDELTA,
                                'build_key': key})
                    touched.add(name)
                    save_records()
                return
            if (old and file_matches_row(name, old)
                    and old.get('target_bytes') == str(target.stat().st_size)
                    and old.get('source_bytes') == str(source.stat().st_size)):
                decoded = work / f'reuse-{threading.get_ident()}.bin'
                try:
                    run_decode(xdelta, source, path, decoded, skip_checksum=True)
                    if same_bytes(target, decoded):
                        print(f'patch: {name} re-verified over the fresh state',
                              flush=True)
                        with records_lock:
                            row = records[name]
                            row.update({'adds': metadata.get('adds', ''),
                                        'anchor': metadata.get('anchor', ''),
                                        'order': metadata.get('order', ''),
                                        'choices': metadata.get('choices', ''),
                                        'verify': VERIFY_XDELTA,
                                        'build_key': key})
                            touched.add(name)
                            save_records()
                        return
                finally:
                    decoded.unlink(missing_ok=True)
            if path.exists():
                if old:
                    if sha256(path) != old['patch_sha256']:
                        raise RuntimeError(
                            f'{path} was modified; refusing to replace your file')
                else:
                    decoded = work / f'existing-{threading.get_ident()}.bin'
                    try:
                        run_decode(xdelta, source, path, decoded)
                        if not same_bytes(target, decoded):
                            raise RuntimeError(
                                f'{path} is not the expected patch; refusing to'
                                ' replace it')
                    finally:
                        decoded.unlink(missing_ok=True)
                    record_row(name, source, target, metadata, key,
                               hashes=hashes)
                    print(f'patch: {name} verified and reused', flush=True)
                    return
            print(f'patch: {name}', flush=True)
            generated = work / f'new-{threading.get_ident()}-{name}'
            try:
                run_delta(xdelta, source, target, generated,
                          disable_armor=disable_armor)
                publish(generated, path)
            finally:
                generated.unlink(missing_ok=True)
            record_row(name, source, target, metadata, key, hashes=hashes)

        # The Rev 1 conversion is independent of the build inputs; reuse it
        # whenever its bytes still match the source disc.
        revision_row = records.get(REV1_PATCH)
        if (revision_row and file_matches_row(REV1_PATCH, revision_row)
                and revision_row.get('source_sha256') == rev1_hash):
            print(f'patch: {REV1_PATCH} unchanged; reusing verified patch', flush=True)
            with records_lock:
                row = records[REV1_PATCH]
                row.update({'adds': '', 'anchor': '', 'order': '',
                            'choices': '', 'verified': '', 'build_key': ''})
                touched.add(REV1_PATCH)
                save_records()
        else:
            patch(rev1, original, REV1_PATCH,
                  {'adds': '', 'anchor': '', 'order': '', 'choices': ''}, '',
                  hashes={'source', 'target'})

        built_first = False

        def base_task(image, placement, audit, key):
            try:
                verify_image(image, placement, audit)
                patch(original, image, BASE_PATCH,
                      {'adds': '', 'anchor': '', 'order': '', 'choices': ''},
                      key, hashes={'source', 'target'})
            finally:
                placement.unlink(missing_ok=True)
                shutil.rmtree(audit, ignore_errors=True)

        def edge_task(labels, image, placement, audit, baseline, key):
            ordered = solver_order(labels)
            option = ordered[-1]
            edge = edges[frozenset(labels)]
            metadata = {
                'adds': option,
                'anchor': anchor_text(edge.anchor),
                'order': str(solver_order(CHOICE_ORDER).index(option)),
                'choices': state_choices(labels),
            }
            try:
                verify_image(image, placement, audit, baseline=baseline,
                             no_text=True)
                source = ensure_image(edge.parent)
                patch(source, image, edge.file, metadata, key)
                if not edge.anchor and not edge.parent:
                    # The whole graph hangs on which options grow the image:
                    # verify the classification against the assembled solo
                    # build, never trust the constant.
                    grew = image.stat().st_size != source.stat().st_size
                    if grew != (option in SIZE_CHANGERS):
                        raise RuntimeError(
                            f'{option} solo build {"grew" if grew else "kept"}'
                            ' the image size but SIZE_CHANGERS says the'
                            ' opposite - correct build_patches.py before'
                            ' releasing')
            finally:
                cue = image.with_suffix('.cue')
                if cue.exists():
                    cue.unlink()
                placement.unlink(missing_ok=True)
                shutil.rmtree(audit, ignore_errors=True)

        def finished(selected, image):
            nonlocal current_key, built_first
            image = Path(image)
            if not built_first:
                current_key = release_fingerprint(rev0, xdelta)
                if current_key != initial_key:
                    raise RuntimeError('build inputs changed during preparation;'
                                       ' rerun to rebuild affected variants')
                built_first = True
            labels = index[tuple(selected)]
            built[labels] = image
            slot = next(slots)
            placement, audit = snapshot_audit(image, slot)
            parent = assembly_parent(labels)
            if not labels:
                futures[labels] = tasks.submit(
                    base_task, image, placement, audit, current_key)
                return
            baseline = baselines.get(labels)
            if baseline is None:
                baseline = original if parent is None else ensure_image(parent)
            futures[labels] = tasks.submit(
                edge_task, labels, image, placement, audit, baseline, current_key)

        def source_image_for(patches):
            labels = index.get(tuple(patches))
            if labels is None:
                raise RuntimeError('release asked for an unknown variant')
            source = assembly_source(labels)
            baselines[labels] = Path(source)
            return str(source)

        mark_cache = work / 'mark'
        mark_state = {}
        MARK_FILES = ('ADV/MES.BIN', 'ADV/BST.BIN', 'B/P.BIN')

        def mark_builder(py):
            # Mark's producer reads these original files, source code and art,
            # not another variant. Generate and verify it once per run;
            # restored copies are byte-identical (checked below), so their
            # pixels cannot diverge from the verified artwork. mark.py's own
            # source and the code it imports, not the whole tool directory:
            # another contributor editing an unrelated generator must not
            # abort a running release.
            inputs = [ROOT / 'src/injection_tools/mark.py',
                      ROOT / 'src/injection_tools/mescodec.py',
                      ROOT / 'src/assets/mark/black',
                      ROOT / 'data/psx/ADV/MES.BIN', ROOT / 'data/psx/ADV/BST.BIN',
                      ROOT / 'data/psx/B/P.BIN', ROOT / 'data/psx/BTLP.BIN']
            current = build_step_cache.digests(inputs)
            if not mark_state:
                build.run(py, os.path.join('injection_tools', 'mark.py'), 'build')
                build.run(py, os.path.join('injection_tools', 'mark.py'), 'verify')
                after = build_step_cache.digests(inputs)
                if after != current:
                    raise RuntimeError('Mark inputs changed during release generation: '
                                       + ', '.join(_changed(current, after))
                                       + ' - rerun once the edits are saved')
                mark_cache.mkdir()
                for name in MARK_FILES:
                    (mark_cache / name).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / 'build' / name, mark_cache / name)
                mark_state.update(inputs=current,
                                  hashes={name: sha256(mark_cache / name)
                                          for name in MARK_FILES})
                return
            stale = [f'cache/{name}' for name in MARK_FILES
                     if sha256(mark_cache / name) != mark_state['hashes'][name]]
            changed = _changed(mark_state['inputs'], current)
            if changed or stale:
                # every variant built so far carries the old artwork, so a
                # release that mixed both would be wrong; stop and say why
                raise RuntimeError(
                    'Mark inputs or cached outputs changed during release generation ('
                    + ', '.join((changed + stale)[:6])
                    + '); variants already built this run are stale - rerun the release build')
            for name in MARK_FILES:
                (ROOT / 'build' / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(mark_cache / name, ROOT / 'build' / name)
            print('build: reused byte-verified Mark artwork', flush=True)

        SIDE_FILES = ('dng_spill.asm', 'affinity_gated.tsv',
                      'descs_drafts.tsv', 'btl_board_drafts.tsv')

        if build_states:
            previous_argv, previous_image = sys.argv, build.ORIGINAL_IMAGE
            try:
                sys.argv = ['build.py', '--incremental'] + ([] if port else ['--no-port'])
                build.ORIGINAL_IMAGE = str(original)
                variants = [(release_selection(labels), str(state_paths[labels]))
                            for labels in build_states]
                build.main(variants_override=variants, after_variant=finished,
                           mark_builder=mark_builder,
                           source_image_for=source_image_for)
            finally:
                sys.argv, build.ORIGINAL_IMAGE = previous_argv, previous_image
                tasks.shutdown(wait=True)     # workers finish before scratch cleanup
            for future in list(futures.values()):   # surface any worker failure here
                future.result()
            if release_fingerprint(rev0, xdelta) != current_key:
                for name in touched - {REV1_PATCH}:
                    records[name]['build_key'] = ''
                save_records()
                raise RuntimeError('build inputs changed during release generation;'
                                   ' rerun the build')
        else:
            tasks.shutdown(wait=True)

        def decode_chain(labels, first, second):
            """Decode the add- patches for `labels` over the base translation,
            the same order and the same strict/-n rule the browser uses for a
            decorated chain. Returns the image path (one of the two scratch
            slots)."""
            current = ensure_image(())
            dest = first
            applied = set()
            for label in solver_order(labels):
                anchor = frozenset(item for item in applied
                                   if item in SIZE_CHANGERS)
                name = patch_file(label, anchor)
                row = records.get(name)
                if not row or not file_matches_row(name, row):
                    raise RuntimeError(
                        f'cannot verify {name}: it is missing from the release')
                canonical = (applied == {item for item in row['choices'].split(',')
                                         if item} - {label})
                run_decode(xdelta, current, output / name, dest,
                           skip_checksum=not canonical)
                applied.add(label)
                current = dest
                dest = second if dest == first else first
            return current

        expected_rows = {BASE_PATCH, REV1_PATCH} | {
            edge.file for edge in edges.values()}

        def sample_phase():
            """The release's verification: each sampled selection is built
            as a real one-shot disc from retail, the chain is applied
            exactly the way the browser applies it, and the result must be
            that disc byte for byte. Every row a sample exercised records
            the selection; rows no sample exercised are named in the
            summary - that residual risk is what sampling accepts.

            All selections that still need verifying are built in one
            `build.main` pass, so the shared asset preparation runs once,
            not once per sample."""
            def chain_names(labels):
                ordered = solver_order(labels)
                return [BASE_PATCH] + [
                    patch_file(label, frozenset(item for item in ordered[:index]
                                                if item in SIZE_CHANGERS))
                    for index, label in enumerate(ordered)]

            def covered(selection, names):
                return all(selection in
                           (records.get(name, {}).get('verified') or '').split(';')
                           for name in names)

            pending = []
            for number, labels in enumerate(samples):
                selection = state_choices(labels)
                names = chain_names(labels)
                if covered(selection, names):
                    print(f'patch: sample {selection} already verified', flush=True)
                    continue
                image = work / f'sample-{number}.bin'
                image.unlink(missing_ok=True)
                pending.append((number, labels, selection, names, image))
            def audit_sample(selected, path):
                """Audit the disc while the build tree that produced it is
                still live: the sample must be a proper build, not just
                bytes written by the fake builder."""
                path = Path(path)
                verify_image(path, path.with_name(path.name + '.placement.tsv'),
                             baseline=original, no_text=True)

            if pending:
                previous_argv, previous_image = sys.argv, build.ORIGINAL_IMAGE
                try:
                    sys.argv = ['build.py', '--incremental', '--no-port']
                    build.ORIGINAL_IMAGE = str(original)
                    build.main(variants_override=[
                                   (release_selection(labels), str(image))
                                   for _number, labels, _selection, _names, image
                                   in pending],
                               after_variant=audit_sample,
                               mark_builder=mark_builder,
                               source_image_for=lambda patches: str(original))
                finally:
                    sys.argv, build.ORIGINAL_IMAGE = previous_argv, previous_image
            used = {}
            for number, labels, selection, names, image in pending:
                print(f'patch: checking sample {selection}', flush=True)
                built_bytes = image.stat().st_size
                first = work / f'sample-{number}-a.bin'
                second = work / f'sample-{number}-b.bin'
                try:
                    applied = decode_chain(labels, first, second)
                    if applied.stat().st_size != built_bytes:
                        raise RuntimeError(
                            f'the sampled chain for {selection} produces '
                            f'{applied.stat().st_size} bytes, the built disc '
                            f'is {built_bytes}')
                    if sha256(applied) != sha256(image):
                        raise RuntimeError(
                            f'the sampled chain for {selection} does not '
                            'reproduce the built disc byte for byte - the '
                            'patches do not compose; review build_patches.py '
                            '(SIZE_CHANGERS, solver order)')
                finally:
                    first.unlink(missing_ok=True)
                    second.unlink(missing_ok=True)
                    image.unlink(missing_ok=True)
                    image.with_suffix('.cue').unlink(missing_ok=True)
                for name in names:
                    used.setdefault(name, []).append(selection)
                print(f'patch: sample {selection} verified byte for byte',
                      flush=True)
            with records_lock:
                for name, selections in used.items():
                    row = records[name]
                    # Union with earlier runs' samples: a new seed must not
                    # erase the selections that already verified this row.
                    row['verified'] = ';'.join(dict.fromkeys(
                        ((row['verified'].split(';')) if row['verified'] else [])
                        + selections))
                    touched.add(name)
                save_records()
            unverified = sorted(name for name in expected_rows
                                if name.startswith('add-')
                                and name in records
                                and not records[name]['verified'])
            if unverified:
                print('patch: NO sample exercised '
                      + ', '.join(unverified)
                      + ' - these apply unverified (the risk sampling accepts;'
                      ' report anything broken)', flush=True)

        sample_phase()

        missing = expected_rows - set(records)
        if missing:
            raise RuntimeError('not every release patch was created: '
                               + ', '.join(sorted(missing)))
        stale_rows = set(records) - expected_rows
        if stale_rows:
            for name in stale_rows:
                del records[name]
            print(f'patch: pruned {len(stale_rows)} stale manifest rows', flush=True)
            save_records()
        stale_files = [path for path in output.glob('*.xdelta')
                       if path.name not in expected_files]
        for path in stale_files:
            print(f'patch: removing stale {path.name}', flush=True)
            path.unlink()
        for name in sorted(expected_files):
            if not (output / name).is_file():
                raise RuntimeError(f'{name} is missing from the release')
        # The README is generated, never hand-typed: option names come from
        # release_options.json (the same file the web patcher's features.js
        # is generated from), file names and counts from the same structures
        # that produced the release, so adding an option rewrites this file
        # correctly.
        features = feature_names()
        entries = [(REV1_PATCH, 'Rev 1 discs only (Rev 0 skips it)'),
                   (BASE_PATCH, 'the base translation')]
        for option, anchor in add_edges():
            comment = features.get(option, option)
            if anchor:
                applied = ' + '.join(features.get(label, label)
                                     for label in solver_order(anchor))
                comment += f' (with {applied} applied)'
            entries.append((patch_file(option, anchor), comment))
        width = max(len(name) for name, _comment in entries)
        digits = len(str(len(entries)))
        listing = '\n'.join(
            f'  {str(number).rjust(digits)}. {name.ljust(width)}  {comment}'
            for number, (name, comment) in enumerate(entries, 1))
        readme = output / 'README.txt'
        readme.write_text(
            'Persona translation patches\n'
            '===========================\n'
            '\n'
            'Patching this by hand isn\'t recommended, it explicitly ignores\n'
            'the xdelta checksums to not have a trillion patches doing the\n'
            'exact same thing. Use the webapp\n'
            'https://ayla6.github.io/megami-ibunroku-persona-translation.\n'
            '\n'
            f'{len(expected_files)} patch files cover every combination of\n'
            'the release options. Apply them in this order, skipping the\n'
            'add- patches for options you do not want:\n'
            '\n'
            f'{listing}\n'
            '\n'
            '    xdelta3 -d -s your.bin <patch>.xdelta result.bin\n'
            '\n'
            'Size-changing options come first: an insertion shifts every\n'
            'offset after it, so each such patch is encoded against the\n'
            'layout built before it, and the order above is fixed. In-place\n'
            'options come last, one file per size-changing layout; their\n'
            'patches keep the image size, so they compose over one another\n'
            'by same-offset copies.\n'
            '\n'
            'Each patch is encoded from one canonical state. When your disc\n'
            'has exactly that state, xdelta\'s own window checksums verify\n'
            'the step. On a decorated disc (other in-place options already\n'
            'applied) those checksums describe the canonical target, so pass\n'
            '-n and check the output size instead:\n'
            '\n'
            '    xdelta3 -n -d -s your.bin <patch>.xdelta result.bin\n'
            '\n'
            'The release does not claim a checksum for every combination: a\n'
            'decorated disc never matches one canonical hash. It was\n'
            'verified by SAMPLING instead - the combinations listed in the\n'
            'manifest\'s verified column were built as real discs and the\n'
            'web patcher\'s exact chain was applied to the original and\n'
            'compared byte for byte. Combinations no sample covered are the\n'
            'risk this accepts; report anything broken.\n'
            '\n'
            'manifest.tsv has one row per patch file, not one per\n'
            'combination: adds names the option, anchor the size-changers the\n'
            'patch was encoded against, and order the fixed apply order.\n'
            f'A release is complete when its manifest lists {len(expected_rows)}\n'
            f'steps across {len(expected_files)} patch files.\n',
            encoding='utf-8')
    print(f'{len(expected_files)} verified patch files ({len(expected_rows)} steps)'
          f' available in {output}', flush=True)


def find_xdelta3(explicit=None):
    bundled = ROOT / 'external_tools' / 'xdelta3' / ('xdelta3.exe' if sys.platform == 'win32' else 'xdelta3')
    return explicit or (str(bundled) if bundled.is_file() else None) or shutil.which('xdelta3')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--rev0', default=build.ORIGINAL_IMAGE, help='original Rev 0 BIN')
    parser.add_argument('--rev1', default=str(DEFAULT_REV1), help='original Rev 1 BIN')
    parser.add_argument('--output', default=str(ROOT / 'dist' / 'patches'),
                        help='directory for verified patches (existing patches can be reused)')
    parser.add_argument('--xdelta3', default=None, help='path to xdelta3 (default: external_tools, then PATH)')
    parser.add_argument('--port', action='store_true', help='regenerate translation tables first')
    parser.add_argument('--workers', type=int, default=3,
                        help='parallel disc audits and delta encodes (default: 3)')
    parser.add_argument('--sample', type=int, default=3, metavar='N',
                        help='random combinations to verify end to end, on top'
                             ' of the popular ones (default: 3; the release is'
                             ' verified by sampling, not by proving every'
                             ' combination)')
    parser.add_argument('--seed', type=int, default=0,
                        help='the random combinations\' seed (default: 0; the'
                             ' same seed rebuilds the same release)')
    parser.add_argument('--publish-release', '--publish-web',
                        dest='publish_release', action='store_true',
                        help='upload the release and refresh the local web'
                             ' patcher copy afterwards (GitHub Actions deploys'
                             ' the site on push; --publish-web is the old name)')
    args = parser.parse_args(argv)
    tool = find_xdelta3(args.xdelta3)
    if not tool:
        parser.error('xdelta3 is required; run python src/setup_external_tools.py or pass --xdelta3')
    try:
        build_release(args.rev0, args.rev1, args.output, tool, port=args.port,
                      workers=args.workers, sample_n=args.sample, seed=args.seed)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'build_patches.py: {error}\n')
    if args.publish_release:
        sys.path.insert(0, str(ROOT / 'tools'))
        import publish_patches
        publish_patches.publish(directory=args.output, allow_incomplete=False)


if __name__ == '__main__':
    main()
