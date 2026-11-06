"""Release matrix, exact xdelta sources, round trips and safe publication."""
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


class ReleasePatches(unittest.TestCase):
    def test_release_matrix_has_eight_choices_and_no_debug(self):
        choices = list(release.combinations())
        self.assertEqual(len(choices), 256)
        self.assertEqual(choices[0], ([], []))
        self.assertEqual(len({tuple(selected) for _labels, selected in choices}), 256)
        for labels, selected in choices:
            self.assertNotIn('debug', selected)
            self.assertEqual('rewards' in labels, 'rewards' in selected)
            self.assertEqual('encounters' in labels, 'encounters' in selected)

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
                list(release.combinations())

    def test_solver_order_and_release_edges(self):
        cases = {
            # labels -> (file, parent state, verify mode)
            ('mark',): ('add-mark.xdelta', (), 'xdelta'),
            ('saves',): ('add-saves.xdelta', (), 'xdelta'),
            ('60fps',): ('add-60fps.xdelta', (), 'xdelta'),
            ('rewards',): ('add-rewards.xdelta', (), 'xdelta'),
            ('encounters',): ('add-encounters.xdelta', (), 'xdelta'),
            ('run',): ('add-run.xdelta', (), 'xdelta'),
            ('saves', '60fps'): ('add-60fps-saves.xdelta', ('saves',), 'xdelta'),
            ('mark', 'battlespeed'): ('add-battlespeed.xdelta', ('mark',), 'sha256'),
            ('saves', 'mark'): ('add-saves.xdelta', ('mark',), 'sha256'),
            ('mark', 'rewards'): ('add-rewards.xdelta', ('mark',), 'sha256'),
            ('mark', 'run'): ('add-run.xdelta', ('mark',), 'sha256'),
            ('mark', 'upright'): ('add-upright.xdelta', ('mark',), 'sha256'),
            ('battlespeed', '60fps'): ('add-60fps.xdelta', ('battlespeed',), 'sha256'),
            ('mark', 'saves', '60fps'):
                ('add-60fps-saves.xdelta', ('mark', 'saves'), 'sha256'),
            ('saves', 'mark', '60fps', 'encounters'):
                ('add-60fps-saves.xdelta',
                 ('mark', 'encounters', 'saves'), 'sha256'),
            ('battlespeed', '60fps', 'encounters'):
                ('add-60fps.xdelta', ('battlespeed', 'encounters'),
                 'sha256'),
            ('mark', 'battlespeed', 'rewards', 'encounters'):
                ('add-encounters.xdelta',
                 ('mark', 'battlespeed', 'rewards'), 'sha256'),
            ('mark', 'battlespeed', 'rewards', 'encounters', 'run'):
                ('add-run.xdelta',
                 ('mark', 'battlespeed', 'rewards', 'encounters'), 'sha256'),
        }
        for labels, (file, parent, verify) in cases.items():
            edge = release.release_edge(list(labels))
            self.assertEqual(edge.file, file, f'file for {labels}')
            self.assertEqual(edge.parent, parent, f'parent of {labels}')
            self.assertEqual(edge.verify, verify, f'verify for {labels}')
        self.assertEqual(
            release.release_file_names(),
            {'add-mark.xdelta', 'add-battlespeed.xdelta',
             'add-rewards.xdelta', 'add-encounters.xdelta', 'add-run.xdelta',
             'add-upright.xdelta',
             'add-saves.xdelta', 'add-60fps.xdelta', 'add-60fps-saves.xdelta',
             'rev0-to-base.xdelta', 'rev1-to-rev0.xdelta'})

    @unittest.skipUnless(shutil.which('xdelta3'), 'xdelta3 not installed')
    def test_complete_release_round_trips_and_publishes_no_images(self):
        tool = shutil.which('xdelta3')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rev0, rev1, out = root / 'zero.bin', root / 'one.bin', root / 'release'
            rev0.write_bytes(b'retail revision zero' * 100)
            rev1.write_bytes(b'retail revision one' * 100)
            actual_run = subprocess.run
            verified = []

            def run(cmd, **kwargs):
                if len(cmd) > 1 and str(cmd[1]).endswith('verify_disc.py'):
                    verified.append(Path(cmd[2]).read_bytes())
                    return subprocess.CompletedProcess(cmd, 0)
                return actual_run(cmd, **kwargs)

            combo = {tuple(sorted(selected)): labels
                     for labels, selected in release.combinations()}

            def variant_bytes(labels):
                # a structured body (distinctive everywhere, like the real
                # sectors, so xdelta must match true offsets) where in-place
                # options overwrite their fixed slot - the image keeps its
                # size - and size-changers insert, shifting every later
                # slot. The layout is a pure function of the selected set,
                # so an add- patch copies riding-along markers through,
                # exactly the property the release proofs rely on.
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

            def fake_build(variants_override, after_variant, mark_builder,
                           source_image_for=None):
                for selected, path in variants_override:
                    if selected and source_image_for is not None:
                        # every variant is built on the staged retail copy, so
                        # its bytes match an ordinary build.py invocation
                        source = Path(source_image_for(selected))
                        self.assertTrue(source.is_file())
                        self.assertEqual(source.name, 'original.bin')
                        self.assertEqual(source.read_bytes(), rev0.read_bytes())
                    Path(path).write_bytes(variant_bytes(combo[tuple(sorted(selected))]))
                    Path(path + '.placement.tsv').write_text(
                        'path\textent\tsize\tsha256\n')
                    after_variant(selected, path)

            with patch.object(release, 'ROOT', root), \
                    patch.object(release, 'scratch_root', scratch_in(root)), \
                    patch.object(release, 'release_fingerprint', return_value='test-key'), \
                    patch.object(release.image_check, 'require'), \
                    patch.object(release.image_check, 'require_rev1'), \
                    patch.object(release.build, 'main', side_effect=fake_build) as builder, \
                    patch.object(release.subprocess, 'run', side_effect=run):
                release.build_release(rev0, rev1, out, tool)
                self.assertEqual(len(verified), 256)
                self.assertEqual(len(list(out.glob('*.xdelta'))), 11)
                self.assertFalse(list(out.glob('*.bin')))
                # the README is generated from the graph and the one
                # wording file, so it names every file and every option
                readme = (out / 'README.txt').read_text(encoding='utf-8')
                for name in release.release_file_names():
                    self.assertIn(name, readme)
                for item in release.RELEASE_OPTIONS:
                    self.assertIn(item['name'], readme)
                self.assertIn('257 steps', readme)
                self.assertIn('11 patch files', readme)
                self.assertFalse(list((root / 'build/patch-work').glob('parent-*')))
                with (out / 'manifest.tsv').open() as f:
                    rows = {(row['patch'], row['source_sha256']): row
                            for row in csv.DictReader(f, delimiter='\t')}
                self.assertEqual(len(rows), 257)
                self.assertEqual(rows[('rev1-to-rev0.xdelta', release.sha256(rev1))]['source_sha256'],
                                 release.sha256(rev1))
                base = rows[('rev0-to-base.xdelta', release.sha256(rev0))]
                self.assertEqual(base['source_sha256'], release.sha256(rev0))
                targets = {row['target_sha256'] for row in rows.values()}
                for (name, source), row in rows.items():
                    self.assertEqual(row['source_sha256'], source, name)
                    if name != 'rev1-to-rev0.xdelta':
                        self.assertIn(source, targets,
                                      f'{name} must delta from a step in the release')
                # anchor-exact steps verify with xdelta's own checksums,
                # decorated steps carry the whole-file sha256 certificate
                self.assertEqual(base['verify'], 'xdelta')
                mark_state = variant_bytes(('mark',))
                self.assertEqual(rows[('add-mark.xdelta', base['target_sha256'])]['verify'],
                                 'xdelta')
                decorated = rows[('add-battlespeed.xdelta', hashlib.sha256(mark_state).hexdigest())]
                self.assertEqual(decorated['verify'], 'sha256')
                self.assertEqual(decorated['target_sha256'],
                                 hashlib.sha256(variant_bytes(('mark', 'battlespeed'))).hexdigest())
                # the chain must actually compose: decoding it reproduces
                # the known variant bytes exactly - this pins the graph
                # walking and the add- patch portability together
                def chain(labels):
                    steps = []
                    current = tuple(labels)
                    while current:
                        edge = release.release_edge(current)
                        steps.append((edge.file, edge.verify))
                        current = edge.parent
                    steps.append((release.BASE_PATCH, 'xdelta'))
                    return steps
                for labels in (('mark',), ('saves', 'mark'), ('mark', 'encounters', '60fps'),
                               ('mark', 'battlespeed', 'rewards', 'saves', '60fps')):
                    decoded = root / 'chain.bin'
                    source = rev0
                    for step, verify in reversed(chain(labels)):
                        command = [tool, '-d', '-f', '-q']
                        if verify == 'sha256':
                            command.append('-n')
                        command += ['-s', str(source), str(out / step), str(decoded)]
                        subprocess.run(command, check=True)
                        source = decoded
                    self.assertEqual(decoded.read_bytes(), variant_bytes(labels),
                                     f'chain to {labels}')
                conversion = out / 'rev1-to-rev0.xdelta'
                stamp = conversion.stat().st_mtime_ns
                release.build_release(rev0, rev1, out, tool)
                self.assertEqual(builder.call_count, 1, 'unchanged release must not rebuild')
                self.assertEqual(conversion.stat().st_mtime_ns, stamp)
                # the pending set a deleted file pulls in is derived from the
                # module itself, so this survives option additions
                def expected_pending(name):
                    def order_key(labels):
                        ordered = release.solver_order(labels)
                        return (0 if not ordered else 1 if len(ordered) == 1 else 2,
                                len(ordered), tuple(ordered))
                    incoming = [labels for labels, _selected in release.combinations()
                                if labels and release.release_edge(labels).file == name]
                    return [sorted(labels) for labels in sorted(incoming, key=order_key)]
                (out / 'add-60fps.xdelta').unlink()
                release.build_release(rev0, rev1, out, tool)
                self.assertEqual(builder.call_count, 2)
                self.assertEqual([sorted(v[0]) for v in builder.call_args.kwargs['variants_override']],
                                 expected_pending('add-60fps.xdelta'))
                self.assertEqual(conversion.stat().st_mtime_ns, stamp)
                (out / 'add-saves.xdelta').unlink()
                release.build_release(rev0, rev1, out, tool)
                self.assertEqual(builder.call_count, 3,
                                 'variants that only ride along stay valid while the file is rebuilt')
                self.assertEqual([sorted(v[0]) for v in builder.call_args.kwargs['variants_override']],
                                 expected_pending('add-saves.xdelta'))
                paths = [path for _, path in builder.call_args.kwargs['variants_override']]
                self.assertEqual(len(paths), len(set(paths)),
                                 'each variant must write its own scratch image')
                self.assertEqual(conversion.stat().st_mtime_ns, stamp)
            self.assertFalse(list(root.glob('.persona-patches-*')))

    @unittest.skipUnless(shutil.which('xdelta3'), 'xdelta3 not installed')
    def test_failed_portability_proof_stops_the_release(self):
        tool = shutil.which('xdelta3')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rev0, rev1, out = root / 'zero.bin', root / 'one.bin', root / 'release'
            rev0.write_bytes(b'retail revision zero' * 100)
            rev1.write_bytes(b'retail revision one' * 100)
            actual_run = subprocess.run

            def run(cmd, **kwargs):
                if len(cmd) > 1 and str(cmd[1]).endswith('verify_disc.py'):
                    return subprocess.CompletedProcess(cmd, 0)
                return actual_run(cmd, **kwargs)

            combo = {tuple(sorted(selected)): labels
                     for labels, selected in release.combinations()}

            def variant_bytes(labels):
                # a structured body (distinctive everywhere, like the real
                # sectors, so xdelta must match true offsets) where in-place
                # options overwrite their fixed slot - the image keeps its
                # size - and size-changers insert, shifting every later
                # slot. The layout is a pure function of the selected set,
                # so an add- patch copies riding-along markers through,
                # exactly the property the release proofs rely on.
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

            def fake_build(variants_override, after_variant, mark_builder,
                           source_image_for=None):
                for selected, path in variants_override:
                    labels = combo[tuple(sorted(selected))]
                    if labels == ['mark', 'battlespeed']:
                        # bytes the add-battlespeed splice cannot produce
                        # over the mark state: the sha256 proof must catch
                        # this, because nothing else would - mark's marker
                        # is missing from where it would have been copied
                        Path(path).write_bytes(variant_bytes(('battlespeed',)))
                    else:
                        Path(path).write_bytes(variant_bytes(labels))
                    Path(path + '.placement.tsv').write_text(
                        'path\textent\tsize\tsha256\n')
                    after_variant(selected, path)

            with patch.object(release, 'ROOT', root), \
                    patch.object(release, 'scratch_root', scratch_in(root)), \
                    patch.object(release, 'release_fingerprint', return_value='test-key'), \
                    patch.object(release.image_check, 'require'), \
                    patch.object(release.image_check, 'require_rev1'), \
                    patch.object(release.subprocess, 'run', side_effect=run), \
                    patch.object(release.build, 'main', side_effect=fake_build):
                with self.assertRaisesRegex(RuntimeError, 'add-battlespeed'):
                    release.build_release(rev0, rev1, out, tool)

    @unittest.skipUnless(shutil.which('xdelta3'), 'xdelta3 not installed')
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
                    patch.object(release, 'release_fingerprint', return_value='test-key'), \
                    patch.object(release.image_check, 'require'), \
                    patch.object(release.image_check, 'require_rev1'), \
                    patch.object(release.build, 'main', side_effect=RuntimeError('stop')):
                with self.assertRaisesRegex(RuntimeError, 'stop'):
                    release.build_release(rev0, rev1, out, shutil.which('xdelta3'))
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

    @unittest.skipUnless(shutil.which('xdelta3'), 'xdelta3 not installed')
    def test_failed_round_trip_never_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rev0, rev1, out = root / 'zero', root / 'one', root / 'release'
            rev0.write_bytes(b'zero')
            rev1.write_bytes(b'one')
            with patch.object(release, 'ROOT', root), \
                    patch.object(release, 'scratch_root', scratch_in(root)), \
                    patch.object(release, 'release_fingerprint', return_value='test-key'), \
                    patch.object(release.image_check, 'require'), \
                    patch.object(release.image_check, 'require_rev1'), \
                    patch.object(release, 'run_delta',
                                 side_effect=RuntimeError('round-trip differs')):
                with self.assertRaisesRegex(RuntimeError, 'round-trip'):
                    release.build_release(rev0, rev1, out, shutil.which('xdelta3'))
            self.assertFalse((out / 'rev1-to-rev0.xdelta').exists())
            self.assertFalse((root / 'build/patch-work').exists())


if __name__ == '__main__':
    unittest.main()
