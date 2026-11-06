"""Release graph, canonical states, proofs, round trips and safe publication."""
import csv
import hashlib
import os
import random
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import build_patches as release


def scratch_in(root):
    """Keep a test's workspace under its temp root, not the real /tmp."""
    def scratch_root(_required_bytes):
        (root / 'build').mkdir(parents=True, exist_ok=True)
        return root / 'build'
    return scratch_root


class ReleaseIO(unittest.TestCase):

    def test_hash_cache_notices_a_rewritten_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'image.bin'
            path.write_bytes(b'first')
            first = release.sha256(path)
            self.assertEqual(release.sha256(path), first)
            path.write_bytes(b'other')
            self.assertNotEqual(release.sha256(path), first)

    def test_scratch_root_honors_the_environment(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {release.SCRATCH_ENV: tmp}):
            self.assertEqual(release.scratch_root(1), Path(tmp))
            self.assertTrue(Path(tmp).is_dir())

    def test_manifest_is_one_row_per_patch_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'manifest.tsv'
            header = '\t'.join(release.MANIFEST_FIELDS) + '\n'

            def row(patch, adds='', verify='xdelta'):
                cells = dict.fromkeys(release.MANIFEST_FIELDS, '')
                cells.update(patch=patch, adds=adds, verify=verify,
                             source_sha256='source', target_sha256='target',
                             patch_sha256='file')
                return '\t'.join(cells[name] for name in release.MANIFEST_FIELDS)

            path.write_text(header + row('add-a.xdelta', 'a') + '\n')
            self.assertEqual(list(release.read_manifest(path)), ['add-a.xdelta'])

            path.write_text(header + row('add-a.xdelta', 'a') + '\n'
                            + row('add-a.xdelta', 'a') + '\n')
            with self.assertRaisesRegex(ValueError, 'per-combination'):
                release.read_manifest(path)

            path.write_text('patch\tchoices\tsource_sha256\ttarget_sha256\n'
                            'p.xdelta\t\t\ta\n')
            with self.assertRaisesRegex(ValueError, 'unrecognized manifest'):
                release.read_manifest(path)

            path.write_text(header + row('add-a.xdelta', 'a', 'sha256') + '\n')
            with self.assertRaisesRegex(ValueError, 'verified with'):
                release.read_manifest(path)

    def test_workspace_is_private_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(release, 'scratch_root', scratch_in(root)):
                with release.workspace(0) as work:
                    self.assertTrue(work.is_dir())
                    (work / 'image.bin').write_bytes(b'image')
                    with self.assertRaises(RuntimeError):
                        with release.workspace(0):
                            pass
                self.assertFalse(work.exists())


def variant_bytes(labels):
    """Structured stand-in for a built disc.

    In-place options overwrite a fixed slot (the image keeps its size);
    size-changers insert, shifting every later slot. The layout is a pure
    function of the selected set, so an add- patch copies riding-along
    markers through exactly the property the release proofs rely on.
    """
    rng = random.Random(7)
    seed = bytes(rng.randrange(256) for _ in range(4096))
    body = bytearray()
    counter = 0
    while len(body) < 1 << 17:
        body += seed[:-2] + counter.to_bytes(2, 'little')
        counter += 1
    shift = 0
    for label in release.CHOICE_ORDER:
        if label in set(labels):
            marker = f'[{label}]'.encode()
            at = 8192 * (release.CHOICE_ORDER.index(label) + 1) + shift
            if label in release.SIZE_CHANGERS:
                body[at:at] = marker
                shift += len(marker)
            else:
                body[at:at + len(marker)] = marker
    return bytes(body)


