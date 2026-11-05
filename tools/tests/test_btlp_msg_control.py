"""PSP terminal waits must not become い in the PS1 battle interpreter."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools/tests')]
from mips_cpu import CPU, REG
import btlp
import etext

INTERPRETER = 0x8007C9E0
INDICATOR = 0x8007FA44
GLYPH = 0x8007C754
SRC, WINDOW, STACK, RETURN = 0x801C1000, 0x801C2000, 0x801CF000, 0x801F0000


class RetailBattleMessage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.retail = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        cls.assert_entry = bytes.fromhex('e0ffbd271400b1af218880001000b0af')
        assert cls.retail[INTERPRETER - btlp.B:INTERPRETER - btlp.B + len(cls.assert_entry)] == cls.assert_entry

    def execute_token(self, c, address, wait, events):
        for name, value in dict(a0=WINDOW, a1=address, a2=wait, sp=STACK, ra=RETURN).items():
            c.r[REG[name]] = value
        def hook(cpu):
            if cpu.pc not in (INDICATOR, GLYPH):
                return False
            if cpu.pc == GLYPH:
                events.append(('glyph', cpu.read(cpu.r[REG['a1']], 1)))
                cpu.r[REG['v0']] = cpu.r[REG['a1']] + 1
            else:
                events.append(('indicator',))
            cpu.pc = cpu.r[REG['ra']]
            cpu.next_pc = cpu.pc + 4
            return True
        c.start(INTERPRETER)
        c.run(RETURN, limit=10000, intercept=hook)
        return c.r[REG['v0']]

    def machine(self, source):
        c = CPU()
        c.load(btlp.B, self.retail)
        c.load(SRC, source)
        c.load(WINDOW, bytes(0x300))
        return c

    def test_psp_wait_is_really_a_kana_on_retail_ps1(self):
        c = self.machine(bytes.fromhex('ff02fff5'))
        events = []
        p = self.execute_token(c, SRC, 0, events)
        self.assertEqual(p, SRC + 1)
        self.assertEqual(etext.glyph[c.read(p, 1)], 'い')
        p = self.execute_token(c, p, 0, events)
        self.assertEqual(p, SRC + 2)
        self.assertEqual(events, [('glyph', 2)])
        p = self.execute_token(c, p, 0, events)
        self.assertEqual(p, SRC + 4)

    def test_corrected_terminal_retains_caller_controlled_wait(self):
        for wait in (0, 1):
            script = etext.encode(btlp.msg_script('Analyze a demon<FF02>'), end=btlp.END)
            self.assertNotIn(bytes.fromhex('ff02'), script)
            c = self.machine(script)
            events = []
            p = self.execute_token(c, SRC + len(script) - 2, wait, events)
            self.assertEqual(p, SRC + len(script))
            self.assertEqual(c.read(WINDOW + 2, 2), 8 if wait else 0)
            self.assertEqual(events, [('indicator',)] if wait else [])

    def test_do_not_silently_drop_nonterminal_waits_or_pages(self):
        for script in ('A<FF02>B', 'A<FF04>B', 'A<FF05><3C><00>B', 'A<FF05>'):
            with self.subTest(script=script):
                with self.assertRaises(ValueError):
                    btlp.msg_script(script)
        self.assertEqual(btlp.msg_script('A<FFF6>B<FF02>'), 'A<FFF6>B')
        self.assertEqual(btlp.msg_script('A<FFFC>B'), 'A<FFFC>B')

    def test_terminal_psp_timed_wait_is_not_printed(self):
        script = etext.encode(btlp.msg_script('A<FF05><3C><00>'), end=btlp.END)
        self.assertEqual(script, etext.encode('A', end=btlp.END))
        c = self.machine(bytes.fromhex('ff053c00fff5'))
        events = []
        p = self.execute_token(c, SRC, 0, events)
        self.assertEqual(p, SRC + 1)
        self.execute_token(c, p, 0, events)
        self.assertEqual(events, [('glyph', 5)])


if __name__ == '__main__':
    unittest.main()
