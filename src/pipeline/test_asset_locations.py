"""Authored patch assets and generated mappings have distinct owners."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import toolbelt
import smallfont_vwf
import fmv_subgen


class AssetLocations(unittest.TestCase):
    def test_generated_mappings_live_with_translation(self):
        self.assertEqual(Path(toolbelt.MAPPINGS),
                         ROOT / 'translation' / 'generated_mappings')
        self.assertEqual(Path(toolbelt.SOURCE_MAPPINGS),
                         ROOT / 'src' / 'porting')

    def test_authored_small_font_sheet_is_in_source(self):
        self.assertEqual(Path(smallfont_vwf.SHEET),
                         ROOT / 'src' / 'mods' / 'latin-alphabet' / 'assets' / 'fonts' / 'smallfont_page_modified.png')
        self.assertTrue(Path(smallfont_vwf.SHEET).is_file())

    def test_fmv_assets_are_in_source(self):
        self.assertEqual(Path(fmv_subgen.FMV_DIR), ROOT / 'src' / 'mods' / 'fmv-translation' / 'assets')
        self.assertTrue((Path(fmv_subgen.FMV_DIR) / 'MV1C.png').is_file())


if __name__ == '__main__':
    unittest.main()
