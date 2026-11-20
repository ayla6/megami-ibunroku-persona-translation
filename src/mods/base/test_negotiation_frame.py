"""Execute the Rev 0 primary window reset and sprite position calculation."""
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from mips_cpu import CPU, REG
import toolpath

ROOT = Path(toolpath.ROOT)
OVERLAY = 0x800643C4
RESET = 0x8007D008
WINDOW = 0x800EB890
TALK_DEPTH = 0x800CD50C
STOP = 0x80001000


class NegotiationFrame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = TemporaryDirectory()
        cls.addClassCleanup(cls.workspace.cleanup)
        work = Path(cls.workspace.name)
        src = ROOT/'src/mods/base/asm'
        asm = work/'fixture.asm'
        asm.write_text(
            f'.psx\n.include "{src}/common/addresses.inc"\n'
            f'.open "{ROOT}/data/psx/BTLP.BIN", "{work}/overlay.bin", {OVERLAY}\n'
            f'.include "{src}/btlp/negotiation_frame.asm"\n.close\n')
        subprocess.run([str(ROOT/'external_tools/armips/armips'), '-erroronwarning', str(asm)],
                       check=True, capture_output=True)
        cls.overlay = (work/'overlay.bin').read_bytes()

    def setUp(self):
        self.cpu = CPU()
        self.cpu.load(OVERLAY, self.overlay)

    def test_main_contact_box_uses_the_wider_margin(self):
        for depth in (0, 1):
            with self.subTest(depth=depth):
                self.cpu.write(TALK_DEPTH, depth, 1)
                self.cpu.r[REG['ra']] = STOP
                self.cpu.start(RESET)
                self.cpu.run(STOP, limit=100)
                self.assertEqual(self.cpu.read(WINDOW + 0x268, 2), 38)
                self.assertEqual(self.cpu.read(WINDOW + 0x26A, 2), 0xAC)

                # Native BtlSeqWindowDraw adds the window origin to the
                # current cell position before writing the sprite's x.
                self.cpu.r[REG['s2']] = WINDOW + 0x268
                self.cpu.r[REG['s3']] = WINDOW + 0x28
                self.cpu.r[REG['sp']] = 0x801EF000
                self.cpu.write(WINDOW + 0x28, 16, 2)
                self.cpu.start(0x8007D288)
                self.cpu.run(0x8007D2A4, limit=16)
                self.assertEqual(self.cpu.read(0x801EF020, 2), 54)

    def test_other_window_and_interpreter_are_untouched(self):
        retail = (ROOT/'data/psx/BTLP.BIN').read_bytes()
        start, stop = 0x8007CD38 - OVERLAY, 0x8007D71C - OVERLAY
        self.assertEqual(self.overlay[start:RESET - OVERLAY],
                         retail[start:RESET - OVERLAY])
        self.assertEqual(self.overlay[RESET - OVERLAY + 4:stop],
                         retail[RESET - OVERLAY + 4:stop])


if __name__ == '__main__':
    unittest.main()
