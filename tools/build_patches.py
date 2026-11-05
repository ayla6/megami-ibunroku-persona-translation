"""Build, verify and incrementally resume the xdelta3 patch set.

The release is a graph, not a list: a patch is named SOURCE-to-TARGET and is
deltaed from another variant, so each manifest row's `source_sha256` equals
its parent's `target_sha256` and the chain from the base translation to any
combination can be walked from the manifest alone. Big choices (Mark
artwork, save UI) are layers, so every combination that includes one is
patched from a variant that already has it and those bytes are encoded once.

Injection and assembly are the only sequential stage: they own the shared
build/ tree. Every variant image is written onto a clone of the staged retail
copy, exactly as `build.py --qol=...` writes it, so a release target is the
same bytes as the build a developer can reproduce by hand. Parent variants
are only delta sources: the chain's patches stay small because xdelta matches
the unchanged file contents even when two variants place them at different
extents. Each finished image is snapshotted (its placement record plus the
builder's small report files) and the audit, xdelta encode, check-only
decode, hashing and publication run in a worker pool behind the assembly of
the next variant. The audit reads the snapshot, never the live tree, and
compares every image with retail - the same baseline an ordinary build uses.

Scratch images live in a private workspace on the fastest filesystem with
room (the system temp directory by default, `PERSONA_BUILD_SCRATCH` to
override) and are deleted on exit. Reruns rebuild only what changed:
recorded patches are re-hashed and reused, and a missing intermediate image
is reconstructed by decoding its verified patches from the staged original.
A Mark input edited mid-run stops the run by name, because every variant
built so far would carry the old artwork.
"""
import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import itertools
from importlib import metadata
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

CHOICES = (
    ('saves', ('saves',)),
    ('mark', ('mark',)),
    ('battlespeed', ('battlespeed',)),
    ('60fps', ('60fps',)),
    ('rewards-encounters', ('encounters', 'rewards')),
)
# Choices whose delta against other variants is big enough that every other
# combination should be patched from a variant that already includes them,
# instead of re-encoding them against every patch (mark alone is ~810 KB).
LAYERS = ('mark', 'saves')
# The layer variants kept as delta sources while their children are built
# (as frozensets: choice order in a combination must not matter).
LAYER_ROOTS = frozenset({frozenset(('mark',)), frozenset(('saves',)),
                         frozenset(('mark', 'saves'))})
DEFAULT_REV1 = (ROOT / 'data/discs/Megami Ibunroku - Persona - Be Your True Mind (Japan) (Rev 1)' /
                'Megami Ibunroku - Persona - Be Your True Mind (Japan) (Rev 1).bin')
SCRATCH_ENV = 'PERSONA_BUILD_SCRATCH'
SCRATCH_NAME = 'persona-patch-work'


def parent_labels(labels):
    """The combination a patch for `labels` is deltaed from.

    Everything that is not a layer choice is dropped wholesale (it is
    small); a combination made only of layer choices drops its smallest
    layer, so mark is always kept when present. Order-independent."""
    kept = [label for label in LAYERS if label in labels]
    if len(kept) == len(labels):
        return kept[:-1]        # pure-layer combination: drop the smallest
    return kept


CHOICE_ORDER = [label for label, _group in CHOICES]


def patch_name(labels):
    """Chain step names carry their source: SOURCE-to-TARGET, both parts in
    the usual choices order regardless of how the labels arrived."""
    parent = parent_labels(labels)
    display = [label for label in CHOICE_ORDER if label in parent]
    child = [label for label in CHOICE_ORDER if label in labels]
    source = '-'.join(display) if display else 'base'
    return f'{source}-to-{"-".join(child)}.xdelta'


def combinations():
    """All release choices, with grouped rewards/encounters and no debug."""
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

    A variant image is ~700 MB and immutable once built. Every layer image,
    pending image and hardlinked delta source is the same inode, and the same
    image is deliberately hashed at several graph edges, so rereading it each
    time is pure disk I/O. The signature includes the inode and timestamps, so
    a rewritten file (including through os.replace) never hits a stale digest.
    """
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

    `-J` reconstructs every target window and checks its checksum but writes
    nothing. The old round trip decoded another full ~700 MB image and read
    both that image and the target back just to compare them; this checks the
    same property without the two extra disk passes.
    """
    env = dict(os.environ)
    env.pop('XDELTA', None)
    flags = ['-a'] if disable_armor else []
    output.unlink(missing_ok=True)      # scratch; xdelta3 refuses to overwrite
    subprocess.run([tool, '-e', '-A', *flags, '-s', str(source), str(target), str(output)],
                   check=True, env=env)
    subprocess.run([tool, '-d', '-J', '-s', str(source), str(output)],
                   check=True, env=env)


