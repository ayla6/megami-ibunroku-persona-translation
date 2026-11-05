"""Frozen story decisions reproduce the two-region port without PSP-JP text."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/injection_tools'), str(ROOT / 'src/extraction_tools/psp')]
import match_jp
import port_story
import source_plan
import story_port_plan as plan


def convert_all():
    out = []
    for name in ('E0', 'E1', 'E2', 'E3'):
        for index in range(len(port_story.psx_entries(name))):
            out.append((name, index) + tuple(port_story.convert_entry(name, index)))
    return out


class StorySourcePlan(unittest.TestCase):
    def tearDown(self):
        os.environ.pop(plan.REPLAY_ENV, None)
        plan._plan = None

    def replay(self, path=None):
        os.environ[plan.REPLAY_ENV] = str(path or plan.PLAN)
        plan._plan = None
        load = port_story.load_psp
        def no_jp(*args, **kwargs):
            raise AssertionError('PSP-JP accessed: ' + repr(args[:2]))
        def load_us(which, region='jp'):
            if region == 'jp':
                no_jp(which, region)
            return load(which, region)
        return patch.object(port_story, 'jsp_entries', side_effect=no_jp), \
            patch.object(port_story, 'load_psp', side_effect=load_us), \
            patch.object(match_jp, 'psx_id_twin', side_effect=no_jp), \
            patch.object(match_jp, 'us_twin', side_effect=no_jp)

    @unittest.skipUnless(plan.PLAN.exists() and (ROOT / 'data/psp_jp').exists()
                         and (ROOT / 'data/psp_us').exists()
                         and (ROOT / 'data/psx/ADV/E0.BIN').exists(),
                         'requires source plan and both extracted source regions')
    def test_replay_matches_two_region_port_without_reading_psp_jp(self):
        original = convert_all()
        guards = self.replay()
        with guards[0], guards[1], guards[2], guards[3]:
            replay = convert_all()
        self.assertEqual(replay, original)
        self.assertTrue(plan.PLAN.read_bytes().isascii())

    @unittest.skipUnless(plan.PLAN.exists() and (ROOT / 'data/psx/ADV/E0.BIN').exists(),
                         'requires source plan and PSX scripts')
    def test_missing_decision_is_refused_not_silently_flagged(self):
        metadata, matches = source_plan.read(plan.PLAN)
        speaker = next(i for i, row in enumerate(matches)
                       if row['us_sub'] == 'arbitrate')
        dropped = matches.pop(speaker)
        name, index = dropped['rel'], int(dropped['pos'].split(':')[0])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'plan.tsv'
            source_plan.write(path, metadata, matches)
            guards = self.replay(path)
            with guards[0], guards[1], guards[2], guards[3], \
                    self.assertRaisesRegex(ValueError, 'no speaker decision'):
                port_story.convert_entry(name, index)


if __name__ == '__main__':
    unittest.main()
