"""Reviewed runtime ranges must describe real, bounded live memory.

The map is evidence, not a wish list: every protected row names an owner and
the rev-0 instructions that establish its extent. These checks pin the rows
whose extent comes from retail bytes and from the generated tables, so a
later edit cannot silently widen a range over patch data or shrink it below
a live writer.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src' / 'injection_tools'))
import demons
import write_guard

PSX = ROOT / 'data' / 'psx'
OVL_BASE = 0x800643C4
EXE_MAGIC = b'PS-X EXE'

BSS_IMAGES = {
    'BTLP.BIN': PSX / 'BTLP.BIN',
    'DNG.BIN': PSX / 'DNG.BIN',
    'SLPS_005.00': PSX / 'SLPS_005.00',
    'OPEN.EXE': PSX / 'EXE' / 'OPEN.EXE',
}
PERSONALITY_IMAGES = {
    'ADV.BIN': (PSX / 'ADV.BIN', 'ADV'),
    'DNG.BIN': (PSX / 'DNG.BIN', 'DNG'),
    'S2D.BIN': (PSX / 'S2D.BIN', 'S2D'),
}


def load(image):
    """The retail bytes and the address of file offset zero.

    A PS-X EXE's t_addr is the text load address; the 0x800-byte header sits
    immediately before it, so file offset zero is t_addr - 0x800.
    """
    data = image.read_bytes()
    if data.startswith(EXE_MAGIC) and len(data) >= 0x800:
        return data, int.from_bytes(data[0x18:0x1C], 'little') - 0x800
    return data, OVL_BASE


def rows():
    return write_guard.protected_regions()


def rows_for(image, owner):
    return [row for row in rows() if row[0] == image and row[3] == owner]


class Manifest(unittest.TestCase):
    def test_every_row_is_complete_and_distinct(self):
        reviewed = rows()
        self.assertTrue(reviewed)
        self.assertEqual(len(reviewed), len(set(reviewed)))
        for image, start, end, owner in reviewed:
            self.assertEqual(Path(image).name, image)
            self.assertLess(start, end)
            self.assertTrue(owner.strip())

    def test_reviewed_images_exist_in_the_retail_tree(self):
        for image, _start, _end, _owner in rows():
            matches = list(PSX.rglob(image))
            self.assertEqual(len(matches), 1, f'{image}: expected one retail image')

    def test_blanket_tail_is_only_used_where_code_touches_it(self):
        tails = {row[0] for row in rows()
                 if row[3].endswith('zero-fill BSS tail')}
        self.assertEqual(tails, set(BSS_IMAGES))
        # MOVIE.EXE has a zero tail too, but no direct access was found.
        self.assertNotIn('MOVIE.EXE', tails)


class ZeroFillTails(unittest.TestCase):
    def test_tail_starts_after_the_last_retail_byte_and_runs_to_eof(self):
        for image, path in BSS_IMAGES.items():
            data, base = load(path)
            last = len(data) - 1
            while last >= 0 and not data[last]:
                last -= 1
            start, end = base + last + 1, base + len(data)
            found = [row for row in rows()
                     if row[0] == image and row[3].endswith('zero-fill BSS tail')]
            self.assertEqual(len(found), 1, image)
            self.assertEqual((found[0][1], found[0][2]), (start, end), image)
            self.assertFalse(any(data[last + 1:]), image)

    def test_battle_tail_stops_before_the_patch_extension(self):
        # The small-font table starts at 0x800F8960; the reviewed tail ends at
        # the retail EOF, so extension slots stay outside it.
        found = rows_for('BTLP.BIN', 'battle overlay zero-fill BSS tail')
        self.assertEqual(len(found), 1)
        self.assertLessEqual(found[0][2], 0x800F8960)

    def test_battle_effect_pointer_array_is_five_u32_slots(self):
        found = rows_for('BTLP.BIN', 'battle effect work pointers')
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0][1], found[0][2]), (0x800D26E0, 0x800D26E0 + 5 * 4))


class DerivedTables(unittest.TestCase):
    def test_personality_tables_match_the_generated_race_tables(self):
        for image, (path, overlay) in PERSONALITY_IMAGES.items():
            start = (demons.RACE_TABLES[overlay]
                     + demons.RACE_COUNT * demons.RACE_LEN)
            found = rows_for(image, 'personality affinity table')
            self.assertEqual(len(found), 1, image)
            self.assertEqual((found[0][1], found[0][2]),
                             (start, start + demons.RACE_COUNT), image)
            data, base = load(path)
            self.assertEqual(len(data[start - base:start - base + demons.RACE_COUNT]),
                             demons.RACE_COUNT, image)

    def test_name_rows_match_the_entry_layout(self):
        equ = write_guard._equ_map(str(ROOT / 'src' / 'asm' / 'common' / 'addresses.inc'))
        family = equ['NAME_FAMILY_TEXT_ADDR']
        given = equ['NAME_GIVEN_TEXT_ADDR']
        self.assertEqual(given - family, 16)
        cells = rows_for('NAME.BIN', 'name-entry field cells')
        lengths = rows_for('NAME.BIN', 'name-entry field lengths')
        self.assertEqual(len(cells), 1)
        self.assertEqual(len(lengths), 1)
        self.assertEqual((cells[0][1], cells[0][2]), (family, family + 3 * 16))
        self.assertEqual((lengths[0][1], lengths[0][2]), (family + 3 * 16, family + 3 * 16 + 3))


if __name__ == '__main__':
    unittest.main()
