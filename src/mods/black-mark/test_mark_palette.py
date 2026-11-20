"""Mark's art keeps opaque black out of the PS1 transparency slot."""
from pathlib import Path
import sys
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
import pngpage


def disc_palette(*entries):
    pal = [0] * 256
    for index, value in entries:
        pal[index] = value
    return pal


def image(pixels):
    im = Image.new('RGBA', (len(pixels), 1))
    im.putdata(pixels)
    return im


class MarkPalette(unittest.TestCase):
    def test_opaque_black_does_not_land_on_the_transparent_key(self):
        pal, pix = pngpage.rgba_to_page(
            image([(0, 0, 0, 255), (0, 0, 0, 0)]), disc_palette())
        self.assertNotEqual(pix[0], 0)
        self.assertEqual(pal[pix[0]], pngpage.OPAQUE)
        self.assertEqual(pix[1], 0)
        self.assertEqual(pal[0], pngpage.TRANSPARENT)
        self.assertEqual([None if i == 0 else pal[i] & pngpage.RGB15 for i in pix],
                         pngpage.art_colours(image([(0, 0, 0, 255), (0, 0, 0, 0)])))

    def test_unchanged_colour_keeps_its_original_slot(self):
        pal, pix = pngpage.rgba_to_page(
            image([(248, 0, 0, 255)]), disc_palette((7, 0x8000 | 31)))
        self.assertEqual(pix[0], 7)
        self.assertEqual(pal[7], 0x8000 | 31)

    def test_full_palette_stops_at_255_opaque_colours(self):
        def art(n):
            return image([
                (((v & 31) << 3), (((v >> 5) & 31) << 3),
                 (((v >> 10) & 31) << 3), 255) for v in range(n)])

        pal, pix = pngpage.rgba_to_page(art(255), disc_palette())
        self.assertEqual(len(set(pix)), 255)
        with self.assertRaises(SystemExit):
            pngpage.rgba_to_page(art(256), disc_palette())

    def test_a_hole_shows_up_as_a_mismatch(self):
        art = image([(0, 0, 0, 255)])
        self.assertNotEqual([None], pngpage.art_colours(art))


if __name__ == '__main__':
    unittest.main()
