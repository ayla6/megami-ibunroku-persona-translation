"""The EBOOT twin plan reproduces the boot-string porters without PSP-JP."""
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
import boot_btlmsg
import btlmsg
import control_consumer
import eboot_twin_plan as plan
import notice_consumer
import port_btlbanner
import port_btlneg
import reward_notice
import source_plan
import toolbelt

DEFAULT_ZONE = btlmsg.ZONE


def run_all():
    btlmsg.ZONE = DEFAULT_ZONE
    calls = []
    out = io.StringIO()
    with patch.object(toolbelt, 'upsert_generated',
                      side_effect=lambda rel, rows: calls.append((rel, list(rows))) or len(rows)), \
            patch.object(toolbelt, 'route_over', side_effect=lambda *a: None), \
            patch.object(toolbelt, 'unport', side_effect=lambda *a: None), \
            contextlib.redirect_stdout(out):
        boot_btlmsg.main()
        port_btlneg.port(apply=True)
        port_btlbanner.port(apply=True)
    return calls, out.getvalue()


def guard_jp(read):
    def guarded(region, *args, **kwargs):
        if region in ('jp', 'psp_jp'):
            raise AssertionError('PSP-JP was read')
        return read(region, *args, **kwargs)
    return guarded


class EbootTwinPlan(unittest.TestCase):
    def tearDown(self):
        os.environ.pop(plan.REPLAY_ENV, None)
        os.environ.pop(reward_notice.REPLAY_ENV, None)
        plan._loaded = plan._loaded_path = None
        plan._us = None
        reward_notice._loaded = reward_notice._loaded_path = None

    @unittest.skipUnless(plan.PLAN.exists() and (ROOT / 'data/psp_jp').exists()
                         and (ROOT / 'data/psp_us').exists()
                         and (ROOT / 'data/psx/BTLP.BIN').exists(),
                         'requires source plan and both extracted source regions')
    def test_replay_matches_two_region_run_without_reading_psp_jp(self):
        original = run_all()
        os.environ[plan.REPLAY_ENV] = str(plan.PLAN)
        os.environ[reward_notice.REPLAY_ENV] = str(reward_notice.PLAN)
        read_eboot = toolbelt.read_eboot
        read_extracted = toolbelt.read_extracted
        import match_jp
        with patch.object(toolbelt, 'read_eboot', side_effect=guard_jp(read_eboot)), \
                patch.object(toolbelt, 'read_extracted',
                             side_effect=guard_jp(read_extracted)), \
                patch.object(notice_consumer, 'derive',
                             side_effect=AssertionError('PSP-JP notice proof')), \
                patch.object(control_consumer, 'derive',
                             side_effect=AssertionError('PSP-JP control proof')), \
                patch.object(match_jp, 'exact_twins',
                             side_effect=AssertionError('PSP-JP twins')), \
                patch.object(match_jp, 'us_twin',
                             side_effect=AssertionError('PSP-JP US twin')), \
                patch.object(match_jp, 'unanimous_twin',
                             side_effect=AssertionError('PSP-JP unanimous twin')):
            replay = run_all()
        self.assertEqual(replay, original)
        self.assertTrue(plan.PLAN.read_bytes().isascii())

    @unittest.skipUnless(plan.PLAN.exists() and (ROOT / 'data/psx/BTLP.BIN').exists(),
                         'requires source plan and BTLP.BIN')
    def test_capture_ignores_ephemeral_filled_rows(self):
        """generated/ must not shrink the captured decision domain."""
        calls = {}
        with patch.object(plan, 'begin_capture'), patch.object(plan, 'write'), \
                patch.object(boot_btlmsg, 'main'), \
                patch.object(port_btlneg, 'port',
                             side_effect=lambda **kw: calls.setdefault('btlneg', kw)), \
                patch.object(port_btlbanner, 'port',
                             side_effect=lambda **kw: calls.setdefault('banner', kw)):
            plan.capture()
        self.assertEqual(calls['btlneg'], {'apply': False, 'force': True})
        self.assertEqual(calls['banner'], {'apply': False})

    def test_missing_twin_decision_fails_the_port(self):
        metadata, matches = source_plan.read(plan.PLAN)
        matches = matches[1:]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'plan.tsv'
            source_plan.write(path, metadata, matches)
            os.environ[plan.REPLAY_ENV] = str(path)
            with self.assertRaisesRegex(plan.PlanError, 'no decision'):
                run_all()


if __name__ == '__main__':
    unittest.main()
