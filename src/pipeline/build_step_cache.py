"""Content-checked cache for explicitly declared, deterministic build steps.

The caller declares every input and output. A hit requires both the input
fingerprint and every existing output byte to match the last successful run.
Nothing is restored or deleted: a missing or edited output reruns the step.
"""
import hashlib
import csv
import os
from pathlib import Path
import sys


def _digest(path):
    import file_digest
    return file_digest.digest(Path(path))


def _files(paths):
    for path in sorted(map(Path, paths), key=str):
        if path.is_dir():
            for child in sorted(path.rglob('*')):
                if child.is_file() and '__pycache__' not in child.parts and child.suffix != '.pyc':
                    yield child
        elif path.is_file():
            yield path
        else:
            # Missing inputs must change the key if they later appear.
            yield path


def digests(paths):
    """Per-file SHA-1 (or 'missing') of exactly the files a fingerprint covers.

    Exposed so a caller that has to explain a changed fingerprint can name the
    files that differ instead of reporting only that something moved."""
    result = {str(path): (_digest(path) if path.is_file() else 'missing')
              for path in _files(paths)}
    import file_digest
    file_digest.flush()
    return result


def fingerprint(paths, context=()):
    h = hashlib.sha1()
    # the interpreter by what it IS: /usr/bin/python and /usr/bin/python3
    # are one Python, and a key that told them apart made every build
    # launched the other way miss (and overwrite) the cache
    for value in (sys.version, os.path.realpath(sys.executable), *context):
        h.update(str(value).encode('utf-8') + b'\0')
    for path, digest in digests(paths).items():
        h.update(path.encode('utf-8') + b'\0')
        h.update(digest.encode('ascii') + b'\0')
    return h.hexdigest()


def run(name, inputs, outputs, action, manifest, context=(), reuse=True):
    """Run action unless its inputs and complete output set are unchanged."""
    manifest = Path(manifest)
    outputs = tuple(map(Path, outputs))
    key = fingerprint(inputs, context)
    old_key, old_outputs = '', {}
    try:
        with manifest.open(encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f, delimiter='\t')
            if reader.fieldnames != ['kind', 'path', 'sha1']:
                raise ValueError('invalid cache header')
            for row in reader:
                if row['kind'] == 'input' and not old_key and not row['path']:
                    old_key = row['sha1']
                elif row['kind'] == 'source' and row['path']:
                    continue  # individual input hashes are recorded for inspection
                elif row['kind'] == 'output' and row['path'] not in old_outputs:
                    old_outputs[row['path']] = row['sha1']
                else:
                    raise ValueError('invalid cache row')
    except (OSError, ValueError, KeyError, csv.Error):
        old_key, old_outputs = '', {}
    actual = {str(p): _digest(p) for p in outputs if p.is_file()}
    if reuse and old_key == key and len(actual) == len(outputs) and old_outputs == actual:
        print(f'build: {name} unchanged; using verified outputs', flush=True)
        return False
    # Invalidate before invoking the action. A failed or interrupted action
    # cannot leave a record that makes partial output look successful.
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('kind\tpath\tsha1\n', encoding='utf-8')
    action()
    actual = {str(p): _digest(p) for p in outputs if p.is_file()}
    if len(actual) != len(outputs):
        raise RuntimeError(f'{name}: successful step did not produce every declared output')
    if fingerprint(inputs, context) != key:
        print(f'build: {name} inputs changed during generation; not caching', flush=True)
        return True
    tmp = manifest.with_suffix(manifest.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, delimiter='\t', lineterminator='\n')
        writer.writerow(('kind', 'path', 'sha1'))
        writer.writerow(('input', '', key))
        for path in _files(inputs):
            writer.writerow(('source', str(path), _digest(path) if path.is_file() else 'missing'))
        for path, value in sorted(actual.items()):
            writer.writerow(('output', path, value))
    os.replace(tmp, manifest)
    return True


def stamp(path):
    """`size:mtime_ns` of a file: what a remembered digest of it is tied to
    (it is hashed again only once this moves)."""
    st = os.stat(path)
    return f'{st.st_size}:{st.st_mtime_ns}'


def clone(src, dest):
    """dest = src as a copy-on-write clone where the filesystem has them
    (btrfs, XFS: no bytes are read or written), else a plain copy. The
    destination is replaced atomically."""
    import fcntl
    import shutil
    src, dest = os.fspath(src), os.fspath(dest)
    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
    tmp = dest + '.tmp'
    with open(src, 'rb') as a, open(tmp, 'wb') as b:
        try:
            fcntl.ioctl(b.fileno(), 0x40049409, a.fileno())    # FICLONE
            cloned = True
        except OSError:
            cloned = False
    if not cloned:
        shutil.copyfile(src, tmp)
    os.replace(tmp, dest)
