"""Assemble the real 60fps block against changing dialogue-glue sizes."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DngQolLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.armips = ROOT / 'external_tools/armips/armips'
        if not cls.armips.exists():
            cls.armips = shutil.which('armips')
        if not cls.armips:
            raise unittest.SkipTest('requires armips')

    def assemble(self, glue_end):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / 'fixture.asm').write_text(
                '.psx\n'
                f'.include "{ROOT / "src/asm/common/addresses.inc"}"\n'
                f'dng_glue_end equ {glue_end:#x}\n'
                '.create "fixture.bin", 0x800643C4\n'
                f'.include "{ROOT / "src/asm/qol/fps60_dng.asm"}"\n'
                '.close\n')
            result = subprocess.run([str(self.armips), 'fixture.asm', '-sym2', 'fixture.sym'],
                                    cwd=directory, capture_output=True, text=True)
            symbols = {}
            if result.returncode == 0:
                for line in (directory / 'fixture.sym').read_text().splitlines():
                    match = re.fullmatch(r'([0-9a-fA-F]{8}) (\w+)', line)
                    if match:
                        symbols[match[2]] = int(match[1], 16)
            return result, symbols

    def test_tracks_aligned_glue_end_including_reported_overlap(self):
        for glue_end in (0x800A1574, 0x800A1628, 0x800A1700, 0x800A1A40):
            with self.subTest(glue_end=hex(glue_end)):
                result, symbols = self.assemble(glue_end)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                start = (glue_end + 15) & ~15
                self.assertEqual(symbols['dngq_frame_sync'], start)
                self.assertGreaterEqual(start, glue_end)
                self.assertLessEqual(start + 0x5C0, 0x800A2000)
                self.assertLess(symbols['dngq_vars'] + 0x54, start + 0x5C0)

    def test_growth_into_spill_window_still_fails_closed(self):
        result, _ = self.assemble(0x800A1A41)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('frame glue overlaps the dungeon spill window', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
