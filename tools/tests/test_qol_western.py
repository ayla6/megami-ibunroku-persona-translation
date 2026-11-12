"""Western controls (--qol=western): PadRead's swap and the controller page.

PadRead (the one resident pad read) swaps Circle/Cross and Triangle/Square
for controller TYPE 1 only, on both controllers' halves of the held word; the
page's layout tables name the swapped buttons in every overlay that carries
them, and the run action follows the cancel button. Runs on the built game
files, built with `--qol=western` and with or without `run`.

Run after assembly:
    python -m unittest discover -s tools/tests -p test_qol_western.py -v
"""
from pathlib import Path
import re
import struct
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = 0x800643C4
STACK = 0x801FF000
RETURN = 0x801FF800
PAD_READ = 0x80025140
PAD_LIB = 0x80041428                  # the library call PadRead makes first
PAD_BUFFER = 0x800563F0               # what it leaves there: the active-low pad word
TRIANGLE, CIRCLE, CROSS, SQUARE = 0x10, 0x20, 0x40, 0x80
ENTRIES = 20                          # per layout, two columns of ten
RUN_INDEX = 19                        # the run action's name index


def equ(name):
    text = (ROOT / 'src/asm/common/addresses.inc').read_text()
    return int(re.search(rf'^{name}\s+equ\s+(\w+)', text, re.M).group(1), 0)


