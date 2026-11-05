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
import threading

_DIGESTS = {}
_DIGEST_LOCK = threading.Lock()


def _digest(path):
    """SHA-1 of a file, remembered within this process.

    A build hashes the same inputs several times (a step's input fingerprint,
    then the release's input fingerprint before and after the run), and those
    inputs are the bulk of the game data. The cache key is the inode, size and
    both timestamps, so a rewritten or replaced file - including an edit made
    while this process is running - is always re-read."""
    status = path.stat()
    signature = (status.st_dev, status.st_ino, status.st_size,
                 status.st_mtime_ns, status.st_ctime_ns)
    with _DIGEST_LOCK:
        cached = _DIGESTS.get(signature)
    if cached is not None:
        return cached
    h = hashlib.sha1()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    result = h.hexdigest()
    with _DIGEST_LOCK:
        _DIGESTS[signature] = result
    return result


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
    return {str(path): (_digest(path) if path.is_file() else 'missing')
            for path in _files(paths)}


def fingerprint(paths, context=()):
    h = hashlib.sha1()
    for value in (sys.version, sys.executable, *context):
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
