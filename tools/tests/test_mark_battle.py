"""Mark's battle sheet is found through BTLP.BIN's member table and swapped
in place inside B/P.BIN."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

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

    def test_gun_sheet_uses_corresponding_second_bank_entry(self):
        pbin, btlp = disc()
        self.assertEqual(mark.BATTLE_GUN_MEMBER, mark.BATTLE_MEMBER + 10)
        self.assertEqual(mark.battle_entry_offset(pbin, btlp, mark.BATTLE_GUN_MEMBER),
                         TABLE[mark.BATTLE_GUN_MEMBER] * 2048)

    def test_original_gun_export_matches_retail(self):
        root = ROOT / 'data' / 'psx'
        pbin = (root / 'B' / 'P.BIN').read_bytes()
        btlp = (root / 'BTLP.BIN').read_bytes()
        expected = mark.battle_image(pbin, btlp, mark.BATTLE_GUN_MEMBER)
        with Image.open(ROOT / 'src/assets/mark/og/battle_gun.png') as actual:
            self.assertEqual(actual.size, expected.size)
            self.assertEqual(actual.convert('RGBA').tobytes(), expected.tobytes())

    def test_ending_portrait_follows_mapped_profile_text(self):
        import csv
        with (ROOT / 'src/extraction_tools/matching/endtext_map.tsv').open() as f:
            rows = list(csv.DictReader(f, delimiter='\t'))
        profile = next(int(row['ps1_tim_offset'], 16) for row in rows
                       if row['entry_offset'] == '0x163000')
        data = (ROOT / 'data/psx/EXE/END.BIN').read_bytes()
        text = mark.timcodec.parse(data, profile)
        self.assertEqual(mark.ENDING_PORTRAIT, ((text['end'] + 0x7ff) & ~0x7ff) + 4)
        expected = mark.ending_image(data)
        with Image.open(ROOT / 'src/assets/mark/og/ending.png') as actual:
            self.assertEqual(actual.size, expected.size)
            self.assertEqual(actual.convert('RGB').tobytes(), expected.tobytes())

    def test_ending_swap_and_retail_restore_preserve_translated_pages(self):
        original = (ROOT / 'data/psx/EXE/END.BIN').read_bytes()
        t = mark.timcodec.parse(original, mark.ENDING_PORTRAIT)
        translated = bytearray(original)
        translated[0x9e100] ^= 1
        art = mark.ending_image(original)
        art.putpixel((0, 0), (255, 0, 0))
        built = mark.ending_swap(translated, art)
        self.assertEqual(built[:t['at']], translated[:t['at']])
        self.assertEqual(built[t['end']:], translated[t['end']:])
        self.assertNotEqual(built[t['at']:t['end']], original[t['at']:t['end']])
        with tempfile.TemporaryDirectory() as tmp, patch.object(mark, 'ROOT', tmp):
            root = Path(tmp)
            (root / 'data/psx/EXE').mkdir(parents=True)
            (root / 'build/EXE').mkdir(parents=True)
            (root / 'data/psx/EXE/END.BIN').write_bytes(original)
            path = root / 'build/EXE/END.BIN'
            path.write_bytes(built)
            mark.cmd_retail()
            self.assertEqual(path.read_bytes(), bytes(translated))

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

    def test_gun_swap_preserves_other_entries(self):
        pbin, btlp = disc()
        off = TABLE[mark.BATTLE_GUN_MEMBER] * 2048
        blob = tim(2, 2)
        mutable = bytearray(pbin)
        mutable[off + mark.BATTLE_TIM_HEADER:off + mark.BATTLE_TIM_HEADER + len(blob)] = blob
        pbin = bytes(mutable)
        out = mark.battle_swap(pbin, btlp, art(), mark.BATTLE_GUN_MEMBER, 'battle_gun.png')
        self.assertEqual(out[:off], pbin[:off])
        end = off + mark.BATTLE_TIM_HEADER + len(blob)
        self.assertEqual(out[end:], pbin[end:])
        sheet = mark.battle_tim(out, btlp, mark.BATTLE_GUN_MEMBER)
        self.assertEqual(mark.page_shows_art(mark.page_pixels(out, sheet),
                                            mark.clut_rgb15(out, sheet), art()), [])

    def test_wrong_size_is_refused_before_writing(self):
        pbin, btlp = disc()
        with self.assertRaises(SystemExit):
            mark.battle_swap(pbin, btlp, Image.new('RGBA', (4, 4)))


if __name__ == '__main__':
    unittest.main()
