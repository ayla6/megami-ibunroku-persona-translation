"""The battle-dialogue plan reproduces the two-region port without PSP-JP."""
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/injection_tools'), str(ROOT / 'src/extraction_tools/psp')]
import btlevt_port_plan as plan
import port_btlevt
import source_plan


def run_port():
    calls = {}
    with patch.object(sys, 'argv', ['port_btlevt.py', '--apply']), \
            patch.object(port_btlevt.toolbelt, 'upsert_generated',
                         side_effect=lambda rel, rows: calls.setdefault('rows', list(rows)) or len(rows)), \
            patch.object(port_btlevt.toolbelt, 'route_over',
                         side_effect=lambda *a: calls.setdefault('over', []).append(a)), \
            patch.object(port_btlevt.toolbelt, 'route_gaps',
                         side_effect=lambda *a: calls.setdefault('gaps', []).append(a)), \
            contextlib.redirect_stdout(io.StringIO()):
        port_btlevt.main()
    return calls


def no_jp_read(read):
    def guarded(region, *args, **kwargs):
        if region == 'psp_jp':
            raise AssertionError('PSP-JP text was read')
        return read(region, *args, **kwargs)
    return guarded


class BattleSourcePlan(unittest.TestCase):
    def tearDown(self):
        os.environ.pop(plan.REPLAY_ENV, None)

    @unittest.skipUnless(plan.PLAN.exists() and (ROOT / 'data/psp_jp').exists()
                         and (ROOT / 'data/psp_us').exists()
                         and (ROOT / 'data/psx/BTLP.BIN').exists(),
                         'requires source plan and both extracted source regions')
    def test_replay_matches_two_region_port_without_reading_psp_jp(self):
        original = run_port()
        os.environ[plan.REPLAY_ENV] = str(plan.PLAN)
        read = port_btlevt.toolbelt.read_extracted
        with patch.object(port_btlevt, 'jp_units', side_effect=AssertionError('PSP-JP units')), \
                patch.object(port_btlevt.toolbelt, 'read_extracted', side_effect=no_jp_read(read)):
            replay = run_port()
        self.assertEqual(replay.get('rows'), original.get('rows'))
        self.assertEqual(replay.get('over'), original.get('over'))
        self.assertEqual(replay.get('gaps'), original.get('gaps'))
        self.assertTrue(plan.PLAN.read_bytes().isascii())

    @unittest.skipUnless(plan.PLAN.exists() and (ROOT / 'data/psx/BTLP.BIN').exists(),
                         'requires source plan and BTLP.BIN')
    def test_missing_message_decision_fails_the_port(self):
        _metadata, matches = source_plan.read(plan.PLAN)
        matches.pop()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'plan.tsv'
            source_plan.write(path, _metadata, matches)
            os.environ[plan.REPLAY_ENV] = str(path)
            with self.assertRaisesRegex(plan.PlanError, 'does not cover every'):
                run_port()


if __name__ == '__main__':
    unittest.main()
