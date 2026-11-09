"""The battle-dialogue plan reproduces the two-region port without PSP-JP."""
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
import re
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/injection_tools'), str(ROOT / 'src/extraction_tools/psp')]
import btlevt_port_plan as plan
import port_btlevt
import source_plan
import btlevt
import etext
import toolbelt
import vwf_wrap


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

    @unittest.skipUnless((ROOT / 'data/psp_jp').exists()
                         and (ROOT / 'data/psp_us').exists()
                         and (ROOT / 'data/psx/BTLP.BIN').exists(),
                         'requires both PSP regions and BTLP.BIN')
    def test_every_ported_battle_message_keeps_source_controls_and_words(self):
        data = btlevt.data()
        psx = [(a - btlevt.B, etext.decode(data[a - btlevt.B:e - btlevt.B - 2]))
               for a, e in btlevt.messages(data)]
        units = port_btlevt.us_units()
        sources, _ = port_btlevt.plan_sources(psx, port_btlevt.jp_units(), units)
        rows = {r['pos']: r['en'] for r in toolbelt.read_generated('BTLP')}

        def content(text):
            # Layout is allowed to place line breaks and change word gaps,
            # but semantic control order and all visible characters survive.
            text = re.sub(r'<FFF6>', '', text)
            return re.sub(r'\s+', '', text)

        checked = 0
        for src in sources:
            if src['kind'] != 'ok':
                continue
            speaker, segs = port_btlevt.us_flow(units, src['lo'], src['hi'], src['speaker'])
            if src['cut'] == 'leading':
                leading, sep, _ = segs[0].partition('<FF05>')
                segs = [leading + sep]
            elif src['cut'] == 'tail' and '<FF05>' in segs[0]:
                segs = [segs[0].split('<FF05>', 1)[1]] + segs[1:]
            source = port_btlevt.compose(segs, speaker or src['speaker'])
            actual = rows[hex(src['off'])]
            with self.subTest(pos=hex(src['off'])):
                self.assertEqual(content(actual), content(source))
                pages = actual.split('<FFFB><FFF7>')
                for page in pages:
                    lines = page.split('<FFF6>')
                    self.assertLessEqual(len(lines), 4)
                    for line in lines:
                        self.assertLessEqual(vwf_wrap.text_width(line), 240)
            checked += 1
        self.assertGreaterEqual(checked, 90)

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
