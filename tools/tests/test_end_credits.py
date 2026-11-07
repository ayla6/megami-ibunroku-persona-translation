"""The credits shortcut's END.EXE script is built from retail, never retyped.

`end_credits.py` turns retail ending 1's staff-roll tail into the sixth
ending script (ending 5), moves the script table into a dead END.EXE function
and repoints the one reader. These tests pin the mechanical properties: the
retail entries stay verbatim, the tail is the real one, every translated
staff-roll page is still played, and the generated assembly puts the table and
script where the patched reader looks.

`endtext.credits_layout` is checked too: the roll's pitch must keep the
15-row glyphs off each other, and a block that cannot fit must fail the build
instead of overlapping lines.
"""
from pathlib import Path
import re
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import end_credits
import endtext

END = ROOT / 'data/psx/EXE/END.EXE'

# END.EXE's opcode switch (the one that runs g_end_script): sltiu v0,v1,0xC,
# out-of-range -> default, then lui/addiu build the jump-table address.
SWITCH_SLTIU = 0x80080FA4
SWITCH_BEQZ = 0x80080FA8
SWITCH_LUI = 0x80080FB0
SWITCH_ADDIU = 0x80080FB4
SWITCH_ENTRIES = 12


def words_at(data, addr, size):
    return list(struct.unpack('<%dH' % (size // 2),
                              end_credits.rd(data, addr, size)))


def dwords_at(data, addr, size):
    return list(struct.unpack('<%dI' % (size // 4),
                              end_credits.rd(data, addr, size)))


def word_at(data, addr):
    return dwords_at(data, addr, 4)[0]


class CreditsScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = END.read_bytes()
        cls.table, cls.script = end_credits.plan(cls.data)
        cls.sectors = list(struct.unpack(
            '<%dH' % end_credits.SECTOR_COUNT,
            end_credits.rd(cls.data, end_credits.SECTORS,
                           end_credits.SECTOR_COUNT * 2)))

    def test_table_is_retail_plus_one_credits_entry(self):
        retail = dwords_at(self.data, end_credits.SCRIPT_TABLE,
                           end_credits.SCRIPT_COUNT * 4)
        self.assertEqual(self.table, retail)
        asm = end_credits.emit(self.table, self.script)
        values = [int(v, 16) for v in
                  re.findall(r'^\s*\.word\s+(0x[0-9a-fA-F]+)', asm, re.M)]
        self.assertEqual(values, retail +
                         [end_credits.CREDITS_SCRIPTS + 4 * (len(retail) + 1)])

    def test_reader_instruction_is_repointed_at_the_new_table(self):
        asm = end_credits.emit(self.table, self.script)
        hi = ((end_credits.CREDITS_SCRIPTS + 0x8000) >> 16) & 0xFFFF
        lo = end_credits.CREDITS_SCRIPTS & 0xFFFF
        self.assertIn(f'.org {end_credits.TABLE_PTR_LUI:#010x}', asm)
        self.assertIn(f'lui     at, {hi:#06x}', asm)
        self.assertIn(f'.org {end_credits.TABLE_PTR_ADDIU:#010x}', asm)
        self.assertIn(f'addiu   at, at, {lo:#06x}', asm)

    def test_script_is_the_retail_staff_roll_tail(self):
        # Ending 1's script, decoded the way the game runs it.
        table = dwords_at(self.data, end_credits.SCRIPT_TABLE,
                          end_credits.SCRIPT_COUNT * 4)
        nxt = min(p for p in table if p > table[end_credits.ENDING_1])
        retail = words_at(self.data, table[end_credits.ENDING_1],
                          nxt - table[end_credits.ENDING_1])
        end = end_credits.script_end(retail)
        credits = set(end_credits.credits_pages(self.sectors))

        first = next(i for i in range(end)
                     if retail[i] in (0, 1, 2) and retail[i + 1] in credits)
        start = first
        while start >= 0 and retail[start] != 0:
            start -= 1
        self.assertGreaterEqual(start, 0)

        music = []
        i = 0
        while i < start:
            if retail[i] in end_credits.ONE_ARG:
                if retail[i] == 0xB:
                    music = retail[i:i + 2]
                i += 2
            else:
                i += 1

        tail = music + retail[start:end]
        # the bad endings hold the last screen with 0xA; ending 5 ends
        self.assertEqual(tail[-1], 0xA)
        self.assertEqual(self.script, tail[:-1] + [9])

    def switch_table(self):
        """END.EXE's own opcode jump table and its default (ignored) path."""
        sltiu = word_at(self.data, SWITCH_SLTIU)
        beqz = word_at(self.data, SWITCH_BEQZ)
        lui = word_at(self.data, SWITCH_LUI)
        addiu = word_at(self.data, SWITCH_ADDIU)
        self.assertEqual(sltiu >> 26, 0x0B)             # sltiu
        self.assertEqual((sltiu >> 16) & 31, 2)         # v0
        self.assertEqual(sltiu & 0xFFFF, SWITCH_ENTRIES)
        self.assertEqual(beqz >> 26, 0x04)              # beqz
        simm = beqz & 0xFFFF
        if simm & 0x8000:
            simm -= 0x10000
        default = SWITCH_BEQZ + 4 + simm * 4
        self.assertEqual(lui >> 26, 0x0F)               # lui at,hi
        self.assertEqual((lui >> 16) & 31, 1)
        self.assertEqual(addiu >> 26, 0x09)             # addiu at,at,lo
        table = ((lui & 0xFFFF) << 16) + (addiu & 0xFFFF)
        return dwords_at(self.data, table, SWITCH_ENTRIES * 4), default

    def test_the_script_only_uses_opcodes_ending_5_handles(self):
        # The bad endings end their script on 0xA, which END.EXE's switch
        # does not handle: it is the default "draw and loop" path, so the
        # last screen stays up forever. Ending 5 must use 0x9 (the end
        # opcode, which reaches done:) or the shortcut would never return.
        table, default = self.switch_table()
        self.assertNotEqual(table[9], default, '0x9 must reach done:')
        self.assertEqual(table[0xA], default, '0xA is a no-op hold')
        ops, i = set(), 0
        while i < len(self.script):
            op = self.script[i]
            ops.add(op)
            i += 2 if op in end_credits.ONE_ARG else 1
        self.assertEqual(self.script[-1], 9)
        for op in sorted(ops):
            self.assertIn(op, range(SWITCH_ENTRIES))
            self.assertNotEqual(table[op], default,
                                f'opcode {op:#x} would be ignored forever')

    def test_every_staff_roll_page_is_played_and_the_movies_are_gone(self):
        credits = set(end_credits.credits_pages(self.sectors))
        pages, ops = set(), set()
        i = 0
        while i < len(self.script):
            op = self.script[i]
            ops.add(op)
            if op in (0, 1, 2):
                pages.add(self.script[i + 1])
                i += 2
            elif op in end_credits.ONE_ARG:
                i += 2
            elif op in end_credits.NO_ARG:
                i += 1
            else:
                self.fail(f'unknown ending-script opcode {op:#x} at {i}')
        self.assertTrue(credits <= pages)
        self.assertNotIn(0x7, ops)                 # no embedded FMV
        self.assertEqual(self.script[-1], 9)       # ends: done: returns to the title


class CreditsLayout(unittest.TestCase):
    W, H = 320, 240

    def page(self, top):
        pix = bytearray([1]) * (self.W * self.H)
        pix[top * self.W + 10] = 0                 # old ink marks the block top
        return pix

    def test_glyphs_have_room_between_lines(self):
        lines = ['■ Main Planning', 'Takayuki Ide', 'Name Two']
        items, marks = endtext.credits_layout(self.page(30), self.W, self.H,
                                              lines)
        ys = [y for _, y, _ in items]
        self.assertEqual(ys[0], 30)
        for a, b in zip(ys, ys[1:]):
            self.assertGreaterEqual(b - a, endtext.GLYPH_ROWS)
        self.assertEqual(marks, [(10, 36)])

    def test_block_moves_up_only_as_far_as_needed(self):
        lines = ['■ Title'] + ['Name'] * 4
        block = 4 * endtext.CREDIT_PITCH + endtext.GLYPH_ROWS
        items, _ = endtext.credits_layout(self.page(200), self.W, self.H,
                                          lines)
        self.assertEqual(items[0][1], self.H - block)

    def test_a_block_that_cannot_fit_fails(self):
        lines = ['■ Title'] + ['Name'] * 20
        with self.assertRaises(ValueError):
            endtext.credits_layout(self.page(0), self.W, self.H, lines)


if __name__ == '__main__':
    unittest.main()
