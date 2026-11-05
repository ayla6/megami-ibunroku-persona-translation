"""Font allocation must not share bytes with the resident small-font anchor.

Pure allocator tests do not generate files. Asset tests inspect the current
font outputs and build/FONT.BIN; run them again after regeneration/assembly.
"""
from pathlib import Path
import re
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import make_vwf_font as font


def assert_disjoint(case, offset, size, reservations):
    for lo, hi in reservations:
        case.assertTrue(offset + size <= lo or hi <= offset,
                        f'glyph {offset:#x}..{offset + size:#x} overlaps '
                        f'reserved {lo:#x}..{hi:#x}')


def generated_glyphs(text):
    """Read the emitted .org/.byte pairs, independently of the allocator."""
    offset = None
    for line in text.splitlines():
        match = re.match(r'\.org FONT_GLYPHS_ADDR \+ (0x[0-9A-Fa-f]+)', line)
        if match:
            offset = int(match[1], 16)
        elif '.byte' in line:
            if offset is None:
                raise AssertionError('glyph bytes without .org')
            yield offset, bytes(int(v, 16) for v in re.findall(r'0x([0-9A-Fa-f]+)', line))
            offset = None


class FontSlotOwnership(unittest.TestCase):
    def test_all_anchor_declarations_are_reserved(self):
        text = (ROOT / 'src/asm/common/addresses.inc').read_text()
        declarations = {name: int(value, 0) for name, value in re.findall(
            r'^(FONT_GLYPHS_ADDR|SF_FONT_(?:GATE|REPLAY|CELL)_\w+) equ (0x[0-9A-Fa-f]+)',
            text, re.M)}
        base = declarations.pop('FONT_GLYPHS_ADDR')
        expected = []
        for name, address in declarations.items():
            start = address - base - (4 if '_REPLAY_' in name else 0)
            expected.append((start, start + (4 if '_CELL_' in name else 32)))
        self.assertEqual(font.font_reservations(), sorted(expected))
        self.assertEqual(len(expected), 6)
        for lo, hi in font.font_free_runs():
            assert_disjoint(self, lo, hi - lo, expected)

    def test_registration_addresses_are_read_not_hardcoded(self):
        declarations = """FONT_GLYPHS_ADDR equ 0x80000000
SF_FONT_GATE_TEST equ 0x80000100
SF_FONT_REPLAY_TEST equ 0x80000204
SF_FONT_CELL_TEST equ 0x80000014
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'addresses.inc'
            path.write_text(declarations)
            reserved = font.font_reservations(path)
        self.assertEqual(reserved, [(20, 24), (256, 288), (512, 544)])
        with patch.object(font, 'FONT_SLOT_RUNS', [(0, 1)]), \
             patch.object(font, 'font_reservations', return_value=reserved):
            self.assertEqual(font.font_free_runs(), [(0, 20), (24, 64)])
            index, assembly = font.place({ord('A'): bytes([0x55]) * 16})
        self.assertEqual(index[ord('A') - font.FIRST], 24)
        emitted = list(generated_glyphs(assembly))
        self.assertEqual(emitted, [(24, bytes([0x55]) * 16)])

    def test_fragmented_capacity_and_total_exhaustion_fail_closed(self):
        with patch.object(font, 'FONT_SLOT_RUNS', [(0, 1)]), \
             patch.object(font, 'font_reservations', return_value=[(16, 20), (32, 64)]):
            # Only the shared blank fits; 12 trailing bytes are not a glyph.
            index, _ = font.place({})
            self.assertEqual(set(index), {0})
            with self.assertRaisesRegex(SystemExit, '32 bytes needed, 16 available'):
                font.place({ord('A'): bytes(16)})
        with patch.object(font, 'FONT_SLOT_RUNS', [(0, 0)]), \
             patch.object(font, 'font_reservations', return_value=[(0, 32)]):
            with self.assertRaisesRegex(SystemExit, '0 available'):
                font.place({})

    def test_missing_or_unsupported_ownership_declarations_fail_closed(self):
        text = (ROOT / 'src/asm/common/addresses.inc').read_text()
        for modified in ('FONT_GLYPHS_ADDR equ 0x801E0000\n',
                         re.sub(r'^SF_FONT_CELL_FAST equ [^\n]*\n', '', text, flags=re.M),
                         text.replace('SF_FONT_CELL_BG equ 0x801E1A50',
                                      'SF_FONT_CELL_BG equ unsupported_expression')):
            with self.subTest(text=modified[:50]), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'addresses.inc'
                path.write_text(modified)
                with self.assertRaises(SystemExit):
                    font.font_reservations(path)

    def test_real_glyphs_preserve_art_and_avoid_all_owners(self):
        _glyphs, _used, store, _widths = font.build()
        index, assembly = font.place(store)
        reserved = font.font_reservations()
        emitted = dict(generated_glyphs(assembly))
        self.assertEqual(len(emitted), len(store))
        for code, rows in store.items():
            offset = index[code - font.FIRST]
            self.assertEqual(emitted[offset], rows)
            assert_disjoint(self, offset, 16, reserved)
        for offset in set(index):
            assert_disjoint(self, offset, 16, reserved)
        # Adjacent glyphs may share only byte-identical suffixes/prefixes.
        owned = {}
        for code, rows in store.items():
            offset = index[code - font.FIRST]
            for i, value in enumerate(rows):
                if offset + i in owned:
                    self.assertEqual(owned[offset + i], value)
                owned[offset + i] = value
        blank = next(index[c - font.FIRST] for c in range(font.FIRST, font.TOP + 1)
                     if c not in store)
        for i in range(16):
            if blank + i in owned:
                self.assertEqual(owned[blank + i], 0)

    def test_exact_prefix_suffix_sharing_fits_without_changing_art(self):
        with patch.object(font, 'FONT_SLOT_RUNS', [(0, 0)]), \
             patch.object(font, 'font_reservations', return_value=[]):
            a = bytes(15) + b'\x01'
            b = b'\x01' + bytes(15)
            index, assembly = font.place({ord('A'): a, ord('B'): b})
            self.assertEqual((index[ord('A') - font.FIRST], index[ord('B') - font.FIRST]), (1, 16))
            image = bytearray(32)
            for offset, rows in generated_glyphs(assembly):
                image[offset:offset + len(rows)] = rows
            self.assertEqual(image[1:17], a)
            self.assertEqual(image[16:32], b)
            self.assertEqual(image[:16], bytes(16))

    def test_collision_oracle_rejects_registration_pointer_as_glyph(self):
        reserved = font.font_reservations()
        word = next((lo, hi) for lo, hi in reserved if hi - lo == 4)
        with self.assertRaisesRegex(AssertionError, 'overlaps reserved'):
            assert_disjoint(self, word[0], 16, reserved)


class FontAssetReadback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = ROOT / 'src/asm/font'
        cls.glyphs, cls.used, cls.store, cls.widths = font.build()
        cls.index, cls.assembly = font.place(cls.store)
        cls.generated = dict(generated_glyphs((cls.directory / 'vwf_glyphs.asm').read_text()))
        raw_index = (cls.directory / 'vwf_index.bin').read_bytes()
        cls.stored_index = [int.from_bytes(raw_index[i:i+2], 'little')
                            for i in range(0, len(raw_index), 2)]

    def test_generated_allocation_and_glyph_bytes(self):
        self.assertEqual(self.stored_index, self.index, 'regenerate font outputs')
        for code, rows in self.store.items():
            offset = self.stored_index[code - font.FIRST]
            assert_disjoint(self, offset, 16, font.font_reservations())
            self.assertEqual(self.generated[offset], rows)
        self.assertEqual((self.directory / 'vwf_width.bin').read_bytes(), self.widths)
        expected = b''.join(bytes(self.glyphs.get(code, [0] * font.CH))
                            for code in range(font.FIRST, font.TOP + 1))
        self.assertEqual((self.directory / 'vwf_font.bin').read_bytes(), expected)

    def test_production_gate_rejects_overwritten_glyph_and_runtime_index(self):
        build = ROOT / 'build'
        names = ('FONT.BIN', 'SLPS_005.00', 'persona.sym')
        if not all((build / name).exists() for name in names):
            self.skipTest('requires assembled font and executable')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'build').mkdir()
            (root / 'src').symlink_to(ROOT / 'src', target_is_directory=True)
            (root / 'data').symlink_to(ROOT / 'data', target_is_directory=True)
            for name in names:
                (root / 'build' / name).write_bytes((build / name).read_bytes())
            with patch.object(font, 'ROOT', str(root)), \
                 patch.object(font, 'build', return_value=(self.glyphs, self.used, self.store, self.widths)):
                font.verify()
                code = next(iter(self.store))
                offset = self.index[code - font.FIRST]
                path = root / 'build/FONT.BIN'
                atlas = bytearray(path.read_bytes())
                atlas[offset] ^= 1
                path.write_bytes(atlas)
                with self.assertRaisesRegex(SystemExit, 'glyph .* overwritten'):
                    font.verify()
                path.write_bytes((build / 'FONT.BIN').read_bytes())
                atlas = bytearray(path.read_bytes())
                protected_cell = next(i for i in range(len(atlas) // 32)
                                      if not any(lo <= i <= hi for lo, hi in font.FONT_SLOT_RUNS))
                atlas[protected_cell * 32] ^= 1
                path.write_bytes(atlas)
                with self.assertRaisesRegex(SystemExit, 'retail atlas cell .* overwritten'):
                    font.verify()
                path.write_bytes((build / 'FONT.BIN').read_bytes())
                symbols = {m[2]: int(m[1], 16) for line in (build / 'persona.sym').read_text().splitlines()
                           if (m := re.fullmatch(r'([0-9a-fA-F]{8}) (\w+)', line))}
                path = root / 'build/SLPS_005.00'
                exe = bytearray(path.read_bytes())
                base = struct.unpack_from('<I', exe, 0x18)[0]
                exe[0x800 + symbols['vwf_font_index'] - base] ^= 1
                path.write_bytes(exe)
                with self.assertRaisesRegex(SystemExit, 'runtime vwf_font_index table overwritten'):
                    font.verify()

    def test_assembled_font_preserves_every_stored_glyph(self):
        path = ROOT / 'build/FONT.BIN'
        if not path.exists():
            self.skipTest('requires assembled build/FONT.BIN')
        data = path.read_bytes()
        # Use the currently emitted index as the renderer does, not a fresh
        # expected one: this catches the historical registration-word overwrite.
        for code, rows in self.store.items():
            with self.subTest(code=hex(code)):
                offset = self.stored_index[code - font.FIRST]
                self.assertEqual(data[offset:offset + 16], rows,
                                 f'FONT.BIN glyph bytes overwritten at {offset:#x}')


if __name__ == '__main__':
    unittest.main()
