"""--mods=battle-speedup: a turn's parts and the entry camera in groups of hidden ticks (mods/battle-speedup/btlp.asm).

BtlDrawFrame runs on the R3000 model, tick after tick, with every library and
battle call it makes stubbed and recorded. With the speed at 1 each tick is
retail's. A group of N ticks waits for retail's vblanks and shows a frame
once, its first N - 1 ticks draw no object and hand the GPU an empty drawing
area, its last tick draws; a drawn tick flips the buffers, a hidden one keeps
its buffer, so drawn ticks alternate buffers for any N.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
import toolpath  # noqa: E402,F401  (every tool folder on sys.path)
from mips_cpu import CPU, REG  # noqa: E402

BTLP = 0x800643C4
FRAME = 0x80080F14
SENTINEL = 0x80001000
G = 0x800D0000
POOL = 0x80100000
STRIDE = 0xE660
PAD1_EDGE = 0x800F88F0
STAGE, AUTO, HALF_RATE, VSYNC_COUNT = G - 0xF96, G + 0x2250, G - 0xF8D, G - 0xF6B
INTRO_STEP = G - 0xF8F
FRAME_INDEX, CLOSING = G - 0xF08, G - 0xF8C
VSYNC, PUT_DISP, PUT_DRAW, DRAW_OTAG = 0x80025C98, 0x8002BD98, 0x8002BBC0, 0x8002BB4C
STUBS = {0x8008EA70, 0x8008F05C, 0x8001950C, 0x8001B6DC, 0x8001B06C, 0x80018E2C,
         0x80082310, 0x8002B99C, 0x8008B620, 0x8008AF14, 0x8008B230, 0x8008B13C,
         0x80082718, 0x8006B8EC, 0x80065E98, 0x800667BC, 0x8002B54C, 0x8002B810,
         0x8002B5E8, VSYNC, PUT_DISP, PUT_DRAW, DRAW_OTAG, 0x8008E980}


def assemble(work, *defines):
    armips = ROOT / 'external_tools/armips/armips'
    source = work / 'bs.asm'
    out = work / ('BTLP' + ''.join(defines) + '.BIN')
    source.write_text(
        '.psx\n'
        f'.include "{ROOT / "src/mods/base/asm/common/addresses.inc"}"\n'
        f'.open "{ROOT / "data/psx/BTLP.BIN"}", "{out}", {BTLP:#x}\n'
        f'.include "{ROOT / "src/mods/battle-speedup/btlp.asm"}"\n'
        '.close\n')
    symbols = work / 'bs.sym'
    args = [str(armips), str(source), '-sym2', str(symbols), '-erroronwarning']
    for name in defines:
        args += ['-definelabel', name, '1']
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    sym = {}
    for line in symbols.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            sym[parts[1].lower()] = int(parts[0], 16)
    return out.read_bytes(), sym


class Battle:
    """One battle's worth of BTLP state and the calls its frames make."""

    def __init__(self, image):
        self.c = c = CPU()
        c.load(BTLP, image)
        c.write(G - 0xF68, POOL)
        for f in (0, 1):
            env = POOL + f * STRIDE
            c.write(env, (240 * f) << 16)          # clip x 0, y 0 / 240
            c.write(env + 4, (240 << 16) | 320)    # clip w 320, h 240
            c.write(env + 0x18, 1, 1)              # isbg
        self.calls = []
        self.buffers = []                          # each tick's frame buffer

    def intercept(self, c):
        if c.pc not in STUBS:
            return False
        a0 = c.r[REG['a0']]
        entry = [c.pc, a0]
        if c.pc == PUT_DRAW:
            entry += [c.read(a0), c.read(a0 + 4), c.read(a0 + 0x18, 1)]
        if c.pc == 0x8008E980:                     # BtlPadRead: this tick's fresh presses
            c.write(PAD1_EDGE, self.press, 2)
        self.calls.append(tuple(entry))
        c.pc = c.r[REG['ra']]
        c.next_pc = c.pc + 4
        return True

    def tick(self, press=0, stage=2, auto=0, step=0):
        c = self.c
        self.press = press
        c.write(STAGE, stage, 1)
        c.write(G - 0xF95, step, 1)                          # g_btl_step
        c.write(AUTO, auto, 1)
        c.r[REG['sp']] = 0x801FF000
        c.r[REG['ra']] = SENTINEL
        c.r[REG['s1']] = 0x5151
        self.calls = []
        frame = c.read(FRAME_INDEX, 1)
        c.start(FRAME)
        c.run(SENTINEL, 20000, self.intercept)
        self.assertions(frame)
        self.buffers.append(frame)
        return self.calls

    def assertions(self, frame):
        c = self.c
        assert c.r[REG['sp']] == 0x801FF000 and c.r[REG['s1']] == 0x5151
        hidden = any(e[0] == PUT_DRAW and e[2:] == (0x00010001, 0, 0) for e in self.calls)
        assert c.read(FRAME_INDEX, 1) == frame ^ (0 if hidden else 1)   # a drawn tick flips
        env = POOL + frame * STRIDE
        assert (c.read(env), c.read(env + 4), c.read(env + 0x18, 1)) == \
            ((240 * frame) << 16, (240 << 16) | 320, 1)     # DRAWENV left as it was

    def kind(self, calls):
        """'shown+drawn', 'shown+empty', 'drawn', 'empty' for one tick."""
        names = [pc for pc, *_ in calls]
        tail = names[names.index(0x8002B5E8) + 1:]
        shown = tail[:2] == [VSYNC, PUT_DISP]
        draw = next(e for e in calls if e[0] == PUT_DRAW)
        empty = draw[2:] == (0x00010001, 0, 0)
        assert empty or draw[3] == (240 << 16) | 320
        assert tail[-2:] == [DRAW_OTAG, 0x8008E980] or (
            empty and tail[-3:] == [DRAW_OTAG, 0x8002B5E8, 0x8008E980])  # hidden: DrawSync
        return ('shown+' if shown else '') + ('empty' if empty else 'drawn')


