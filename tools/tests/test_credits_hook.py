"""The staff-roll shortcut's title hook (credits/open.asm, credits/slps.asm).

Select on the title is unused, so OPEN.EXE claims it: the hook writes the
sentinel into g_title_choice and returns through the menu's own epilogue.
The resident reads g_title_choice and indexes retail's five-entry switch;
its hook sends every press to the dispatch in OPEN.EXE (mapped while the
title executes). The dispatch starts END.EXE ending 5 for the sentinel and
otherwise reproduces retail's bounds test and rejoins the untouched lookup
at 0x80011558, so a retail choice runs the same instructions in the same
order.

These tests pin both halves: the bytes (the lookup, the removed bounds test,
the neighbours) and the real behaviour on the R3000 (every retail choice
lands on its own case; out-of-range values fall through; the sentinel sets
the movie state).
"""
from pathlib import Path
import struct
import sys
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
SLPS_BASE = 0x80010000
OPEN_BASE = 0x80080000

RESIDENT_SWITCH = 0x80011550
RESIDENT_LOOKUP = 0x80011558
RESIDENT_TABLE = 0x80010138
RESIDENT_FALLTHROUGH = 0x800113F0
KEY_HOOK = 0x8008B53C
CONFIRM_PATH = 0x80081D94
NO_CONFIRM_PATH = 0x80082138
CHOICE_EPILOGUE = 0x80082250
DISPATCH = 0x8008B57C
DEAD_END = 0x8008B5C0

TITLE_CHOICE = 0x801F15B8
CARD_SCAN = 0x800B359C
MOVIE_ID = 0x801F15C2
MOVIE_NEXT = 0x801F15C4
GP_SCRATCH = 0x801F1500
STATE_NEXT = 0x68

# OPEN.EXE's own gp, its InitPAD port-1 buffer and the pad update in the
# title loop (0x800826A0: read held from the buffer, derive the press).
OPEN_GP = 0x800B3530
PAD_BUF = 0x800B358C
PAD_PRESS = 0xC
PAD_UPDATE = 0x800826A0
PAD_UPDATE_END = 0x800826F4

RETURN = 0xDEAD0000


def jal(target):
    return 0x0C000000 | ((target >> 2) & 0x03FFFFFF)


def j(target):
    return 0x08000000 | ((target >> 2) & 0x03FFFFFF)


def branch(op, rs, rt, pc, target):
    return (op << 26) | (rs << 21) | (rt << 16) | (((target - (pc + 4)) >> 2) & 0xFFFF)


