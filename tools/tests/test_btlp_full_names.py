"""Execute the assembled battle-dialogue name copy against source-derived names."""
import re
import struct
import sys
import unittest
from pathlib import Path

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import etext
import items
import name_tails

RETURN = 0x801F0000
STACK = 0x801FF000
OUTPUT = 0x80120000
OFFER_NAME = 0x800EB26D
ENEMY_NAME = 0x8005DB53
ITEM_NAME = 0x8004440C
LIST_NAMES = 0x80057E00
LIST_STRIDE = 21


class BattleFullNames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.item_rows = name_tails.item_rows()
        cls.demon_rows = name_tails.demon_rows()
        if not cls.item_rows or not cls.demon_rows:
            raise AssertionError('source-derived item and demon names must not be empty')
        cls.symbols = {}
        for line in (ROOT / 'build/persona.sym').read_text().splitlines():
            match = re.fullmatch(r'([0-9A-Fa-f]{8}) (\w+)', line)
            if match:
                cls.symbols[match[2]] = int(match[1], 16)
        cls.overlay = (ROOT / 'build/BTLP.BIN').read_bytes()
        cls.exe = (ROOT / 'build/SLPS_005.00').read_bytes()

    def machine(self):
        c = CPU()
        c.load(0x800643C4, self.overlay)
        base, size = struct.unpack_from('<II', self.exe, 0x18)
        c.load(base, self.exe[0x800:0x800 + size])
        c.r[REG['sp']] = STACK
        c.r[REG['ra']] = RETURN
        return c

    def copy(self, c, src, limit=10):
        for name, value in dict(a0=OUTPUT, a1=src, a2=limit, sp=STACK, ra=RETURN).items():
            c.r[REG[name]] = value
        c.start(0x8007A86C)
        c.run(RETURN, limit=200000)
        data = bytearray()
        for i in range(48):
            value = c.read(OUTPUT + i, 1)
            if value == 0xFF:
                return bytes(data)
            data.append(value)
        self.fail('unterminated name')

    def test_every_item_record(self):
        c = self.machine()
        for ident, text in self.item_rows:
            with self.subTest(ident=ident):
                self.assertEqual(self.copy(c, ITEM_NAME + ident * 32), etext.encode(text, end=None))

    def test_every_offer_name(self):
        c = self.machine()
        for ident, text in self.demon_rows:
            with self.subTest(ident=ident):
                head = items.encode(text)[:10]
                c.write(OFFER_NAME - 1, ident, 1)
                c.load(OFFER_NAME, head + (b'\xff' if len(head) < 10 else b''))
                self.assertEqual(self.copy(c, OFFER_NAME), etext.encode(text, end=None))

    def test_every_enemy_actor_name(self):
        c = self.machine()
        for ident, text in self.demon_rows:
            with self.subTest(ident=ident):
                src = ENEMY_NAME + (ident % 9) * 0xEC
                head = items.encode(text)[:10]
                c.write(src - 1, ident, 1)
                c.load(src, head + (b'\xff' if len(head) < 10 else b''))
                dest = 0x800EBD80 + 6 * 24
                c.load(dest - 1, bytes([0x5A]) * 26)
                for name, value in dict(a0=4, a1=src, sp=STACK, ra=RETURN).items():
                    c.r[REG[name]] = value
                c.start(0x8007A920)
                c.run(RETURN, limit=200000)
                actual = bytes(c.read(dest + i, 1) for i in range(24)).split(b'\xff')[0]
                self.assertEqual(actual, etext.encode(text, end=None))
                self.assertEqual(c.read(dest - 1, 1), 0x5A)
                self.assertEqual(c.read(dest + 24, 1), 0x5A)

    def test_actual_insert_producer_keeps_other_slots_intact(self):
        c = self.machine()
        for kind, rows in ((2, name_tails.demon_rows()), (3, name_tails.item_rows())):
            ident, text = max(rows, key=lambda row: len(row[1]))
            if kind == 2:
                c.write(OFFER_NAME - 1, ident, 1)
                c.load(OFFER_NAME, items.encode(text)[:10])
                src, slot = OFFER_NAME, 3
            else:
                src, slot = ITEM_NAME + ident * 32, 4
            destination = 0x800EBD80 + slot * 24
            c.load(destination - 1, bytes([0x5A]) * 26)
            for name, value in dict(a0=kind, a1=src, sp=STACK, ra=RETURN).items():
                c.r[REG[name]] = value
            c.start(0x8007A920)
            c.run(RETURN, limit=200000)
            actual = bytes(c.read(destination + i, 1) for i in range(24)).split(b'\xff')[0]
            self.assertEqual(actual, etext.encode(text, end=None))
            self.assertEqual(c.read(destination - 1, 1), 0x5A)
            self.assertEqual(c.read(destination + 24, 1), 0x5A)

    def test_victory_item_producer_and_descriptor(self):
        c = self.machine()
        descriptor = 0x800DF7AC - 0x800643C4
        self.assertEqual(struct.unpack_from('<I', self.overlay, descriptor)[0], 0x8002BC84)
        self.assertEqual(self.overlay[descriptor + 4], 20)
        for ident, text in self.item_rows:
            with self.subTest(ident=ident):
                c.write(0x800F7EB8, ident, 2)
                c.r[REG['sp']] = STACK
                c.start(0x800AADD8)
                c.run(0x800AAE68, limit=200000)
                actual = bytes(c.read(0x8002BC84 + i, 1) for i in range(21)).split(b'\xff')[0]
                self.assertEqual(actual, items.encode(text))
                self.assertEqual(c.read(0x800120A0, 2) & 1, 1)
        c.write(0x800F7EB8, 0, 2)
        c.r[REG['sp']] = STACK
        c.start(0x800AADD8)
        c.run(0x800AAE68)
        self.assertEqual(c.read(0x8002BC84, 1), 0xFF)
        self.assertEqual(c.read(0x800120A0, 2) & 1, 0)

    def test_item_list_row_writer(self):
        c = self.machine()
        for ident, text in self.item_rows:
            if ident >= 0x56:
                continue
            slot = ident % 12
            dst = LIST_NAMES + slot * LIST_STRIDE
            c.load(dst - 1, bytes([0x5A]) * (LIST_STRIDE + 2))
            c.write(0x800F8088, ident | (1 << 9), 2)
            for name, value in dict(s1=0x800F8088, s5=dst, sp=STACK).items():
                c.r[REG[name]] = value
            c.start(0x800AD014)
            c.run(0x800AD09C, limit=200000)
            actual = bytes(c.read(dst + i, 1) for i in range(LIST_STRIDE)).split(b'\xff')[0]
            self.assertEqual(actual, items.encode(text), ident)
            self.assertEqual(c.read(dst - 1, 1), 0x5A)
            self.assertEqual(c.read(dst + LIST_STRIDE, 1), 0x5A)
        c.write(0x800F8088, 0, 2)
        c.r[REG['s1']] = 0x800F8088
        c.r[REG['s5']] = LIST_NAMES
        c.r[REG['sp']] = STACK
        c.start(0x800AD014)
        c.run(0x800AD09C)
        self.assertEqual(c.read(LIST_NAMES, 1), 0xFF)

    def test_spell_list_keeps_retail_rows_and_terminates(self):
        c = self.machine()
        c.load(LIST_NAMES - 1, bytes([0x5A]) * (12 * LIST_STRIDE + 2))
        c.r[REG['a0']] = 1
        c.r[REG['sp']] = STACK
        c.r[REG['ra']] = RETURN
        c.start(0x800AD41C)
        c.run(RETURN, limit=200000)
        for slot in range(12):
            expected = bytes(c.read(0x80047D44 + (slot + 1) * 20 + i, 1) for i in range(10))
            actual = bytes(c.read(LIST_NAMES + slot * LIST_STRIDE + i, 1) for i in range(10))
            self.assertEqual(actual, expected, slot)
            self.assertEqual(c.read(LIST_NAMES + slot * LIST_STRIDE + 10, 1), 0xFF)
        self.assertEqual(c.read(LIST_NAMES - 1, 1), 0x5A)
        self.assertEqual(c.read(LIST_NAMES + 12 * LIST_STRIDE, 1), 0x5A)


if __name__ == '__main__':
    unittest.main()
