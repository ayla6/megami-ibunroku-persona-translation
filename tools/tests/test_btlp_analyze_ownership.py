"""ANALYZE status board: only the translated producers' buffers are VWF.

The board's rows are runtime-generated, so they sit outside every producer
ownership range. addresses.inc registers the buffers of the translated
producers as always-owned spans; this test binds that table back to the live
board and the installed lookup:

  * every span holds board rows and the spans do not overlap;
  * no other static list points a row into a span (the shared kana label bank,
    the untranslated label block and the fixed-width MAG ATK / MAG DEF labels
    stay outside);
  * the installed lookup owns exactly the board rows inside the spans, and
    every other board row keeps the retail path.
"""
import re
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src' / 'injection_tools'), str(ROOT / 'tools' / 'tests')]
import toolbelt  # noqa: E402

B = 0x800643C4
# The ANALYZE board list header {count, rows} whose rows the spans describe.
BOARD_HDR = 0x800DEC00


def symbols():
    return {m.group(2): int(m.group(1), 16)
            for line in (ROOT / 'build' / 'persona.sym').read_text().splitlines()
            if (m := re.fullmatch(r'([0-9a-fA-F]{8})\s+(\S+)', line))}


class AnalyzeOwnership(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = (ROOT / 'build' / 'BTLP.BIN').read_bytes()
        cls.full = (ROOT / 'build' / 'SLPS_005.00').read_bytes()
        cls.sym = symbols()
        cls.spans = tuple(
            (name, toolbelt.asm_equ(f'ANALYZE_{name}_BUF'),
             toolbelt.asm_equ(f'ANALYZE_{name}_END'))
            for name in ('NAME', 'SPELL', 'TRAIT'))
        count, rows = struct.unpack_from('<II', cls.image, BOARD_HDR - B)
        cls.board = []
        for k in range(count):
            _x, _y, text, n, _cl, _h, _v = struct.unpack_from(
                '<hhIBBBB', cls.image, rows + 12 * k - B)
            cls.board.append((k, text, n))
        cls.board_span = tuple((k, text) for k, text, _n in cls.board
                               if any(lo <= text < hi for _n, lo, hi in cls.spans))

    def test_spans_are_disjoint_and_hold_board_rows(self):
        ordered = sorted(self.spans, key=lambda span: span[1])
        for _name, lo, hi in ordered:
            self.assertLess(lo, hi)
        for (_n0, _lo0, hi0), (_n1, lo1, _hi1) in zip(ordered, ordered[1:]):
            self.assertLessEqual(hi0, lo1)
        for name, lo, hi in self.spans:
            self.assertTrue([k for k, text, _n in self.board
                             if lo <= text < hi], name)

    def test_owned_rows_are_the_translated_producers(self):
        # Header name, six spell rows and the affinity value line. The MAG
        # ATK / MAG DEF labels (0x800DEA2C/0x800DEA34) and the "TRAIT:" label
        # at 0x800DEA3C are fixed-width, like the untranslated label block
        # above them (0x800DEA18..0x800DEA28), the rank/kind labels and the
        # kana bank.
        self.assertEqual([k for k, _text in self.board_span],
                         [1, 16, 17, 18, 19, 20, 21, 36])
        spans = {name: [k for k, text, _n in self.board if lo <= text < hi]
                 for name, lo, hi in self.spans}
        self.assertEqual(spans['NAME'], [1])
        self.assertEqual(spans['SPELL'], [16, 17, 18, 19, 20, 21])
        self.assertEqual(spans['TRAIT'], [36])

    def test_labels_are_not_owned(self):
        # The MAG ATK / MAG DEF slots and the "TRAIT:" label keep the retail
        # fixed-cell path; only the affinity value line is VWF.
        for text in (0x800DEA2C, 0x800DEA34, 0x800DEA3C):
            self.assertEqual(self._lookup(text), 0, hex(text))
        self.assertEqual(self._lookup(toolbelt.asm_equ('ANALYZE_TRAIT_BUF')), 1)

    def test_trait_descriptor_holds_the_full_line(self):
        # The row points at the relocated buffer and its count is the whole
        # 47-cell bound; the drawer stops at the line's FF inside it.
        buf = toolbelt.asm_equ('ANALYZE_TRAIT_BUF')
        end = toolbelt.asm_equ('ANALYZE_TRAIT_END')
        _k, text, n = self.board[36]
        self.assertEqual(text, buf)
        self.assertEqual(n, end - buf)

    def test_trait_buffer_binds_the_pool_line_cap(self):
        # The append loop copies until the tail's own FF, without a length
        # check. That is only safe while the drawn line cap, the pool cap and
        # the relocated buffer all agree.
        import affinity
        import smallfont_vwf
        span = (toolbelt.asm_equ('ANALYZE_TRAIT_END')
                - toolbelt.asm_equ('ANALYZE_TRAIT_BUF'))
        self.assertEqual(affinity.LINE_MAX, span)
        self.assertEqual(smallfont_vwf.POOL_LINE_MAX, span)

    def test_trait_hook_appends_the_pool_tail(self):
        # Drive the installed append routine over a real long record. The
        # head is the built record's own 25 cells; the routine must add the
        # canonical pool tail and its FF, then reach the displaced call.
        import affinity
        from mips_cpu import CPU, REG
        buf = toolbelt.asm_equ('ANALYZE_TRAIT_BUF')
        record = affinity.TABLE + 41 * affinity.STRIDE - affinity.SLPS_BASE
        head = self.full[record:record + 25]
        self.assertEqual(len(head), 25)
        text = affinity.record_en()[41]
        import smallfont_vwf
        want = bytes(smallfont_vwf.char_code(c) for c in text)
        self.assertEqual(head, want[:25])
        c = CPU()
        c.load(B, self.image)
        c.load(0x80010000, self.full[0x800:])
        c.load(0x801FF000, bytes(0x60))
        c.write(0x801FF05C, 41, 1)                   # actor + 0x5C = record 41
        c.load(buf, head)
        c.r[REG['s0']] = 0x801FF000
        c.r[REG['a3']] = buf
        c.r[REG['a0']] = 0x800F829C                  # the displaced call's argument
        c.r[REG['a1']] = 0x12345678
        c.r[REG['sp']] = 0x801ff800
        c.start(self.sym['btl_trait_tail'])
        for _ in range(200):
            if c.pc == 0x800AE43C:
                break
            c.step()
        else:
            self.fail('trait append did not reach the displaced call')
        tail = len(want) - 25 + 1                 # tail glyphs + its FF
        got = bytes(c.mem[c.offset(buf + 25, tail):
                          c.offset(buf + 25, tail) + tail])
        self.assertEqual(got, want[25:] + b'\xff')
        self.assertEqual(c.r[REG['a1']], 0x12345678)
        self.assertEqual(c.r[REG['a0']], 0x800F829C)
        self.assertEqual(c.r[REG['a2']], 3)

    def _trait_run(self, resist, head_record=None):
        """Drive btl_trait_tail with `resist` and a record's own 25-cell head.

        Returns the CPU stopped at the displaced call; a fall-through past
        the routine (into the pool) never reaches it and fails here."""
        import affinity
        from mips_cpu import CPU, REG
        if head_record is None:
            head_record = resist
        buf = toolbelt.asm_equ('ANALYZE_TRAIT_BUF')
        record = affinity.TABLE + head_record * affinity.STRIDE - affinity.SLPS_BASE
        c = CPU()
        c.load(B, self.image)
        c.load(0x80010000, self.full[0x800:])
        c.load(0x801FF000, bytes(0x60))
        c.write(0x801FF05C, resist, 1)
        c.load(buf, self.full[record:record + 25])
        c.r[REG['s0']] = 0x801FF000
        c.r[REG['a3']] = buf
        c.r[REG['a0']] = 0x800F829C
        c.r[REG['a1']] = 0x12345678
        c.r[REG['sp']] = 0x801ff800
        c.start(self.sym['btl_trait_tail'])
        for _ in range(200):
            if c.pc == 0x800AE43C:
                break
            c.step()
        else:
            self.fail(f'trait append (resist {resist:#x}) did not reach the call')
        return c, buf

    def test_trait_no_tail_ends_at_the_head(self):
        # Most records fit their own 25 cells: the routine must put the FF
        # right after the head and rejoin the displaced call - not fall into
        # the pool data that follows the code.
        pool = (ROOT / 'build' / 'affinity_pool.bin').read_bytes()
        index = struct.unpack_from('<120H', pool)
        import affinity
        en = affinity.record_en()
        k = next(k for k in range(120)
                 if index[k] == 0xFFFF and (en.get(k) or '').strip())
        c, buf = self._trait_run(k)
        at = c.offset(buf + 25, 5)
        self.assertEqual(bytes(c.mem[at:at + 1]), b'\xff')
        self.assertEqual(bytes(c.mem[at + 1:at + 5]), bytes(4))

    def test_trait_out_of_range_resist_ends_at_the_head(self):
        # 0xFF is what an empty Persona slot leaves in Char.resist; retail
        # would index the label table out of bounds. The append must stop at
        # the 25-cell head instead of reading a live BTLP word as an offset.
        c, buf = self._trait_run(0xFF, head_record=0)
        at = c.offset(buf + 25, 1)
        self.assertEqual(bytes(c.mem[at:at + 1]), b'\xff')

    def test_no_other_static_list_points_into_a_span(self):
        image, end = self.image, B + len(self.image)
        # The board ownership directory is a {base, span} table, not a
        # BtlGfxTextList; its words can accidentally look like one.
        dir_lo = toolbelt.asm_equ('BTL_BOARD_SPANS_ADDR')
        dir_hi = dir_lo + toolbelt.asm_equ('BTL_BOARD_SPANS_SIZE')
        lists = []
        for off in range(0, len(image) - 8, 4):
            count, rows = struct.unpack_from('<II', image, off)
            if not 1 <= count <= 400 or not B <= rows < end - 12 * count:
                continue
            if (rows - B) % 4 or dir_lo <= B + off < dir_hi:
                continue
            lists.append((B + off, count, rows))
        self.assertTrue(lists)
        users = []
        for at, count, rows in lists:
            for k in range(count):
                _x, _y, text, _n, _cl, _h, _v = struct.unpack_from(
                    '<hhIBBBB', image, rows + 12 * k - B)
                if not B <= text < end:
                    continue
                for name, lo, hi in self.spans:
                    if lo <= text < hi:
                        users.append((at, k, name))
        self.assertTrue(users)
        for at, k, name in users:
            self.assertEqual(at, BOARD_HDR, (hex(at), k, name))

    def _lookup(self, text):
        from mips_cpu import CPU, REG
        c = CPU()
        c.load(B, self.image)
        c.load(0x80010000, self.full[0x800:])
        c.r[REG['a0']] = text
        c.r[REG['sp']] = 0x801ff000
        c.r[REG['ra']] = 0x8000fff0
        c.start(self.sym['btl_name_lookup'])
        # The resident lookup walks every producer range and every entry of
        # the battle-owned span directory (15 entries), so a fixed small
        # step budget would just measure the directory's size.
        for _ in range(1000):
            if c.pc == 0x8000fff0:
                self.assertEqual(c.r[REG['a0']], text)
                return c.r[REG['v0']]
            c.step()
        self.fail(f'name lookup did not return for {text:#x}')

    def test_installed_lookup_owns_exactly_the_translated_rows(self):
        owned = {text for _k, text in self.board_span}
        for k, text, _n in self.board:
            want = 1 if text in owned else 0
            self.assertEqual(self._lookup(text), want, (k, hex(text)))

    def test_span_end_is_not_owned(self):
        # A pointer at the end of a span belongs to whatever follows (another
        # list or the untranslated block), so the bound is half-open. Every
        # entry in the built directory holds the same contract, including the
        # board 23 label table and its three full-name rows.
        spans = [(name, lo, hi) for name, lo, hi in self.spans]
        addr = toolbelt.asm_equ('BTL_BOARD_SPANS_ADDR')
        size = toolbelt.asm_equ('BTL_BOARD_SPANS_SIZE')
        for i in range(0, size - 4, 8):
            base, span, _pad = struct.unpack_from('<IHH', self.image,
                                                  addr - B + i)
            spans.append((hex(base), base, base + span))
        for _name, lo, hi in spans:
            self.assertEqual(self._lookup(hi), 0, hex(hi))
            self.assertEqual(self._lookup(lo), 1, hex(lo))
            self.assertEqual(self._lookup(lo + (hi - lo) // 2), 1, hex(lo))


if __name__ == '__main__':
    unittest.main()