def write_manifest(path, rows):
    fields = ('patch', 'choices', 'source_bytes', 'source_sha256', 'target_bytes',
              'target_sha256', 'patch_sha256', 'build_key')
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
            if not name or Path(name).name != name or name in rows:
                raise ValueError(f'{path}: invalid or duplicate patch name {name!r}')
            row['build_key'] = row.get('build_key') or ''
            rows[name] = {key: row[key] for key in (*required, 'build_key')}
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
        *dependencies, pil_features.version_module('freetype2'), 'release-matrix-v3'))


def scratch_root(required_bytes):
    """Pick the filesystem this run keeps its private disc images on.

    The images are the release build's dominant I/O, so keep them off the
    project's data disk when another filesystem has room: an explicit
    $PERSONA_BUILD_SCRATCH first, then the system temp directory (tmpfs on
    most Linux systems), then build/ beside the project. Everything in it is
    scratch that is deleted on exit, so the directory must be disposable."""
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

    The directory is created with mkdir() (never exist_ok) so a concurrent or
    interrupted run can never be mistaken for ours; everything inside it is
    therefore this run's own work and is deleted wholesale on exit - a new
    scratch artifact must never be able to strand the next run."""
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
    help_text = subprocess.run([xdelta, '-h'], capture_output=True, text=True, check=False)
    disable_armor = 'disable armor' in (help_text.stdout + help_text.stderr).lower()
    output.mkdir(parents=True, exist_ok=True)
    image_bytes = rev0.stat().st_size
    # Enough for a few images: the workspace picks a fast filesystem when it
    # can hold this much and then caps how many images may be in flight.
    with workspace(4 * image_bytes) as work:
        manifest = output / 'manifest.tsv'
        records = read_manifest(manifest)
        expected_names = {patch_name(labels) for labels, selected in variants
                          if selected} | {'rev1-to-rev0.xdelta', 'rev0-to-base.xdelta'}
        foreign = sorted(set(records) - expected_names)
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
        # original, the base image, the image being assembled, and up to
        # three reconstructed layer images.
        if supports_reflink(work):
            image_slots = max(1, workers) + 1
        else:
            free_images = shutil.disk_usage(work).free // max(1, image_bytes)
            image_slots = max(1, min(max(1, workers) + 1, free_images - 7))
        images_allowed = threading.Semaphore(image_slots)

        def save_records():
            write_manifest(manifest, [records[name] for name in sorted(records)])

        def is_valid(name, source_hash, key=None):
            row, path = records.get(name), output / name
            if not row or not path.is_file() or row['source_sha256'] != source_hash:
                return False
            if key is not None and row['build_key'] != key:
                return False
            if sha256(path) != row['patch_sha256']:
                raise RuntimeError(f'{path} was modified; refusing to replace your file')
            return True

        def decode_existing(source, patch_path, dest):
            env = dict(os.environ)
            env.pop('XDELTA', None)
            subprocess.run([xdelta, '-d', '-s', str(source), str(patch_path), str(dest)],
                           check=True, env=env)

        def publish(generated, path):
            """Atomically install the verified patch, across filesystems too."""
            staged = path.with_name(path.name + '.tmp')
            try:
                shutil.copyfile(generated, staged)
                os.replace(staged, path)
            finally:
                staged.unlink(missing_ok=True)

        def patch(source, target, name, choices, source_hash, key='', slot=0):
            slot_decoded = work / f'decoded-{slot}.bin'
            slot_generated = work / f'new-{slot}.xdelta'
            path = output / name
            target_hash = sha256(target)
            old = records.get(name)
            if is_valid(name, source_hash) and old['target_sha256'] == target_hash:
                print(f'patch: {name} unchanged; reusing verified patch', flush=True)
                with records_lock:
                    old['build_key'] = key
                    touched.add(name)
                    save_records()
                return
            if path.exists():
                if old:
                    if sha256(path) != old['patch_sha256']:
                        raise RuntimeError(f'{path} was modified; refusing to replace your file')
                else:
                    try:
                        decode_existing(source, path, slot_decoded)
                        if not same_bytes(target, slot_decoded):
                            raise RuntimeError(f'{path} is not the expected patch; refusing to replace it')
                    finally:
                        slot_decoded.unlink(missing_ok=True)
                    with records_lock:
                        records[name] = {'patch': name, 'choices': ','.join(choices),
                            'source_bytes': str(source.stat().st_size), 'source_sha256': source_hash,
                            'target_bytes': str(target.stat().st_size), 'target_sha256': target_hash,
                            'patch_sha256': sha256(path), 'build_key': key}
                        touched.add(name)
                        save_records()
                    print(f'patch: {name} verified and reused', flush=True)
                    return
            print(f'patch: {name}', flush=True)
            run_delta(xdelta, source, target, slot_generated, disable_armor=disable_armor)
            if path.exists() and (not old or sha256(path) != old['patch_sha256']):
                raise RuntimeError(f'{path} changed during generation; refusing to replace it')
            publish(slot_generated, path)
            with records_lock:
                records[name] = {'patch': name, 'choices': ','.join(choices),
                    'source_bytes': str(source.stat().st_size), 'source_sha256': source_hash,
                    'target_bytes': str(target.stat().st_size), 'target_sha256': target_hash,
                    'patch_sha256': sha256(path), 'build_key': key}
                touched.add(name)
                save_records()

        patch(rev1, original, 'rev1-to-rev0.xdelta', [], rev1_hash)
        index = {tuple(selected): labels for labels, selected in variants}
        base_name = 'rev0-to-base.xdelta'
        base_valid = not port and is_valid(base_name, rev0_hash, initial_key)

        def recorded_source_hash(labels):
            """Manifest hash of the image `labels` is patched from."""
            parent = parent_labels(labels)
            if not parent:
                return records[base_name]['target_sha256']
            row = records.get(patch_name(parent))
            if not row:
                raise RuntimeError(
                    f'{patch_name(labels)}: parent patch {patch_name(parent)}'
                    ' is missing from the manifest')
            return row['target_sha256']

        # Each pending variant writes its image to its own path. Nothing has
        # to copy it out of the way before the next assembly starts, and a
        # layer variant can hardlink its image as its children's source.
        variant_images = itertools.count()

        def pending_variant(selected):
            return selected, str(work / f'image-{next(variant_images)}.bin')

        pending = []
        for labels, selected in variants:
            if not selected:
                if not base_valid:
                    pending.append((selected, str(base)))
                continue
            name = patch_name(labels)
            if not base_valid or port:
                pending.append(pending_variant(selected))
                continue
            try:
                parent_hash = recorded_source_hash(labels)
            except RuntimeError:
                pending.append(pending_variant(selected))
                continue
            if not is_valid(name, parent_hash, initial_key):
                pending.append(pending_variant(selected))
            else:
                print(f'patch: {name} unchanged; skipping variant build', flush=True)

        def build_order(item):
            """The base translation first, then layer variants, then the
            combinations patched from them."""
            labels = tuple(index[tuple(item[0])])
            return (0 if not labels else 1 if frozenset(labels) in LAYER_ROOTS else 2,
                    len(labels), labels)

        pending.sort(key=build_order)
        if base_valid:
            print(f'patch: {base_name} unchanged; reusing verified patch', flush=True)

        # Delta-source images already materialized on scratch this run, by
        # choice labels. Layer images are kept as hardlinks so they survive
        # their pending target being consumed by the delta pool.
        built_images = {}

        def ensure_image(labels, dest):
            """Reconstruct a variant image - or the base translation when
            `labels` is empty - by decoding verified patches from the staged
            original. Runs inside delta-pool threads; every destination
            decodes through its own scratch file. An existing destination is
            only reused after it matches its recorded hash - a stale or
            wrongly named layer file fails loud instead of poisoning the
            chain."""
            row = records.get(base_name if not labels else patch_name(labels))
            if dest.exists():
                if row is None or sha256(dest) != row['target_sha256']:
                    raise RuntimeError(
                        f'{dest.name} does not match its recorded verification'
                        ' - delete the scratch workspace and rerun')
                built_images[frozenset(labels)] = dest
                return dest
            scratch = dest.with_suffix('.dec')
            try:
                if not labels:
                    source, name = original, base_name
                else:
                    parent = parent_labels(labels)
                    if parent:
                        source = ensure_image(parent, work / ('layer-%s.bin' % '-'.join(parent)))
                    else:
                        source = ensure_image([], base)
                    name = patch_name(labels)
                row = records.get(name)
                if not row or not (output / name).is_file():
                    raise RuntimeError(
                        f'cannot reconstruct {dest.name}: {name} is missing'
                        ' from the release')
                decode_existing(source, output / name, scratch)
                if sha256(scratch) != row['target_sha256']:
                    raise RuntimeError(
                        f'reconstructed {name} does not match its manifest')
                os.replace(scratch, dest)
            finally:
                scratch.unlink(missing_ok=True)
            built_images[frozenset(labels)] = dest
            return dest

        def image_for_parent(labels):
            """The image a combination's patch is deltaed from, materialized.

            Keys are frozensets: `labels` arrives in choice order, while
            parent_labels() emits LAYERS order, so the two must not be
            compared as lists."""
            parent = parent_labels(labels)
            path = built_images.get(frozenset(parent))
            if path is not None and Path(path).exists():
                return path
            return ensure_image(parent, base if not parent else
                                work / ('layer-%s.bin' % '-'.join(parent)))

        def source_for(labels):
            """(image path, sha256) this combination is patched from."""
            return image_for_parent(labels), recorded_source_hash(labels)

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

        def delta_task(labels, stable, placement, audit, name, slot, parent_names):
            """Audit the finished image and publish its patch off the main
            assembly path. Everything here reads slot-private snapshots -
            the placement record and the builder's report files - so the
            tree has already moved on to the next variant safely."""
            try:
                for parent in parent_names:
                    future = futures.get(parent)
                    if future is not None:
                        # the parent built this run: its manifest row must
                        # exist before this patch's row can reference it
                        future.result()
                source, source_hash = source_for(labels)
                # Built on retail like any other build, so retail is the
                # audit baseline; the parent is only this patch's delta source.
                verify_image(stable, placement, audit)
                patch(source, stable, name, labels, source_hash, current_key, slot=slot)
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
            slot = next(slots)
            audit_placement, audit = snapshot_audit(image, slot)
            if not selected:
                verify_image(image, audit_placement, audit)
                built_images[frozenset()] = image
                patch(original, image, base_name, [], rev0_hash, current_key)
                return
            name = patch_name(labels)
            parent = parent_labels(labels)
            images_allowed.acquire()          # keep the scratch disk bounded
            stable = image                    # every variant already has its own path
            if frozenset(labels) in LAYER_ROOTS:
                # keep this image as the delta source for its children, under
                # the exact name ensure_image computes; a hardlink costs no
                # data blocks and survives stable.unlink()
                layer_name = '-'.join(label for label in LAYERS if label in labels)
                layer_image = work / f'layer-{layer_name}.bin'
                layer_image.unlink(missing_ok=True)
                try:
                    os.link(image, layer_image)
                except OSError:
                    clone_file(image, layer_image)
                built_images[frozenset(labels)] = layer_image
            cue = image.with_suffix('.cue')
            if cue.exists():
                cue.unlink()
            futures[name] = tasks.submit(
                delta_task, labels, stable, audit_placement, audit, name,
                slot, [patch_name(parent)] if parent else [])
            submitted.append(futures[name])

        def source_image_for(_patches):
            """Write every variant onto the staged retail copy.

            This is deliberately the same source an ordinary `build.py`
            invocation uses, so the release target for a combination is the
            exact image a developer gets from the same command. Parent
            variants are still used, but only as the delta source for a
            patch, never as the image a variant is built on."""
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
                for name in touched - {'rev1-to-rev0.xdelta'}:
                    records[name]['build_key'] = ''
                save_records()
                raise RuntimeError('build inputs changed during release generation; rerun the build')
        expected = {base_name, 'rev1-to-rev0.xdelta'} | {
            patch_name(labels) for labels, selected in variants if selected}
        if not expected.issubset(records):
            raise RuntimeError('not every release patch was created')
        readme = output / 'README.txt'
        if not readme.exists():
            readme.write_text(
                'Apply patches in order; each name is SOURCE-to-TARGET and its\n'
                'SOURCE must be the bytes you already have.\n'
                'Rev 1 discs: apply rev1-to-rev0.xdelta first (Rev 0 skips it).\n'
                'Apply rev0-to-base.xdelta to the original Rev 0 image; that is\n'
                'the base translation. Then follow the chain to your combination,\n'
                'for example: base-to-mark.xdelta, then mark-to-saves-mark.xdelta,\n'
                'then saves-mark-to-saves-mark-60fps.xdelta.\n'
                'manifest.tsv lists every chain: each row source_sha256 is the\n'
                'target_sha256 of the patch before it. Apply whole chains only;\n'
                'a patch against one variant never fits another.\n'
                'rewards-encounters enables both double rewards and half encounters.\n'
                'A release is complete when its manifest lists all 33 patches.\n',
                encoding='utf-8')
    print(f'{len(expected)} verified patches available in {output}', flush=True)


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
