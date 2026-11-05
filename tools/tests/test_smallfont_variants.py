"""Font artwork, allocation and producer-owned fixed-cell policy."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import smallfont_vwf as sf
import smallfont_variants as variants
import smallfont_lc


def cell_bytes(page, code):
    u, v = (code % variants.PAGE_COLS) * 8, (code // variants.PAGE_COLS) * 12
    return b''.join(bytes(page[(v + y) * 256 + u:(v + y) * 256 + u + 8]) for y in range(12))


class VariantArt(unittest.TestCase):
    def test_uses_only_the_latin_repertoire_in_the_text_band(self):
        slots = variants.slots()
        self.assertEqual(slots, variants.editable_codes())
        self.assertTrue(set(variants.editable_codes()) <= set(slots))
        regular, compact = variants.cell_codes()
        self.assertEqual(len(regular), len(slots))
        self.assertEqual(len(compact), len(slots))
        self.assertFalse(set(regular) & set(compact))
        self.assertFalse(set(regular + compact) & variants.protected_codes())
        for cell in regular + compact:
            self.assertLess(cell, variants.PAGE_CODES)
            self.assertLess(variants.cell_uv(cell)[1] + 11, sf.GLYPH_ROWS)
        for slot, code in enumerate(slots):
            for compact_face in (False, True):
                self.assertNotEqual(variants.uv(slot, compact_face), variants.cell_uv(code))
                x, y = variants.uv(slot, compact_face)
                self.assertLess(y + 11, sf.GLYPH_ROWS)
                self.assertLess(x + 7, 256)

    def test_retail_read_cells_are_never_claimed(self):
        import toolbelt
        protected = variants.protected_codes()
        self.assertIn(0, protected, 'the blank space cell stays blank')
        for char in "ABCabc019.-:/'":
            self.assertIn(toolbelt.smallfont_char(char), protected)
        self.assertTrue(set(variants.editable_codes()) <= protected)
        self.assertFalse(set(variants.spare_codes()) & protected)
        self.assertGreaterEqual(len(variants.spare_codes()), 2 * len(variants.slots()))

    def test_original_text_and_ui_survive_both_sprite_faces(self):
        retail, palette, _ = sf.disc_page()
        regular, _, _ = sf.thin_page_indices()
        page, metrics = variants.compose(retail, regular, palette, sf.glyph_rows)
        fixed = bytearray(retail)
        smallfont_lc.draw(fixed, 256)
        claimed = set(variants.cell_codes()[0] + variants.cell_codes()[1])
        for code in range(sf.GLYPH_CODES):
            if code not in claimed:
                self.assertEqual(cell_bytes(page, code), cell_bytes(fixed, code),
                                 f'retail/read cell {code} changed')
        self.assertEqual(page[sf.GLYPH_ROWS * 256:], retail[sf.GLYPH_ROWS * 256:])
        faces_differ = False
        for slot, code in enumerate(variants.slots()):
            seen = []
            for compact in (False, True):
                u, v = variants.uv(slot, compact)
                rows = [page[(v + y) * 256 + u:(v + y) * 256 + u + 8] for y in range(12)]
                ink = [x for row in rows for x, colour in enumerate(row) if colour not in (0, 2)]
                advance = metrics[code] >> 4 if compact else metrics[code] & 15
                self.assertEqual(min(ink), 0)
                self.assertEqual(max(ink) + 2, advance, 'every face keeps the 1px letter gap')
                seen.append(b''.join(bytes(row) for row in rows))
            faces_differ = faces_differ or seen[0] != seen[1]
        self.assertTrue(faces_differ, 'the compact face is independent artwork, not a squeeze')
        self.assertEqual(metrics[0], 0x14, 'word space: 4 px normal, 1 px compact')
        self.assertEqual(sf.tier_adv(metrics[0], 0, 2), 1, 'stage 3 word space')
        self.assertEqual(sf.tier_adv(metrics[0], 0, 1), 2, 'stage 2 word space')

    def test_compact_starter_copies_intact_glyphs_without_resampling(self):
        import tempfile
        retail, palette, _ = sf.disc_page()
        regular, _, _ = sf.thin_page_indices()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'starter.png'
            with patch.object(variants, 'COMPACT', path):
                variants.prepare(regular, palette, sf.glyph_rows)
            self.assertTrue(path.exists(), 'prepare must create the starter it announces')
            sheet, size = variants.sheet_pixels(path, palette)
        self.assertEqual(size, (variants.EDIT_COLS * 8, 60))
        for code in variants.slots():
            self.assertEqual(sf.glyph_rows(sheet, 256, code),
                             sf.glyph_rows(regular, 256, code),
                             f'code {code:#x}: starter changed the artwork')

    def test_tags_never_land_in_code_an_optional_patch_rewrites(self):
        for overlay in ('ADV', 'DNG', 'S2D'):
            stock = (ROOT / f'data/psx/{overlay}.BIN').read_bytes()
            retired = variants.retired_ranges(overlay)
            for address, _word in variants.fixed_producers(stock, overlay):
                self.assertFalse(any(lo <= address < hi for lo, hi in retired),
                                 f'{overlay}: tag {address:#x} lands in retired code')

    def test_character_producers_are_tagged_without_rewriting_wording(self):
        for overlay in ('ADV', 'DNG', 'S2D'):
            stock = (ROOT / f'data/psx/{overlay}.BIN').read_bytes()
            rows = variants.fixed_producers(stock, overlay)
            self.assertTrue(rows)
            for address, word in rows:
                original = int.from_bytes(stock[address - 0x800643C4:address - 0x800643C4 + 4], 'little')
                self.assertEqual(word ^ original, 0x4000)
