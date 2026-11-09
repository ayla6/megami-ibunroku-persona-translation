"""The demon reaction-line guard must follow each pack's own text length.

btlp/demonline_bound.asm replaces the retail 64 KB window in BtlSayDemonLine
with header word 2 (the loaded pack's text length).  These tests run the
patched instructions on the CPU model and pin both directions: a line inside
the grown translated packs is kept, and a pointer outside the pack still
becomes the "nothing" script.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools' / 'tests')]
from mips_cpu import CPU, REG  # noqa: E402
import btlp  # noqa: E402

SITE = 0x800686DC          # lui v0,0x7fe4 in the retail build
STOP = 0x800686FC          # after the replacement, before the slot test
SCRATCH = 0x801C0000
TEXT_LEN = 0x801C0008      # header word 2 = g_btl_scratch_size
NOTHING = 0x800CD9C8       # g_btl_talk_nothing_script
SLOT_NONE = 0xFFFF

PATCHED = bytes.fromhex(
    '1c80033c'   # lui  v1,0x801c
    '0800628c'   # lw   v0,8(v1)
    '23180302'   # subu v1,s0,v1
    '2b106200'   # sltu v0,v1,v0
    '03004014'   # bnez v0,0x800686fc
    'ffff0334'   # ori  v1,zero,0xffff  (branch delay)
)


class DemonLineGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / 'build' / 'BTLP.BIN'
        if not path.exists():
            raise unittest.SkipTest('requires build/BTLP.BIN')
        cls.data = path.read_bytes()
        cls.offset = SITE - btlp.B

    def test_site_is_the_patched_bound(self):
        self.assertEqual(self.data[self.offset:self.offset + len(PATCHED)],
                         PATCHED)

    def run_guard(self, text_length, script):
        cpu = CPU()
        cpu.load(btlp.B, self.data)
        cpu.write(TEXT_LEN, text_length)
        cpu.r[REG['s0']] = script
        cpu.start(SITE)
        cpu.run(STOP, limit=20)
        return cpu.r[REG['s0']], cpu.r[REG['v1']]

    def assert_kept(self, text_length, script):
        kept, v1 = self.run_guard(text_length, script)
        self.assertEqual(kept, script, 'a line inside the pack was dropped')
        self.assertEqual(v1, SLOT_NONE, 'the slot-none constant was not restored')

    def assert_dropped(self, text_length, script):
        kept, v1 = self.run_guard(text_length, script)
        self.assertEqual(kept, NOTHING, 'a pointer outside the pack was kept')
        self.assertEqual(v1, SLOT_NONE, 'the slot-none constant was not restored')

    def test_line_in_a_grown_pack_is_kept(self):
        # SINSI/KOUMAN grew past 64 KB; retail's constant would drop these.
        for text_length in (0x10CD0, 0x10CEC):
            self.assert_kept(text_length, SCRATCH + 0x10000)
            self.assert_kept(text_length, SCRATCH + text_length - 4)

    def test_line_past_a_small_pack_is_dropped(self):
        # The bound is tighter than 64 KB when the pack is small.
        self.assert_kept(0x8000, SCRATCH + 0x7000)
        self.assert_dropped(0x8000, SCRATCH + 0x9000)

    def test_out_of_scratch_pointers_are_dropped(self):
        for script in (SCRATCH + 0x10CD0,          # exclusive end
                       SCRATCH + 0x10CD4,          # past the text
                       0x100000013,                # 0xFFFFFFFF directory entry
                       SCRATCH - 0x10):            # wrapped below the base
            self.assert_dropped(0x10CD0, script)


if __name__ == '__main__':
    unittest.main()
