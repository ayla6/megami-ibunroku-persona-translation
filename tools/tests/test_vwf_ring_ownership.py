"""Execute the assembled compositor with BTLP's real code resident."""
from pathlib import Path
import re
import struct
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
RING = 0x80057800
SIZE = 12 * 128
OLD_RING = 0x800BBB70
OVERLAY = 0x800643C4
CFG, COUNT, QUEUE = 0x801A0000, 0x801A0020, 0x801A1000
GLYPH, ACTIVATE = 0x801A0100, 0x801A0200
STACK, RETURN = 0x801CF000, 0x801F0000


class CompositorRingOwnership(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slps = (ROOT / 'build/SLPS_005.00').read_bytes()
        cls.btlp = (ROOT / 'build/BTLP.BIN').read_bytes()
        cls.sym = {m[2]: int(m[1], 16)
                   for line in (ROOT / 'build/persona.sym').read_text().splitlines()
                   if (m := re.fullmatch(r'([0-9A-Fa-f]{8}) (\w+)', line))}

    def test_draw_preserves_battle_code_and_scratch_neighbors(self):
        cpu = CPU()
        base, size = struct.unpack_from('<II', self.slps, 0x18)
        cpu.load(base, self.slps[0x800:0x800 + size])
        cpu.load(OVERLAY, self.btlp)
        cpu.load(RING - 16, bytes([0xA5]) * (SIZE + 32))
        cpu.load(GLYPH, bytes([0xFF]) * 16)
        cpu.write(ACTIVATE, 0x03E00008)  # jr ra; nop
        cpu.write(CFG + 4, ACTIVATE)
        cpu.write(CFG + 8, COUNT)
        cpu.write(CFG + 12, QUEUE)
        state = self.sym['vwf_dlg_state']
        cpu.write(state + 8, 0x0102, 2)
        cpu.write(state + 10, 1, 1)
        before = bytes(cpu.mem[cpu.offset(OLD_RING):cpu.offset(OLD_RING) + SIZE])
        self.assertEqual(self.sym['vwf_dlg_ring'], RING)
        for cell in range(12):
            cpu.write(state + 4, 0xFFFF, 2)
            cpu.r[REG['a0']], cpu.r[REG['a1']] = GLYPH, 0
            cpu.r[REG['s0']], cpu.r[REG['s2']], cpu.r[REG['s3']] = 0, cell * 16, 7
            cpu.r[REG['s5']], cpu.r[REG['sp']], cpu.r[REG['ra']] = CFG, STACK, RETURN
            cpu.start(self.sym['vwf_dialog_draw'])
            cpu.run(RETURN, limit=100000)
            self.assertEqual(cpu.read(QUEUE + cell * 12), RING + cell * 128)
            self.assertNotEqual(cpu.read(RING + cell * 128), 0)
        self.assertEqual(cpu.read(COUNT), 12)
        self.assertEqual(bytes(cpu.mem[cpu.offset(OLD_RING):cpu.offset(OLD_RING) + SIZE]), before)
        self.assertEqual(bytes(cpu.mem[cpu.offset(RING - 16):cpu.offset(RING)]), bytes([0xA5]) * 16)
        self.assertEqual(bytes(cpu.mem[cpu.offset(RING + SIZE):cpu.offset(RING + SIZE + 16)]), bytes([0xA5]) * 16)


if __name__ == '__main__':
    unittest.main()