class BattleSpeedup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / 'external_tools/armips/armips').exists():
            raise unittest.SkipTest('requires armips')
        cls.tmp = tempfile.TemporaryDirectory(prefix='bs-')
        work = Path(cls.tmp.name)
        cls.image, cls.sym = assemble(work, 'MOD_BATTLE_SPEEDUP')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def speeds(self, b, actions=1, skills=1, entry=1):
        """The three ranges' bytes (bs_vars ACTIONS SKILLS ENTRY)."""
        for offset, value in ((5, actions), (6, skills), (7, entry)):
            b.c.write(self.sym['bs_vars'] + offset, value, 1)

    def assert_drawn_alternate(self, b, kinds):
        first = len(b.buffers) - len(kinds)
        drawn = [b.buffers[first + i] for i, k in enumerate(kinds) if k.endswith('drawn')]
        self.assertTrue(all(x != y for x, y in zip(drawn, drawn[1:])), drawn)

    def test_a_speed_of_one_is_the_retail_tick(self):
        b = Battle(self.image)
        self.speeds(b)
        b.c.write(HALF_RATE, 1, 1)
        b.c.write(INTRO_STEP, 4, 1)
        for t in range(4):
            calls = b.tick()
            self.assertEqual(b.kind(calls), 'shown+drawn')
            f = t & 1
            self.assertIn((PUT_DISP, POOL + f * STRIDE + 0x5C), calls)
            self.assertIn((DRAW_OTAG, POOL + f * STRIDE + 0xD6C0), calls)

    def test_a_turn_runs_in_groups(self):
        for speed in (2, 3, 4):
            # the rest of a turn runs `actions`, the half-rate effects `skills`
            for half_rate, wait, n in ((0, 1, speed), (1, 2, speed + 1)):
                b = Battle(self.image)
                self.speeds(b, actions=speed, skills=speed + 1)
                b.c.write(HALF_RATE, half_rate, 1)
                kinds, waits = [], []
                for _ in range(3 * n):
                    b.c.write(VSYNC_COUNT, 0, 1)
                    calls = b.tick(stage=2)
                    kinds.append(b.kind(calls))
                    waits.append([pc for pc, *_ in calls].count(VSYNC))
                group = ['shown+empty'] + ['empty'] * (n - 2) + ['drawn']
                self.assertEqual(kinds, group * 3)
                self.assertEqual(waits, ([wait] + [0] * (n - 1)) * 3)   # retail's waits a shown frame
                self.assert_drawn_alternate(b, kinds)
                self.assertEqual([b.kind(b.tick(stage=1, auto=1)) for _ in range(n)], group)  # AUTO
                self.assertEqual([b.kind(b.tick(stage=1)) for _ in range(2)],
                                 ['shown+drawn'] * 2)     # the command stage: retail ticks

    def test_the_entry_camera_follows_its_speed(self):
        b = Battle(self.image)
        self.speeds(b, actions=3, skills=3, entry=2)
        b.c.write(INTRO_STEP, 4, 1)
        kinds = [b.kind(b.tick(stage=0)) for _ in range(6)]
        self.assertEqual(kinds, ['shown+empty', 'drawn'] * 3)
        self.assert_drawn_alternate(b, kinds)
        b.c.write(INTRO_STEP, 0, 1)
        self.assertEqual(b.kind(b.tick(stage=0)), 'shown+drawn')
        b = Battle(self.image)                           # `entry` 1: the retail camera
        self.speeds(b, actions=2, skills=2, entry=1)
        b.c.write(INTRO_STEP, 4, 1)
        self.assertEqual([b.kind(b.tick(stage=0)) for _ in range(2)], ['shown+drawn'] * 2)

    def test_only_the_hook_sites_and_the_dead_function_change(self):
        retail = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        for i in range(0, len(retail), 4):
            if self.image[i:i + 4] != retail[i:i + 4]:
                address = BTLP + i
                self.assertTrue(0x80080F2C <= address < 0x80081358
                                or 0x80065D88 <= address < 0x80065E98
                                or address in (0x80082A9C, 0x80082E6C, 0x80082E70), hex(address))


if __name__ == '__main__':
    unittest.main()
