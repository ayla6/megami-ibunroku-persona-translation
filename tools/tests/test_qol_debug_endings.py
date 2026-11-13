"""--qol=debug reaches every ending from the title.

OPEN.EXE: on the title menu L1/L2/R1/R2/Select set the resident's movie
globals and its own g_state_next (off the resident's gp, not OPEN's) and leave
through the menu's retail tail with a choice no title case takes; any other
press reaches the retail confirm test with the pressed word intact.

END.EXE: holding R1 skips EndDraw's vblank wait, Start during an ending movie
raises g_end_movie_done. Both stubs otherwise reach VSync unchanged, and only
the hook sites and the dead functions they use change in either image.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/tests')]
from mips_cpu import CPU, REG  # noqa: E402

IMAGE = 0x80080000
OPEN_GP = 0x800B3530
END_GP = 0x800AD2B4
CONFIRM = 0x80081D88               # retail andi v1, 0x820
TAIL = 0x8008223C                  # retail: store the choice, card scan -1
MOVIE_ID = 0x801F15C2
MOVIE_NEXT = 0x801F15C4
STATE_NEXT = 0x80055C5C            # resident g_state_next (gp 0x80055BF4 + 0x68)
END_VSYNC = 0x8008CA8C
SENTINEL = 0x80001000
L2, R2, L1, R1, SELECT, START, CIRCLE = 0x1, 0x2, 0x4, 0x8, 0x100, 0x800, 0x20


def assemble(exe, patch, work):
    armips = ROOT / 'external_tools/armips/armips'
    source = work / f'{exe}.asm'
    source.write_text(
        '.psx\n'
        f'.include "{ROOT / "src/asm/common/addresses.inc"}"\n'
        f'.open "{ROOT / "data/psx/EXE" / exe}", "{work / exe}", 0x80080000 - 0x800\n'
        f'.include "{ROOT / "src/asm/qol" / patch}"\n'
        '.close\n')
    symbols = work / f'{exe}.sym'
    result = subprocess.run([str(armips), str(source), '-sym2', str(symbols),
                             '-erroronwarning'], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    sym = {}
    for line in symbols.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            sym[parts[1].lower()] = int(parts[0], 16)
    return (work / exe).read_bytes(), sym


def changed(image, retail):
    return [IMAGE + i - 0x800 for i in range(0x800, len(retail), 4)
            if image[i:i + 4] != retail[i:i + 4]]


class DebugEndings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / 'external_tools/armips/armips').exists():
            raise unittest.SkipTest('requires armips')
        Path('/tmp/opencode').mkdir(exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(prefix='dbgend-', dir='/tmp/opencode')
        work = Path(cls.tmp.name)
        cls.open, cls.open_sym = assemble('OPEN.EXE', 'debug_open.asm', work)
        cls.end, cls.end_sym = assemble('END.EXE', 'debug_end.asm', work)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cpu(self, image, gp):
        c = CPU()
        c.load(IMAGE, image[0x800:])
        c.r[REG['gp']] = gp
        c.r[REG['sp']] = 0x801FF000
        c.r[REG['ra']] = SENTINEL
        return c

    def run_to(self, c, start, stops, bound=200):
        c.start(start)
        for _ in range(bound):
            if c.pc in stops:
                return c.pc
            c.step()
        self.fail(f'{start:#x} did not reach {stops}')

    def title(self, pressed):
        c = self.cpu(self.open, OPEN_GP)
        c.write(OPEN_GP + 0xC, pressed)
        for address, size in ((MOVIE_ID, 2), (MOVIE_NEXT, 4), (STATE_NEXT, 4)):
            c.write(address, 0x5A5A5A5A & ((1 << 8 * size) - 1), size)
        return c, self.run_to(c, 0x80081D80, (CONFIRM, TAIL))

    def test_each_button_starts_its_ending(self):
        for pressed, ending in ((L1, 0), (L2, 1), (R1, 2), (R2, 3), (SELECT, 4),
                                (L1 | START, 0)):
            with self.subTest(pressed=hex(pressed)):
                c, pc = self.title(pressed)
                self.assertEqual(pc, TAIL)
                self.assertEqual(c.read(MOVIE_ID, 2), 0x30 + ending)
                self.assertEqual(c.read(MOVIE_NEXT), 0xFFFFFFFF)
                self.assertEqual(c.read(STATE_NEXT), 6)
                self.assertEqual(c.r[REG['v0']], 0xFE)

    def test_other_presses_reach_the_retail_test(self):
        for pressed in (0, START, CIRCLE, 0x40, 0xF000):
            with self.subTest(pressed=hex(pressed)):
                c, pc = self.title(pressed)
                self.assertEqual(pc, CONFIRM)
                self.assertEqual(c.r[REG['v1']], pressed)
                self.assertEqual(c.read(MOVIE_ID, 2), 0x5A5A)
                self.assertEqual(c.read(STATE_NEXT), 0x5A5A5A5A)

    def test_r1_skips_the_roll_vblank_wait(self):
        for held, expect in ((0, END_VSYNC), (R1, SENTINEL), (START, END_VSYNC)):
            with self.subTest(held=hex(held)):
                c = self.cpu(self.end, END_GP)
                c.write(END_GP + 4, held)
                c.r[REG['a0']] = 2
                pc = self.run_to(c, self.end_sym['dbg_end_draw_vsync'], (END_VSYNC, SENTINEL))
                self.assertEqual(pc, expect)
                self.assertEqual(c.r[REG['a0']], 2)

    def test_start_ends_an_ending_movie(self):
        for trig, done in ((0, 0), (START, 1), (R1, 0)):
            with self.subTest(trig=hex(trig)):
                c = self.cpu(self.end, END_GP)
                c.write(END_GP, 0)
                c.write(END_GP + 12, trig)
                pc = self.run_to(c, self.end_sym['dbg_end_movie_vsync'], (END_VSYNC,))
                self.assertEqual(pc, END_VSYNC)
                self.assertEqual(c.read(END_GP), done)
                self.assertEqual(c.r[REG['a0']], 0)

    def test_only_the_hooks_and_dead_functions_change(self):
        retail = (ROOT / 'data/psx/EXE/OPEN.EXE').read_bytes()
        for address in changed(self.open, retail):
            self.assertTrue(address in (0x80081D80, 0x80081D84)
                            or 0x8008B53C <= address < 0x8008B5C0, hex(address))
        retail = (ROOT / 'data/psx/EXE/END.EXE').read_bytes()
        for address in changed(self.end, retail):
            self.assertTrue(address in (0x80082518, 0x80082878)
                            or 0x80083D60 <= address < 0x80083EF4, hex(address))
        # the delay slots still pass VSync its retail argument
        word = lambda image, a: int.from_bytes(image[a - IMAGE + 0x800:a - IMAGE + 0x804], 'little')
        self.assertEqual(word(self.end, 0x8008251C), 0x34040002)   # ori a0, zero, 2
        self.assertEqual(word(self.end, 0x8008287C), 0x00002021)   # addu a0, zero, zero


if __name__ == '__main__':
    unittest.main()
