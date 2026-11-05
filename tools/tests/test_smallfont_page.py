"""Small-font page ownership: python -m unittest discover -s tools/tests -p test_smallfont_page.py."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import smallfont_vwf as sf


class PageImport(unittest.TestCase):
    def setUp(self):
        self.width = 256
        self.palette = [(i * 16, i * 16, i * 16) for i in range(16)]
        self.disc = bytearray(i % 16 for i in range(self.width ** 2))
        self.sheet = Image.new('RGB', (self.width, self.width), self.palette[3])
        for target, name, kwargs in (
                (sf, 'disc_page', {'return_value': (self.disc, self.palette, self.width)}),
                (sf.features, 'on', {'return_value': True}),
                (sf.os.path, 'exists', {'return_value': True}),
                (Image, 'open', {'side_effect': lambda _: self.sheet.copy()})):
            mocker = patch.object(target, name, **kwargs)
            mocker.start()
            self.addCleanup(mocker.stop)
        saved_shadow_count = sf.SHADOW_FIX
        self.addCleanup(setattr, sf, 'SHADOW_FIX', saved_shadow_count)

    def test_sheet_owns_glyph_band_only(self):
        before = bytes(self.disc)
        with patch.object(sf, 'repair_shadows', return_value=0) as shadows:
            page, palette, _ = sf.thin_page_indices()
        edge = sf.GLYPH_ROWS * self.width
        self.assertEqual(page[:edge], bytes([3]) * edge)
        self.assertEqual(page[edge:], before[edge:])
        self.assertEqual(bytes(self.disc), before)
        self.assertEqual(palette, self.palette)
        self.assertEqual(len(page), len(before))
        shadows.assert_called_once_with(page)

    def test_shadow_derivation_does_not_change_ui_art(self):
        page, _, _ = sf.thin_page_indices()
        edge = sf.GLYPH_ROWS * self.width
        self.assertEqual(page[edge:], self.disc[edge:])

    def test_non_glyph_sheet_colours_are_not_imported(self):
        self.sheet.putpixel((0, sf.GLYPH_ROWS), (1, 2, 3))
        page, _, _ = sf.thin_page_indices()
        edge = sf.GLYPH_ROWS * self.width
        self.assertEqual(page[edge:], self.disc[edge:])

    def test_invalid_glyph_colour_fails(self):
        self.sheet.putpixel((0, sf.GLYPH_ROWS - 1), (1, 2, 3))
        with self.assertRaisesRegex(SystemExit, 'is not in the page CLUT'):
            sf.page_indices()

    def test_wrong_sheet_dimensions_fail(self):
        self.sheet = Image.new('RGB', (128, 128), self.palette[3])
        with self.assertRaisesRegex(SystemExit, 'want'):
            sf.page_indices()

    def test_latin_only_sheet_maps_slots_to_their_cells(self):
        import smallfont_variants
        self.sheet = Image.new('RGB', smallfont_variants.SHEET_SIZE, self.palette[3])
        self.sheet.putpixel((0, 0), self.palette[5])    # slot 0 = the first editable code
        with patch.object(sf, 'repair_shadows', return_value=0):
            page, _, _ = sf.thin_page_indices()
        codes = smallfont_variants.editable_codes()
        changed = [code for code in range(sf.GLYPH_CODES)
                   if page[(code // 31) * 12 * self.width + (code % 31) * 8:
                           (code // 31) * 12 * self.width + (code % 31) * 8 + 8]
                   != self.disc[(code // 31) * 12 * self.width + (code % 31) * 8:
                                (code // 31) * 12 * self.width + (code % 31) * 8 + 8]]
        self.assertEqual(sorted(changed), codes)
        first = smallfont_variants.cell_uv(codes[0])
        self.assertEqual(page[first[1] * self.width + first[0]], 5)

    def test_latin_off_preserves_retail_page(self):
        with patch.object(sf.features, 'on', return_value=False), \
                patch.object(Image, 'open') as sheet:
            page, _, _ = sf.page_indices()
        self.assertEqual(page, self.disc)
        sheet.assert_not_called()

    def test_vwf_off_uses_latin_redraw_not_sheet(self):
        import smallfont_lc
        with patch.object(sf.features, 'on', side_effect=lambda gate: gate == 'SF_LATIN'), \
                patch.object(smallfont_lc, 'draw') as draw, \
                patch.object(Image, 'open') as sheet:
            page, _, _ = sf.page_indices()
        draw.assert_called_once_with(self.disc, self.width)
        self.assertEqual(page, self.disc)
        sheet.assert_not_called()


@unittest.skipUnless((ROOT / 'data/psx/ADV/ADVCMD.BIN').exists()
                     and Path(sf.SHEET).exists(), 'requires local retail page and authored sheet')
class DiscPageImport(unittest.TestCase):
    def test_retail_ui_and_picker_texture_survive_authored_glyph_import(self):
        retail, palette, width = sf.disc_page()
        with patch.object(sf.features, 'on', return_value=True):
            page, _, _ = sf.page_indices()
        edge = sf.GLYPH_ROWS * width
        import smallfont_variants as variants
        self.assertEqual(page[edge:], retail[edge:])
        claimed = set(variants.cell_codes()[0] + variants.cell_codes()[1])

        def cell(pix, code):
            u, v = (code % variants.PAGE_COLS) * 8, (code // variants.PAGE_COLS) * 12
            return b''.join(bytes(pix[(v + y) * width + u:(v + y) * width + u + 8])
                            for y in range(12))

        import smallfont_lc
        fixed = bytearray(retail)
        smallfont_lc.draw(fixed, width)
        for code in range(sf.GLYPH_CODES):
            if code not in claimed:
                self.assertEqual(cell(page, code), cell(fixed, code),
                                 f'retail/read cell {code} changed')
        self.assertNotEqual(page[:edge], retail[:edge])
        # The retail choice cel uses u=0,v=180,w=16,h=16; its ink is two rows.
        picker = lambda pix: bytes(pix[y * width + x]
                                   for y in range(180, 196) for x in range(16))
        self.assertTrue(any(picker(retail)))
        self.assertEqual(picker(page), picker(retail))
        # Glyph bytes are the authored sheet, with the normal derived shadows.
        import smallfont_variants as sheet_loader
        sheet_indices, sheet_size = sheet_loader.sheet_pixels(sf.SHEET, palette)
        rgb2i = {}
        for i, colour in enumerate(palette):
            rgb2i.setdefault(tuple(colour), i)
        expected = bytearray(fixed)
        if sheet_size == (width, width):
            expected[:edge] = sheet_indices[:edge]
        else:
            for code in sheet_loader.editable_codes():
                u, v = sheet_loader.cell_uv(code)
                for y in range(12):
                    expected[(v + y) * width + u:(v + y) * width + u + 8] = \
                        sheet_indices[(v + y) * width + u:(v + y) * width + u + 8]
        sf.repair_shadows(expected)
        self.assertEqual(sf.thin_page_indices()[0][:edge], expected[:edge])
        self.assertTrue(any(cell(page, code) != cell(fixed, code) for code in claimed))

    def test_menu_builder_keeps_picker_strip_in_final_tim(self):
        import menu_gfx
        import tim
        retail = (ROOT / 'data/psx/ADV/ADVCMD.BIN').read_bytes()
        original_tim = tim.parse(retail, menu_gfx.PAGE)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(menu_gfx, 'ROOT', directory), \
                    patch.object(menu_gfx, 'PREVIEW', directory), \
                    patch.object(menu_gfx, 'other_pages'), \
                    patch.object(sf.features, 'on', return_value=True), \
                    redirect_stdout(StringIO()):
                menu_gfx.main()
            built = (Path(directory) / 'build/ADV/ADVCMD.BIN').read_bytes()
        built_tim = tim.parse(built, menu_gfx.PAGE)
        self.assertEqual(len(built), len(retail))
        for y in range(180, 196):
            old_at = original_tim['at'] + y * original_tim['w'] * 2
            new_at = built_tim['at'] + y * built_tim['w'] * 2
            self.assertEqual(built[new_at:new_at + 8], retail[old_at:old_at + 8])
        strip_at = built_tim['at'] + 194 * built_tim['w'] * 2
        self.assertEqual(built[strip_at:strip_at + 8], b'\xff' * 8)


class SortGateVerification(unittest.TestCase):
    # Golden MIPS words: fixture addresses are independent of production symbols.
    STUBS = (
        (0x801e1a50, 0x801ece60,
         (0x3c08801e, 0x8d081a50, 0x0807b398, 0x340c5245, 0)),
        (0x801e1a54, 0x801edba0,
         (0x3c08801e, 0x8d081a54, 0x0807b6e8, 0x340c5245, 0)),
    )
    GATES = (
        (0x801ece60, 0x801effc4, (0x8d0bfffc, 0, 0x156c0c56, 0, 0x01000008, 0)),
        (0x801edba0, 0x801effe4, (0x8d0bfffc, 0, 0x156c090e, 0, 0x01000008, 0)),
        (0x801eff00, 0x801efe00, (0x8d0bfffc, 0, 0x156cffbd, 0, 0x01000008, 0)),
    )

    def test_stub_exact_words_and_delay_slots(self):
        for cell, gate, words in self.STUBS:
            sf._verify_sort_stub(words, 0x80030000, cell, gate, 0x5245, 'test')
            for i in range(len(words)):
                corrupt = list(words)
                corrupt[i] ^= 1
                with self.subTest(cell=cell, word=i), self.assertRaises(SystemExit):
                    sf._verify_sort_stub(corrupt, 0x80030000, cell, gate, 0x5245, 'test')

    def test_gate_exact_words_delays_and_signed_pc_relative_target(self):
        for gate, replay, words in self.GATES:
            sf._verify_sort_gate(words, gate, replay, 'test')
            for i in range(len(words)):
                corrupt = list(words)
                corrupt[i] ^= 1
                with self.subTest(gate=gate, word=i), self.assertRaises(SystemExit):
                    sf._verify_sort_gate(corrupt, gate, replay, 'test')

    def test_old_branch_pc_and_missing_load_delay_are_rejected(self):
        gate, replay, words = self.GATES[0]
        with self.assertRaises(SystemExit):
            sf._verify_sort_gate(words, gate + 8, replay, 'test')
        with self.assertRaises(SystemExit):
            sf._verify_sort_gate((words[0], *words[2:]), gate, replay, 'test')


if __name__ == '__main__':
    unittest.main()
