"""Cached products must survive configuration switches and detect corruption."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import toolpath  # noqa: E402,F401
import file_digest
import materialized_cache as cache


class MaterializedCache(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.write_text('input')
        self.output = self.root / 'output'
        self.extra = self.root / 'extra'
        self.calls = 0

    def run_step(self, context='a', fail=False):
        def action():
            self.calls += 1
            self.output.write_text(context + self.source.read_text())
            if context == 'b':
                self.extra.write_text('extra')
            if fail:
                raise RuntimeError('interrupted')
        return cache.run('test', [self.source],
                         lambda: [self.output] + ([self.extra] if context == 'b' else []),
                         action, self.root / 'cache', context=(context,))

    def test_hit_restore_and_context_switch(self):
        self.assertTrue(self.run_step())
        self.assertFalse(self.run_step())
        self.output.unlink()
        self.assertFalse(self.run_step())
        self.output.write_text('corrupt live file')
        self.assertFalse(self.run_step())
        self.assertTrue(self.run_step('b'))
        self.assertFalse(self.run_step())
        self.assertEqual(self.output.read_text(), 'ainput')
        self.assertFalse(self.extra.exists())
        self.assertEqual(self.calls, 2)

    def test_corrupt_blob_and_changed_input_rebuild(self):
        self.run_step()
        blob = next((self.root / 'cache/blobs').iterdir())
        blob.write_text('corrupt')
        self.assertTrue(self.run_step())
        stamp = self.source.stat().st_mtime_ns
        self.source.write_text('other')
        os.utime(self.source, ns=(stamp, stamp))
        self.assertTrue(self.run_step())
        self.assertEqual(self.output.read_text(), 'aother')

    def test_failure_never_commits(self):
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            self.run_step(fail=True)
        self.assertTrue(self.run_step())

    def test_identical_hit_does_not_rewrite_manifest(self):
        self.run_step()
        active = self.root / 'cache/active.tsv'
        before = active.stat().st_mtime_ns
        self.run_step()
        self.assertEqual(active.stat().st_mtime_ns, before)

    def test_persistent_digest_checks_ctime_and_reuses_disk_record(self):
        with patch.object(file_digest, 'CACHE', self.root / 'digests.tsv'), \
             patch.object(file_digest, '_records', None), patch.object(file_digest, '_dirty', False):
            first = file_digest.digest(self.source)
            file_digest.flush()
            file_digest._records = None
            file_digest.records()
            with patch.object(Path, 'open', side_effect=AssertionError('reread')):
                self.assertEqual(file_digest.digest(self.source), first)
            stamp = self.source.stat().st_mtime_ns
            self.source.write_text('other')
            os.utime(self.source, ns=(stamp, stamp))
            self.assertNotEqual(file_digest.digest(self.source), first)
