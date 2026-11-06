"""Web patcher integrity: vendored xdelta3 wasm checksums, the page's own
SHA-256, disc identification in check-only mode, and real decode chains
under Node - checksummed and -n + hash-verified.

The harnesses run the same callMain sequences as webpatcher/worker.js
against synthetic patches produced with the local xdelta3 CLI: one proves
that -J accepts the matching source and rejects the other revision, the
others apply chains and check the final bytes against the CLI's own
ground truth. The checksum test keeps vendor/README.md honest after
rebuilds."""

import hashlib
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / 'webpatcher' / 'vendor'
TESTS = Path(__file__).resolve().parent
HARNESS = TESTS / 'webpatcher_chain.js'
OPFS_HARNESS = TESTS / 'webpatcher_opfs_chain.js'
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
    """Option wording lives in tools/release_options.json (the single
    source the release README and the generated webpatcher features.js
    both come from). Every release choice must be named and explained
    there, in CHOICES order; another test proves the generated file
    matches."""

    def options(self):
        import json
        source = ROOT / 'tools' / 'release_options.json'
        return json.loads(source.read_text(encoding='utf-8'))

    def test_every_release_choice_is_named_and_explained(self):
        import sys
        sys.path.insert(0, str(ROOT / 'tools'))
        import build_patches

        options = self.options()
        choices = [label for label, _group in build_patches.CHOICES]
        self.assertEqual([item['label'] for item in options], choices,
                         'release_options.json must list exactly the'
                         ' release choices, in CHOICES order')
        for item in options:
            self.assertEqual(sorted(item), ['description', 'label', 'name'],
                             item['label'])
            self.assertTrue(item['name'].strip(), item['label'])
            self.assertTrue(item['description'].strip(), item['label'])

    def test_generated_features_file_matches_the_json(self):
        import json
        import sys
        sys.path.insert(0, str(ROOT / 'tools'))
        import generate_features

        with tempfile.TemporaryDirectory() as tmp:
            target = generate_features.generate(
                target=Path(tmp) / 'features.js')
            generated = target.read_text(encoding='utf-8')
        payload = generated.split('globalThis.FEATURES = ', 1)[1]
        features = json.loads(payload.rstrip().rstrip(';'))
        self.assertEqual(
            features,
            {item['label']: {'name': item['name'],
                             'description': item['description']}
             for item in self.options()})


@unittest.skipIf(shutil.which('node') is None, 'node not installed')
class Sha256ChainTest(unittest.TestCase):
    """The worker's verify=sha256 steps: decode with -n through the wasm,
    hash natively with crypto.subtle, refuse a wrong hash. crypto.subtle
    needs a secure context in browsers - the page is served from localhost
    or real HTTPS (e.g. tailscale serve) - Node always has it."""

    @classmethod
    def setUpClass(cls):
        cls.xdelta = find_xdelta3()

    def setUp(self):
        if self.xdelta is None:
            self.skipTest('xdelta3 not installed')

    def run_harness(self, work, step_hashes):
        argv = ['node', str(TESTS / 'webpatcher_sha256_chain.js'),
                str(VENDOR / 'xdelta3.js'),
                str(ROOT / 'webpatcher' / 'workerfs.js'),
                str(ROOT / 'webpatcher' / 'xdelta.js'),
                work] + step_hashes
        return subprocess.run(argv, capture_output=True, text=True, timeout=300)

    def test_chain_decodes_with_n_and_verifies_every_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            rng = random.Random(3)
            rev1 = disc(8 << 20, 1)
            base = edit(rev1, 2)
            final = edit(base, 3)
            Path(work / 'source.bin').write_bytes(rev1)
            patches = []
            sources = [work / 'source.bin']
            for index, target in enumerate((base, final)):
                target_file = work / f'target{index}.bin'
                target_file.write_bytes(target)
                patch = work / f'p{index}.xdelta'
                subprocess.run([self.xdelta, '-e', '-A', '-a', '-s',
                                str(sources[-1]), str(target_file), str(patch)],
                               check=True)
                patches.append(patch)
                sources.append(target_file)
            step_hashes = [x for pair in (
                (patch.name, hashlib.sha256(target).hexdigest())
                for patch, target in zip(patches, (base, final)))
                for x in pair]
            proc = self.run_harness(str(work), step_hashes)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertIn('SHA_CHAIN_OK', proc.stdout)
            # the same chain with a wrong expectation must be refused
            step_hashes[-1] = '0' * 64
            proc = self.run_harness(str(work), step_hashes)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('SHA_CHAIN_FAIL', proc.stdout + proc.stderr)


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
             str(ROOT / 'webpatcher' / 'workerfs.js'),
             str(ROOT / 'webpatcher' / 'xdelta.js'), source, patch,
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

    def run_harness(self, harness, marker, opfs=False):
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

            argv = ['node', str(harness), str(VENDOR / 'xdelta3.js'),
                    str(ROOT / 'webpatcher' / 'workerfs.js')]
            if opfs:
                argv.append(str(ROOT / 'webpatcher' / 'scratch.js'))
                argv.append(str(ROOT / 'webpatcher' / 'opfsfs.js'))
            argv.append(str(ROOT / 'webpatcher' / 'xdelta.js'))
            argv += [tmp, expected, 'p0.xdelta', 'p1.xdelta']
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertIn(marker, proc.stdout)

    def test_chain_matches_cli_ground_truth(self):
        self.run_harness(HARNESS, 'CHAIN_OK')

    def test_opfs_chain_matches_cli_ground_truth(self):
        """The optional on-disk scratch filesystem applies the same chain."""
        self.run_harness(OPFS_HARNESS, 'OPFS_CHAIN_OK', opfs=True)


if __name__ == '__main__':
    unittest.main()