class CreditsHook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [ROOT / 'build' / 'SLPS_005.00', ROOT / 'build/EXE/OPEN.EXE']
        if not all(path.exists() for path in paths):
            raise unittest.SkipTest('requires the assembled SLPS and OPEN.EXE')
        cls.slps = paths[0].read_bytes()
        cls.open = paths[1].read_bytes()
        cls.retail_slps = (ROOT / 'data/psx/SLPS_005.00').read_bytes()
        cls.retail_open = (ROOT / 'data/psx/EXE/OPEN.EXE').read_bytes()

    def word(self, data, base, address):
        return struct.unpack_from('<I', data, address - base + 0x800)[0]

    def half(self, data, base, address):
        return struct.unpack_from('<H', data, address - base + 0x800)[0]

    # -------------------------------------------------------------
    # bytes: only the bounds test moved; retail's lookup is untouched
    # -------------------------------------------------------------

    def test_resident_hook_replaces_only_the_bounds_test(self):
        # the hook is one jump; the delay slot is a nop
        self.assertEqual(self.word(self.slps, SLPS_BASE, RESIDENT_SWITCH),
                         j(DISPATCH))
        self.assertEqual(self.word(self.slps, SLPS_BASE, RESIDENT_SWITCH + 4), 0)
        # retail's index shift, lui and table lookup must survive verbatim
        for address in range(RESIDENT_LOOKUP, 0x80011574 + 4, 4):
            self.assertEqual(self.word(self.slps, SLPS_BASE, address),
                             self.word(self.retail_slps, SLPS_BASE, address),
                             f'0x{address:08x} is retail')

    def test_open_hook_and_dispatch_live_in_the_dead_function(self):
        self.assertEqual(self.word(self.open, OPEN_BASE, 0x80081D88), j(KEY_HOOK))
        self.assertEqual(self.word(self.open, OPEN_BASE, 0x80081D8C), 0)
        # retail's own nop at 0x80081D90 and the confirm path stay as shipped
        self.assertEqual(self.word(self.open, OPEN_BASE, 0x80081D90),
                         self.word(self.retail_open, OPEN_BASE, 0x80081D90))
        self.assertEqual(self.word(self.open, OPEN_BASE, CONFIRM_PATH),
                         self.word(self.retail_open, OPEN_BASE, CONFIRM_PATH))
        # the dead function's next neighbour is untouched
        self.assertEqual(self.word(self.open, OPEN_BASE, DEAD_END),
                         self.word(self.retail_open, OPEN_BASE, DEAD_END))

        # the Select path: sentinel + card scan -1, through the epilogue
        self.assertEqual(self.word(self.open, OPEN_BASE, KEY_HOOK), 0x30620100)   # andi v0,v1,0x100
        self.assertEqual(self.word(self.open, OPEN_BASE, KEY_HOOK + 4),
                         branch(5, 2, 0, KEY_HOOK + 4, KEY_HOOK + 0x20))          # bnez
        self.assertEqual(self.word(self.open, OPEN_BASE, KEY_HOOK + 0x20), 0x3C01801F)  # lui at,0x801f
        self.assertEqual(self.word(self.open, OPEN_BASE, KEY_HOOK + 0x24), 0x340200FE)  # ori v0,0,0xfe
        self.assertEqual(self.word(self.open, OPEN_BASE, KEY_HOOK + 0x28), 0xA02215B8)  # sb
        self.assertEqual(self.word(self.open, OPEN_BASE, KEY_HOOK + 0x38), j(CHOICE_EPILOGUE))

        # the dispatch: sentinel first, retail bounds + lookup second
        self.assertEqual(self.word(self.open, OPEN_BASE, DISPATCH), 0x2462FF02)  # addiu v0,v1,-0xfe
        self.assertEqual(self.word(self.open, OPEN_BASE, DISPATCH + 4),
                         branch(5, 2, 0, DISPATCH + 4, DISPATCH + 0x28))         # bnez
        self.assertEqual(self.word(self.open, OPEN_BASE, DISPATCH + 8), 0x3C01801F)  # lui at,0x801f
        self.assertEqual(self.word(self.open, OPEN_BASE, DISPATCH + 0x0C), 0x34020035)  # ori v0,0,0x35
        self.assertEqual(self.word(self.open, OPEN_BASE, DISPATCH + 0x10), 0xA42215C2)  # sh v0,0x15c2(at)
        self.assertEqual(self.word(self.open, OPEN_BASE, DISPATCH + 0x18), 0xAC2215C4)  # sw v0,0x15c4(at)
        self.assertEqual(self.word(self.open, OPEN_BASE, DISPATCH + 0x20), 0xAF820068)  # sw v0,0x68(gp)
        self.assertEqual(self.word(self.open, OPEN_BASE, DISPATCH + 0x24),
                         j(DISPATCH + 0x3C))                                     # shared return
        self.assertEqual(self.word(self.open, OPEN_BASE, DISPATCH + 0x28), 0x2C620005)  # sltiu v0,v1,5
        self.assertEqual(self.word(self.open, OPEN_BASE, DISPATCH + 0x2C),
                         branch(4, 2, 0, DISPATCH + 0x2C, DISPATCH + 0x3C))      # beqz
        self.assertEqual(self.word(self.open, OPEN_BASE, DISPATCH + 0x34), j(RESIDENT_LOOKUP))
        self.assertEqual(self.word(self.open, OPEN_BASE, DISPATCH + 0x3C),
                         j(RESIDENT_FALLTHROUGH))
        self.assertEqual(DISPATCH + 0x44, DEAD_END)   # fills the dead function exactly

    # -------------------------------------------------------------
    # runtime: the R3000 executes the real chain
    # -------------------------------------------------------------

    def machine(self):
        cpu = CPU()
        size = struct.unpack_from('<I', self.slps, 0x1C)[0]
        cpu.load(SLPS_BASE, self.slps[0x800:0x800 + size])
        size = struct.unpack_from('<I', self.open, 0x1C)[0]
        cpu.load(OPEN_BASE, self.open[0x800:0x800 + size])
        cpu.r[REG['gp']] = GP_SCRATCH
        return cpu

    def press(self, byte2, byte3):
        """The title's press word for raw InitPAD bytes (active low)."""
        cpu = self.machine()
        cpu.r[REG['gp']] = OPEN_GP
        cpu.load(OPEN_GP + 4, b'\x00' * 4)      # last frame: nothing held
        cpu.load(PAD_BUF, bytes((0xFF, 0x41, byte2, byte3)))
        cpu.start(PAD_UPDATE)
        cpu.run(PAD_UPDATE_END)
        return cpu.read(OPEN_GP + PAD_PRESS) & 0xFFFF

    def test_the_select_bit_is_the_games_own_pad_word(self):
        # InitPAD's port-1 buffer is status, id, Select..Left, L2..Square;
        # the title loop shifts the third byte into the high half.
        select = self.press(0xFE, 0xFF)     # Select: byte 2, bit 0
        circle = self.press(0xFF, 0xDF)     # Circle: byte 3, bit 5
        start = self.press(0xF7, 0xFF)      # Start:  byte 2, bit 3
        self.assertEqual(select, 0x0100)
        self.assertEqual(circle, 0x0020)
        self.assertEqual(start, 0x0800)
        # and the hook tests exactly that bit, not a hand-guessed one
        hook = self.word(self.open, OPEN_BASE, KEY_HOOK)
        self.assertEqual(hook >> 26, 0x0C, 'andi')
        self.assertEqual((hook >> 21) & 31, 3, 'v1 (source)')
        self.assertEqual((hook >> 16) & 31, 2, 'v0 (dest)')
        self.assertEqual(hook & 0xFFFF, select)

    def test_every_retail_choice_lands_on_its_own_case(self):
        # retail's own five-entry table, read from the retail image
        targets = [self.word(self.retail_slps, SLPS_BASE, RESIDENT_TABLE + 4 * i)
                   for i in range(5)]
        for choice, target in enumerate(targets):
            with self.subTest(choice=choice):
                cpu = self.machine()
                cpu.r[REG['v1']] = choice
                cpu.start(RESIDENT_SWITCH)
                cpu.run(target)
                self.assertEqual(cpu.r[REG['v0']], target)
                self.assertEqual(cpu.r[REG['at']], RESIDENT_TABLE + 4 * choice)

    def test_out_of_range_values_take_retail_fallthrough(self):
        for choice in (5, 0xFF):
            with self.subTest(choice=choice):
                cpu = self.machine()
                cpu.r[REG['v1']] = choice
                cpu.load(MOVIE_ID, b'\xAA' * 2)
                cpu.load(MOVIE_NEXT, b'\xAA' * 4)
                cpu.load(GP_SCRATCH + STATE_NEXT, b'\xAA' * 4)
                cpu.start(RESIDENT_SWITCH)
                cpu.run(RESIDENT_FALLTHROUGH)
                self.assertEqual(cpu.read(MOVIE_ID, 2), 0xAAAA)
                self.assertEqual(cpu.read(MOVIE_NEXT), 0xAAAAAAAA)
                self.assertEqual(cpu.read(GP_SCRATCH + STATE_NEXT), 0xAAAAAAAA)

    def test_the_sentinel_starts_the_credits_ending(self):
        cpu = self.machine()
        cpu.r[REG['v1']] = 0xFE
        cpu.load(MOVIE_ID - 4, b'\xAA' * 8)
        cpu.load(GP_SCRATCH + STATE_NEXT, b'\xAA' * 4)
        cpu.start(RESIDENT_SWITCH)
        cpu.run(RESIDENT_FALLTHROUGH)
        self.assertEqual(cpu.read(MOVIE_ID, 2), 0x35)          # g_movie_id: ending 5
        self.assertEqual(cpu.read(MOVIE_NEXT), 0xFFFFFFFF)      # back to the title
        self.assertEqual(cpu.read(GP_SCRATCH + STATE_NEXT), 6)  # GAME_STATE_MOVIE

    def test_select_writes_the_sentinel_and_the_confirm_unchanged(self):
        cpu = self.machine()
        cpu.r[REG['v1']] = self.press(0xFE, 0xFF)               # Select
        cpu.load(TITLE_CHOICE, b'\xAA')
        cpu.load(CARD_SCAN, b'\xAA' * 4)
        cpu.start(KEY_HOOK)
        cpu.run(CHOICE_EPILOGUE)
        self.assertEqual(cpu.read(TITLE_CHOICE, 1), 0xFE)
        self.assertEqual(cpu.read(CARD_SCAN), 0xFFFFFFFF)

        # a retail confirm press still runs retail's own path
        for press in (self.press(0xFF, 0xDF), self.press(0xF7, 0xFF)):
            with self.subTest(press=press):
                cpu = self.machine()
                cpu.r[REG['v1']] = press
                cpu.start(KEY_HOOK)
                cpu.run(CONFIRM_PATH)

        # no confirm press still goes where retail sent it
        cpu = self.machine()
        cpu.r[REG['v1']] = 0
        cpu.start(KEY_HOOK)
        cpu.run(NO_CONFIRM_PATH)


if __name__ == '__main__':
    unittest.main()
