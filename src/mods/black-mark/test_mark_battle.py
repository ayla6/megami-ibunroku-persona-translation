"""The declared art uses shared container handlers and preserves nearby data."""
from pathlib import Path
import csv
import hashlib
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
import toolpath
import image_replacements as images
import mods
import tim
import pngpage

MOD = mods.by_label()['black-mark']
RULES = {r.image.name: r for r in images.rules(MOD)}
TABLE = tuple(1 + 5*i for i in range(21))
SECTORS = TABLE[-1]


def minimal_tim(width: int, height: int) -> bytes:
    clut = struct.pack('<IHHHH', 524, 0, 0, 16, 16) + bytes(512)
    pixels = struct.pack('<IHHHH', 12+width*height, 0, 0, width//2, height) + bytes(width*height)
    return struct.pack('<II', 0x10, 9) + clut + pixels


def disc() -> tuple[bytes, bytes]:
    data = bytearray(SECTORS*2048)
    blob = minimal_tim(2, 2)
    for name in ('battle.png', 'battle_gun.png'):
        at = TABLE[RULES[name].entry]*2048 + 12
        data[at:at+len(blob)] = blob
        struct.pack_into('<I', data, at+len(blob), 0xDEADBEEF)
    return bytes(data), struct.pack('<22H', *TABLE, 0)


def art() -> Image.Image:
    result = Image.new('RGBA', (2, 2))
    result.putdata([(0, 0, 0, 255), (0, 0, 0, 0), (248, 0, 0, 255), (0, 0, 0, 0)])
    return result


class DeclaredArt(unittest.TestCase):
    def test_member_table_is_found_by_shape(self):
        data, table = disc()
        self.assertEqual(images.battle_table(table, len(data)//2048), TABLE)
        with self.assertRaises(ValueError):
            images.battle_table(bytes(44), SECTORS)

    def test_declared_gun_sheet_uses_second_bank(self):
        self.assertEqual(RULES['battle_gun.png'].entry, RULES['battle.png'].entry+10)
        data, table = disc()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'BTLP.BIN').write_bytes(table)
            with patch.object(images, 'RETAIL', root):
                self.assertEqual(images.offset(RULES['battle_gun.png'], data),
                                 TABLE[RULES['battle_gun.png'].entry]*2048+12)

    def test_reference_exports_match_retail(self):
        tree = ROOT/'data/psx'
        gun = images.source_image(RULES['battle_gun.png'], tree)
        self.assertEqual(gun.size, (128, 250))
        self.assertEqual(hashlib.sha1(gun.tobytes()).hexdigest(),
                         '060ab0bf19be76bcc4357818c00f35d765e96f5c')
        ending = images.source_image(RULES['ending.png'], tree)
        self.assertEqual(ending.size, (149, 208))
        self.assertEqual(hashlib.sha1(ending.convert('RGB').tobytes()).hexdigest(),
                         '2ba16f49d37e9915aa0c400322b697dba4ff2544')

    def test_shared_export_refuses_to_overwrite_art(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images.export_images(MOD, ROOT/'data/psx', root)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                images.export_images(MOD, ROOT/'data/psx', root)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_ending_portrait_follows_mapped_profile_text(self):
        with (ROOT/'src/porting/endtext_map.tsv').open() as stream:
            rows = list(csv.DictReader(stream, delimiter='\t'))
        profile = next(int(r['ps1_tim_offset'], 16) for r in rows if r['entry_offset']=='0x163000')
        data = (ROOT/'data/psx/EXE/END.BIN').read_bytes()
        self.assertEqual(RULES['ending.png'].entry, ((tim.parse(data, profile)['end']+2047)&~2047)+4)

    def test_ending_swap_and_restore_preserve_translated_pages(self):
        rule = RULES['ending.png']
        original = (ROOT/'data/psx'/rule.file).read_bytes()
        info = tim.parse(original, rule.entry)
        translated = bytearray(original)
        translated[0x9e100] ^= 1
        edited = images.tim_image(original, rule.entry)
        edited.putpixel((0, 0), (255, 0, 0))
        built = images.replace_image(translated, rule.entry, edited.convert('RGBA'), rule.mode)
        self.assertEqual(built[:info['at']], translated[:info['at']])
        self.assertEqual(built[info['end']:], translated[info['end']:])
        self.assertNotEqual(built[info['at']:info['end']], original[info['at']:info['end']])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'data/EXE').mkdir(parents=True)
            (root/'build/EXE').mkdir(parents=True)
            (root/'data'/rule.file).write_bytes(original)
            target = root/'build'/rule.file
            target.write_bytes(built)
            with patch.object(images, 'RETAIL', root/'data'), patch.object(images, 'BUILD', root/'build'), patch.object(images, 'rules', return_value=[rule]):
                images.restore([MOD])
            self.assertEqual(target.read_bytes(), bytes(translated))

    def test_swaps_preserve_other_members_and_model_data(self):
        data, _table = disc()
        for name in ('battle.png', 'battle_gun.png'):
            at = TABLE[RULES[name].entry]*2048+12
            info = tim.parse(data, at)
            updated = images.replace_image(data, at, art(), 'indexed')
            palette_at = info['clut']['at']
            self.assertEqual(updated[:palette_at], data[:palette_at])
            self.assertEqual(updated[info['end']:], data[info['end']:])
            self.assertNotEqual(updated[info['at']:info['end']], data[info['at']:info['end']])
            actual = images.tim_image(updated, at)
            self.assertEqual(pngpage.art_colours(actual), pngpage.art_colours(art()))
            with self.assertRaisesRegex(ValueError, 'dimensions'):
                images.replace_image(data, at, Image.new('RGBA', (4, 4)), 'indexed')


if __name__ == '__main__':
    unittest.main()
