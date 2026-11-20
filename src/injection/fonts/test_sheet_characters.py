"""Editable dialogue-sheet labels keep cell order and use the shared codec."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import bpe
import etext
import make_vwf_font as font


class SheetCharacters(TestCase):
    def test_white_end_column_sets_advance_without_drawing(self):
        from PIL import Image
        with TemporaryDirectory() as directory:
            path = Path(directory) / font.EDITIONS['large'][0]
            image = Image.new('RGBA', (16, 16))
            image.putpixel((1, 5), (0, 0, 0, 255))
            for y in range(16):
                image.putpixel((4, y), (255, 255, 255, 255))
            image.putpixel((9, 5), (0, 0, 0, 255))
            image.save(path)
            widths = {}
            with patch.object(font, 'LAYOUT', ('A￥',)), patch.object(font, 'FONT_DIR', directory):
                cell = font.load_sheet('large', advances=widths)[ord('A')]
            self.assertEqual(cell[5], 0x40)
            self.assertEqual(sum(cell), 0x40)
            self.assertEqual(widths[ord('A')], 6)
            self.assertEqual(font.atlas_payload(cell, widths[ord('A')]),
                             bytes(cell) + bytes(14) + b'\xA5\x06')

    def test_custom_cell_maps_to_matching_glyph_and_round_trips(self):
        mark = 'é'
        code = font.LAST + len(font.INTERNAL_MARKS) + 1
        with patch.object(font, 'LAYOUT', ('Y￥é',)), \
                patch.object(font, 'CUSTOM_MARKS', mark), \
                patch.dict(font.EXTRA_CODE, {mark: code}), \
                patch.dict(etext._VWF_CHAR, {code: mark}), \
                patch.object(font, 'read_png', return_value=(24, 16, lambda x, y: x in (9, 17) and y == 5, lambda x, y: False)):
            for edition in font.EDITIONS:
                glyphs = font.load_sheet(edition)
                self.assertEqual(glyphs[code][5], 0x40)
                self.assertEqual(sum(glyphs[code]), 0x40)
            encoded = etext.encode(mark, end=b'\xff\xef')
            self.assertEqual(encoded, b'\xec\xff\xef')
            self.assertEqual(etext.decode(encoded), mark + '<FFEF>')
            packed, pairs = bpe.pack({0: encoded})
            self.assertEqual(bpe.unpack(packed[0], pairs), encoded)

    def test_invalid_labels_and_exhaustion_fail(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'characters.tsv'
            path.write_text('characters\nAé\nBé\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                font.read_sheet_characters(path)
        self.assertEqual(font.custom_marks(('éñåö',)), 'éñåö')
        with self.assertRaisesRegex(ValueError, 'too many'):
            font.custom_marks(('éñåöç',))

    def test_reclaimed_cell_survives_battle_script_compression(self):
        mark, cell = 'é', 0x1EB
        with patch.dict(font.ATLAS_CODE, {mark: cell}), \
                patch.dict(etext._ATLAS_CHAR, {cell: mark}):
            encoded = etext.encode(mark * 4, end=b'\xff\xef')
            self.assertEqual(encoded, b'\x81\xeb' * 4 + b'\xff\xef')
            self.assertEqual(etext.decode(encoded), mark * 4 + '<FFEF>')
            packed, pairs = bpe.pack({0: encoded})
            self.assertEqual(bpe.unpack(packed[0], pairs), encoded)
