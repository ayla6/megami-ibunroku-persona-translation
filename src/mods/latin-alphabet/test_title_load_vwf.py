"""Execute the retail title's name writer with R3000 delay slots enabled."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
import toolpath  # noqa: E402,F401
import title_vwf
import smallfont_vwf
import smallfont_variants
import toolbelt
from mips_cpu import CPU, REG


class TitleNames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        title_vwf.build()
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        out = Path(cls.temporary.name)
        image = out / 'open.bin'
        asm = out / 'test.asm'
        asm.write_text(f'.psx\n.open "{ROOT / "data/psx/EXE/OPEN.EXE"}", "{image}", 0x8007F800\n'
                       '.include "../../latin-alphabet/asm/compat/retail_load_names.asm"\n.close\n')
        subprocess.run([str(ROOT / 'external_tools/armips/armips'), '-erroronwarning', str(asm)],
                       cwd=ROOT / 'src/mods/base/asm', check=True, capture_output=True)
        cls.image = image.read_bytes()
        page, _, _ = smallfont_vwf.disc_page()
        cls.metrics = smallfont_vwf.btl_orig_widths(
            smallfont_variants.original_metrics(page, smallfont_vwf.glyph_rows), smallfont_vwf.text_bits())

    def test_saved_name_metrics_uvs_bounds_and_repeated_calls(self):
        cpu = CPU()
        cpu.fill(0xA5)
        cpu.load(0x8007F800, self.image)
        text = bytes(toolbelt.smallfont_char(c) for c in 'WiMiW') + b'\xff'
        cpu.load(0x80060000, text)
        for repeat in range(2):
            cpu.r[REG['a0']], cpu.r[REG['a1']] = 3, 0x80060000
            cpu.r[REG['ra']] = 0x80000000
            cpu.start(0x800858E8)
            for _ in range(1000):
                if cpu.pc == 0x80000000:
                    break
                cpu.step()
            else:
                self.fail('name writer did not return')
            pen = 0x58
            for i, code in enumerate(text[:-1]):
                sprite = 0x80111484 + (3 * 34 + 25 + i) * 36
                metric = self.metrics[code]
                self.assertEqual(cpu.read(sprite + 4, 2), pen - (metric >> 4))
                self.assertEqual(cpu.read(sprite + 14, 1), (code % 31) * 8)
                self.assertEqual(cpu.read(sprite + 15, 1), (code // 31) * 12)
                self.assertEqual(cpu.read(sprite + 6, 2), 0xA5A5)
                pen += metric & 15
            untouched = 0x80111484 + (3 * 34 + 25 + len(text) - 1) * 36
            self.assertEqual(cpu.read(untouched + 4, 2), 0xA5A5)

    def test_title_font_page_matches_the_active_alphabet_gates(self):
        import menu_gfx
        import tim
        built = ROOT / 'build/OPEN.BIN'
        if not built.exists():
            self.skipTest('requires assembled title data')
        reference = (ROOT / 'data/psx/ADV/ADVCMD.BIN').read_bytes()
        image = tim.parse(reference, menu_gfx.PAGE)
        ref = smallfont_vwf.unpack_page(reference[image['at']:image['at'] + 128 * 256])
        original = (ROOT / 'data/psx/OPEN.BIN').read_bytes()
        start, width = menu_gfx.PAGE_COPIES['OPEN.BIN']
        length = width // 2 * menu_gfx.GLYPH_ROWS
        old = original[start:start + length]
        expected = smallfont_vwf.page_copy(smallfont_vwf.unpack_page(old), ref,
                                          smallfont_vwf.page_indices()[0], width,
                                          menu_gfx.GLYPH_ROWS)
        self.assertEqual(built.read_bytes()[start:start + length], expected)
