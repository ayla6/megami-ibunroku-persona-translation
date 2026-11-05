"""Release matrix, exact xdelta sources, round trips and safe publication."""
import csv
import os
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
    def test_release_matrix_has_five_choices_and_no_debug(self):
        choices = list(release.combinations())
        self.assertEqual(len(choices), 32)
        self.assertEqual(choices[0], ([], []))
        self.assertEqual(len({tuple(selected) for _labels, selected in choices}), 32)
        for labels, selected in choices:
            self.assertNotIn('debug', selected)
            self.assertEqual('encounters' in selected, 'rewards' in selected)
            self.assertEqual('rewards-encounters' in labels, 'rewards' in selected)

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

    def test_layer_parents_and_patch_names(self):
        cases = {
            ('mark',): [],
            ('saves',): [],
            ('battlespeed',): [],
            ('mark', 'saves'): ('mark',),
            ('saves', 'mark'): ('mark',),
            ('mark', 'battlespeed'): ('mark',),
            ('saves', '60fps'): ('saves',),
            ('mark', 'saves', 'battlespeed'): ('mark', 'saves'),
            ('saves', 'mark', '60fps', 'rewards-encounters'): ('mark', 'saves'),
            ('battlespeed', '60fps', 'rewards-encounters'): (),
        }
        for labels, parent in cases.items():
            self.assertEqual(release.parent_labels(list(labels)), list(parent),
                             f'parent of {labels}')
        self.assertEqual(release.patch_name(['saves']), 'base-to-saves.xdelta')
        self.assertEqual(release.patch_name(['mark', '60fps']), 'mark-to-mark-60fps.xdelta')
        self.assertEqual(release.patch_name(['mark', 'saves']), 'mark-to-saves-mark.xdelta')
        self.assertEqual(release.patch_name(['saves', 'mark', '60fps']),
                         'saves-mark-to-saves-mark-60fps.xdelta')

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
                    Path(path).write_bytes(b'translation:' + ','.join(selected).encode())
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
                self.assertEqual(len(verified), 32)
                self.assertEqual(len(list(out.glob('*.xdelta'))), 33)
                self.assertFalse(list(out.glob('*.bin')))
                self.assertFalse(list((root / 'build/patch-work').glob('layer-*')))
                with (out / 'manifest.tsv').open() as f:
                    rows = {row['patch']: row for row in csv.DictReader(f, delimiter='\t')}
                self.assertEqual(len(rows), 33)
                self.assertEqual(rows['rev1-to-rev0.xdelta']['source_sha256'], release.sha256(rev1))
                base = rows['rev0-to-base.xdelta']
                self.assertEqual(base['source_sha256'], release.sha256(rev0))
                targets = {row['target_sha256'] for row in rows.values()}
                for name, row in rows.items():
                    if name == 'rev1-to-rev0.xdelta':
                        continue
                    self.assertIn(row['source_sha256'], targets,
                                  f'{name} must delta from a patch in the release')
                self.assertEqual(rows['mark-to-mark-60fps.xdelta']['source_sha256'],
                                 rows['base-to-mark.xdelta']['target_sha256'])
                self.assertEqual(rows['saves-mark-to-saves-mark-60fps.xdelta']['source_sha256'],
                                 rows['mark-to-saves-mark.xdelta']['target_sha256'])
                # the chain must actually carry each layer's content: decoding
                # it has to reproduce the known variant bytes exactly - this
                # pins the layer-source mixup that once made the saves delta
                # silently vanish from mark-to-saves-mark
                combo = {tuple(labels): selected
                         for labels, selected in release.combinations()}
                expected = {labels: b'translation:' + ','.join(combo[labels]).encode()
                            for labels in (('mark',), ('saves', 'mark'))}
                for labels in (('mark',), ('saves', 'mark')):
                    chain = []
                    current = list(labels)
                    while current:
                        chain.append(release.patch_name(current))
                        current = release.parent_labels(current)
                    chain.append('rev0-to-base.xdelta')
                    decoded = root / 'chain.bin'
                    source = rev0
                    for step in reversed(chain):
                        subprocess.run([tool, '-d', '-f', '-q', '-s', str(source),
                                        str(out / step), str(decoded)], check=True)
                        source = decoded
                    self.assertEqual(decoded.read_bytes(), expected[labels],
                                     f'chain to {labels}')
                conversion = out / 'rev1-to-rev0.xdelta'
                stamp = conversion.stat().st_mtime_ns
                release.build_release(rev0, rev1, out, tool)
                self.assertEqual(builder.call_count, 1, 'unchanged release must not rebuild')
                self.assertEqual(conversion.stat().st_mtime_ns, stamp)
                (out / 'mark-to-mark-60fps.xdelta').unlink()
                release.build_release(rev0, rev1, out, tool)
                self.assertEqual(builder.call_count, 2)
                self.assertEqual([sorted(v[0]) for v in builder.call_args.kwargs['variants_override']],
                                 [['60fps', 'mark']])
                self.assertEqual(conversion.stat().st_mtime_ns, stamp)
                (out / 'base-to-saves.xdelta').unlink()
                release.build_release(rev0, rev1, out, tool)
                self.assertEqual(builder.call_count, 3, 'layer children stay valid when only the root is rebuilt')
                self.assertEqual([sorted(v[0]) for v in builder.call_args.kwargs['variants_override']],
                                 [['saves']])
                paths = [path for _, path in builder.call_args.kwargs['variants_override']]
                self.assertEqual(len(paths), len(set(paths)),
                                 'each variant must write its own scratch image')
                self.assertEqual(conversion.stat().st_mtime_ns, stamp)
            self.assertFalse(list(root.glob('.persona-patches-*')))

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
