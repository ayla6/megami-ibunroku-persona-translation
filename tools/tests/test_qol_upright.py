"""Upper Right movement: the d-pad walks the other diagonal in the 2D rooms.

AdvFieldRun maps Up/Down/Left/Right to the four isometric walking directions.
Retail is the PSP's Upper Left scheme; this patch keeps the same clockwise
order but starts it at the upper right. Only the four direction constants
change, so the branch order, scripted walks, triggers, exits and facing stay
retail.
"""
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools/tests')]
from mips_cpu import CPU, REG  # noqa: E402

BASE = 0x800643C4
HELD = 0x800DC000
WALK_DIR = 0x800BC470
ENTER = 0x8007EB1C
STOP = 0x8007EBCC
FRAME = 0x801FF000

# d-pad bit -> the walking direction AdvFieldRun must store.
DIRECTIONS = ((0x1000, 3), (0x4000, 2), (0x8000, 0), (0x2000, 1))
SITES = {0x8007EB54: 0x34020003,   # Up:    ori v0, zero, 3
         0x8007EB58: 0xA422C470,   #        sh v0, g_adv_walk_dir(at)
         0x8007EB68: 0x34020002,   # Down:  ori v0, zero, 2
         0x8007EB84: 0x34020000,   # Left:  ori v0, zero, 0
         0x8007EBA0: 0x34020001}   # Right: ori v0, zero, 1


class UpperRightPatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        armips = ROOT / 'external_tools/armips/armips'
        if not armips.exists():
            raise unittest.SkipTest('requires armips')
        cls.tmp = tempfile.TemporaryDirectory(prefix='upright-', dir='/tmp/opencode')
        work = Path(cls.tmp.name)
        source = work / 'fixture.asm'
        source.write_text(
            '.psx\n'
            f'.include "{ROOT / "src/asm/common/addresses.inc"}"\n'
            f'.open "{ROOT / "data/psx/ADV.BIN"}", "{work / "ADV_UPRIGHT.BIN"}", {BASE:#x}\n'
            f'.include "{ROOT / "src/asm/qol/upper_right_adv.asm"}"\n'
            '.close\n')
        symbols = work / 'fixture.sym'
        result = subprocess.run([str(armips), str(source), '-sym2', str(symbols),
                                 '-erroronwarning'], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.image = (work / 'ADV_UPRIGHT.BIN').read_bytes()
        cls.retail = (ROOT / 'data/psx/ADV.BIN').read_bytes()
        cls.symbols = {}
        for line in symbols.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and re.fullmatch(r'[0-9A-Fa-f]{8}', parts[0]):
                cls.symbols[parts[1]] = int(parts[0], 16)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def word(self, address):
        return struct.unpack('<I', self.image[address - BASE:address - BASE + 4])[0]

    def test_only_the_four_direction_sites_change(self):
        changed = {BASE + i for i in range(0, len(self.retail), 4)
                   if self.image[i:i + 4] != self.retail[i:i + 4]}
        self.assertEqual(changed, set(SITES))
        for address, expected in SITES.items():
            self.assertEqual(self.word(address), expected, f'{address:#x}')

    def test_each_direction_walks_the_upper_right_way(self):
        for bit, expected in DIRECTIONS:
            with self.subTest(pad=bit):
                self.assertEqual(self.walk(bit), expected)
        self.assertEqual(self.walk(0), 4)       # WALK_NONE

    def test_the_sites_are_the_labels_the_patch_assembled(self):
        self.assertEqual(self.symbols['adv_upright_enter'], ENTER)
        self.assertEqual(self.symbols['adv_upright_up'], 0x8007EB54)
        self.assertEqual(self.symbols['adv_upright_up_store'], 0x8007EB58)
        self.assertEqual(self.symbols['adv_upright_down'], 0x8007EB68)
        self.assertEqual(self.symbols['adv_upright_left'], 0x8007EB84)
        self.assertEqual(self.symbols['adv_upright_right'], 0x8007EBA0)

    def walk(self, held):
        cpu = CPU()
        cpu.load(BASE, self.image)
        cpu.write(HELD, held)
        cpu.write(0x801F15EF, 2, 1)             # the leader's current facing
        cpu.r[REG['sp']] = FRAME
        cpu.r[REG['ra']] = 0x80001000
        cpu.start(ENTER)
        cpu.run(STOP, limit=200)
        return cpu.read(WALK_DIR, 2)


if __name__ == '__main__':
    unittest.main()
