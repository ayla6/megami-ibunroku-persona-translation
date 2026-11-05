"""Mark's battle sheet is found through BTLP.BIN's member table and swapped
in place inside B/P.BIN."""
from pathlib import Path
import struct
import sys
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src' / 'injection_tools'))
import mark


SECTORS = 101                  # 20 entries of 5 sectors after the first
TABLE = [1 + 5 * i for i in range(21)]
MEMBER_OFFSET = TABLE[mark.BATTLE_MEMBER] * 2048


def tim(width, height):
    """A minimal 8bpp TIM with a 256-entry CLUT and an all-index-0 page."""
    clut = struct.pack('<IHHHH', 12 + 256 * 2, 0, 0, 16, 16) + b'\x00' * 512
    image = struct.pack('<IHHHH', 12 + width * height, 0, 0,
                        width // 2, height) + b'\x00' * (width * height)
    return struct.pack('<II', 0x10, 0x9) + clut + image


def disc():
    btlp = struct.pack('<22H', *TABLE, 0)
    pbin = bytearray(SECTORS * 2048)
    blob = tim(2, 2)
    struct.pack_into('<III', pbin, MEMBER_OFFSET, 0x8014000C, 0, 0)
    pbin[MEMBER_OFFSET + mark.BATTLE_TIM_HEADER:
         MEMBER_OFFSET + mark.BATTLE_TIM_HEADER + len(blob)] = blob
    # Sentinel after the TIM: the swap must not touch the model data.
    struct.pack_into('<I', pbin,
                     MEMBER_OFFSET + mark.BATTLE_TIM_HEADER + len(blob),
                     0xDEADBEEF)
    return bytes(pbin), btlp


def art():
    im = Image.new('RGBA', (2, 2))
    im.putdata([(0, 0, 0, 255), (0, 0, 0, 0),
                (248, 0, 0, 255), (0, 0, 0, 0)])
    return im


class MarkBattleSheet(unittest.TestCase):
    def test_member_table_is_found_by_shape(self):
        pbin, btlp = disc()
        self.assertEqual(mark.battle_member_sectors(btlp, len(pbin) // 2048),
                         tuple(TABLE))

    def test_missing_member_table_is_refused(self):
        with self.assertRaises(SystemExit):
            mark.battle_member_sectors(bytes(44), SECTORS)

    def test_swap_rewrites_only_the_tim(self):
        pbin, btlp = disc()
        before = mark.battle_tim(pbin, btlp)
        end = before['pix_at'] + before['pix_len']
        out = mark.battle_swap(pbin, btlp, art())
        self.assertEqual(len(out), len(pbin))
        self.assertEqual(out[end:end + 4], b'\xef\xbe\xad\xde')
        tim = mark.battle_tim(out, btlp)
        self.assertEqual((tim['px_w'], tim['h']), (2, 2))
        self.assertEqual(mark.page_shows_art(
            mark.page_pixels(out, tim), mark.clut_rgb15(out, tim), art()), [])
        self.assertNotEqual(mark.page_pixels(out, tim),
                            mark.page_pixels(pbin, before))

    def test_wrong_size_is_refused_before_writing(self):
        pbin, btlp = disc()
        with self.assertRaises(SystemExit):
            mark.battle_swap(pbin, btlp, Image.new('RGBA', (4, 4)))


if __name__ == '__main__':
    unittest.main()
