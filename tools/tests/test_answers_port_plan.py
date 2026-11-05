"""The answer plan reproduces the two-region port without PSP-JP."""
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
import answers_port_plan as plan
import port_answers
import source_plan
import text


def run():
    calls = {'upsert': [], 'over': [], 'gaps': [], 'manual': []}

    def remember(bucket, *args):
        calls[bucket].append(args)
        return len(args[-1]) if bucket == 'upsert' else None

    with patch.object(port_answers.toolbelt, 'upsert_generated',
                      side_effect=lambda rel, rows: remember('upsert', rel, list(rows))), \
            patch.object(port_answers.toolbelt, 'route_over',
                         side_effect=lambda *a: remember('over', *a)), \
            patch.object(port_answers.toolbelt, 'route_gaps',
                         side_effect=lambda *a: remember('gaps', *a)), \
            patch.object(port_answers.toolbelt, 'write_manual',
                         side_effect=lambda *a: remember('manual', *a)), \
            contextlib.redirect_stdout(io.StringIO()):
        rows = port_answers.collect(apply=True)
    calls['rows'] = rows
    return calls


def guard_jp(fn):
    def guarded(*args, **kwargs):
        region = args[1] if len(args) > 1 else kwargs.get('region')
        if region in ('jp', 'psp_jp'):
            raise AssertionError('PSP-JP text was read')
        return fn(*args, **kwargs)
    return guarded


class AnswerSourcePlan(unittest.TestCase):
    def tearDown(self):
        os.environ.pop(plan.REPLAY_ENV, None)
        plan._loaded = plan._loaded_path = None

    @unittest.skipUnless(plan.PLAN.exists() and (ROOT / 'data/psp_jp').exists()
                         and (ROOT / 'data/psp_us').exists()
                         and (ROOT / 'data/psx/TALK').exists(),
                         'requires source plan and both extracted source regions')
    def test_replay_matches_two_region_port_without_reading_psp_jp(self):
        original = run()
        os.environ[plan.REPLAY_ENV] = str(plan.PLAN)
        read_extracted = port_answers.toolbelt.read_extracted
        with patch.object(port_answers, 'load_talk_slots',
                          side_effect=guard_jp(text.load_talk_slots)), \
                patch.object(text, 'load_talk_slots',
                             side_effect=guard_jp(text.load_talk_slots)), \
                patch.object(port_answers.toolbelt, 'read_extracted',
                             side_effect=guard_jp(read_extracted)), \
                patch.object(port_answers, 'psp_answer_slots',
                             side_effect=AssertionError('PSP-JP answer slots')), \
                patch.object(port_answers, 'slot_spellings',
                             side_effect=AssertionError('PSP-JP spellings')), \
                patch.object(port_answers, 'same_slot_pairs',
                             side_effect=AssertionError('PSP-JP slot pairs')):
            replay = run()
        self.assertEqual(replay['rows'], original['rows'])
        self.assertEqual(replay['upsert'], original['upsert'])
        self.assertEqual(replay['over'], original['over'])
        self.assertEqual(replay['gaps'], original['gaps'])
        self.assertTrue(plan.PLAN.read_bytes().isascii())

    @unittest.skipUnless(plan.PLAN.exists() and (ROOT / 'data/psx/TALK').exists(),
                         'requires source plan and PSX talk data')
    def test_missing_answer_decision_fails_the_port(self):
        metadata, matches = source_plan.read(plan.PLAN)
        matches = [r for r in matches if not (r['mode'] == 'answer'
                                              and r['split'] != 'miss')]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'plan.tsv'
            source_plan.write(path, metadata, matches)
            os.environ[plan.REPLAY_ENV] = str(path)
            with self.assertRaisesRegex(plan.PlanError, 'no answer source'):
                run()


if __name__ == '__main__':
    unittest.main()
