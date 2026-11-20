"""Text-free dungeon matches reproduce the full PSP-JP matching pass."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import dng_port_plan as plan
import port_dng


class DungeonSourcePlan(unittest.TestCase):
    def test_quote_style_does_not_displace_a_verified_anchor(self):
        source = 'It isn’t open.'
        with patch.object(port_dng, 'boxes', return_value=[(16, 'A different box.'), (32, source)]):
            self.assertEqual(port_dng.us_near('test', 16, "isn't open"), ('test', 32, source))

    def test_missing_anchor_rejects_a_nearby_unrelated_box(self):
        with patch.object(port_dng, 'boxes', return_value=[(16, 'A different box.')]) as boxes:
            with self.assertRaisesRegex(ValueError, 'anchor .* is missing'):
                port_dng.us_near('test', 16, "isn't open")
        boxes.assert_called_once_with('us', 'test')

    @unittest.skipUnless(plan.PLAN.exists() and
                         (ROOT / 'data/psp_jp/PSP_GAME/USRDIR/pack/dng').exists() and
                         (ROOT / 'data/psp_us/PSP_GAME/USRDIR/pack/dng').exists(),
                         'requires both PSP dungeon trees to compare')
    def test_replay_matches_two_region_port_without_reading_psp_jp(self):
        original, surface = port_dng.port(False, strict=True)
        read = port_dng.boxes
        def no_jp(region, *args, **kwargs):
            if region == 'jp':
                raise AssertionError('PSP-JP dungeon text was read')
            return read(region, *args, **kwargs)
        with patch.object(port_dng, 'boxes', side_effect=no_jp):
            replay, replay_surface = port_dng.port(False, strict=True, without_psp_jp=True)
        self.assertEqual(replay_surface, surface)
        self.assertEqual(replay, original)
        self.assertTrue(plan.PLAN.read_bytes().isascii())

    @unittest.skipUnless(plan.PLAN.exists() and
                         (ROOT / 'data/psp_us/PSP_GAME/USRDIR/pack/dng').exists(),
                         'requires source plan, PSX and PSP-US')
    def test_damaged_plan_is_refused_before_any_rows_are_written(self):
        import dngpacks
        surface = {}
        for rel, path in dngpacks.pack_files():
            if len(Path(rel).name) == 3:
                for off, _length, ja in dngpacks.boxes(Path(path).read_bytes()):
                    surface.setdefault(rel, []).append((hex(off), ja))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'plan.tsv'
            lines = plan.PLAN.read_text(encoding='utf-8').splitlines(keepends=True)
            path.write_text(''.join(lines[:-1]), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'missing or damaged'):
                plan.replay(surface, path)


if __name__ == '__main__':
    unittest.main()
