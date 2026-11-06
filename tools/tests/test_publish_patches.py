"""Patch release publication: the completeness gate, the archive, the GitHub
upload target and the local webpatcher/patches copy. The site itself is
deployed by .github/workflows/pages.yml, not by this script."""

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class LocalSyncTest(unittest.TestCase):

    def test_symlink_to_the_release_directory_is_left_alone(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import publish_patches

        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / 'webpatcher'
            dist = Path(tmp) / 'dist'
            site.mkdir()
            dist.mkdir()
            (dist / 'manifest.tsv').write_text('release')
            (site / 'patches').symlink_to(dist, target_is_directory=True)
            with patch.object(publish_patches, 'SITE', site), \
                    patch.object(publish_patches, 'DIST', dist):
                publish_patches.sync_local_patches()
            self.assertTrue((site / 'patches').is_symlink())
            self.assertEqual((site / 'patches' / 'manifest.tsv').read_text(),
                             'release')
            features = (site / 'features.js').read_text(encoding='utf-8')
            self.assertIn('globalThis.FEATURES = ', features)
            self.assertIn('"saves"', features)


class PublishArgsTest(unittest.TestCase):
    """Publishing uploads a release by default and must be switchable off
    without touching gh, git or the network."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import publish_patches
        self.publish = publish_patches

    def test_release_uploads_by_default_and_no_release_turns_it_off(self):
        self.assertTrue(self.publish.parse_args([]).release)
        self.assertFalse(self.publish.parse_args(['--no-release']).release)
        self.assertIsNone(self.publish.parse_args([]).tag)


class PublishArchiveTest(unittest.TestCase):
    """The release is one zip of the release files; build_patches.py
    --publish-release goes through the same publish() path."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import publish_patches
        self.publish = publish_patches

    def test_archive_holds_every_release_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / 'patches'
            dist.mkdir()
            (dist / 'manifest.tsv').write_text('manifest')
            (dist / 'README.txt').write_text('readme')
            (dist / 'a.xdelta').write_bytes(b'patch')
            archive = Path(tmp) / self.publish.ARCHIVE_NAME
            self.publish.write_archive(archive, dist)
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(sorted(bundle.namelist()),
                                 ['README.txt', 'a.xdelta', 'manifest.tsv'])
                for info in bundle.infolist():
                    self.assertEqual(info.external_attr >> 16, 0o100644,
                                     f'{info.filename} is not world-readable')

    def test_publish_uploads_then_syncs_the_given_directory(self):
        # build_patches.py --output must publish that directory, not the
        # default dist/patches.
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            with patch.object(self.publish, 'release_is_complete',
                              return_value=True) as complete, \
                    patch.object(self.publish, 'upload_release') as upload, \
                    patch.object(self.publish, 'sync_local_patches') as sync:
                tag = self.publish.publish(tag='patches-test',
                                           directory=output)
        self.assertEqual(tag, 'patches-test')
        complete.assert_called_once_with(output)
        upload.assert_called_once_with('patches-test', output)
        sync.assert_called_once_with(output)

    def test_replacing_an_existing_release_redeploys_the_site(self):
        # A new release fires the workflow's release trigger; clobbering an
        # existing one fires nothing, so publish() dispatches the workflow.
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            for uploaded, expected in (('updated', 1), ('created', 0)):
                with patch.object(self.publish, 'release_is_complete',
                                  return_value=True), \
                        patch.object(self.publish, 'upload_release',
                                     return_value=uploaded), \
                        patch.object(self.publish, 'deploy_site') as deploy, \
                        patch.object(self.publish, 'sync_local_patches'):
                    self.publish.publish(tag='patches-test', directory=output)
                self.assertEqual(deploy.call_count, expected, uploaded)

    def test_release_upload_targets_the_repository_the_page_reads(self):
        calls = []

        def fake_run(*cmd, capture=False):
            calls.append(cmd)
            if cmd[:2] == ('gh', 'repo'):
                return 'name'
            if 'view' in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            return ''

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(self.publish, 'release_files',
                             return_value=[]), \
                patch.object(self.publish, 'write_archive',
                             return_value=Path(tmp) / 'a.zip'), \
                patch.object(self.publish, 'run', side_effect=fake_run):
            self.publish.upload_release('patches-test')
        repo_view = [cmd for cmd in calls if cmd[:2] == ('gh', 'repo')]
        self.assertEqual(repo_view[0][3], self.publish.GITHUB_REPO)
        release_calls = [cmd for cmd in calls if cmd[1] == 'release']
        self.assertTrue(release_calls)
        for cmd in release_calls:
            self.assertEqual(cmd[cmd.index('--repo') + 1],
                             self.publish.GITHUB_REPO)
        # the release carries the zip and nothing else: individual files
        # go out inside it, and the Pages workflow unpacks them
        for cmd in release_calls:
            if 'upload' not in cmd and 'create' not in cmd:
                continue
            paths = [arg for arg in cmd if arg.endswith(('.xdelta', '.tsv',
                                                         '.txt', '.zip'))]
            self.assertEqual(paths, [str(Path(tmp) / 'a.zip')], cmd)

    def test_completeness_requires_one_row_per_patch_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            self.assertFalse(self.publish.release_is_complete(output))
            manifest = output / 'manifest.tsv'
            header = ('patch\tadds\tanchor\torder\tchoices\tverify\t'
                      'source_sha256\ttarget_sha256\tproof_choices\t'
                      'proof_sha256\n')
            manifest.write_text(header + '\n'.join(
                f'p{i}.xdelta\t\t\t{i}\t\t\t\t\t\t' for i in range(11)) + '\n')
            self.assertFalse(self.publish.release_is_complete(output),
                             'eleven patch files are not a release')
            manifest.write_text(header + '\n'.join(
                f'p{i}.xdelta\t\t\t{i}\t\t\t\t\t\t' for i in range(12)) + '\n')
            self.assertTrue(self.publish.release_is_complete(output))
            # the per-combination manifest repeats patch names; it is not a
            # complete release of this layout
            manifest.write_text(header + '\n'.join(
                f'p{i % 11}.xdelta\t\t\t{i % 11}\t\t\t\t\t\t'
                for i in range(513)) + '\n')
            self.assertFalse(self.publish.release_is_complete(output))
            # the old per-combination header is refused outright
            manifest.write_text(
                'patch\tchoices\tsource_sha256\ttarget_sha256\n'
                + '\n'.join(f'p{i}.xdelta\t\t\ta{i}' for i in range(12))
                + '\n')
            self.assertFalse(self.publish.release_is_complete(output))

    def test_missing_release_repository_stops_before_the_archive(self):
        def failing_run(*cmd, capture=False):
            raise subprocess.CalledProcessError(1, cmd)

        with patch.object(self.publish, 'run', side_effect=failing_run), \
                patch.object(self.publish, 'write_archive') as archive:
            with self.assertRaises(SystemExit):
                self.publish.upload_release('patches-test')
        archive.assert_not_called()

    def test_incomplete_release_is_refused_before_upload(self):
        with patch.object(self.publish, 'release_is_complete',
                          return_value=False), \
                patch.object(self.publish, 'upload_release') as upload:
            with self.assertRaises(SystemExit):
                self.publish.publish(tag='patches-test')
        upload.assert_not_called()


if __name__ == '__main__':
    unittest.main()