class Western(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sym = ROOT / 'build/persona.sym'
        if not sym.exists() or not re.search(r'^[0-9A-Fa-f]{8} western_pad$',
                                             sym.read_text(), re.M):
            raise unittest.SkipTest('requires a build with --qol=western')
        cls.run_built = bool(re.search(r'^[0-9A-Fa-f]{8} dngrun_walk$',
                                       sym.read_text(), re.M))
        cls.exe = (ROOT / 'build/SLPS_005.00').read_bytes()

    def pad_read(self, buttons, pad_type):
        """PadRead's result for the pad word `buttons` (active high)."""
        c = CPU()
        base, size = struct.unpack_from('<II', self.exe, 0x18)
        c.load(base, self.exe[0x800:0x800 + size])
        c.write(PAD_BUFFER, ~buttons & 0xFFFFFFFF)
        c.write(equ('PAD_TYPE_ADDR'), pad_type, 1)

        def stub(cpu):
            if cpu.pc != PAD_LIB:
                return False
            cpu.start(cpu.r[REG['ra']])
            return True
        c.r[REG['sp']], c.r[REG['ra']], c.r[REG['a0']] = STACK, RETURN, 1
        c.start(PAD_READ)
        c.run(RETURN, intercept=stub, limit=1000)
        self.assertEqual(c.r[REG['sp']], STACK, 'PadRead must restore the stack')
        return c.r[REG['v0']]

    def test_type_1_swaps_the_face_buttons(self):
        for held, expect in ((CIRCLE, CROSS), (CROSS, CIRCLE), (TRIANGLE, SQUARE),
                             (SQUARE, TRIANGLE),
                             (CIRCLE | TRIANGLE, CROSS | SQUARE),
                             (CIRCLE | CROSS, CIRCLE | CROSS),
                             (0x1000 | 0x0001 | 0x0800, 0x1000 | 0x0001 | 0x0800)):
            with self.subTest(held=hex(held)):
                self.assertEqual(self.pad_read(held, 0), expect)

    def test_type_1_swaps_both_controllers_and_leaves_the_rest(self):
        for low in range(0x100):
            for high in (0, CIRCLE | SQUARE):
                word = (high << 16) | low | 0xF00
                swapped = self.pad_read(word, 0)
                expect = 0
                for source, target in ((CIRCLE, CROSS), (CROSS, CIRCLE),
                                       (TRIANGLE, SQUARE), (SQUARE, TRIANGLE)):
                    expect |= target if low & source else 0
                    expect |= target << 16 if high & source else 0
                rest = word & ~((CIRCLE | CROSS | TRIANGLE | SQUARE) * 0x10001)
                self.assertEqual(swapped, rest | expect, hex(word))

    def test_type_2_is_untouched(self):
        for held in (CIRCLE, CROSS, TRIANGLE, SQUARE, 0xFFFF, 0xF0F0F0F0):
            self.assertEqual(self.pad_read(held, 1), held)

    # ------------------------------------------------------------ the page
    def layouts(self, name, table, built=True):
        path = ROOT / ('build' if built else 'data/psx') / f'{name}.BIN'
        data = path.read_bytes()
        return list(data[table - OVERLAY:table - OVERLAY + 4 * ENTRIES])

    def expected(self, retail, name):
        out = list(retail)
        for layout in (0, 2):                         # the TYPE 1 layouts
            for column in (0, 10):
                at = layout * ENTRIES + column
                out[at:at + 4] = [retail[at + 1], retail[at], retail[at + 3], retail[at + 2]]
        return out

    def test_page_names_the_swapped_buttons_in_every_overlay(self):
        for name, table in (('ADV', equ('ADV_PAD_LAYOUTS')), ('S2D', equ('S2D_PAD_LAYOUTS')),
                            ('DNG', equ('DNG_PAD_LAYOUTS'))):
            with self.subTest(overlay=name):
                retail = self.layouts(name, table, built=False)
                built = self.layouts(name, table)
                expect = self.expected(retail, name)
                if name == 'DNG' and self.run_built:
                    # run's action sits on TYPE 1's cancel button, Circle now,
                    # and on Cross in TYPE 2
                    expect[0] = RUN_INDEX
                    expect[ENTRIES + 1] = RUN_INDEX
                self.assertEqual(built, expect)

    def test_retail_tables_are_what_the_swap_assumes(self):
        # each layout starts circle, cross, triangle, square: TYPE 1's circle
        # is the accept action, its cross the cancel
        retail = self.layouts('DNG', equ('DNG_PAD_LAYOUTS'), built=False)
        self.assertEqual(retail[0:4], [0x07, 0x02, 0x00, 0x03])
        self.assertEqual(retail[10:14], [0x01, 0x02, 0x11, 0x03])
        self.assertEqual(retail[40:44], [0x01, 0x02, 0x00, 0x04])
        self.assertEqual(retail[50:54], [0x01, 0x02, 0x09, 0x04])

    # ------------------------------------------------- title and battle page
    def test_title_tests_the_swapped_masks(self):
        retail = (ROOT / 'data/psx/EXE/OPEN.EXE').read_bytes()
        built = (ROOT / 'build/EXE/OPEN.EXE').read_bytes()
        swap = {0x40: 0x20, 0x80: 0x10, 0x820: 0x840}
        sites = (0x80081D88, 0x80082140, 0x8008313C, 0x80083170, 0x800831A4, 0x80083768,
                 0x800837C4, 0x800837F8, 0x80083BD0, 0x80083C7C, 0x80083CB0)
        for site in sites:
            at = site - 0x80080000 + 0x800
            before = struct.unpack_from('<I', retail, at)[0]
            after = struct.unpack_from('<I', built, at)[0]
            self.assertEqual(before >> 26, 0xC, hex(site))           # andi
            self.assertEqual(after & ~0xFFFF, before & ~0xFFFF, hex(site))
            self.assertEqual(after & 0xFFFF, swap[before & 0xFFFF], hex(site))

    def test_battle_controls_page_swaps_the_type_1_icons(self):
        retail = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        built = (ROOT / 'build/BTLP.BIN').read_bytes()
        base = equ('BTLP_CONTROLS_ICONS') - OVERLAY
        icons = lambda data: [data[base + 8 * i + 4] for i in range(8)]
        # circle, cross, square, triangle, L1, L2, R1, R2 (u of each cell)
        self.assertEqual(icons(retail), [0xA0, 0xB0, 0xD0, 0xC0, 0x00, 0x18, 0x30, 0x48])
        self.assertEqual(icons(built), [0xB0, 0xA0, 0xC0, 0xD0, 0x00, 0x18, 0x30, 0x48])

    def test_choice_menu_corner_icon_keeps_the_plate(self):
        import sys
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import mescodec
        decode = lambda data: mescodec.decode(data, 0x200 + 64 * 24)[0]
        retail = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        built = (ROOT / 'build/BTLP.BIN').read_bytes()
        at = equ('BTLP_INDICATOR_ICON') - OVERLAY
        old, new = decode(retail[at:]), decode(built[at:])
        rgb = lambda img, o: int.from_bytes(img[2 * img[0x200 + o]:][:2], 'little') & 0x7FFF
        for y in range(24):                                          # plain frame untouched
            for x in range(32):
                self.assertEqual(rgb(old, y * 64 + x), rgb(new, y * 64 + x))


if __name__ == '__main__':
    unittest.main()
