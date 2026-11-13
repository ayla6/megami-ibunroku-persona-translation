"""Release graph, canonical states, sampled chains, round trips, publication."""
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
    markers through exactly the property the release chains rely on.
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
            # run writes where western does, so alone it differs from run
            # applied over western: the case a partner file exists for
            marker = (b'[run+western]' if label == 'run' and 'western' in labels
                      else f'[{label}]'.encode())
            at = 8192 * (release.CHOICE_ORDER.index(label) + 1) + shift
            if label in release.SIZE_CHANGERS:
                body[at:at] = marker
                shift += len(marker)
            else:
                body[at:at + len(marker)] = marker
    return bytes(body)


class ReleaseGraph(unittest.TestCase):
    def test_release_graph_is_only_canonical_states(self):
        canonical = release.canonical_states()
        anchors = release.size_changer_states()
        self.assertEqual(anchors, [(), ('saves',), ('60fps',),
                                   ('saves', '60fps')])
        self.assertEqual(len(canonical), 14)
        self.assertEqual(canonical[0], ())
        self.assertEqual({tuple(labels) for labels in canonical[:4]},
                         set(anchors))
        for option in release.in_place_options():
            self.assertIn(tuple(release.solver_order([option])), canonical)
            self.assertEqual(tuple(release.solver_order([option])), (option,))
        self.assertEqual(len({tuple(release.release_selection(labels))
                              for labels in canonical}), 14)

        expected = {'rev0-to-base.xdelta', 'rev1-to-rev0.xdelta',
                    'add-saves.xdelta', 'add-60fps.xdelta',
                    'add-60fps-saves.xdelta'}
        for option in release.in_place_options():
            expected.add(release.patch_file(option, frozenset()))
        # a partnered option has a second file over its partner
        expected.add('add-run-western.xdelta')
        self.assertEqual(len(release.release_file_names()), 15)
        self.assertEqual(release.release_file_names(), expected)

    def test_samples_start_with_the_expected_popular_sets(self):
        picks = release.sample_selections(3, 0)
        self.assertEqual(picks[:len(release.SAMPLE_POPULAR)],
                         [tuple(release.solver_order(labels))
                          for labels in release.SAMPLE_POPULAR])
        self.assertEqual(len(picks), 6, 'three popular sets plus three random')
        canonical = set(release.canonical_states())
        self.assertEqual(len(set(picks)), len(picks), 'no duplicate samples')
        for labels in picks[3:]:
            self.assertNotIn(frozenset(labels), canonical,
                             'random samples exercise decorated chains')
            self.assertTrue(labels)
        self.assertEqual(picks, release.sample_selections(3, 0),
                         'the same seed samples the same combinations')
        self.assertNotEqual(picks[3:], release.sample_selections(3, 1)[3:],
                            'a new seed samples new combinations')

    def test_assembly_parent_keeps_the_one_shot_size_changer_layout(self):
        self.assertEqual(release.assembly_parent(()), ())
        for option in release.in_place_options():
            self.assertEqual(release.assembly_parent((option,)), ())
        # Every size-changer is laid out from retail in one pass, so it
        # matches a one-shot build.py --qol=... disc.
        self.assertIsNone(release.assembly_parent(('saves',)))
        self.assertIsNone(release.assembly_parent(('60fps',)))
        self.assertIsNone(release.assembly_parent(('saves', '60fps')))
        self.assertIsNone(release.assembly_parent(('mark', 'saves')))
        self.assertIsNone(release.assembly_parent(('saves', 'mark')))

    def test_add_edges_cover_every_option_and_anchor(self):
        edges = {(option, tuple(sorted(anchor)))
                 for option, anchor in release.add_edges()}
        for option in release.in_place_options():
            self.assertIn((option, ()), edges)
            self.assertNotIn((option, ('saves',)), edges)
        self.assertIn(('saves', ()), edges)
        self.assertIn(('60fps', ()), edges)
        self.assertIn(('60fps', ('saves',)), edges)
        self.assertIn(('run', ()), edges)
        self.assertIn(('run', ('western',)), edges)
        self.assertEqual(len(edges), 13)

    def test_every_add_edge_is_encoded_from_a_canonical_state(self):
        canonical = set(release.canonical_states())
        files = release.release_file_names()
        for labels in canonical:
            if not labels:
                continue
            edge = release.release_edge(labels)
            self.assertIn(edge.parent, canonical, labels)
            self.assertIn(edge.file, files, labels)
            anchor = release.assembly_parent(labels)
            ordered = release.solver_order(labels)
            if ordered[-1] in release.PARTNERS and ordered[:-1] == [release.PARTNERS[ordered[-1]]]:
                # the pair is assembled on the base, encoded over the partner
                self.assertEqual(edge.parent, tuple(ordered[:-1]), labels)
            elif anchor is not None:
                self.assertEqual(edge.parent, anchor, labels)
            else:
                # A second size-changer is laid out from retail in one pass,
                # but its patch is still encoded from the earlier layout.
                ordered = release.solver_order(labels)
                self.assertEqual(
                    edge.parent,
                    tuple(label for label in ordered[:-1]
                          if label in release.SIZE_CHANGERS),
                    labels)

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
    """A release against a synthetic disc: canonical states are assembled,
    patches are encoded, the sampled selections are rebuilt from retail and
    the published chains must reproduce them byte for byte, and reruns
    rebuild only what changed."""

    samples = (('mark', 'battlespeed'),
               ('mark', 'encounters', 'western', 'run', 'saves'))

    def setUp(self):
        self.tool = shutil.which('xdelta3')
        self.canonical = release.canonical_states()

    def run_release(self, root, rev0, rev1, out, corrupt=None, samples=None):
        verified = []

        def run(cmd, **kwargs):
            if len(cmd) > 1 and str(cmd[1]).endswith('verify_disc.py'):
                verified.append(Path(cmd[2]).read_bytes())
                return subprocess.CompletedProcess(cmd, 0)
            return actual_run(cmd, **kwargs)

        actual_run = subprocess.run
        built = set()

        def fake_build(variants_override, after_variant=None, mark_builder=None,
                       source_image_for=None):
            for selected, path in variants_override:
                labels = tuple(release.solver_order(
                    release.state_labels(selected)))
                self.assertTrue((out / release.REV1_PATCH).is_file(),
                                'revision conversion must precede every translation build')
                if labels:
                    self.assertTrue((out / release.BASE_PATCH).is_file(),
                                    'base patch must be published before any option build')
                    self.assertIn(release.BASE_PATCH,
                                  release.read_manifest(out / 'manifest.tsv'),
                                  'the verified base must be recorded before any option build')
                if source_image_for is not None:
                    source = Path(source_image_for(selected))
                    self.assertTrue(source.is_file())
                    parent = release.assembly_parent(labels)
                    if labels not in self.canonical:
                        # sample builds are one-shot from retail
                        expected = rev0.read_bytes()
                    elif not labels or parent is None:
                        expected = rev0.read_bytes()
                    elif parent in self.canonical or parent in built:
                        expected = variant_bytes(parent)
                    else:
                        expected = variant_bytes(())
                    self.assertEqual(source.read_bytes(), expected,
                                     f'source image for {labels}')
                data = variant_bytes(labels)
                if corrupt is not None and labels == corrupt:
                    data = data[:-1] + bytes([data[-1] ^ 0xFF])
                Path(path).write_bytes(data)
                Path(str(path) + '.placement.tsv').write_text(
                    'path\textent\tsize\tsha256\n')
                built.add(labels)
                if after_variant is not None:
                    after_variant(selected, path)

        with patch.object(release, 'ROOT', root), \
                patch.object(release, 'scratch_root', scratch_in(root)), \
                patch.object(release, 'sample_selections',
                             return_value=list(self.samples if samples is None
                                               else samples)), \
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
            self.assertEqual(len(verified), 14 + len(self.samples),
                             'an audit per canonical state and per sample disc')
            self.assertEqual(builder.call_count, 2,
                             'one canonical batch plus one sample batch')
            self.assertEqual(len(list(out.glob('*.xdelta'))), 15)
            self.assertFalse(list(out.glob('*.bin')))
            readme = (out / 'README.txt').read_text(encoding='utf-8')
            for name in release.release_file_names():
                self.assertIn(name, readme)
            for item in release.RELEASE_OPTIONS:
                self.assertIn(item['name'], readme)
            self.assertIn('15 steps across 15 patch files', ' '.join(readme.split()))
            self.assertIn('SAMPLING', readme)

            with (out / 'manifest.tsv').open() as f:
                rows = list(csv.DictReader(f, delimiter='\t'))
            self.assertEqual(len(rows), 15)
            by_name = {row['patch']: row for row in rows}
            self.assertEqual(len(by_name), 15, 'one row per patch file')
            self.assertEqual(by_name['rev1-to-rev0.xdelta']['source_sha256'],
                             release.sha256(rev1))
            base = by_name['rev0-to-base.xdelta']
            self.assertEqual(base['source_sha256'], release.sha256(rev0))
            self.assertTrue(base['target_sha256'])
            # An add- row's source is whatever the player's earlier options
            # made it, so whole-image hashes would describe a disc that was
            # never built: only the patch file's hash and its sizes are real.
            for option, anchor in release.add_edges():
                row = by_name[release.patch_file(option, anchor)]
                self.assertEqual(row['adds'], option)
                self.assertEqual(row['anchor'], ','.join(
                    label for label in release.solver_order(release.CHOICE_ORDER)
                    if label in anchor))
                self.assertEqual(row['order'],
                                 str(release.solver_order(release.CHOICE_ORDER).index(option)))
                self.assertEqual(row['source_sha256'], '')
                self.assertEqual(row['target_sha256'], '')
                self.assertTrue(row['patch_sha256'])
                self.assertTrue(row['target_bytes'])
            for labels in self.samples:
                for name in [release.BASE_PATCH] + [
                        release.patch_file(label, release.anchor_of(
                            label, release.solver_order(labels)[:index]))
                        for index, label in enumerate(release.solver_order(labels))]:
                    self.assertIn(','.join(release.solver_order(labels)),
                                  by_name[name]['verified'].split(';'),
                                  f'{name} must record the sample that used it')

            conversion = out / 'rev1-to-rev0.xdelta'
            stamp = conversion.stat().st_mtime_ns
            _, builder = self.run_release(root, rev0, rev1, out)
            self.assertEqual(builder.call_count, 0,
                             'unchanged release must not rebuild')
            self.assertEqual(conversion.stat().st_mtime_ns, stamp)

            # A partial/interrupted release may have option patches but no
            # base. It must regenerate and publish the base first, before
            # reconstructing parents or assembling any option/sample.
            (out / release.BASE_PATCH).unlink()
            _, builder = self.run_release(root, rev0, rev1, out)
            self.assertTrue((out / release.BASE_PATCH).is_file())
            first_build = builder.call_args_list[0].kwargs['variants_override']
            self.assertEqual(release.state_labels(first_build[0][0]), ())
            self.assertEqual(conversion.stat().st_mtime_ns, stamp)

            (out / 'add-60fps.xdelta').unlink()
            _, builder = self.run_release(root, rev0, rev1, out)
            self.assertEqual(builder.call_count, 1,
                             'no sample needs 60fps; only its state rebuilds')
            self.assertEqual(
                [release.state_labels(selected)
                 for selected, _path in builder.call_args.kwargs['variants_override']],
                [('60fps',)])
            self.assertEqual(conversion.stat().st_mtime_ns, stamp)

            (out / 'add-saves.xdelta').unlink()
            _, builder = self.run_release(root, rev0, rev1, out)
            self.assertEqual(builder.call_count, 2,
                             'the canonical state plus the sample that uses it')
            canonical_call, sample_call = builder.call_args_list
            self.assertEqual(
                [release.state_labels(selected)
                 for selected, _path in
                 canonical_call.kwargs['variants_override']],
                [('saves',)])
            self.assertEqual(
                [tuple(release.solver_order(release.state_labels(selected)))
                 for selected, _path in
                 sample_call.kwargs['variants_override']],
                [tuple(release.solver_order(self.samples[1]))])
            paths = [path for _, path in
                     canonical_call.kwargs['variants_override']]
            self.assertEqual(len(paths), len(set(paths)),
                             'each variant must write its own scratch image')
            self.assertEqual(conversion.stat().st_mtime_ns, stamp)

    def test_sampled_chain_mismatch_stops_the_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rev0, rev1, out = root / 'zero.bin', root / 'one.bin', root / 'release'
            rev0.write_bytes(b'retail revision zero' * 100)
            rev1.write_bytes(b'retail revision one' * 100)
            # The disc built for a sampled selection does not match what the
            # published chain produces: the sample comparison must catch it.
            with self.assertRaisesRegex(RuntimeError, 'reproduce the built disc'):
                self.run_release(root, rev0, rev1, out,
                                 corrupt=tuple(self.samples[0]))

    def test_base_audit_failure_stops_before_option_assembly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rev0, rev1, out = root / 'zero.bin', root / 'one.bin', root / 'release'
            rev0.write_bytes(b'retail revision zero' * 100)
            rev1.write_bytes(b'retail revision one' * 100)
            assembled = []
            actual_run = subprocess.run

            def run(cmd, **kwargs):
                if len(cmd) > 1 and str(cmd[1]).endswith('verify_disc.py'):
                    raise RuntimeError('base audit failed')
                return actual_run(cmd, **kwargs)

            def fake_build(variants_override, after_variant=None, **_kwargs):
                for selected, path in variants_override:
                    assembled.append(tuple(selected))
                    Path(path).write_bytes(variant_bytes(()))
                    Path(str(path) + '.placement.tsv').write_text('path\textent\tsize\tsha256\n')
                    after_variant(selected, path)

            with patch.object(release, 'ROOT', root), \
                    patch.object(release, 'scratch_root', scratch_in(root)), \
                    patch.object(release, 'release_fingerprint', return_value='test-key'), \
                    patch.object(release.image_check, 'require'), \
                    patch.object(release.image_check, 'require_rev1'), \
                    patch.object(release.build, 'main', side_effect=fake_build), \
                    patch.object(release.subprocess, 'run', side_effect=run):
                with self.assertRaisesRegex(RuntimeError, 'base audit failed'):
                    release.build_release(rev0, rev1, out, self.tool)
            self.assertEqual(assembled, [()])
            self.assertTrue((out / release.REV1_PATCH).is_file())
            self.assertFalse((out / release.BASE_PATCH).exists())
            self.assertFalse(list(out.glob('add-*.xdelta')))

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
