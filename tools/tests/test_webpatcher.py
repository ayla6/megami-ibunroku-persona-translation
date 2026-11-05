"""Web patcher integrity: vendored xdelta3 wasm checksums, disc identification
in check-only mode, and a real decode chain under Node.

The harnesses run the same callMain sequences as webpatcher/worker.js against
synthetic patches produced with the local xdelta3 CLI: one proves that -J
accepts the matching source and rejects the other revision, the other applies
a chain and checks the final bytes against the CLI's own ground truth. The
checksum test keeps vendor/README.md honest after rebuilds."""

import hashlib
import os
import random
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / 'webpatcher' / 'vendor'
TESTS = Path(__file__).resolve().parent
HARNESS = TESTS / 'webpatcher_chain.js'
IDENTIFY = TESTS / 'webpatcher_identify.js'


def disc(size, seed):
    """Structured bytes: small patches, big outputs, like the real game."""
    rng = random.Random(seed)
    base = bytes(rng.randrange(256) for _ in range(4096))
    out = bytearray()
    counter = 0
    while len(out) < size:
        out += base[:-2] + counter.to_bytes(2, 'little')
        counter += 1
    return out


def edit(buf, seed, count=16):
    rng = random.Random(seed)
    out = bytearray(buf)
    for _ in range(count):
        pos = rng.randrange(len(out) - 64)
        out[pos:pos + 64] = bytes(rng.randrange(256) for _ in range(64))
    return out


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def find_xdelta3():
    local = ROOT / 'external_tools' / 'xdelta3' / 'xdelta3'
    if local.exists():
        return str(local)
    return shutil.which('xdelta3')


class VendorArtifactTest(unittest.TestCase):

    def test_checksums_recorded_and_current(self):
        table = (VENDOR / 'README.md').read_text(encoding='utf-8')
        recorded = dict(re.findall(r'^\| (\S+) \| ([0-9a-f]{64}) \|$', table, re.M))
        self.assertEqual(sorted(recorded), ['xdelta3.js', 'xdelta3.wasm'],
                         'vendor/README.md must record both artifact checksums')
        for name, expected in recorded.items():
            self.assertEqual(sha256(VENDOR / name), expected,
                             f'{name} no longer matches vendor/README.md')


class FeatureWordingTest(unittest.TestCase):
    """app.js names and explains every release choice. The table is JSON so
    this can read it: an option added to the release without wording shows up
    as a raw internal label, and this test fails instead."""

    def features(self):
        import json
        source = (ROOT / 'webpatcher' / 'app.js').read_text(encoding='utf-8')
        match = re.search(r'^const FEATURES = (\{.*?^\});$', source, re.M | re.S)
        self.assertIsNotNone(match, 'app.js has no FEATURES table')
        return json.loads(match.group(1))

    def test_every_release_choice_is_named_and_explained(self):
        import sys
        sys.path.insert(0, str(ROOT / 'tools'))
        import build_patches

        features = self.features()
        choices = [label for label, _group in build_patches.CHOICES]
        self.assertEqual(list(features), choices,
                         'FEATURES must list exactly the release choices')
        for choice, info in features.items():
            self.assertEqual(sorted(info), ['description', 'name'], choice)
            self.assertTrue(info['name'].strip(), choice)
            self.assertTrue(info['description'].strip(), choice)


@unittest.skipIf(shutil.which('node') is None, 'node not installed')
class IdentifySourceTest(unittest.TestCase):
    """Revisions are told apart by xdelta's check-only mode: a Rev 1 source
    passes rev1-to-rev0 and fails rev0-to-base, and the reverse for Rev 0."""

    @classmethod
    def setUpClass(cls):
        cls.xdelta = find_xdelta3()

    def setUp(self):
        if self.xdelta is None:
            self.skipTest('xdelta3 not installed')

    def run_identify(self, source, patch, expected):
        proc = subprocess.run(
            ['node', str(IDENTIFY), str(VENDOR / 'xdelta3.js'),
             str(ROOT / 'webpatcher' / 'workerfs.js'), source, patch,
             str(expected)],
            capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn('IDENTIFY_OK', proc.stdout)

    def test_check_only_accepts_matching_source_and_rejects_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Rev 1 has an inserted block in the middle, so xdelta copies the
            # tail from a different offset; feeding Rev 0 as the source then
            # produces the wrong bytes and fails the target checksum. That is
            # the same shape as the real discs, which also differ in size.
            rng = random.Random(1)
            head, insert, tail = (rng.randbytes(1 << 20), rng.randbytes(4096),
                                  rng.randbytes(1 << 20))
            rev0 = head + tail
            rev1 = head + insert + tail
            rev0_path = os.path.join(tmp, 'rev0.bin')
            rev1_path = os.path.join(tmp, 'rev1.bin')
            with open(rev0_path, 'wb') as handle:
                handle.write(rev0)
            with open(rev1_path, 'wb') as handle:
                handle.write(rev1)
            patch = os.path.join(tmp, 'rev1-to-rev0.xdelta')
            subprocess.run([self.xdelta, '-e', '-A', '-a', '-s', rev1_path,
                            rev0_path, patch], check=True)

            self.run_identify(rev1_path, patch, 0)
            self.run_identify(rev0_path, patch, 1)


@unittest.skipIf(shutil.which('node') is None, 'node not installed')
class DecodeChainTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.xdelta = find_xdelta3()

    def setUp(self):
        if self.xdelta is None:
            self.skipTest('xdelta3 not installed')

    def encode(self, source, target):
        target_file = os.path.join(self.work, f'target{len(self.patches)}.bin')
        Path(target_file).write_bytes(target)
        patch = os.path.join(self.work, f'p{len(self.patches)}.xdelta')
        subprocess.run([self.xdelta, '-e', '-A', '-a', '-s', source,
                        target_file, patch], check=True)
        self.patches.append(patch)

    def test_chain_matches_cli_ground_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.work = tmp
            self.patches = []
            rev1 = disc(8 << 20, 1)
            base = edit(rev1, 2)
            final = edit(base, 3)
            source = os.path.join(tmp, 'source.bin')
            Path(source).write_bytes(rev1)
            self.encode(source, base)
            self.encode(os.path.join(tmp, 'target0.bin'), final)
            expected = hashlib.sha256(final).hexdigest()

            proc = subprocess.run(
                ['node', str(HARNESS), str(VENDOR / 'xdelta3.js'),
                 str(ROOT / 'webpatcher' / 'workerfs.js'), tmp,
                 expected, 'p0.xdelta', 'p1.xdelta'],
                capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertIn('CHAIN_OK', proc.stdout)


if __name__ == '__main__':
    unittest.main()
