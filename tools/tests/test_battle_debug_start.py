"""Execute the opt-in battle debug entry using the assembled overlay."""
from pathlib import Path
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
BASE = 0x800643C4
STUB = 0x8008F05C
MENU = 0x800A0CF8
BUSY = 0x8008F130
STEP = 0x800CF06B
END = 0x801F0000


class BattleDebugStart(unittest.TestCase):
    def setUp(self):
        image = ROOT / 'build/BTLP.BIN'
        if not image.exists():
            self.skipTest('requires assembled debug overlay')
        self.cpu = CPU()
        self.cpu.load(BASE, image.read_bytes())
        if self.cpu.read(0x80081358) != (0x08000000 | ((STUB >> 2) & 0x3ffffff)):
            self.skipTest('requires --qol=debug assembly')
        self.cpu.r[REG['sp']] = 0x801e0000
        self.cpu.write(0x801e001c, END)
        self.cpu.write(0x801e0018, 0x12345678)
        self.cpu.write(STEP, 7, 1)
        self.cpu.start(STUB)

    def run_stub(self, expect_menu):
        c = self.cpu
        called = False
        for _ in range(300):
            if c.pc == MENU:
                self.assertFalse(called)
                called = True
                self.assertEqual(c.read(STEP, 1), 0)
                self.assertEqual(c.read(BUSY, 1), 1)
                c.write(STEP, 2, 1)
                # Stand in for the callee; it preserves s0 under the MIPS ABI.
                c.start(c.r[REG['ra']])
            if c.pc == END:
                break
            c.step()
        else:
            self.fail('debug hook did not return')
        self.assertEqual(called, expect_menu)
        self.assertEqual(c.read(STEP, 1), 7)
        self.assertEqual(c.r[REG['s0']], 0x12345678)
        if expect_menu:
            self.assertEqual(c.read(BUSY, 1), 0)

    def test_fresh_start_on_either_pad(self):
        for pad in (0x800F88F0, 0x800F88F4):
            with self.subTest(pad=hex(pad)):
                self.setUp()
                self.cpu.write(pad, 0x0800, 2)
                self.run_stub(True)

    def test_no_press_does_not_open(self):
        self.run_stub(False)

    def test_busy_and_closing_do_not_reenter(self):
        for address in (BUSY, 0x800CF074):
            with self.subTest(address=hex(address)):
                self.setUp()
                self.cpu.write(address, 1, 1)
                self.cpu.write(0x800F88F0, 0x0800, 2)
                self.run_stub(False)


if __name__ == '__main__':
    unittest.main()
