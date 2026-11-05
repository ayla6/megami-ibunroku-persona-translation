"""Run the assembled Persona-release patch and retail inventory routines."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools/tests')]
import etext
import giftmsg
import toolbelt
from mips_cpu import CPU, REG

PENDING = 0x800eae4c
INVENTORY = 0x801f267c
PERSONAS = 0x801f1dc4
RELEASE_ITEMS = 0x800baa92


class GiftInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.retail = (ROOT / 'data/psx/ADV.BIN').read_bytes()
        cls.built = (ROOT / 'build/ADV.BIN').read_bytes()
        cls.slps = (ROOT / 'build/SLPS_005.00').read_bytes()
        rows = {r['pos']: r for r in toolbelt.merged_rows('ADV')}
        text = rows.get(hex(giftmsg.OLD_A - giftmsg.B), {}).get('en', '')
        if not text.strip():
            raise unittest.SkipTest('gift message is untranslated; retail code is retained')
        cls.message = etext.encode(text.strip())
        cls.persona = cls.message.index(b'\xff\x0c') + 2
        cls.items = [i + 2 for i in range(len(cls.message) - 3)
                     if cls.message[i:i + 2] == b'\xff\x09']
        if len(cls.items) != 2:
            raise AssertionError('gift message must have two item parameters')

    def execute(self, image, slot, persona, item, initial):
        cpu = CPU()
        cpu.load(0x80010000, self.slps[0x800:])
        cpu.load(giftmsg.B, image)
        cpu.r[REG['sp']] = 0x801ff000
        cpu.r[REG['s2']] = slot
        cpu.write(PERSONAS + slot * 64, persona, 1)
        cpu.write(RELEASE_ITEMS + persona * 2, item, 2)
        for i, value in enumerate(initial):
            cpu.write(INVENTORY + 2 * i, value, 2)
            cpu.write(PENDING + 2 * i, value, 2)
        cpu.start(giftmsg.START)
        cpu.run(giftmsg.END, limit=2000000)
        inventory = bytes(cpu.mem[cpu.offset(INVENTORY):cpu.offset(INVENTORY) + 0x17f * 2])
        pending = bytes(cpu.mem[cpu.offset(PENDING):cpu.offset(PENDING) + 0x17f * 2])
        return cpu, inventory, pending

    def test_real_inventory_and_message_match_retail(self):
        for slot, persona, item in ((0, 1, 1), (7, 37, 0x123), (15, 99, 0x1fe)):
            for count in (0, 3):
                with self.subTest(slot=slot, persona=persona, item=item, count=count):
                    initial = [item | (count << 9)] if count else []
                    original, expected, expected_pending = self.execute(
                        self.retail, slot, persona, item, initial)
                    patched, actual, actual_pending = self.execute(
                        self.built, slot, persona, item, initial)
                    self.assertEqual(actual, expected)
                    self.assertEqual(actual_pending, expected_pending)
                    self.assertEqual(int.from_bytes(actual[:2], 'little'), item | ((count + 1) << 9))
                    self.assertEqual(original.read(0x800bb559, 1), persona)
                    start = giftmsg.START + 8
                    self.assertEqual(patched.read(start + self.persona, 1), persona)
                    for offset in self.items:
                        self.assertEqual(patched.read(start + offset, 1), item & 0xff)
                        self.assertEqual(patched.read(start + offset + 1, 1), item >> 8)
                    self.assertEqual(patched.r[REG['s1']] - self.persona, start)
                    self.assertEqual(patched.r[REG['sp']], 0x801ff000)


if __name__ == '__main__':
    unittest.main()
