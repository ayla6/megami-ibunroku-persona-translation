"""S2D source plans retain correspondences, never Japanese text."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/extraction_tools/matching'),
                str(ROOT / 'src/injection_tools'), str(ROOT / 'src/extraction_tools/psp')]
import port_s2d
import s2d
import s2d_port_plan as plan
import toolbelt


class SourcePlan(unittest.TestCase):
    @unittest.skipUnless(plan.PLAN.exists() and (ROOT / 'data/psx/S2D.BIN').exists()
                         and (ROOT / 'data/extracted_text/psp_jp/EBOOT.tsv').exists()
                         and (ROOT / 'data/extracted_text/psp_us/EBOOT.tsv').exists(),
                         'requires both extracted source regions to compare')
    def test_replay_matches_two_region_port_without_reading_psp_jp(self):
        original = port_s2d.port(False, force=True, strict=True)
        read = toolbelt.read_extracted
        def no_jp(region, *args, **kwargs):
            if region == 'psp_jp':
                raise AssertionError('PSP-JP text was read')
            return read(region, *args, **kwargs)
        with patch.object(toolbelt, 'read_extracted', side_effect=no_jp), \
                patch.object(plan.tables, 'jp_boot', side_effect=AssertionError('JP BOOT read')):
            replay = port_s2d.port(False, force=True, without_psp_jp=True, strict=True)
        by_pos = lambda rows: {r['pos']: (r['psp'], r['en']) for r in rows}
        self.assertEqual(by_pos(replay), by_pos(original))
        self.assertTrue(plan.PLAN.read_bytes().isascii())

    @unittest.skipUnless(plan.PLAN.exists() and (ROOT / 'data/psx/S2D.BIN').exists()
                         and (ROOT / 'data/extracted_text/psp_us/EBOOT.tsv').exists(),
                         'requires source plan, PSX and PSP-US')
    def test_missing_or_corrupted_matches_fail_instead_of_losing_rows(self):
        data = s2d.data()
        boxes = s2d.script_boxes(data)
        lines = plan.PLAN.read_text(encoding='utf-8').splitlines(keepends=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'plan.tsv'
            path.write_text(''.join(lines[:-1]), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'missing or damaged'):
                plan.replay(data, boxes, set(), path)
            meta, matches = plan.source_plan.read(plan.PLAN)
            meta['psx_sha1'] = '0' * 40
            plan.source_plan.write(path, meta, matches)
            with self.assertRaisesRegex(ValueError, 'PSX input'):
                plan.replay(data, boxes, set(), path)


if __name__ == '__main__':
    unittest.main()