class ReleaseGraph(unittest.TestCase):
    def test_release_graph_is_canonical_states_plus_fixtures(self):
        canonical = release.canonical_states()
        self.assertEqual(len(canonical), 11)
        self.assertEqual(canonical[0], ())
        for option in release.in_place_options():
            self.assertIn((option,), canonical)
        self.assertIn(('saves',), canonical)
        self.assertIn(('60fps',), canonical)
        self.assertIn(('saves', '60fps'), canonical)
        self.assertEqual(len({tuple(release.release_selection(labels))
                              for labels in canonical}), 11)

        all_in_place = tuple(release.in_place_options())
        fixtures = release.proof_states()
        self.assertEqual(len(fixtures), 4)
        self.assertIn(all_in_place, fixtures)
        self.assertIn(tuple(release.solver_order([*all_in_place, 'saves'])),
                      fixtures)
        self.assertIn(tuple(release.solver_order([*all_in_place, '60fps'])),
                      fixtures)
        self.assertIn(tuple(release.solver_order([*all_in_place, 'saves', '60fps'])),
                      fixtures)

        self.assertEqual(len(release.release_file_names()), 12)
        self.assertEqual(
            release.release_file_names(),
            {'add-mark.xdelta', 'add-battlespeed.xdelta',
             'add-rewards.xdelta', 'add-encounters.xdelta', 'add-run.xdelta',
             'add-upright.xdelta', 'add-skipfmv.xdelta',
             'add-saves.xdelta', 'add-60fps.xdelta', 'add-60fps-saves.xdelta',
             'rev0-to-base.xdelta', 'rev1-to-rev0.xdelta'})

    def test_assembly_parent_keeps_the_one_shot_size_changer_layout(self):
        self.assertEqual(release.assembly_parent(()), ())
        self.assertEqual(release.assembly_parent(('mark',)), ())
        self.assertEqual(release.assembly_parent(('saves',)), ())
        self.assertIsNone(release.assembly_parent(('saves', '60fps')))
        all_in_place = tuple(release.in_place_options())
        self.assertEqual(release.assembly_parent((*all_in_place, 'saves')),
                         all_in_place)
        self.assertIsNone(release.assembly_parent(
            (*all_in_place, 'saves', '60fps')))

    def test_add_edges_cover_every_option_and_anchor(self):
        edges = {(option, tuple(sorted(anchor)))
                 for option, anchor in release.add_edges()}
        for option in release.in_place_options():
            self.assertIn((option, ()), edges)
        self.assertIn(('saves', ()), edges)
        self.assertIn(('60fps', ()), edges)
        self.assertIn(('60fps', ('saves',)), edges)
        self.assertEqual(len(edges), 10)

    def test_xdelta_selection_prefers_explicit_then_bundled_then_path(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(release, 'ROOT', Path(tmp)), \
                patch.object(release.shutil, 'which', return_value='/path/xdelta3'):
            binary = Path(tmp) / 'external_tools/xdelta3' / ('xdelta3.exe' if sys.platform == 'win32' else 'xdelta3')
            binary.parent.mkdir(parents=True)
            self.assertEqual(release.find_xdelta3(), '/path/xdelta3')
            binary.write_bytes(b'fake')
            self.assertEqual(release.find_xdelta3(), str(binary))
            self.assertEqual(release.find_xdelta3('/explicit/xdelta3'), '/explicit/xdelta3')

    def test_unknown_new_qol_patch_requires_release_review(self):
        with patch.dict(release.build.QOL_PATCHES, {'new-feature': ('QOL_NEW', 'test')}):
            with self.assertRaisesRegex(ValueError, 'review release choices'):
                release.check_choices()


@unittest.skipUnless(shutil.which('xdelta3'), 'xdelta3 not installed')
class ReleaseBuild(unittest.TestCase):
    """A full release against a synthetic disc: canonical states and proof
    fixtures are assembled, patches are encoded, every decorated step is
    proven, and reruns rebuild only what changed."""

    def setUp(self):
        self.tool = shutil.which('xdelta3')
        self.canonical = release.canonical_states()
        self.fixtures = release.proof_states()
        self.known = set(self.canonical) | set(self.fixtures)
        self.by_selection = {tuple(release.release_selection(labels)): labels
                             for labels in self.known}

    def run_release(self, root, rev0, rev1, out, corrupt=None):
        verified = []

        def run(cmd, **kwargs):
            if len(cmd) > 1 and str(cmd[1]).endswith('verify_disc.py'):
                verified.append(Path(cmd[2]).read_bytes())
                return subprocess.CompletedProcess(cmd, 0)
            return actual_run(cmd, **kwargs)

        actual_run = subprocess.run
        built = set()

        def fake_build(variants_override, after_variant, mark_builder,
                       source_image_for=None):
            for selected, path in variants_override:
                labels = self.by_selection[tuple(selected)]
                if source_image_for is not None:
                    source = Path(source_image_for(selected))
                    self.assertTrue(source.is_file())
                    parent = release.assembly_parent(labels)
                    if not labels or parent is None:
                        expected = rev0.read_bytes()
                    elif (parent in self.canonical or parent in self.fixtures
                          or parent in built):
                        expected = variant_bytes(parent)
                    else:
                        expected = variant_bytes(())
                    self.assertEqual(source.read_bytes(), expected,
                                     f'source image for {labels}')
                data = variant_bytes(labels)
                if corrupt is not None and labels == corrupt:
                    data = data[:-1] + bytes([data[-1] ^ 0xFF])
                Path(path).write_bytes(data)
                Path(path + '.placement.tsv').write_text(
                    'path\textent\tsize\tsha256\n')
                built.add(labels)
                after_variant(selected, path)

        with patch.object(release, 'ROOT', root), \
                patch.object(release, 'scratch_root', scratch_in(root)), \
                patch.object(release, 'release_fingerprint',
                             return_value='test-key'), \
                patch.object(release.image_check, 'require'), \
                patch.object(release.image_check, 'require_rev1'), \
                patch.object(release.build, 'main',
                             side_effect=fake_build) as builder, \
                patch.object(release.subprocess, 'run', side_effect=run):
            release.build_release(rev0, rev1, out, self.tool)
        return verified, builder

    def test_complete_release_round_trips_and_publishes_no_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rev0, rev1, out = root / 'zero.bin', root / 'one.bin', root / 'release'
            rev0.write_bytes(b'retail revision zero' * 100)
            rev1.write_bytes(b'retail revision one' * 100)
            verified, builder = self.run_release(root, rev0, rev1, out)
            # one audit per assembled state: 11 canonical + 4 fixtures
            self.assertEqual(len(verified), 15)
            self.assertEqual(len(list(out.glob('*.xdelta'))), 12)
            self.assertFalse(list(out.glob('*.bin')))
            readme = (out / 'README.txt').read_text(encoding='utf-8')
            for name in release.release_file_names():
                self.assertIn(name, readme)
            for item in release.RELEASE_OPTIONS:
                self.assertIn(item['name'], readme)
            self.assertIn('12 steps across 12 patch files', ' '.join(readme.split()))

            with (out / 'manifest.tsv').open() as f:
                rows = list(csv.DictReader(f, delimiter='\t'))
            self.assertEqual(len(rows), 12)
            by_name = {row['patch']: row for row in rows}
            self.assertEqual(len(by_name), 12, 'one row per patch file')
            self.assertEqual(by_name['rev1-to-rev0.xdelta']['source_sha256'],
                             release.sha256(rev1))
            base = by_name['rev0-to-base.xdelta']
            self.assertEqual(base['source_sha256'], release.sha256(rev0))
            targets = {row['target_sha256'] for row in rows}
            for name, row in by_name.items():
                if name != 'rev1-to-rev0.xdelta':
                    self.assertIn(row['source_sha256'], targets,
                                  f'{name} must delta from a canonical state')
            for option, anchor in release.add_edges():
                row = by_name[release.patch_file(option, anchor)]
                self.assertEqual(row['adds'], option)
                self.assertEqual(row['anchor'], ','.join(
                    label for label in release.solver_order(release.CHOICE_ORDER)
                    if label in anchor))
                self.assertEqual(row['order'],
                                 str(release.solver_order(release.CHOICE_ORDER).index(option)))
                self.assertTrue(row['proof_sha256'], row['patch'])
                self.assertEqual(row['proof_choices'], ','.join(
                    release.solver_order(release.proof_target(option, anchor))))

            def chain(labels):
                """The rows a browser applies, derived from adds/anchor/order."""
                applied = set()
                steps = [release.BASE_PATCH]
                for label in release.solver_order(labels):
                    anchor = frozenset(item for item in applied
                                       if item in release.SIZE_CHANGERS)
                    steps.append(release.patch_file(label, anchor))
                    applied.add(label)
                return steps

            for labels in (('mark',), ('saves', 'mark'),
                           ('mark', 'encounters', '60fps'),
                           ('mark', 'battlespeed', 'rewards', 'saves', '60fps')):
                decoded = root / 'chain.bin'
                source = rev0
                for step in chain(labels):
                    command = [self.tool, '-d', '-f', '-q', '-n']
                    if step == release.BASE_PATCH:
                        command.remove('-n')
                    command += ['-s', str(source), str(out / step), str(decoded)]
                    subprocess.run(command, check=True)
                    source = decoded
                self.assertEqual(decoded.read_bytes(), variant_bytes(labels),
                                 f'chain to {labels}')

            conversion = out / 'rev1-to-rev0.xdelta'
            stamp = conversion.stat().st_mtime_ns
            _, builder = self.run_release(root, rev0, rev1, out)
            self.assertEqual(builder.call_count, 0,
                             'unchanged release must not rebuild')
            self.assertEqual(conversion.stat().st_mtime_ns, stamp)

            _, builder = self.run_release(root, rev0, rev1, out)
            self.assertEqual(builder.call_count, 0)

            all_in_place = tuple(release.in_place_options())
            (out / 'add-60fps.xdelta').unlink()
            _, builder = self.run_release(root, rev0, rev1, out)
            self.assertEqual(builder.call_count, 1)
            self.assertEqual(
                [self.by_selection[tuple(v[0])]
                 for v in builder.call_args.kwargs['variants_override']],
                [('60fps',), all_in_place,
                 tuple(release.solver_order([*all_in_place, '60fps']))])
            self.assertEqual(conversion.stat().st_mtime_ns, stamp)

            (out / 'add-saves.xdelta').unlink()
            _, builder = self.run_release(root, rev0, rev1, out)
            self.assertEqual(builder.call_count, 1)
            self.assertEqual(
                [self.by_selection[tuple(v[0])]
                 for v in builder.call_args.kwargs['variants_override']],
                [('saves',), all_in_place,
                 tuple(release.solver_order([*all_in_place, 'saves']))])
            paths = [path for _, path in builder.call_args.kwargs['variants_override']]
            self.assertEqual(len(paths), len(set(paths)),
                             'each variant must write its own scratch image')
            self.assertEqual(conversion.stat().st_mtime_ns, stamp)

    def test_failed_portability_proof_stops_the_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rev0, rev1, out = root / 'zero.bin', root / 'one.bin', root / 'release'
            rev0.write_bytes(b'retail revision zero' * 100)
            rev1.write_bytes(b'retail revision one' * 100)
            # A decorated fixture whose bytes the patch chain cannot produce:
            # nothing else in the build would notice.
            with self.assertRaisesRegex(RuntimeError, 'decorated parent'):
                self.run_release(root, rev0, rev1, out,
                                 corrupt=tuple(release.proof_states())[0])

    def test_existing_unrelated_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / 'release'
            out.mkdir()
            (out / 'keep').write_text('user data')
            rev0, rev1 = root / 'zero', root / 'one'
            rev0.write_bytes(b'zero')
            rev1.write_bytes(b'one')
            with patch.object(release, 'ROOT', root), \
                    patch.object(release, 'scratch_root', scratch_in(root)), \
                    patch.object(release, 'release_fingerprint',
                                 return_value='test-key'), \
                    patch.object(release.image_check, 'require'), \
                    patch.object(release.image_check, 'require_rev1'), \
                    patch.object(release.build, 'main',
                                 side_effect=RuntimeError('stop')):
                with self.assertRaisesRegex(RuntimeError, 'stop'):
                    release.build_release(rev0, rev1, out, self.tool)
            self.assertEqual((out / 'keep').read_text(), 'user data')
            self.assertTrue((out / 'rev1-to-rev0.xdelta').exists())

    def test_rev1_rejects_wrong_size_and_wrong_crc(self):
        with tempfile.TemporaryDirectory() as tmp:
            disc = Path(tmp) / 'rev1.bin'
            disc.write_bytes(b'test')
            with self.assertRaisesRegex(SystemExit, 'expected Rev 1'):
                release.image_check.require_rev1(str(disc))
            with patch.object(release.image_check, 'REV1_SIZE', 4), \
                    patch.object(release.image_check, 'REV1_CRC32', 0):
                with self.assertRaisesRegex(SystemExit, 'CRC32'):
                    release.image_check.require_rev1(str(disc))

    def test_round_trip_uses_check_only_decode(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(release.subprocess, 'run', side_effect=fake_run):
            release.run_delta('/xdelta3', Path(tmp) / 'source',
                              Path(tmp) / 'target', Path(tmp) / 'patch',
                              disable_armor=True)
        self.assertEqual(len(calls), 2)
        self.assertIn('-e', calls[0])
        self.assertIn('-a', calls[0])
        self.assertIn('-d', calls[1])
        self.assertIn('-J', calls[1])
        self.assertNotIn(str(Path(tmp) / 'target'), calls[1])

    def test_failed_round_trip_never_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rev0, rev1, out = root / 'zero', root / 'one', root / 'release'
            rev0.write_bytes(b'zero')
            rev1.write_bytes(b'one')
            with patch.object(release, 'ROOT', root), \
                    patch.object(release, 'scratch_root', scratch_in(root)), \
                    patch.object(release, 'release_fingerprint',
                                 return_value='test-key'), \
                    patch.object(release.image_check, 'require'), \
                    patch.object(release.image_check, 'require_rev1'), \
                    patch.object(release, 'run_delta',
                                 side_effect=RuntimeError('round-trip differs')):
                with self.assertRaisesRegex(RuntimeError, 'round-trip'):
                    release.build_release(rev0, rev1, out, self.tool)
            self.assertFalse((out / 'rev1-to-rev0.xdelta').exists())
            self.assertFalse((root / 'build/patch-work').exists())


if __name__ == '__main__':
    unittest.main()
