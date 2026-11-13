"""The incremental cache must never accept stale or partial outputs."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import build_step_cache as cache
import build


class StepCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()
        self.source = self.inputs / 'source'
        self.source.write_text('first')
        self.out = self.root / 'output'
        self.manifest = self.root / 'cache/manifest.tsv'
        self.calls = 0

    def action(self):
        self.calls += 1
        self.out.write_text(self.source.read_text())

    def run_step(self, context=()):
        return cache.run('test', [self.inputs], [self.out], self.action,
                         self.manifest, context=context)

    def test_reuses_only_identical_inputs_and_outputs(self):
        self.assertTrue(self.run_step())
        self.assertFalse(self.run_step())
        stamp = self.source.stat().st_mtime_ns
        self.source.write_text('other')
        os.utime(self.source, ns=(stamp, stamp))
        self.assertTrue(self.run_step())
        self.out.write_text('tampered')
        self.assertTrue(self.run_step())
        self.out.unlink()
        self.assertTrue(self.run_step())
        self.assertEqual(self.calls, 4)

    def test_context_and_new_files_invalidate(self):
        self.run_step(('one',))
        self.assertTrue(self.run_step(('two',)))
        (self.inputs / 'new').write_text('new')
        self.assertTrue(self.run_step(('two',)))

    def test_manifest_records_source_hashes_and_forced_build_refreshes_it(self):
        self.run_step()
        import hashlib
        self.assertIn(f'source\t{self.source}\t{hashlib.sha1(b"first").hexdigest()}',
                      self.manifest.read_text())
        self.assertTrue(cache.run('test', [self.inputs], [self.out], self.action,
                                  self.manifest, reuse=False))
        self.assertEqual(self.calls, 2)

    def test_inputs_changing_during_action_are_not_cached(self):
        def mutate():
            self.action()
            self.source.write_text('changed during build')
        cache.run('test', [self.inputs], [self.out], mutate, self.manifest)
        self.assertTrue(self.run_step())

    def test_failure_and_missing_outputs_never_cache(self):
        self.run_step()
        self.source.write_text('changed')
        def fail():
            self.out.write_text('partial')
            raise RuntimeError('failed')
        with self.assertRaises(RuntimeError):
            cache.run('test', [self.inputs], [self.out], fail, self.manifest)
        self.assertTrue(self.run_step())
        self.out.unlink()
        with self.assertRaisesRegex(RuntimeError, 'did not produce'):
            cache.run('test', [self.inputs], [self.out], lambda: None, self.manifest)

    def test_build_fmv_stage_reuses_only_complete_artifacts(self):
        (self.root / 'src').mkdir()
        (self.root / 'translation').mkdir()
        (self.root / 'build').mkdir()
        (self.root / 'src' / 'input').write_text('one')
        outputs = [self.root / 'build' / f'movie_subs{suffix}.bin' for suffix in
                   ('_data', '_open_data', '_end_data', '_tex', '_open_tex', '_end_tex',
                    '_zoom', '_open_zoom', '_end_zoom')]
        def produce(*_args):
            for output in outputs:
                output.write_bytes(b'result')
        with patch.object(build, 'ROOT', str(self.root)), patch.object(build, 'run', side_effect=produce) as runner:
            build.prepare_fmv_data(sys.executable, incremental=True)
            build.prepare_fmv_data(sys.executable, incremental=True)
            self.assertEqual(runner.call_count, 1)
            outputs[0].write_bytes(b'wrong')
            build.prepare_fmv_data(sys.executable, incremental=True)
            self.assertEqual(runner.call_count, 2)
            build.prepare_fmv_data(sys.executable, incremental=False)
            self.assertEqual(runner.call_count, 3)


if __name__ == '__main__':
    unittest.main()
