"""BTLP's second text window draws by staged cells, not the character cursor.

The window keeps the retail character cursor at +0x1C (the VWF engine's pos,
which never claims a line start) and the staging/sprite counter at +0x20,
which btlp_activate keeps at the highest activated cell + 1.  A row whose pen
reaches the fifteenth cell (225-240 px) has pos 14 but fifteen staged cells;
drawing by pos lost the last glyph ('Special Phys damage+Charge (1 foe)').
Every loop bound of BtlTextWindowDraw must read +0x20.
"""
import re
import unittest
from pathlib import Path

import capstone

ROOT = Path(__file__).resolve().parents[2]
BASE = 0x800643C4
# BtlTextWindowDraw in BTLP.BIN (both the opening-box quad path and the flat path).
START, END = 0x8007D718, 0x8007DE44
PLACED = ('-0x44e0(', '-0x24c($s3)')   # struct+0x1C directly, and via the dx base
STAGED = ('-0x44dc(', '-0x248($s3)')   # struct+0x20 directly


def loads(path):
    data = Path(path).read_bytes()
    md = capstone.Cs(capstone.CS_ARCH_MIPS,
                     capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
    out = []
    for addr in range(START, END, 4):
        ins = next(md.disasm(data[addr - BASE:addr - BASE + 4], addr), None)
        if ins is not None and ins.mnemonic == 'lw':
            out.append(ins.op_str)
    return out


class HelpWindowSpriteCount(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / 'build' / 'BTLP.BIN').exists():
            raise unittest.SkipTest('requires assembled BTLP build')

    def test_draw_loops_read_the_staged_cell_count(self):
        words = loads(ROOT / 'build' / 'BTLP.BIN')
        for field in PLACED:
            self.assertFalse([w for w in words if field in w],
                             f'draw loop still counts characters ({field})')
        for field in STAGED:
            self.assertTrue([w for w in words if field in w],
                            f'draw loop missing staged count ({field})')

    def test_retail_image_uses_the_character_cursor(self):
        words = loads(ROOT / 'data' / 'psx' / 'BTLP.BIN')
        self.assertTrue([w for w in words if PLACED[0] in w])
        self.assertTrue([w for w in words if PLACED[1] in w])


if __name__ == '__main__':
    unittest.main()
