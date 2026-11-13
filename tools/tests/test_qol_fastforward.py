"""--qol=fastforward: START fast-forwards a battle turn (qol/fastforward_btlp.asm).

BtlDrawFrame runs on the R3000 model, tick after tick, with every library and
battle call it makes stubbed and recorded. Off, each tick is retail's: VSync,
PutDispEnv, PutDrawEnv of the frame's own DRAWENV, DrawOTag, in that order,
for the alternating buffers. On, ticks run in groups of FF_RATE: only tick 0
waits for the vblank and shows a frame, ticks 1.. draw no object, build no
arena or mesh and hand the GPU an empty drawing area, the last tick draws for
real, and every tick still submits its ordering table. BtlDrawObjects' two
hooks run on their own as well. Assembled with and without --qol=battlespeed (which owns the
half-rate second VSync).
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/tests')]
from mips_cpu import CPU, REG  # noqa: E402

BTLP = 0x800643C4
FRAME = 0x80080F14
SENTINEL = 0x80001000
G = 0x800D0000
POOL = 0x80100000
STRIDE = 0xE660
PAD1_EDGE = 0x800F88F0
STEP, AUTO, HALF_RATE, VSYNC_COUNT = G - 0xF95, G + 0x2250, G - 0xF8D, G - 0xF6B
FRAME_INDEX, CLOSING = G - 0xF08, G - 0xF8C
VSYNC, PUT_DISP, PUT_DRAW, DRAW_OTAG = 0x80025C98, 0x8002BD98, 0x8002BBC0, 0x8002BB4C
STUBS = {0x8008EA70, 0x8008F05C, 0x8001950C, 0x8001B6DC, 0x8001B06C, 0x80018E2C,
         0x80082310, 0x8002B99C, 0x8008B620, 0x8008AF14, 0x8008B230, 0x8008B13C,
         0x80082718, 0x8006B8EC, 0x80065E98, 0x800667BC, 0x8002B54C, 0x8002B810,
         0x8002B5E8, VSYNC, PUT_DISP, PUT_DRAW, DRAW_OTAG, 0x8008E980}
START = 0x800
RATE = int(re.search(r'^FF_RATE\s+equ\s+(\d+)', (ROOT / 'src/asm/common/addresses.inc')
                     .read_text(), re.M)[1])


def assemble(work, *defines):
    armips = ROOT / 'external_tools/armips/armips'
    source = work / 'ff.asm'
    out = work / ('BTLP' + ''.join(defines) + '.BIN')
    source.write_text(
        '.psx\n'
        f'.include "{ROOT / "src/asm/common/addresses.inc"}"\n'
        f'.open "{ROOT / "data/psx/BTLP.BIN"}", "{out}", {BTLP:#x}\n'
        f'.include "{ROOT / "src/asm/qol/fastforward_btlp.asm"}"\n'
        '.close\n')
    symbols = work / 'ff.sym'
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

    def tick(self, press=0, step=1, auto=0):
        c = self.c
        self.press = press
        c.write(STEP, step, 1)
        c.write(AUTO, auto, 1)
        c.r[REG['sp']] = 0x801FF000
        c.r[REG['ra']] = SENTINEL
        c.r[REG['s1']] = 0x5151
        self.calls = []
        frame = c.read(FRAME_INDEX, 1)
        c.start(FRAME)
        c.run(SENTINEL, 20000, self.intercept)
        self.assertions(frame)
        return self.calls

    def assertions(self, frame):
        c = self.c
        assert c.r[REG['sp']] == 0x801FF000 and c.r[REG['s1']] == 0x5151
        assert c.read(FRAME_INDEX, 1) == frame ^ 1          # buffers alternate every tick
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
        assert tail[-2:] == [DRAW_OTAG, 0x8008E980]
        return ('shown+' if shown else '') + ('empty' if empty else 'drawn')


class FastForward(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / 'external_tools/armips/armips').exists():
            raise unittest.SkipTest('requires armips')
        Path('/tmp/opencode').mkdir(exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(prefix='ff-', dir='/tmp/opencode')
        work = Path(cls.tmp.name)
        cls.alone, cls.sym = assemble(work)
        cls.with_speed, _ = assemble(work, 'QOL_BATTLESPEED')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_off_is_the_retail_tick(self):
        b = Battle(self.with_speed)
        for t in range(4):
            calls = b.tick()
            self.assertEqual(b.kind(calls), 'shown+drawn')
            f = t & 1
            self.assertIn((PUT_DISP, POOL + f * STRIDE + 0x5C), calls)
            self.assertIn((DRAW_OTAG, POOL + f * STRIDE + 0xD6C0), calls)

    def test_start_during_a_turn_runs_groups(self):
        b = Battle(self.with_speed)
        b.tick()
        b.tick(press=START)
        self.assertEqual(b.c.read(PAD1_EDGE, 2), 0)          # consumed
        kinds = [b.kind(b.tick()) for _ in range(3 * RATE)]
        group = ['shown+empty'] + ['empty'] * (RATE - 2) + ['drawn']
        self.assertEqual(kinds, group * 3)
        # drawn ticks alternate buffers (RATE is odd), so none draws the one on screen
        drawn = [i for i, k in enumerate(kinds) if k == 'drawn']
        self.assertEqual({(d + 1) & 1 for d in drawn[::2]} & {(d + 1) & 1 for d in drawn[1::2]},
                         set())
        # START again: the group in progress finishes first, then retail ticks
        kinds = [b.kind(b.tick(press=START if i == 0 else 0)) for i in range(RATE + 2)]
        self.assertEqual(kinds, ['shown+empty'] + ['empty'] * (RATE - 2) + ['drawn']
                         + ['shown+drawn'] * 2)

    def test_the_command_menu_ends_it_and_keeps_start(self):
        b = Battle(self.with_speed)
        b.tick(press=START)
        b.tick(press=START, step=0)                          # command menu: the game's Start
        self.assertEqual(b.c.read(PAD1_EDGE, 2), START)
        self.assertEqual(b.kind(b.tick(step=0)), 'shown+drawn')
        b.tick(press=START, step=0, auto=1)                  # AUTO between rounds: a turn
        self.assertEqual(b.c.read(PAD1_EDGE, 2), 0)
        self.assertEqual(b.kind(b.tick(step=0, auto=1)), 'shown+empty')
        for _ in range(RATE - 1):
            b.tick(step=0)                                   # AUTO stopped mid-group
        self.assertEqual(b.kind(b.tick(step=0)), 'shown+drawn')

    def test_icon_links_into_the_last_ot_entry_only_while_on(self):
        b = Battle(self.with_speed)
        entry = POOL + 0xE65C
        b.c.write(entry, 0x00FFFFFF)
        b.tick()
        self.assertEqual(b.c.read(entry), 0x00FFFFFF)
        b.tick(press=START)                                  # buffer 1
        b.c.write(entry, 0x00FFFFFF)
        b.tick()                                             # buffer 0, on
        prims = self.sym['ff_prims']
        first = b.c.read(entry)
        self.assertEqual(first, prims & 0xFFFFFF)
        self.assertEqual(b.c.read(prims), 0x04000000 | (prims + 20) & 0xFFFFFF)
        self.assertEqual(b.c.read(prims + 20), 0x04FFFFFF)
        self.assertEqual(b.c.read(prims + 4) >> 24, 0x20)    # POLY_F3

    def test_alone_it_keeps_the_half_rate_wait(self):
        for image, waits in ((self.alone, 2), (self.with_speed, 1)):
            b = Battle(image)
            b.c.write(HALF_RATE, 1, 1)
            b.c.write(VSYNC_COUNT, 0, 1)
            calls = b.tick()
            self.assertEqual([pc for pc, *_ in calls].count(VSYNC), waits)

    def hidden_flag(self, b, hidden):
        b.c.write(self.sym['ff_vars'] + 2, hidden, 1)

    def test_a_hidden_tick_draws_no_object(self):
        for image in (self.alone, self.with_speed):
            for hidden, reached in ((0, 0x80087B80), (1, 0x80082AA4)):
                b = Battle(image)
                self.hidden_flag(b, hidden)
                c = b.c
                c.r[REG['v0']], c.r[REG['s0']] = 0x80087B80, 0x80123400   # the delay slot: a0 = s0
                c.r[REG['ra']] = 0x80082AA4
                c.start(0x80082A9C)
                c.step()
                c.step()                                     # the call and its delay slot
                for _ in range(20):
                    if c.pc in (0x80087B80, 0x80082AA4):
                        break
                    c.step()
                self.assertEqual(c.pc, reached)
                self.assertEqual(c.r[REG['a0']], 0x80123400)
                if not hidden:
                    self.assertEqual(c.r[REG['ra']], 0x80082AA4)

    def test_a_hidden_tick_builds_no_arena_or_mesh(self):
        for hidden in (0, 1):
            b = Battle(self.with_speed)
            self.hidden_flag(b, hidden)
            c = b.c
            c.write(G - 0xF06, 1, 1)
            c.start(0x80082E6C)
            seen = []
            for _ in range(40):
                if c.pc in (0x80082E74, 0x800830FC):
                    break
                if c.pc == 0x80029E8C:
                    seen.append(c.r[REG['a0']])
                    c.pc = c.r[REG['ra']]
                    c.next_pc = c.pc + 4
                    continue
                c.step()
            if hidden:
                self.assertEqual((c.pc, seen), (0x800830FC, [100]))
            else:
                self.assertEqual((c.pc, seen, c.r[REG['v0']]), (0x80082E74, [], 1))

    def test_only_the_hook_sites_and_the_dead_function_change(self):
        retail = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        for image in (self.alone, self.with_speed):
            for i in range(0, len(retail), 4):
                if image[i:i + 4] != retail[i:i + 4]:
                    address = BTLP + i
                    self.assertTrue(0x80080F2C <= address < 0x80081358
                                    or 0x80065D88 <= address < 0x80065E98
                                    or address in (0x80098D30, 0x80098D38, 0x80082A9C,
                                                   0x80082E6C, 0x80082E70), hex(address))


if __name__ == '__main__':
    unittest.main()
