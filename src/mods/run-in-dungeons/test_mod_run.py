"""The dungeon run action: nine advances per tile, only frames skipped.

FieldWalk advances the view nine times per tile. Running must keep every
advance (the tile, collision and landing position) and drop drawn frames
only, so every tile still calls FieldStepView nine times and the play clock
still ticks once per drawn frame.

The button is an action on the game's own controller page, not a settings row.
The page's action-name table gains a twentieth name and both field pad types
show the run action on Cross, the same button the walk hook waits for. Cross
also cancels in TYPE 1; cancel is edge-triggered, so holding it to run does
not fire it.

FieldTurn swings the heading round in nine frames; holding Cross draws the
same 5/4 masks there too, so turning is as fast as walking while the button
is down.
"""
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
from mips_cpu import CPU, REG  # noqa: E402
import items  # noqa: E402
import strlib  # noqa: E402
import toolbelt  # noqa: E402

BASE = 0x800643C4
SCENE = 0x800C0000
HELD = SCENE + 0x6E504
FRAME = 0x801FF000
SENTINEL = 0x80001000

LAYOUTS = toolbelt.asm_equ('DNG_PAD_LAYOUTS')
ENTRIES = toolbelt.asm_equ('DNG_PAD_LAYOUT_ENTRIES')
NAMES = toolbelt.asm_equ('DNG_PAD_NAMES')
NAME_COUNT = toolbelt.asm_equ('DNG_PAD_NAME_COUNT')
RUN_INDEX = toolbelt.asm_equ('DNG_PAD_RUN_INDEX')
RUN_NAMES = toolbelt.asm_equ('DNG_RUN_PAD_NAMES')
RUN_NAME = toolbelt.asm_equ('DNG_RUN_NAME')
RUN_ROOM = toolbelt.asm_equ('DNG_RUN_NAME_ROOM')
DRAW_LUI = toolbelt.asm_equ('DNG_PAD_DRAW_LUI')
DRAW_ADDIU = toolbelt.asm_equ('DNG_PAD_DRAW_ADDIU')
TURN_FRAME = toolbelt.asm_equ('DNG_TURN_FRAME')

# The 3D column's buttons, in layout-table order, as the game's held-pad bits:
# circle, cross, triangle, square, L1, R1, L2, R2, start, select.
BUTTONS = (0x20, 0x40, 0x10, 0x80, 0x04, 0x08, 0x01, 0x02, 0x800, 0x100)
CALLS = {0x80068C94: 'begin', 0x80068AA0: 'view', 0x800659B4: 'frame',
         0x8007108C: 'zone', 0x80068B64: 'end', 0x80069754: 'tick'}


class RunPatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        armips = ROOT / 'external_tools/armips/armips'
        if not armips.exists():
            raise unittest.SkipTest('requires armips')
        # The generated wording table is part of the fixture: runtext.py owns
        # the run name and PadDrawLayout's copy of the action-name pointers.
        subprocess.run([sys.executable, str(ROOT / 'src/injection/dungeon/runtext.py')],
                       check=True, capture_output=True)
        cls.tmp = tempfile.TemporaryDirectory(prefix='run-')
        work = Path(cls.tmp.name)
        source = work / 'fixture.asm'
        source.write_text(
            '.psx\n'
            f'.include "{ROOT / "src/mods/base/asm/common/addresses.inc"}"\n'
            f'.open "{ROOT / "data/psx/DNG.BIN"}", "{work / "DNG_RUN.BIN"}", {BASE:#x}\n'
            f'.include "{ROOT / "build/runtext_dng.asm"}"\n'
            f'.include "{ROOT / "src/mods/run-in-dungeons/dng.asm"}"\n'
            '.close\n')
        symbols = work / 'fixture.sym'
        result = subprocess.run([str(armips), str(source), '-sym2', str(symbols),
                                 '-erroronwarning'], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.image = (work / 'DNG_RUN.BIN').read_bytes()
        cls.retail = (ROOT / 'data/psx/DNG.BIN').read_bytes()
        cls.symbols = {}
        for line in symbols.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and re.fullmatch(r'[0-9A-Fa-f]{8}', parts[0]):
                cls.symbols[parts[1]] = int(parts[0], 16)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def address(self, name):
        return self.symbols[name]

    def raw(self, address, size):
        return self.image[address - BASE:address - BASE + size]

    def word(self, address):
        return struct.unpack('<I', self.raw(address, 4))[0]

    def retail_byte(self, address):
        return self.retail[address - BASE]

    def run_entries(self):
        """{field layout: the 3D-column entry the run action was put on}."""
        found = {}
        for layout in (0, 1):
            block = self.raw(LAYOUTS + layout * ENTRIES, ENTRIES)
            entries = [i for i in range(10) if block[i] == RUN_INDEX]
            self.assertEqual(len(entries), 1,
                             f'layout {layout} has {len(entries)} run entries')
            found[layout] = entries[0]
        return found

    def run_bit(self, layout):
        return BUTTONS[self.run_entries()[layout]]

    def cpu(self, layout=0, held=0):
        cpu = CPU()
        cpu.load(BASE, self.image)
        cpu.write(0x800A10D8, SCENE)
        cpu.write(HELD, held)
        cpu.r[REG['sp']] = FRAME
        cpu.r[REG['ra']] = SENTINEL
        cpu.r[REG['s0']] = 0x11111111
        cpu.r[REG['s1']] = 0x0000002A
        cpu.r[REG['s2']] = 0x22222222
        cpu.write(FRAME + 0x18, SENTINEL)
        cpu.write(FRAME + 0x14, 0x0000002A)
        cpu.write(FRAME + 0x10, 0x11111111)
        return cpu

    def walk_tile(self, cpu, calls):
        """Run one FieldWalk tile and return the call counts it added."""
        before = dict(calls)
        cpu.r[REG['sp']] = FRAME
        cpu.r[REG['ra']] = SENTINEL
        cpu.r[REG['s0']] = 0x11111111
        cpu.r[REG['s1']] = 0x0000002A
        cpu.start(self.address('dngrun_walk'))

        def intercept(active):
            name = CALLS.get(active.pc)
            if name is None:
                return False
            calls[name] = calls.get(name, 0) + 1
            if name == 'zone':
                self.assertEqual(active.r[REG['a0']], 0)
            active.pc = active.r[REG['ra']]
            active.next_pc = (active.pc + 4) & 0xFFFFFFFF
            active.pending = None
            return True

        cpu.run(SENTINEL, limit=20000, intercept=intercept)
        return {name: calls.get(name, 0) - before.get(name, 0)
                for name in ('begin', 'view', 'frame', 'zone', 'end', 'tick')}

    # ---- the controller page ------------------------------------------

    def test_both_field_layouts_show_run_on_cross(self):
        entries = self.run_entries()
        self.assertEqual({layout: BUTTONS[entry] for layout, entry in entries.items()},
                         {0: 0x40, 1: 0x40})
        # Cross is CANCEL in TYPE 1 and UNUSED in TYPE 2 in retail.
        self.assertEqual(self.retail_byte(LAYOUTS + entries[0]), 2)
        self.assertEqual(self.retail_byte(LAYOUTS + ENTRIES + entries[1]), 0)

    def test_only_the_two_run_entries_differ_from_the_retail_table(self):
        size = 4 * ENTRIES
        expected = bytearray(self.retail[LAYOUTS - BASE:LAYOUTS - BASE + size])
        for layout, entry in self.run_entries().items():
            expected[layout * ENTRIES + entry] = RUN_INDEX
        self.assertEqual(self.raw(LAYOUTS, size), bytes(expected))

    def test_the_page_reads_a_copy_of_the_name_table_with_run_appended(self):
        lui = self.word(DRAW_LUI)
        addiu = self.word(DRAW_ADDIU)
        self.assertEqual((lui >> 26, (lui >> 16) & 31), (0x0F, REG['at']))   # lui at
        self.assertEqual((addiu >> 26, (addiu >> 21) & 31, (addiu >> 16) & 31),
                         (0x09, REG['at'], REG['at']))                      # addiu at,at
        low = addiu & 0xFFFF
        if low & 0x8000:
            low -= 0x10000
        self.assertEqual((((lui & 0xFFFF) << 16) + low) & 0xFFFFFFFF, RUN_NAMES)

        retail = struct.unpack(f'<{NAME_COUNT}I',
                               self.retail[NAMES - BASE:NAMES - BASE + 4 * NAME_COUNT])
        copy = struct.unpack(f'<{NAME_COUNT + 1}I', self.raw(RUN_NAMES, 4 * (NAME_COUNT + 1)))
        self.assertEqual(copy[:-1], retail)
        self.assertEqual(copy[-1], RUN_NAME)

    def test_the_run_name_is_the_wording_table_row(self):
        name = strlib.glossary('runtext')['name']
        row = bytes(items.glyph(c) for c in name) + b'\xFF'
        self.assertLessEqual(len(row), RUN_ROOM)
        self.assertEqual(self.raw(RUN_NAME, len(row)), row)
        # The row is the whole block before the pointer table.
        self.assertEqual(RUN_NAME + RUN_ROOM, RUN_NAMES)
        # Every pointer the page now reads still names a terminated row.
        copy = struct.unpack(f'<{NAME_COUNT + 1}I', self.raw(RUN_NAMES, 4 * (NAME_COUNT + 1)))
        for index, pointer in enumerate(copy):
            self.assertIn(b'\xFF', self.raw(pointer, 20)[:RUN_ROOM],
                          f'action name {index} has no terminator')

    # ---- walking ------------------------------------------------------

    def test_running_keeps_every_advance_and_averages_half_the_frames(self):
        for layout in (0, 1):
            with self.subTest(layout=layout):
                cpu = self.cpu(layout=layout, held=self.run_bit(layout))
                calls, frames = {}, []
                for _ in range(4):
                    counts = self.walk_tile(cpu, calls)
                    self.assertEqual(counts['begin'], 1)
                    self.assertEqual(counts['view'], 9)
                    self.assertEqual(counts['end'], 1)
                    self.assertEqual(counts['tick'], 1)
                    self.assertEqual(counts['zone'], 1)
                    frames.append(counts['frame'])
                # Five frames on the first tile, four on the next: 4.5 of nine.
                self.assertEqual(frames, [5, 4, 5, 4])
                self.assertEqual(sum(frames), 18)
                # The retail epilogue restored s0 and left s2/s1/v0/sp as retail.
                self.assertEqual(cpu.r[REG['v0']], 0x2A)
                self.assertEqual(cpu.r[REG['s0']], 0x11111111)
                self.assertEqual(cpu.r[REG['s1']], 0x2A)
                self.assertEqual(cpu.r[REG['s2']], 0x22222222)
                self.assertEqual(cpu.r[REG['sp']], FRAME + 0x20)

    def test_releasing_the_button_draws_all_frames_and_restarts_the_cycle(self):
        for layout in (0, 1):
            with self.subTest(layout=layout):
                bit = self.run_bit(layout)
                cpu = self.cpu(layout=layout, held=bit)
                calls = {}
                self.assertEqual(self.walk_tile(cpu, calls)['frame'], 5)
                cpu.write(HELD, 0)
                self.assertEqual(self.walk_tile(cpu, calls)['frame'], 9)
                cpu.write(HELD, bit)
                self.assertEqual(self.walk_tile(cpu, calls)['frame'], 5)

    def test_all_speeds_preserve_steps_endpoints_and_exact_average(self):
        for speed, expected in ((2, [5, 4]), (3, [3]), (4, [3, 2, 2, 2])):
            with self.subTest(speed=speed):
                cpu = self.cpu(held=0x40)
                cpu.write(self.address('dng_run_speed'), speed, 1)
                calls = {}
                frames = []
                for _ in expected:
                    counts = self.walk_tile(cpu, calls)
                    self.assertEqual(counts['view'], 9)
                    self.assertEqual(counts['tick'], 1)
                    self.assertEqual(counts['zone'], 1)
                    self.assertTrue(cpu.read(self.address('dng_run_mask'), 2) & (1 << 9))
                    frames.append(counts['frame'])
                self.assertEqual(frames, expected)
                self.assertEqual(sum(frames) * speed, 9 * len(expected))
                cpu.write(HELD, 0)
                self.assertEqual(self.walk_tile(cpu, calls)['frame'], 9)
                cpu.write(HELD, 0x40)
                self.assertEqual(self.walk_tile(cpu, calls)['frame'], expected[0])

    def test_declared_range_targets_the_assembled_speed_byte(self):
        import csv
        import mods
        setting, = mods.by_label()['run-in-dungeons'].ranges
        self.assertEqual((setting.minimum, setting.maximum, setting.step, setting.default),
                         (2, 4, 1, 2))
        with (ROOT / setting.edits).open(newline='') as stream:
            row, = csv.DictReader(stream, delimiter='\t')
        self.assertEqual(row['path'], 'DNG.BIN')
        self.assertEqual(int(row['offset']), self.address('dng_run_speed') - BASE)
        self.assertEqual(int(row['original']), 100)

    def test_only_the_button_the_page_shows_against_run_runs(self):
        for layout in (0, 1):
            with self.subTest(layout=layout):
                bit = self.run_bit(layout)
                for other in BUTTONS:
                    if other == bit:
                        continue
                    cpu = self.cpu(layout=layout, held=other)
                    self.assertEqual(self.walk_tile(cpu, {})['frame'], 9,
                                     f'layout {layout}, held {other:#x} ran')

    def test_triangle_and_r2_do_not_run(self):
        for layout in (0, 1):
            for bit in (0x10, 0x02):
                with self.subTest(layout=layout, held=bit):
                    cpu = self.cpu(layout=layout, held=bit)
                    self.assertEqual(self.walk_tile(cpu, {})['frame'], 9)

    # ---- turning ------------------------------------------------------

    def turn_frames(self, cpu, held, parity=None, drawn_at=None):
        """Call FieldTurn's frame wrapper for each of the nine frames."""
        if parity is not None:
            cpu.write(self.address('dng_run_parity'), parity, 1)
        cpu.write(HELD, held if isinstance(held, int) else held[0])
        drawn = 0
        for i in range(1, 10):
            if not isinstance(held, int):
                cpu.write(HELD, held[i - 1])
            cpu.r[REG['sp']] = FRAME
            cpu.r[REG['ra']] = SENTINEL
            cpu.r[REG['s1']] = i
            cpu.start(self.address('dngrun_turn_frame'))

            def intercept(active, cpu=cpu):
                nonlocal drawn
                if active.pc != 0x800659B4:
                    return False
                drawn += 1
                if drawn_at is not None:
                    drawn_at.append(i)
                active.pc = active.r[REG['ra']]
                active.next_pc = (active.pc + 4) & 0xFFFFFFFF
                active.pending = None
                return True

            cpu.run(SENTINEL, limit=2000, intercept=intercept)
            self.assertEqual(cpu.r[REG['s1']], i, 'the wrapper clobbered s1')
        return drawn

    def test_the_turn_loop_calls_the_frame_wrapper(self):
        jal = self.word(TURN_FRAME)
        self.assertEqual(jal >> 26, 0x03)                      # jal
        target = ((TURN_FRAME + 4) & 0xF0000000) | ((jal & 0x03FFFFFF) << 2)
        self.assertEqual(target, self.address('dngrun_turn_frame'))

    def test_turning_draws_the_run_masks_when_cross_is_held(self):
        cpu = self.cpu(held=0x40)
        # The first turn takes the dense mask (five frames), the next the
        # sparse one (four), exactly like the walk tiles.
        self.assertEqual([self.turn_frames(cpu, 0x40) for _ in range(4)],
                         [5, 4, 5, 4])

    def test_turning_without_cross_draws_every_frame_and_resets_the_mask(self):
        cpu = self.cpu(held=0)
        self.assertEqual(self.turn_frames(cpu, 0, parity=1), 9)
        self.assertEqual(cpu.read(self.address('dng_run_parity'), 1), 0)

    def test_turning_uses_each_selected_speed_and_preserves_return(self):
        for speed, expected in ((2, [5, 4]), (3, [3]), (4, [3, 2, 2, 2])):
            with self.subTest(speed=speed):
                cpu = self.cpu(held=0x40)
                cpu.write(self.address('dng_run_speed'), speed, 1)
                self.assertEqual([self.turn_frames(cpu, 0x40) for _ in expected], expected)
                self.assertEqual(cpu.r[REG['sp']], FRAME)
                self.assertEqual(cpu.r[REG['ra']], SENTINEL)
                self.assertEqual(self.turn_frames(cpu, 0), 9)
                self.assertEqual(self.turn_frames(cpu, 0x40), expected[0])


    def test_press_and_release_during_a_turn_still_draw_the_endpoint(self):
        for speed in (2, 3, 4):
            for held in ([0]*4 + [0x40]*5, [0]*7 + [0x40]*2,
                         [0x40]*2 + [0] + [0x40]*6):
                with self.subTest(speed=speed, held=held):
                    cpu = self.cpu()
                    cpu.write(self.address('dng_run_speed'), speed, 1)
                    frames = []
                    self.turn_frames(cpu, held, drawn_at=frames)
                    self.assertIn(9, frames)
                    self.assertTrue(cpu.read(self.address('dng_run_mask'), 2) & (1 << 9))
                    self.assertEqual(cpu.r[REG['sp']], FRAME)
                    self.assertEqual(cpu.r[REG['ra']], SENTINEL)


if __name__ == '__main__':
    unittest.main()
