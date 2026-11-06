"""Build, verify and incrementally resume the xdelta3 patch set.

The release applies one option at a time in a fixed solver order, so the
number of patch files grows with the options instead of with their
combinations. `rev1-to-rev0.xdelta` and `rev0-to-base.xdelta` convert the
retail disc to the base translation; every option is then an
`add-<option>.xdelta` file that splices its own changes into whatever
variant it is given. Options whose edits stay in place never move another
option's offsets, so one file each serves every variant. Options that add
bytes shift every offset after the insertion, so an option applied after
them is encoded against the accumulated size-changers: `add-60fps.xdelta`
for discs without the save menu, `add-60fps-saves.xdelta` for discs with
it. With m size-changers the last one needs 2^(m-1) anchor files; in-place
options always ride along for free, so growth stays linear where it
matters.

Checksums are split the same way. A step whose source is exactly the image
the patch was encoded from verifies with xdelta's own per-window checksums
(manifest `verify=xdelta`). Applied over a decorated variant - the same
layout with extra in-place edits riding along - the recorded window
checksums describe a flavor of the target the applier is not producing and
would wrongly reject a correct decode, so those steps decode with `-n` and
are certified instead by the SHA-256 of the whole result (manifest
`verify=sha256`), which is recorded per row. Nothing ships unchecked: the
build proves every sha256 row by decoding the patch against the exact
source state an user can present and comparing the result, byte for byte,
with the audited built disc; the web patcher re-hashes every such step
while applying, and this README tells command line users to do the same.

Injection and assembly are the only sequential stage: they own the shared
build/ tree. Every variant image is written onto a clone of the staged
retail copy, exactly as `build.py --qol=...` writes it, so a release target
is the same bytes as the build a developer can reproduce by hand. Every
finished image is snapshotted (its placement record plus the builder's
small report files) and the audit, the delta encode or portability proof,
and publication run in a worker pool behind the assembly of the next
variant. The audit reads the snapshot, never the live tree, and compares
every image with retail - the same baseline an ordinary build uses.

Scratch images live in a private workspace on the fastest filesystem with
room (`PERSONA_BUILD_SCRATCH` to override, the system temp directory by
default, build/ beside the project otherwise). Images that serve as the
source state of later proofs are kept as hardlinks - they cost no extra
data blocks - and any other parent image is reconstructed by decoding its
verified patch. Reruns rebuild only what changed: recorded patches are
re-hashed and reused, and a missing intermediate image is reconstructed
from the staged original. A Mark input edited mid-run stops the run by
name, because every variant built so far would carry the old artwork.
"""
import argparse
import csv
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
# from; a wrong label here fails the coverage check in combinations() and
# the wording test, never a release.
with open(CHOICES_SOURCE, encoding='utf-8') as _release_options:
    RELEASE_OPTIONS = json.load(_release_options)
CHOICES = tuple((item['label'], (item['label'],)) for item in RELEASE_OPTIONS)
CHOICE_ORDER = [label for label, _group in CHOICES]
# Options whose build appends bytes. Everything after an insertion shifts,
# so patches for options applied later must be encoded against the
# accumulated size-changers; in-place options never need that. The build
# verifies this classification against the solo images it assembles.
SIZE_CHANGERS = frozenset(('saves', '60fps'))
REV1_PATCH = 'rev1-to-rev0.xdelta'
BASE_PATCH = 'rev0-to-base.xdelta'
DEFAULT_REV1 = (ROOT / 'data/discs/Megami Ibunroku - Persona - Be Your True Mind (Japan) (Rev 1)' /
                'Megami Ibunroku - Persona - Be Your True Mind (Japan) (Rev 1).bin')
SCRATCH_ENV = 'PERSONA_BUILD_SCRATCH'
SCRATCH_NAME = 'persona-patch-work'
VERIFY_XDELTA = 'xdelta'      # the patch's own per-window checksums decide
VERIFY_SHA256 = 'sha256'      # decode with -n; the manifest's row hash decides


def solver_order(labels):
    """The release applies one option at a time, in this order.

    In-place options first (their edits never move another option's
    bytes), size-changers last (an insertion shifts every offset after
    it), each group in CHOICES order. The whole release graph hangs off
    this order: a variant is always reached by adding its last option to
    the variant without it."""
    return sorted(labels, key=lambda label: (label in SIZE_CHANGERS,
                                             CHOICE_ORDER.index(label)))


