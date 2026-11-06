"""The resident name-insert count glue (slps_005.00/name_count.asm).

A compact slot (first byte 0x88 or above) stores its real glyph count - the FF
position - so a short name is not padded out to eight; a legacy all-glyph slot
stays at retail's five. The MSG_SURNAME continuation adds the blank separator
glyph the message machine prints before the second half.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / 'tools/tests'))
from mips_cpu import CPU, REG

BASE = 0x80100000
TABLE = 0x80110000
STATE = 0x80120000
STOP = 0x80130000


def compact(*chars):
    return bytes(chars) + b'\xff\x01' + bytes(10 - len(chars) - 2)


def slots(*names):
    """Ten-byte slots laid out at the table base, plus the +10 given half."""
    out = bytearray()
    for name in names:
        out += name
        out += bytes(10 - len(name))
    return bytes(out)


class NameCountGlue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        armips = ROOT / 'external_tools/armips/armips'
        if not armips.exists():
            armips = shutil.which('armips')
        if not armips:
            raise unittest.SkipTest('requires armips')
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            shutil.copy(ROOT / 'src/asm/slps_005.00/name_count.asm', directory)
            (directory / 'fixture.asm').write_text(
                '.psx\n.create "count.bin", %#x\n'
                'NAME_COUNT_ADDR equ %#x\n'
                'NAME_COUNT_SIZE equ 0x68\n'
                'PARTY_NAMES_ADDR equ %#x\n'
                '.include "name_count.asm"\n.close\n' % (BASE, BASE, TABLE))
            result = subprocess.run([str(armips), 'fixture.asm', '-sym2', 'fixture.sym'],
                                    cwd=directory, capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.binary = (directory / 'count.bin').read_bytes()
            cls.symbols = {}
            for line in (directory / 'fixture.sym').read_text().splitlines():
                match = re.fullmatch(r'([0-9A-Fa-f]{8}) (\w+)', line)
                if match:
                    cls.symbols[match[2]] = int(match[1], 16)

    def count(self, table, slot=0, surname=False):
        c = CPU()
        c.load(BASE, self.binary)
        c.load(TABLE, table)
        c.load(STATE, bytes(0x40))
        # a0 and v0 are the helper's inputs: the store path leaves both as it
        # found them, while the surname path replaces a0 with the +10 base
        # (its site never reads a0 afterwards) and keeps v0.
        untouched = {}
        for reg in ('v1', 'a1', 'a2', 'a3',
                    's0', 's2', 's3', 's4', 's5', 's6', 's7'):
            c.r[REG[reg]] = 0x12340000 + REG[reg]
            untouched[reg] = c.r[REG[reg]]
        c.r[REG['a0']] = TABLE
        c.r[REG['v0']] = slot
        c.r[REG['s1']] = STATE
        c.r[REG['ra']] = STOP
        c.start(self.symbols['name_count_surname' if surname else 'name_count_store'])
        c.run(STOP)
        self.assertEqual(c.r[REG['a0']], TABLE + 10 if surname else TABLE, 'a0')
        self.assertEqual(c.r[REG['s1']], STATE, 's1')
        self.assertEqual(c.r[REG['v0']], slot, 'v0')
        for reg, value in untouched.items():
            self.assertEqual(c.r[REG[reg]], value, reg)
        return c.read(STATE + 0x35, 1)

    def test_compact_slot_counts_the_real_length(self):
        for first in range(0x88, 0xE7):
            for length in range(0, 9):
                with self.subTest(first=hex(first), length=length):
                    slot = compact(*([first] + [0xB5] * (length - 1))) if length else \
                        bytes([0xFF, 0x01]) + bytes(8)
                    self.assertEqual(self.count(slots(slot)), length)

    def test_legacy_slot_keeps_retail_five(self):
        # Five two-byte glyphs, exactly ten bytes, no terminator.
        full = bytes([0x87, 0x23, 0x87, 0x24, 0x87, 0x25, 0x87, 0x26, 0x87, 0x27])
        # A shorter legacy name, FF 01-terminated like retail wrote it.
        short = bytes([0x87, 0x23, 0x87, 0x24, 0xFF, 0x01, 0, 0, 0, 0])
        # A legacy name whose first cell is glyph 0 (a leading space).
        leading_space = bytes([0x00, 0x87, 0x23, 0xFF, 0x01, 0, 0, 0, 0, 0])
        for slot in (full, short, leading_space):
            with self.subTest(slot=slot.hex()):
                self.assertEqual(self.count(slots(slot)), 5)

    def test_reaches_the_slot_the_id_selects(self):
        table = slots(compact(0xB5, 0xC9, 0xD3, 0xD1),      # 4
                      compact(0xB6, 0xC9, 0xD6, 0xD2, 0xD7))  # 5
        self.assertEqual(self.count(table, slot=0), 4)
        self.assertEqual(self.count(table, slot=1), 5)

    def test_msg_surname_adds_the_separator_glyph(self):
        table = slots(compact(0xB5, 0xC9, 0xD3, 0xD1),      # family: 4
                      compact(0xB6, 0xC9, 0xD6, 0xD2, 0xD7))  # given: 5
        self.assertEqual(self.count(table, slot=1, surname=True), 6)
        legacy = slots(bytes([0x87, 0x23, 0x87, 0x24, 0xFF, 0x01, 0, 0, 0, 0]),
                       bytes([0x87, 0x23, 0x87, 0x24, 0x87, 0x25, 0x87, 0x26, 0x87, 0x27]))
        self.assertEqual(self.count(legacy, slot=1, surname=True), 6)


if __name__ == '__main__':
    unittest.main()