def patch_file(option, anchor):
    """The file that adds `option` on top of `anchor` (a frozenset of the
    size-changers already applied, never including `option` itself)."""
    suffix = ''.join('-' + label for label in CHOICE_ORDER if label in anchor)
    return f'add-{option}{suffix}.xdelta'


class Edge:
    """How one variant is reached: add `file` to the variant `parent`.

    `anchor` is the set of size-changers the file was encoded against;
    a step whose source is exactly the anchor verifies with xdelta's own
    checksums, anything else (in-place options riding along) is proven
    and checked by whole-file SHA-256 instead."""

    __slots__ = ('file', 'parent', 'anchor', 'verify')

    def __init__(self, file, parent, anchor, verify):
        self.file = file
        self.parent = parent          # parent state, in solver order
        self.anchor = anchor
        self.verify = verify

    def __repr__(self):
        return (f'Edge({self.file}, parent={self.parent}, '
                f'anchor={sorted(self.anchor)}, verify={self.verify})')


def release_edge(labels):
    """The edge to `labels`: its last option's add- file, anchored at the
    size-changers selected before it. In-place options among the parents
    ride along inside the copied regions, so the file serves the decorated
    parent states too - those steps are the sha256-verified ones."""
    ordered = solver_order(labels)
    last = ordered[-1]
    parent = tuple(ordered[:-1])
    anchor = frozenset(label for label in parent if label in SIZE_CHANGERS)
    verify = VERIFY_XDELTA if frozenset(parent) == anchor else VERIFY_SHA256
    return Edge(patch_file(last, anchor), parent, anchor, verify)


def release_file_names():
    """Every patch file a complete release can contain: the two revision
    conversions, one file per in-place option, and per size-changer one
    file per subset of the size-changers that can be applied before it."""
    names = {REV1_PATCH, BASE_PATCH}
    sized = solver_order(sorted(SIZE_CHANGERS, key=CHOICE_ORDER.index))
    for index, option in enumerate(sized):
        preceding = sized[:index]
        for bits in itertools.product((False, True), repeat=len(preceding)):
            anchor = frozenset(s for s, on in zip(preceding, bits) if on)
            names.add(patch_file(option, anchor))
    for option in CHOICE_ORDER:
        if option not in SIZE_CHANGERS:
            names.add(patch_file(option, frozenset()))
    return names


def feature_names():
    """The display name for each option, from release_options.json: the one
    place option wording lives, so the README cannot drift from the page."""
    return {item['label']: item['name'] for item in RELEASE_OPTIONS}


def combinations():
    """All release choices, and no debug."""
    covered = {item for _label, group in CHOICES for item in group}
    if covered | {'debug'} != set(build.QOL_PATCHES):
        raise ValueError('QoL patch list changed; review release choices before publishing')
    for bits in itertools.product((False, True), repeat=len(CHOICES)):
        labels = [label for (label, _group), enabled in zip(CHOICES, bits) if enabled]
        selected = {item for (_label, group), enabled in zip(CHOICES, bits)
                    if enabled for item in group}
        yield labels, [name for name in build.QOL_PATCHES if name in selected]


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


def write_manifest(path, rows):
    fields = ('patch', 'choices', 'verify', 'source_bytes', 'source_sha256',
              'target_bytes', 'target_sha256', 'patch_sha256', 'build_key')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                         dir=path.parent, delete=False) as out:
            temporary = Path(out.name)
            writer = csv.DictWriter(out, fieldnames=fields, delimiter='\t', lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_manifest(path):
    if not path.exists():
        return {}
    with open(path, encoding='utf-8', newline='') as source:
        reader = csv.DictReader(source, delimiter='\t')
        required = {'patch', 'choices', 'source_bytes', 'source_sha256',
                    'target_bytes', 'target_sha256', 'patch_sha256'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f'{path}: unrecognized manifest; refusing to replace it')
        rows = {}
        for row in reader:
            name = row['patch']
            if not name or Path(name).name != name:
                raise ValueError(f'{path}: invalid patch name {name!r}')
            verify = row.get('verify') or VERIFY_XDELTA
            if verify not in (VERIFY_XDELTA, VERIFY_SHA256):
                raise ValueError(f'{path}: unknown verify mode {verify!r} for {name}')
            key = (name, row['source_sha256'])
            if key in rows:
                raise ValueError(f'{path}: duplicate row for {name} source '
                                 f'{row["source_sha256"][:12]}')
            rows[key] = {key_: row[key_] for key_ in (*required, 'build_key')}
            rows[key]['verify'] = verify
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
        *dependencies, pil_features.version_module('freetype2'), 'release-matrix-v4'))


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


def build_release(rev0, rev1, output, xdelta, *, port=False, workers=3):
    """Publish each verified patch and reuse unchanged results on later runs."""
    rev0, rev1, output = Path(rev0).resolve(), Path(rev1).resolve(), Path(output).absolute()
    image_check.require(str(rev0))
    image_check.require_rev1(str(rev1))
    variants = list(combinations())
    edges = {frozenset(labels): release_edge(labels) for labels, _selected in variants
             if labels}
    help_text = subprocess.run([xdelta, '-h'], capture_output=True, text=True, check=False)
    help_text = (help_text.stdout + help_text.stderr).lower()
    disable_armor = 'disable armor' in help_text
    if 'disable checksum' not in help_text:
        raise RuntimeError(f'{xdelta} has no -n (disable checksum); the release'
                           ' needs it to apply add- patches over decorated variants')
    output.mkdir(parents=True, exist_ok=True)
    image_bytes = rev0.stat().st_size
    # Which images stay on scratch for the whole run: the staged retail
    # copy, the base translation, and every state that a later step decodes
    # from - sha256 proof sources, and the anchors the canonical patches
    # are encoded from. The rest are assembled, used, and unlinked.
    kept_labels = {edges[frozenset(labels)].parent for labels, _selected in variants
                   if labels and edges[frozenset(labels)].verify == VERIFY_SHA256}
    kept_labels |= {edges[frozenset(labels)].anchor for labels, _selected in variants
                    if labels and edges[frozenset(labels)].verify == VERIFY_XDELTA}
    kept_labels.discard(())
    kept_states = {frozenset(labels) for labels in kept_labels}
    kept_images = 2 + len(kept_labels)            # + original.bin + base.bin
    with workspace((kept_images + workers + 3) * image_bytes) as work:
        manifest = output / 'manifest.tsv'
        records = read_manifest(manifest)
        expected_files = release_file_names()
        foreign = sorted({name for name, _source in records} - expected_files)
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
        rev0_hash = sha256(original)
        initial_key = release_fingerprint(rev0, xdelta)
        current_key = initial_key
        built_first = False
        touched = set()
        records_lock = threading.Lock()
        tasks = ThreadPoolExecutor(max_workers=max(1, workers))
        submitted = []
        futures = {}
        slots = itertools.count()
        # Backpressure: finished images wait for the delta pool. A reflink
        # filesystem shares their unchanged extents, so only the worker count
        # matters; a plain filesystem must reserve real space for the staged
        # original, the base image, the image being assembled, and the kept
        # parent images.
        if supports_reflink(work):
            image_slots = max(1, workers) + 1
        else:
            free_images = shutil.disk_usage(work).free // max(1, image_bytes)
            image_slots = max(1, min(max(1, workers) + 1, free_images - kept_images))
        images_allowed = threading.Semaphore(image_slots)

        def save_records():
            rows = [records[key] for key in sorted(records)]
            write_manifest(manifest, rows)

        def file_matches_row(name, row):
            path = output / name
            if not row or not path.is_file():
                return False
            if sha256(path) != row['patch_sha256']:
                raise RuntimeError(f'{path} was modified; refusing to replace your file')
            return True

        def is_valid(name, source_hash, key=None):
            row = records.get((name, source_hash))
            if not row or row['source_sha256'] != source_hash:
                return False
            if not file_matches_row(name, row):
                return False
            if key is not None and row['build_key'] != key:
                return False
            return True

        def decode_patch(row, source, dest):
            run_decode(xdelta, source, output / row['patch'], dest,
                       skip_checksum=(row['verify'] == VERIFY_SHA256))

        def publish(generated, path):
            """Atomically install the verified patch, across filesystems too."""
            staged = path.with_name(path.name + '.tmp')
            try:
                shutil.copyfile(generated, staged)
                os.replace(staged, path)
            finally:
                staged.unlink(missing_ok=True)

        def record_row(name, choices, source, source_hash, target, target_hash,
                       key, verify):
            with records_lock:
                records[(name, source_hash)] = {
                    'patch': name, 'choices': ','.join(choices), 'verify': verify,
                    'source_bytes': str(source.stat().st_size),
                    'source_sha256': source_hash,
                    'target_bytes': str(target.stat().st_size),
                    'target_sha256': target_hash,
                    'patch_sha256': sha256(output / name), 'build_key': key}
                touched.add((name, source_hash))
                save_records()

        def patch(source, target, name, choices, source_hash, key='', slot=0):
            """Encode `name` from source to target, or reuse it if verified."""
            slot_decoded = work / f'decoded-{slot}.bin'
            slot_generated = work / f'new-{slot}.xdelta'
            path = output / name
            target_hash = sha256(target)
            old = records.get((name, source_hash))
            if old and file_matches_row(name, old) and old['target_sha256'] == target_hash:
                print(f'patch: {name} unchanged; reusing verified patch', flush=True)
                with records_lock:
                    for (row_name, _source), row in records.items():
                        if row_name == name:
                            row['build_key'] = key
                    touched.add((name, source_hash))
                    save_records()
                return
            if path.exists():
                if old:
                    if sha256(path) != old['patch_sha256']:
                        raise RuntimeError(f'{path} was modified; refusing to replace your file')
                else:
                    try:
                        decode_patch({'patch': name, 'verify': VERIFY_XDELTA},
                                     source, slot_decoded)
                        if not same_bytes(target, slot_decoded):
                            raise RuntimeError(f'{path} is not the expected patch; refusing to replace it')
                    finally:
                        slot_decoded.unlink(missing_ok=True)
                    record_row(name, choices, source, source_hash, target,
                               target_hash, key, VERIFY_XDELTA)
                    print(f'patch: {name} verified and reused', flush=True)
                    return
            print(f'patch: {name}', flush=True)
            run_delta(xdelta, source, target, slot_generated, disable_armor=disable_armor)
            if path.exists() and (not old or sha256(path) != old['patch_sha256']):
                raise RuntimeError(f'{path} changed during generation; refusing to replace it')
            publish(slot_generated, path)
            record_row(name, choices, source, source_hash, target, target_hash,
                       key, VERIFY_XDELTA)

        patch(rev1, original, REV1_PATCH, [], rev1_hash)
        index = {tuple(selected): labels for labels, selected in variants}
        base_valid = not port and is_valid(BASE_PATCH, rev0_hash, initial_key)

        # Manifest hashes of each variant's image; the chain walks these.
        target_hashes = {}

        def recorded_target_hash(labels):
            cached = target_hashes.get(labels)
            if cached is not None:
                return cached
            if not labels:
                name, parent_hash = BASE_PATCH, rev0_hash
            else:
                edge = edges[frozenset(labels)]
                name, parent_hash = edge.file, recorded_target_hash(edge.parent)
            row = records.get((name, parent_hash))
            if not row:
                raise RuntimeError(f'{name} has no manifest row yet')
            target_hashes[labels] = row['target_sha256']
            return row['target_sha256']

        # Each pending variant writes its image to its own path. A variant
        # that later proofs decode from is kept as a hardlink, so it
        # survives its pending target being consumed by the delta pool.
        variant_images = itertools.count()

        def pending_variant(selected):
            return selected, str(work / f'image-{next(variant_images)}.bin')

        pending = []
        for labels, selected in variants:
            if not selected:
                if not base_valid:
                    pending.append((selected, str(base)))
                continue
            edge = edges[frozenset(labels)]
            if not base_valid or port:
                pending.append(pending_variant(selected))
                continue
            try:
                parent_hash = recorded_target_hash(edge.parent)
            except RuntimeError:
                pending.append(pending_variant(selected))
                continue
            if not is_valid(edge.file, parent_hash, initial_key):
                pending.append(pending_variant(selected))
            else:
                print(f'patch: {edge.file} unchanged; skipping variant build'
                      f' ({",".join(labels)})', flush=True)

        def build_order(item):
            """The base translation first, then one-option variants, then
            everything else - a parent state is always shorter than the
            variants that decode from it."""
            labels = tuple(solver_order(index[tuple(item[0])]))
            return (0 if not labels else 1 if len(labels) == 1 else 2,
                    len(labels), labels)

        pending.sort(key=build_order)
        if base_valid:
            print(f'patch: {BASE_PATCH} unchanged; reusing verified patch', flush=True)

        # Delta-source images already materialized on scratch this run, by
        # choice labels.
        built_images = {}

        def parent_image_path(labels):
            return work / ('parent-%s.bin' % '-'.join(solver_order(labels)))

        def ensure_image(labels, dest):
            """Reconstruct a variant image - or the base translation when
            `labels` is empty - by decoding its verified patch. Runs inside
            delta-pool threads; every destination decodes through its own
            scratch file. An existing destination is only reused after it
            matches its recorded hash - a stale or wrongly named image file
            fails loud instead of poisoning the chain."""
            if not labels:
                dest = base          # never duplicate the base translation
                source, name = original, BASE_PATCH
            else:
                edge = edges[frozenset(labels)]
                source = ensure_image(edge.parent, parent_image_path(edge.parent))
                name = edge.file
            key = (name, recorded_target_hash(edge.parent) if labels else rev0_hash)
            row = records.get(key)
            if dest.exists():
                if row is None or sha256(dest) != row['target_sha256']:
                    raise RuntimeError(
                        f'{dest.name} does not match its recorded verification'
                        ' - delete the scratch workspace and rerun')
                built_images[frozenset(labels)] = dest
                return dest
            # thread-unique scratch: two proofs can reconstruct the same
            # parent image concurrently, and os.replace would consume one
            # caller's file out from under the other
            scratch = dest.with_name(dest.stem + f'.dec-{threading.get_ident()}')
            try:
                if not row or not (output / name).is_file():
                    raise RuntimeError(
                        f'cannot reconstruct {dest.name}: {name} is missing'
                        ' from the release')
                decode_patch(row, source, scratch)
                if sha256(scratch) != row['target_sha256']:
                    raise RuntimeError(
                        f'reconstructed {name} does not match its manifest')
                os.replace(scratch, dest)
            finally:
                scratch.unlink(missing_ok=True)
            built_images[frozenset(labels)] = dest
            return dest

        def source_for(labels):
            """(image path, sha256) the variant `labels` is applied to."""
            path = built_images.get(frozenset(labels))
            if path is not None and Path(path).exists():
                return path, recorded_target_hash(labels)
            return ensure_image(labels, base if not labels else
                                parent_image_path(labels)), recorded_target_hash(labels)

        mark_cache = work / 'mark'
        mark_state = {}
        # Everything mark.py writes, relative to build/ (and to its own cache).
        MARK_FILES = ('ADV/MES.BIN', 'ADV/BST.BIN', 'B/P.BIN')

        def mark_builder(py):
            # Mark's producer reads these original files, source code and art,
            # not another variant. Generate and verify it once per run; restored
            # copies are byte-identical (checked below), so their pixels cannot
            # diverge from the verified artwork.
            inputs = [ROOT / 'src/injection_tools', ROOT / 'src/assets/mark/black',
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
                                  hashes={name: sha256(mark_cache / name) for name in MARK_FILES})
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

        def snapshot_audit(image, slot):
            """The audit reads the builder's placement record and its small
            report files. Both are copied to a slot-private snapshot here,
            on the assembly path, before the next variant rewrites the tree
            they came from."""
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

        def verify_image(image, placement=None, side_files=None, baseline=None):
            command = [sys.executable, str(ROOT / 'tools/verify_disc.py'), str(image),
                       '--original', str(baseline or original)]
            if placement is not None:
                command += ['--placement', str(placement)]
            if side_files is not None:
                command += ['--side-files', str(side_files)]
            subprocess.run(command, cwd=ROOT, check=True)

        def prove_portable(stable, edge, source, source_hash, labels, slot):
            """Prove `edge.file` on a decorated source state: decode it with
            the window checksums disabled and compare with the built disc.
            This is the row's certificate - the web patcher and the README
            rely on exactly this check having passed for every sha256 row."""
            decoded = work / f'port-{slot}.bin'
            try:
                run_decode(xdelta, source, output / edge.file, decoded,
                           skip_checksum=True)
                target_hash = sha256(stable)
                if sha256(decoded) == target_hash:
                    record_row(edge.file, labels, source, source_hash, stable,
                               target_hash, current_key, VERIFY_SHA256)
                    print(f'patch: {edge.file} proven for {",".join(labels)}'
                          ' (sha256 over the built disc)', flush=True)
                    return
                raise RuntimeError(
                    f'{edge.file} decoded over {",".join(edge.parent)} does not'
                    f' match the built {",".join(labels)} disc - '
                    f'{edge.parent[-1] if edge.parent else edge.file} cannot ride'
                    ' over that state; review the solver order in'
                    ' build_patches.py (SIZE_CHANGERS)')
            finally:
                decoded.unlink(missing_ok=True)

        def delta_task(labels, stable, placement, audit, slot, wait_for):
            """Audit the finished image and publish or prove its patch off
            the main assembly path. Everything here reads slot-private
            snapshots - the placement record and the builder's report
            files - so the tree has already moved on to the next variant
            safely."""
            edge = edges[frozenset(labels)]
            try:
                for key in wait_for:
                    future = futures.get(key)
                    if future is not None:
                        # that variant's row must exist before this task
                        # can reference it
                        future.result()
                source, source_hash = source_for(edge.parent)
                # Built on retail like any other build, so retail is the
                # audit baseline; the parent is only this step's source.
                verify_image(stable, placement, audit)
                if edge.verify == VERIFY_XDELTA:
                    patch(source, stable, edge.file, labels, source_hash,
                          current_key, slot=slot)
                    if not edge.anchor and len(edge.parent) == 0:
                        # the whole graph hangs on which options grow the
                        # image: verify the classification against the
                        # assembled solo build, never trust the constant
                        option = solver_order(labels)[-1]
                        grew = stable.stat().st_size != source.stat().st_size
                        if grew != (option in SIZE_CHANGERS):
                            raise RuntimeError(
                                f'{option} solo build {"grew" if grew else "kept"}'
                                ' the image size but SIZE_CHANGERS says the'
                                ' opposite - correct build_patches.py before'
                                ' releasing')
                else:
                    if is_valid(edge.file, source_hash, current_key):
                        print(f'patch: {edge.file} unchanged; reusing proof for'
                              f' {",".join(labels)}', flush=True)
                    else:
                        prove_portable(stable, edge, source, source_hash,
                                       labels, slot)
            finally:
                images_allowed.release()
                stable.unlink(missing_ok=True)
                if placement is not None:
                    placement.unlink(missing_ok=True)
                shutil.rmtree(audit, ignore_errors=True)

        def finished(selected, image):
            nonlocal current_key, built_first
            image = Path(image)
            if not built_first:
                current_key = release_fingerprint(rev0, xdelta)
                if current_key != initial_key and len(pending) < len(variants):
                    raise RuntimeError('build inputs changed during preparation; rerun to rebuild affected variants')
                built_first = True
            labels = index[tuple(selected)]
            if not labels:
                slot = next(slots)
                audit_placement, audit = snapshot_audit(image, slot)
                verify_image(image, audit_placement, audit)
                built_images[frozenset()] = image
                patch(original, image, BASE_PATCH, [], rev0_hash, current_key)
                return
            slot = next(slots)
            audit_placement, audit = snapshot_audit(image, slot)
            edge = edges[frozenset(labels)]
            images_allowed.acquire()          # keep the scratch disk bounded
            stable = image                    # every variant already has its own path
            # This task may only touch rows and files published by: the
            # variant it is applied to (its row feeds ensure_image and the
            # recorded hashes), and - for a proof - the canonical variant
            # that encodes this file. Both are strictly smaller variants,
            # so they were submitted earlier and no wait can deadlock.
            wait_for = []
            if edge.parent:
                wait_for.append(frozenset(edge.parent))
            if edge.verify == VERIFY_SHA256:
                wait_for.append(frozenset(edge.anchor) | {solver_order(labels)[-1]})
            if frozenset(labels) in kept_states and frozenset(labels) not in built_images:
                # keep this image as the source state for later steps: a
                # hardlink costs no data blocks and survives stable.unlink()
                keeper = parent_image_path(labels)
                keeper.unlink(missing_ok=True)
                try:
                    os.link(image, keeper)
                except OSError:
                    clone_file(image, keeper)
                built_images[frozenset(labels)] = keeper
            cue = image.with_suffix('.cue')
            if cue.exists():
                cue.unlink()
            futures[frozenset(labels)] = tasks.submit(
                delta_task, labels, stable, audit_placement, audit,
                slot, wait_for)
            submitted.append(futures[frozenset(labels)])

        def source_image_for(_patches):
            """Write every variant onto the staged retail copy.

            This is deliberately the same source an ordinary `build.py`
            invocation uses, so the release target for a combination is the
            exact image a developer gets from the same command."""
            return str(original)

        if pending:
            previous_argv, previous_image = sys.argv, build.ORIGINAL_IMAGE
            try:
                sys.argv = ['build.py', '--incremental'] + ([] if port else ['--no-port'])
                build.ORIGINAL_IMAGE = str(original)
                build.main(variants_override=pending, after_variant=finished,
                           mark_builder=mark_builder,
                           source_image_for=source_image_for)
            finally:
                sys.argv, build.ORIGINAL_IMAGE = previous_argv, previous_image
                tasks.shutdown(wait=True)     # workers finish before scratch cleanup
            for future in submitted:      # surface any worker failure here
                future.result()
            if release_fingerprint(rev0, xdelta) != current_key:
                for key in touched - {(REV1_PATCH, rev1_hash)}:
                    records[key]['build_key'] = ''
                save_records()
                raise RuntimeError('build inputs changed during release generation; rerun the build')
        expected_rows = {(BASE_PATCH, rev0_hash), (REV1_PATCH, rev1_hash)} | {
            (edges[frozenset(labels)].file,
             recorded_target_hash(edges[frozenset(labels)].parent))
            for labels, _selected in variants if labels}
        missing = expected_rows - set(records)
        if missing:
            raise RuntimeError('not every release patch was created: '
                               + ', '.join(sorted(name for name, _s in missing)))
        stale_rows = set(records) - expected_rows
        if stale_rows:
            for key in stale_rows:
                del records[key]
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
        sized = solver_order(sorted(SIZE_CHANGERS, key=CHOICE_ORDER.index))
        for option in solver_order(CHOICE_ORDER):
            if option not in SIZE_CHANGERS:
                entries.append((patch_file(option, frozenset()),
                                features.get(option, option)))
                continue
            preceding = sized[:sized.index(option)]
            for bits in itertools.product((False, True), repeat=len(preceding)):
                anchor = frozenset(s for s, on in zip(preceding, bits) if on)
                if anchor:
                    applied = ' + '.join(f'add-{a}' for a in CHOICE_ORDER if a in anchor)
                    note = f'(with {applied} applied)'
                elif preceding:
                    skipped = ' + '.join(f'add-{a}' for a in CHOICE_ORDER if a in preceding)
                    note = f'(without {skipped})'
                else:
                    note = ''
                entries.append((patch_file(option, anchor),
                                f'{features.get(option, option)} {note}'.rstrip()))
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
            'In-place options never move another patch\'s bytes, so their\n'
            'patches work over any variant. The inserting patches shift\n'
            'every offset after them - that is why they come in one file per\n'
            'disc layout, and why the order above is fixed.\n'
            '\n'
            'If xdelta3 reports a checksum mismatch on an add- patch, your\n'
            'source is a variant the patch was not encoded from. The release\n'
            'has already proven that exact combination byte-for-byte (every\n'
            'patch was decoded against every variant it can meet and compared\n'
            'with the built discs), so retry with -n and check the hash:\n'
            '\n'
            '    xdelta3 -n -d -s your.bin <patch>.xdelta result.bin\n'
            '    sha256sum result.bin\n'
            '\n'
            'manifest.tsv has one row per step: source_sha256 is the hash your\n'
            'input must have, target_sha256 the hash your output must have,\n'
            'and verify says which check certifies the step - xdelta\'s own\n'
            'window checksums, or the whole-file SHA-256 for steps applied\n'
            'over a decorated variant. The web patcher does all of this\n'
            'automatically. A release is complete when its manifest lists\n'
            f'{len(expected_rows)} steps across {len(expected_files)} patch files.\n',
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
                      workers=args.workers)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'build_patches.py: {error}\n')
    if args.publish_release:
        sys.path.insert(0, str(ROOT / 'tools'))
        import publish_patches
        publish_patches.publish(directory=args.output, allow_incomplete=False)


if __name__ == '__main__':
    main()
