"""Execute built small-font MIPS code; no GPU, emulator process, or rebuild.

Run after assembly: python -m unittest discover -s tools/tests -p test_smallfont_runtime.py -v
"""
from pathlib import Path
import os
import re
import struct
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
RETURN = 0x801F0000
STACK = 0x801FF000
OVERLAY = 0x800643C4
TABLE = 0x80058E70
SOURCE = 0x80110900
INDEX = 0x80110200
BG = 0x80110000
MAP = 0x80110100
OT = 0x80110400
ORG = 0x80110500


class RetainedGeometryQA(unittest.TestCase):
    def test_viewport_clamp_opcode_gate_rejects_mutations(self):
        import sys
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import smallfont_vwf
        words = (0x8FB20038, 0, 0x0152702A, 0x11C00007, 0)
        smallfont_vwf.require_viewport_clamp(words, 'test')
        for index in (0, 2, 3):
            altered = list(words)
            altered[index] = 0
            with self.subTest(index=index), self.assertRaisesRegex(SystemExit, 'viewport-right'):
                smallfont_vwf.require_viewport_clamp(altered, 'test')

    def test_complete_tail_and_unsupported_ring_copies(self):
        import sys
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import smallfont_vwf
        widths = bytes([4]) * 256
        self.assertEqual(smallfont_vwf.require_retained_geometry(
            [10, 11, 12, 13, 14], widths, columns=4, column=2,
            scroll=16, viewport=24), 0)
        with self.assertRaisesRegex(ValueError, 'multiple or earlier'):
            smallfont_vwf.require_retained_geometry(
                [10, 11, 12, 13, 14], widths, columns=4, column=2,
                scroll=0, viewport=32)
        with self.assertRaisesRegex(ValueError, 'wider than ring'):
            smallfont_vwf.require_retained_geometry(
                [10, 11, 12], widths, columns=4, column=0,
                scroll=0, viewport=48)
        with self.assertRaisesRegex(ValueError, 'tail is clipped'):
            smallfont_vwf.require_retained_geometry(
                [10, 11, 12, 13, 14], widths, columns=4, column=2,
                scroll=16, viewport=16)


class Pipeline(unittest.TestCase):
    def test_load_delay_uses_old_value_then_commits(self):
        c = CPU()
        # lw t0,0(a0); addu t1,t0,zero; addu t2,t0,zero
        c.load(0x80001000, struct.pack('<III', 0x8C880000, 0x01004821, 0x01005021))
        c.r[4], c.r[8] = 0x80002000, 7
        c.write(0x80002000, 99)
        c.start(0x80001000)
        for _ in range(3): c.step()
        self.assertEqual((c.r[9], c.r[10]), (7, 99))

    def test_branch_reads_stale_load_and_runs_delay_slot(self):
        c = CPU()
        # lw t0,0(a0); beq t0,zero,+2; addiu t1,zero,3; addiu t1,zero,9
        c.load(0x80001000, struct.pack('<IIII', 0x8C880000, 0x11000002, 0x24090003, 0x24090009))
        c.r[4] = 0x80002000
        c.write(0x80002000, 99)
        c.start(0x80001000)
        for _ in range(3): c.step()
        self.assertEqual(c.pc, 0x80001010)
        self.assertEqual(c.r[9], 3)

    def test_instruction_overrides_previous_load_to_same_register(self):
        c = CPU()
        c.load(0x80001000, struct.pack('<II', 0x8C880000, 0x24080003))
        c.r[4] = 0x80002000
        c.write(0x80002000, 99)
        c.start(0x80001000)
        c.step(); c.step()
        self.assertEqual(c.r[8], 3)


class BuiltSmallfont(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = [ROOT / 'build' / name for name in ('persona.sym', 'ADV.BIN', 'SLPS_005.00', 'FONT.BIN')]
        if not all(p.exists() for p in required):
            raise unittest.SkipTest('requires assembled game files in build/')
        cls.symbols = {}
        for line in required[0].read_text().splitlines():
            match = re.fullmatch(r'([0-9A-Fa-f]{8}) (\w+)', line)
            if match: cls.symbols[match[2]] = int(match[1], 16)
        cls.overlay = required[1].read_bytes()
        cls.executable = required[2].read_bytes()
        cls.font = required[3].read_bytes()
        defs = (ROOT / 'src/asm/vwf/smallfont_defs.asm').read_text()
        cls.rows = int(re.search(r'^SF_ROWS\s+equ\s+(\d+)', defs, re.M).group(1))
        cls.buf_size = int(re.search(r'^SF_BUF_SIZE\s+equ\s+(0x[0-9A-Fa-f]+)', defs, re.M).group(1), 16)
        cls.scratch = cls.symbols['sf_name_scratch_adv']

    def machine(self):
        c = CPU()
        c.load(OVERLAY, self.overlay)
        base, size = struct.unpack_from('<II', self.executable, 0x18)
        c.load(base, self.executable[0x800:0x800 + size])
        c.load(0x801E0000, self.font)
        c.r[REG['sp']], c.r[REG['ra']] = STACK, RETURN
        cfg = self.symbols['sf_cfg_adv']
        atlas = c.read(cfg + 4)
        for cell in range(860):
            glyph = cell % 215
            c.load(atlas + cell * 8, struct.pack('<BBHHH', (glyph % 31) * 8, (glyph // 31) * 12, 0x6000, 0, 0x1E))
        widths = c.read(cfg + 0x14)
        c.load(widths, bytes([0x34]) * 256)
        c.write(widths, 0x24, 1)
        return c

    def table(self, c):
        return c.read(self.symbols['sf_cfg_adv'] + 8)

    def test_smallfont_record_and_tab_avoid_r3000_hilo_restart_hazards(self):
        # R3000 requires two instructions after MFHI/MFLO before another
        # multiply or divide, so an interrupt can restart the pipeline safely.
        c = self.machine()
        for ovl in ('adv', 'dng', 's2d'):
            if ovl != 'adv':
                c.load(OVERLAY, (ROOT / 'build' / (ovl.upper() + '.BIN')).read_bytes())
            start = self.symbols['sf_record_' + ovl]
            end = self.symbols['sf_record_end_' + ovl]
            for pc in range(start, end - 8, 4):
                word = c.read(pc)
                if word >> 26 == 0 and word & 63 in (0x10, 0x12):
                    for next_pc in (pc + 4, pc + 8):
                        next_word = c.read(next_pc)
                        self.assertFalse(next_word >> 26 == 0 and
                                         next_word & 63 in (0x18, 0x19, 0x1A, 0x1B),
                                         f'{ovl}: HI/LO hazard at {pc:#x} -> {next_pc:#x}')
        start = self.symbols['sf_tab_advance']
        end = self.symbols['sf_tab_emit']
        for pc in range(start, end - 8, 4):
            word = c.read(pc)
            if word >> 26 == 0 and word & 63 in (0x10, 0x12):
                for next_pc in (pc + 4, pc + 8):
                    next_word = c.read(next_pc)
                    self.assertFalse(next_word >> 26 == 0 and
                                     next_word & 63 in (0x18, 0x19, 0x1A, 0x1B),
                                     f'tab: HI/LO hazard at {pc:#x} -> {next_pc:#x}')

    def record(self, c, codes, count, bank=0, dst=INDEX, source=SOURCE, entry=None, slots=None):
        cfg = self.symbols['sf_cfg_adv']
        c.load(source, bytes(codes))
        if entry is not None:
            c.write(cfg + 8, TABLE)  # captured legacy recorder used this shared table
        for name, value in dict(a0=source, a1=dst, a2=bank * 215, a3=count,
                                t0=cfg, sp=STACK, ra=RETURN).items():
            c.r[REG[name]] = value
        c.start(entry if entry is not None else self.symbols['sf_record_adv'])
        c.run(RETURN)
        for i in range(self.rows if slots is None else slots):
            ptr = (TABLE if entry is not None else self.table(c)) + i * 56
            if c.read(ptr) == dst: return ptr
        self.fail('recorder did not commit a row')

    def test_recorder_even_odd_caps_and_all_clut_banks(self):
        for bank in range(4):
            for cap in (1, 2, 3, 10, 21, 25, 46, 47):
                with self.subTest(bank=bank, cap=cap):
                    c = self.machine()
                    codes = [10 + i % 20 for i in range(55)] + [255]
                    ptr = self.record(c, codes, cap, bank)
                    self.assertEqual(c.read(ptr + 4, 2), cap)
                    self.assertEqual(c.read(ptr + 6, 2) >> 8, bank)
                    self.assertEqual(bytes(c.mem[c.offset(ptr + 8):c.offset(ptr + 8) + cap + 1]), bytes(codes[:cap] + [255]))
                    self.assertEqual(c.r[REG['sp']], STACK)

    def test_name_tiers_choose_least_tightening_and_preserve_banks(self):
        cases = (([10] * 4, 0, [20, 24, 28, 32]),
                 ([10, 0, 11, 0, 12], 1, [20, 26, 32]),
                 ([10] * 5, 2, [20, 23, 26, 29, 32]),
                 ([10] * 6, 0, [20, 24, 28, 32, 36, 40]))
        for codes, tier, expected in cases:
            for bank in range(4):
                for fast in (False, True):
                    with self.subTest(codes=codes, tier=tier, bank=bank, fast=fast):
                        c = self.machine(); self.layer(c)
                        ptr = self.record(c, codes + [255], 2, bank, source=self.scratch)
                        self.assertEqual(c.read(ptr + 7, 1), bank | tier << 2)
                        self.assertEqual([p & 65535 for p in self.render(c, fast=fast)], expected)
                        self.assertTrue(c.read(ptr + 4, 2) & 0x8000)

    def test_tightened_one_pixel_glyph_is_not_a_blank(self):
        for fast in (False, True):
            c = self.machine(); self.layer(c)
            c.write(BG + 8, 80, 2)      # exclude a second ring copy's left bearing
            widths = c.read(self.symbols['sf_cfg_adv'] + 0x14)
            c.write(widths + 174, 0x22, 1)  # narrow ink retains the 1px letter gap
            ptr = self.record(c, [174] * 5 + [10, 10, 255], 2, source=self.scratch)
            self.assertEqual(c.read(ptr + 7, 1) >> 2 & 3, 2)
            self.assertEqual([p & 65535 for p in self.render(c, fast=fast)],
                             [20, 22, 24, 26, 28, 30, 33])
            self.assertTrue(c.read(ptr + 4, 2) & 0x8000)

    def test_blank_marker_is_checked_before_tightening(self):
        c = self.machine(); self.layer(c)
        c.write(c.read(self.symbols['sf_cfg_adv'] + 0x14) + 9, 0x11, 1)
        ptr = self.record(c, [10, 9, 10, 10, 10, 10, 255], 2, source=self.scratch)
        self.assertEqual(c.read(ptr + 7, 1) >> 2 & 3, 2)
        self.assertEqual([p & 65535 for p in self.render(c)], [20, 24, 27, 30, 33])
        # Blank cells already advance by the minimum: do not count them as
        # removable letter gaps when deciding whether tier 2 can fit.
        c = self.machine()
        c.write(c.read(self.symbols['sf_cfg_adv'] + 0x14) + 9, 0x11, 1)
        ptr = self.record(c, [10, 10, 9, 9, 9, 255], 1, source=self.scratch)
        self.assertEqual(c.read(ptr + 7, 1) >> 2 & 3, 0)

    def test_centered_and_non_name_rows_keep_natural_advances(self):
        for source, count in ((SOURCE, 5), (self.scratch, 0x8002)):
            c = self.machine()
            ptr = self.record(c, [10] * 5 + [255], count, source=source)
            self.assertEqual(c.read(ptr + 7, 1) >> 2 & 3, 0)

    def test_fixed_cell_producer_keeps_the_retail_map_and_font(self):
        c = self.machine(); self.layer(c)
        ptr = self.record(c, [166, 167, 168, 255], 0x4008)
        self.assertEqual(c.read(ptr + 7, 1) & 0x40, 0x40)
        self.assertEqual(self.render(c), [])
        self.assertFalse(c.read(ptr + 4, 2) & 0x8000)
        self.assertEqual([c.read(INDEX + 2 * i, 2) for i in range(3)], [166, 167, 168])

    def test_all_condensed_source_names_render_complete_in_every_overlay(self):
        import sys
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import items, demons, name_tails, smallfont_vwf
        import smallfont_variants
        field_widths = (ROOT / 'build/sf_field_width.bin').read_bytes()
        cases = []
        for family, rows, base, stride in (
                ('items', name_tails.item_rows(), items.FIRST - items.STRIDE, items.STRIDE),
                ('demons', name_tails.demon_rows(), demons.REC0, demons.STRIDE)):
            for ident, text in rows:
                codes = items.encode(text)
                if sum(field_widths[c] & 15 for c in codes) <= 80:
                    continue
                # The porter refuses a name no stage fits (items.build fails,
                # the wording is never widened or cut), so only fitting names
                # reach a row and must render complete there.
                if smallfont_vwf.condensed_tier(codes, 80, field_widths)[0] is None:
                    continue
                cases.append((family, ident, codes, base + ident * stride))
        self.assertTrue(cases, 'requires the canonical over-natural-width names')
        original_symbols, original_overlay, original_scratch = self.symbols, self.overlay, self.scratch
        tiers = set()
        try:
            for overlay in ('adv', 'dng', 's2d'):
                self.scratch = original_symbols['sf_name_scratch_' + overlay]
                self.symbols = dict(original_symbols)
                for name in ('sf_cfg', 'sf_state', 'sf_record', 'sf_hook_bg', 'sf_hook_fastbg'):
                    self.symbols[name + '_adv'] = original_symbols[name + '_' + overlay]
                self.overlay = (ROOT / 'build' / (overlay.upper() + '.BIN')).read_bytes()
                for family, ident, codes, source in cases:
                    for fast in (False, True):
                        with self.subTest(overlay=overlay, family=family, ident=ident, fast=fast):
                            c = self.machine(); self.layer(c)
                            c.load(c.read(self.symbols['sf_cfg_adv'] + 0x14), field_widths)
                            tier, px = smallfont_vwf.condensed_tier(codes, 80, field_widths)
                            tiers.add(tier)
                            self.assertIsNotNone(tier)
                            self.assertLessEqual(px, 80)
                            ptr = self.record(c, list(codes[:10]) + ([255] if len(codes) < 10 else []),
                                              10, bank=ident % 4, source=source)
                            self.assertEqual(c.read(ptr + 7, 1), ident % 4 | tier << 2)
                            start = c.offset(ptr + 8)
                            self.assertEqual(bytes(c.mem[start:start + len(codes) + 1]), codes + b'\xff')
                            expected, pen = [], 20
                            for code in codes:
                                if code:
                                    expected.append(pen)
                                pen += smallfont_vwf.tier_adv(field_widths[code], code, tier)
                            self.assertEqual([p & 65535 for p in self.render(c, fast=fast)], expected)
                            glyphs = [code for code in codes if code]
                            for code, (_xy, uv, _wh) in zip(glyphs, self.packets(c)):
                                slot = smallfont_variants.slots().index(code)
                                u, v = smallfont_variants.uv(slot, tier == 2)
                                self.assertEqual(uv & 65535, u | v << 8)
                            self.assertTrue(c.read(ptr + 4, 2) & 0x8000)
        finally:
            self.symbols, self.overlay, self.scratch = original_symbols, original_overlay, original_scratch
        self.assertEqual(tiers, {1, 2})

    def captured_code(self, c, spans):
        path = os.environ.get('SMALLFONT_CRASH_RAM')
        if not path:
            self.skipTest('set SMALLFONT_CRASH_RAM to a captured 2MB RAM file')
        ram = Path(path).read_bytes()
        self.assertEqual(len(ram), 0x200000)
        for address, size in spans:
            offset = c.offset(address, size)
            c.load(address, ram[offset:offset + size])

    def test_captured_recorder_exposes_counter_and_bank_failures(self):
        c = self.machine()
        self.captured_code(c, [(0x8008FE94, 720)])
        ptr = self.record(c, [10, 11, 12, 255], 10, entry=0x8008FE94, slots=32)
        self.assertEqual(c.read(ptr + 4, 2), 6)
        c = self.machine()
        self.captured_code(c, [(0x8008FE94, 720)])
        with self.assertRaisesRegex(AssertionError, 'did not commit'):
            self.record(c, [10, 11, 12, 255], 10, bank=1, entry=0x8008FE94, slots=32)

    def test_captured_guard_branches_on_stale_t3(self):
        c = self.machine()
        self.captured_code(c, [(0x8003235C, 24), (0x801ECE60, 32)])
        target = 0x80160004
        c.write(0x801E1A50, target)
        c.write(target - 4, 0)
        c.r[REG['t3']] = 0x5245
        c.start(0x8003235C)
        c.run(target, limit=40)
        self.assertEqual(c.pc, target)  # invalid guard was incorrectly accepted

    def test_captured_hook_loses_saved_thunk(self):
        c = self.machine(); self.layer(c)
        ptr = self.record(c, [10, 11, 255], 2)
        c.load(TABLE, bytes(c.mem[c.offset(ptr):c.offset(ptr) + 56]))
        c.write(self.symbols['sf_cfg_adv'] + 8, TABLE)
        self.captured_code(c, [(0x8007A230, 1368)])
        for name, value in dict(a0=BG, a1=OT, a2=0, sp=STACK, ra=RETURN).items():
            c.r[REG[name]] = value
        c.start(0x8007A254)
        c.run(0x8007A470, limit=10000)
        self.assertEqual(c.read(c.r[REG['sp']] + 0x28), 0x8007A73C)
        self.assertEqual(c.r[REG['t1']], 0)
        c.step(); c.step()
        self.assertEqual(c.pc, 0)

    def test_ff_count_and_callee_saved_registers(self):
        for bank in range(4):
            c = self.machine()
            saved = [0x12340000 + i for i in range(8)]
            c.r[16:24] = saved
            ptr = self.record(c, [10, 11, 12, 255], 10, bank)
            self.assertEqual(c.read(ptr + 4, 2), 3)
            self.assertEqual(c.r[16:24], saved)

    def test_successful_record_also_executes_retail_writer(self):
        for bank in range(4):
            c = self.machine()
            self.record(c, [10, 11, 12, 255], 10, bank)
            self.assertEqual([c.read(INDEX + i * 2, 2) for i in range(3)],
                             [bank * 215 + n for n in (10, 11, 12)])
            self.assertEqual(c.read(INDEX + 6, 2), 0)

    def test_persona_master_head_retains_tail_and_retail_extent(self):
        base = 0x8004B0CC + 0x2C + 8
        for bank in range(4):
            c = self.machine()
            c.load(base + 0x29 - 8, bytes([30, 31, 255]))
            ptr = self.record(c, list(range(10, 20)), 10, bank, source=base)
            self.assertEqual(c.read(ptr + 4, 2), 10)
            self.assertEqual(bytes(c.mem[c.offset(ptr + 8):c.offset(ptr + 20)]),
                             bytes(list(range(10, 20)) + [30, 31]))
            self.assertEqual([c.read(INDEX + i * 2, 2) for i in range(10)],
                             [bank * 215 + i for i in range(10, 20)])

        c = self.machine()
        ptr = self.record(c, [10, 11, 255], 10, source=base)
        self.assertEqual(c.read(ptr + 4, 2), 2)
        self.layer(c)
        self.assertEqual(len(self.render(c)), 2)

        c = self.machine()
        c.load(base + 0x29 - 8, bytes([0xFE, 0, 0]))
        c.load(self.symbols['persona_tails_x'], bytes([30, 31, 32, 33, 255]))
        ptr = self.record(c, list(range(10, 20)), 10, source=base)
        self.assertEqual(bytes(c.mem[c.offset(ptr + 8):c.offset(ptr + 22)]),
                         bytes(list(range(10, 20)) + [30, 31, 32, 33]))

    def test_guard_ignores_stale_t3(self):
        target = 0x80160004
        for entry, registration, replay in ((0x8003235C, 0x801E1A50, 0x801EFFC4),
                                             (0x8003F554, 0x801E1A54, 0x801EFFE4)):
            for actual in (0, 0x5245):
                for stale in (0, 0x5245):
                    with self.subTest(entry=entry, actual=actual, stale=stale):
                        c = self.machine()
                        c.write(registration, target)
                        c.write(target - 4, actual)
                        c.r[REG['t3']] = stale
                        c.start(entry)
                        expected = target if actual == 0x5245 else replay
                        c.run(expected, limit=40)
                        self.assertEqual(c.pc, expected)

    def layer(self, c, width=40, height=3):
        c.write(BG + 0x14, MAP)
        c.write(BG + 4, 20, 2); c.write(BG + 6, 30, 2)
        c.write(BG + 8, 320, 2); c.write(BG + 10, min(300, height * 12), 2)
        c.write(MAP, 8, 1); c.write(MAP + 1, 12, 1)
        c.write(MAP + 2, width, 2); c.write(MAP + 4, height, 2)
        c.write(MAP + 8, c.read(self.symbols['sf_cfg_adv'] + 4))
        c.write(MAP + 12, INDEX)
        c.write(OT + 4, ORG); c.write(OT + 8, 0)
        c.write(ORG, 0xFFFFFF)

    def render(self, c, ot=OT, fast=False):
        map_ptr = c.read(BG + 0x14)
        index = c.read(map_ptr + 12)
        span = c.read(map_ptr + 2, 2) * c.read(map_ptr + 4, 2) * 2
        logical_before = bytes(c.mem[c.offset(index):c.offset(index) + span])
        for name, value in dict(a0=BG, a1=ot, a2=0, sp=STACK, ra=RETURN).items():
            c.r[REG[name]] = value
        calls = []
        def sorter(cpu):
            body = 0x8003F56C if fast else 0x80032374
            if cpu.pc != body: return False
            calls.append(tuple(cpu.r[4:7]))
            expected_map = bytearray(logical_before)
            for slot in range(self.rows):
                ptr = self.table(cpu) + slot * 56
                count = cpu.read(ptr + 4, 2)
                if not count & 0x8000:
                    continue
                dst = cpu.read(ptr)
                count &= 0x7FFF
                self.assertGreater(count, 0)
                self.assertGreaterEqual(dst, index)
                self.assertLessEqual(dst + count * 2, index + span)
                expected_map[dst - index:dst - index + count * 2] = bytes([255]) * (count * 2)
            self.assertEqual(bytes(cpu.mem[cpu.offset(index):cpu.offset(index) + span]), bytes(expected_map),
                             'retail sorter must see FFFF only for complete claimed rows')
            # Run the actual thunk/prologue, intercept only the GPU sorter body,
            # and model its epilogue. This checks the real body jump target.
            sp = cpu.r[REG['sp']]
            frame = 0xE8 if fast else 0xA8
            ret = cpu.read(sp + (0xE4 if fast else 0xA4))
            saved = ((21, 0xD4), (30, 0xE0), (23, 0xDC)) if fast else ((30, 0xA0), (23, 0x9C), (22, 0x98))
            for reg, offset in saved: cpu.r[reg] = cpu.read(sp + offset)
            cpu.r[REG['sp']] = sp + frame
            for i in list(range(2, 16)) + [24, 25]: cpu.r[i] = 0xDEAD0000 + i
            cpu.start(ret)
            return True
        c.start(self.symbols['sf_hook_fastbg_adv' if fast else 'sf_hook_bg_adv'])
        c.run(RETURN, intercept=sorter)
        self.assertEqual(calls, [(BG, ot, 0)])
        self.assertEqual(bytes(c.mem[c.offset(index):c.offset(index) + span]), logical_before,
                         'temporary suppression must restore every logical map cell')
        state = self.symbols['sf_state_adv']
        end = c.read(state + 0x0C)
        base = c.read(state + 0x20) + c.read(state + 8) * self.buf_size
        if end == 0:  # Invalid/empty viewport returns before allocating a buffer.
            return []
        self.assertGreaterEqual(end, base)
        self.assertLessEqual(end, base + self.buf_size)
        return [c.read(sprite + 4) for sprite, _mode in self.sprites(c)]

    def sprites(self, c):
        """Walk a call's packets: one draw-mode packet, then packets of up
        to three sprites chained in pen and row order."""
        state = self.symbols['sf_state_adv']
        base = c.read(state + 0x20) + c.read(state + 8) * self.buf_size
        end = c.read(state + 0x0C)
        if end == 0:
            return []
        out = []
        p = base
        mode = chained = None
        while p < end:
            tag = c.read(p)
            length = tag >> 24
            if c.read(p + 4) >> 24 == 0xE1:
                mode = c.read(p + 4)
                self.assertEqual(mode, 0xE1000200 | 0x1E, 'one draw mode per call')
                self.assertEqual(length, 1)
            else:
                self.assertEqual(chained, p & 0xFFFFFF, 'a call\'s packets chain in pen and row order')
                self.assertIn(length, (4, 8, 12),
                              'a glyph costs four GP0 words; a packet fits the GPU FIFO')
                for i in range(length // 4):
                    self.assertEqual(c.read(p + 4 + i * 16) >> 24, 0x64)
                    out.append((p + 4 + i * 16, mode))
            chained = tag & 0xFFFFFF
            p += (1 + length) * 4
        self.assertEqual(p, end, 'each packet\'s tag must reach the next one')
        return out

    def packets(self, c):
        return [(c.read(p + 4), c.read(p + 8), c.read(p + 12))
                for p, _mode in self.sprites(c)]

    def test_horizontal_scroll_selects_the_same_ring_copy_in_both_passes(self):
        cases = ((0, [20, 24]), (4, [20, 20]), (24, [28, 32]),
                 (-8, [28, 32]), (32, [20, 24]), (64 + 24, [28, 32]))
        for fast in (False, True):
            for scroll, expected in cases:
                with self.subTest(fast=fast, scroll=scroll):
                    c = self.machine(); self.layer(c, width=4, height=3)
                    c.write(BG + 8, 16, 2); c.write(BG + 12, scroll, 2)
                    ptr = self.record(c, [10, 11, 255], 2)
                    points = self.render(c, fast=fast)
                    self.assertEqual([point & 0xFFFF for point in points], expected)
                    self.assertTrue(c.read(ptr + 4, 2) & 0x8000)
                    self.assertEqual([c.read(INDEX + 2 * i, 2) for i in range(2)], [10, 11])

    def test_simultaneous_horizontal_copies_keep_the_retail_row(self):
        for fast in (False, True):
            c = self.machine(); self.layer(c, width=4, height=3)
            c.write(BG + 8, 48, 2)
            ptr = self.record(c, [10, 11, 255], 2)
            self.assertEqual(self.render(c, fast=fast), [])
            self.assertFalse(c.read(ptr + 4, 2) & 0x8000)
            self.assertEqual([c.read(INDEX + 2 * i, 2) for i in range(2)], [10, 11])

    def test_equal_width_view_with_two_partial_copies_keeps_retail(self):
        for fast in (False, True):
            c = self.machine(); self.layer(c, width=4, height=3)
            c.write(BG + 8, 32, 2); c.write(BG + 12, 4, 2)
            ptr = self.record(c, [10, 11, 255], 2)
            self.assertEqual(self.render(c, fast=fast), [])
            self.assertFalse(c.read(ptr + 4, 2) & 0x8000)

    def test_wide_view_with_hidden_first_copy_keeps_retail(self):
        # With period 32, scroll 24 and viewport width 48, the second and
        # third copies are both visible even though the first is wholly hidden.
        for fast in (False, True):
            c = self.machine(); self.layer(c, width=4, height=3)
            c.write(BG + 8, 48, 2); c.write(BG + 12, 24, 2)
            ptr = self.record(c, [10, 11, 255], 2)
            self.assertEqual(self.render(c, fast=fast), [])
            self.assertFalse(c.read(ptr + 4, 2) & 0x8000)

    def test_normalised_font_cells_start_at_the_pen(self):
        c = self.machine(); self.layer(c, width=4, height=3)
        c.write(BG + 8, 24, 2)
        ptr = self.record(c, [10, 11, 255], 2)
        c.write(c.read(self.symbols['sf_cfg_adv'] + 0x14) + 10, 0x14, 1)
        self.assertEqual([p & 0xFFFF for p in self.render(c)], [20, 24])
        self.assertTrue(c.read(ptr + 4, 2) & 0x8000)
        self.assertEqual(self.packets(c)[0][2] & 0xffff, 8)

    def test_retained_tail_crossing_map_edge_is_emitted_inside_viewport(self):
        # Start at column 2 of a four-cell ring. The five-glyph retained
        # name has only two logical cells but all five VWF quads fit in the
        # 24px view after scrolling the physical map edge into the viewport.
        for fast in (False, True):
            with self.subTest(fast=fast):
                c = self.machine(); self.layer(c, width=4, height=3)
                c.write(BG + 8, 24, 2); c.write(BG + 12, 16, 2)
                ptr = self.record(c, [10, 11, 12, 13, 14, 255], 2,
                                  dst=INDEX + 4, source=self.scratch)
                packets = self.render(c, fast=fast)
                self.assertEqual(c.read(ptr + 7, 1) >> 2 & 3, 2)
                self.assertEqual([p & 0xFFFF for p in packets], [20, 23, 26, 29, 32])
                self.assertTrue(c.read(ptr + 4, 2) & 0x8000)
                self.assertEqual([c.read(INDEX + 4 + i*2, 2) for i in range(2)], [10, 11])

    def test_retained_tail_with_visible_previous_copy_is_unsupported(self):
        # This renderer intentionally does not create multiple ring copies.
        # Retail remains intact; this is NOT proof of a complete retained tail.
        for fast in (False, True):
            c = self.machine(); self.layer(c, width=4, height=3)
            c.write(BG + 8, 32, 2)
            ptr = self.record(c, [10, 11, 12, 13, 14, 255], 2,
                              dst=INDEX + 4, source=self.scratch)
            self.assertEqual(self.render(c, fast=fast), [])
            self.assertFalse(c.read(ptr + 4, 2) & 0x8000)
            self.assertEqual([c.read(INDEX + 4 + i*2, 2) for i in range(2)], [10, 11])

    def test_scrolling_ring_wraps_before_and_after_32_rows(self):
        # Item lists use a 32x12-pixel ring. Exercise both sorter thunks,
        # including a negative scroll and a partially clipped ring-boundary row.
        for fast in (False, True):
            for scroll, expected in ((372, [30, 42]), (384, [30]),
                                     (-12, [30, 42]), (376, [30, 38]),
                                     (384 * 4 + 372, [30, 42])):
                with self.subTest(fast=fast, scroll=scroll):
                    c = self.machine(); self.layer(c, width=40, height=32)
                    index = 0x80140000  # separate from BG, OT, and recorder fixtures
                    c.write(MAP + 12, index)
                    c.write(BG + 10, 72, 2)
                    c.write(BG + 14, scroll, 2)
                    self.record(c, [10, 11, 255], 2, dst=index)
                    self.record(c, [12, 13, 255], 2, dst=index + 31 * 40 * 2)
                    self.render(c, fast=fast)
                    packets = self.packets(c)
                    self.assertEqual(sorted(set(xy >> 16 for xy, _uv, _wh in packets)), expected)
                    if scroll == 376:
                        self.assertEqual({(xy >> 16, wh >> 16) for xy, _uv, wh in packets},
                                         {(30, 8), (38, 12)})

    def test_non_text_cell_geometry_leaves_retail_untouched(self):
        for size in ((16, 16), (8, 16), (16, 12)):
            for fast in (False, True):
                with self.subTest(size=size, fast=fast):
                    c = self.machine(); self.layer(c, width=40, height=32)
                    c.write(MAP, size[0], 1); c.write(MAP + 1, size[1], 1)
                    self.record(c, [10, 11, 255], 2)
                    self.assertEqual(self.render(c, fast=fast), [])
                    self.assertEqual([c.read(INDEX + 2 * i, 2) for i in range(2)], [10, 11])

    def test_zero_height_map_leaves_retail_untouched(self):
        c = self.machine(); self.layer(c, height=0)
        c.write(BG + 10, 72, 2)
        self.assertEqual(self.render(c), [])

    def test_vertical_wrap_in_every_assembled_overlay(self):
        original_symbols, original_overlay = self.symbols, self.overlay
        try:
            for overlay in ('adv', 'dng', 's2d'):
                with self.subTest(overlay=overlay):
                    self.symbols = dict(original_symbols)
                    for name in ('sf_cfg', 'sf_state', 'sf_record', 'sf_hook_bg', 'sf_hook_fastbg'):
                        self.symbols[name + '_adv'] = original_symbols[name + '_' + overlay]
                    self.overlay = (ROOT / 'build' / (overlay.upper() + '.BIN')).read_bytes()
                    c = self.machine(); self.layer(c, width=40, height=32)
                    index = 0x80140000
                    c.write(MAP + 12, index)
                    c.write(BG + 10, 72, 2); c.write(BG + 14, 384, 2)
                    self.record(c, [10, 11, 255], 2, dst=index)
                    self.render(c)
                    self.assertEqual([xy >> 16 for xy, _uv, _wh in self.packets(c)], [30, 30])
        finally:
            self.symbols, self.overlay = original_symbols, original_overlay

    def test_horizontal_wrap_in_every_assembled_overlay(self):
        original_symbols, original_overlay = self.symbols, self.overlay
        try:
            for overlay in ('adv', 'dng', 's2d'):
                self.symbols = dict(original_symbols)
                for name in ('sf_cfg', 'sf_state', 'sf_record', 'sf_hook_bg', 'sf_hook_fastbg'):
                    self.symbols[name + '_adv'] = original_symbols[name + '_' + overlay]
                self.overlay = (ROOT / 'build' / (overlay.upper() + '.BIN')).read_bytes()
                for fast in (False, True):
                    with self.subTest(overlay=overlay, fast=fast):
                        c = self.machine(); self.layer(c, width=4, height=3)
                        c.write(BG + 8, 16, 2); c.write(BG + 12, -8, 2)
                        self.record(c, [10, 11, 255], 2)
                        self.assertEqual([point & 0xFFFF for point in self.render(c, fast=fast)], [28, 32])
        finally:
            self.symbols, self.overlay = original_symbols, original_overlay

    def test_retained_tail_crosses_map_edge_in_every_assembled_overlay(self):
        original_symbols, original_overlay, original_scratch = self.symbols, self.overlay, self.scratch
        try:
            for overlay in ('adv', 'dng', 's2d'):
                self.scratch = original_symbols['sf_name_scratch_' + overlay]
                self.symbols = dict(original_symbols)
                for name in ('sf_cfg', 'sf_state', 'sf_record', 'sf_hook_bg', 'sf_hook_fastbg'):
                    self.symbols[name + '_adv'] = original_symbols[name + '_' + overlay]
                self.overlay = (ROOT / 'build' / (overlay.upper() + '.BIN')).read_bytes()
                for fast in (False, True):
                    with self.subTest(overlay=overlay, fast=fast):
                        c = self.machine(); self.layer(c, width=4, height=3)
                        c.write(BG + 8, 24, 2); c.write(BG + 12, 16, 2)
                        ptr = self.record(c, [10, 11, 12, 13, 14, 255], 2,
                                          dst=INDEX + 4, source=self.scratch)
                        self.assertEqual([p & 0xFFFF for p in self.render(c, fast=fast)],
                                         [20, 23, 26, 29, 32])
                        self.assertTrue(c.read(ptr + 4, 2) & 0x8000)
                        self.assertEqual([c.read(INDEX + 4 + 2*i, 2) for i in range(2)], [10, 11])
        finally:
            self.symbols, self.overlay, self.scratch = original_symbols, original_overlay, original_scratch

    def test_multiple_visible_ring_copies_leave_retail_row_untouched(self):
        for fast in (False, True):
            c = self.machine(); self.layer(c, width=40, height=3)
            c.write(BG + 10, 300, 2)
            self.record(c, [10, 11, 255], 2)
            self.assertEqual(self.render(c, fast=fast), [])
            self.assertEqual([c.read(INDEX + 2 * i, 2) for i in range(2)], [10, 11])

    def test_viewport_bounds_and_partial_uv_crop(self):
        c = self.machine(); self.layer(c, height=3)
        c.write(BG + 8, 10, 2); c.write(BG + 10, 8, 2)
        c.write(BG + 12, 3, 2); c.write(BG + 14, 2, 2)
        self.record(c, [10, 11, 255], 2)
        self.render(c)
        packets = self.packets(c)
        self.assertEqual(len(packets), 2)
        for xy, uv, wh in packets:
            x, y = xy & 65535, xy >> 16
            w, h = wh & 65535, wh >> 16
            self.assertGreaterEqual(x, 20); self.assertGreaterEqual(y, 30)
            self.assertLessEqual(x + w, 30); self.assertLessEqual(y + h, 38)
        xy, uv, wh = packets[0]
        self.assertEqual((xy, uv & 65535, wh), ((30 << 16) | 20, (2 << 8) | 83, (8 << 16) | 5))

    def test_viewport_clipping_edge_matrix(self):
        for fast in (False, True):
            with self.subTest(fast=fast, edge='right-bottom'):
                c = self.machine(); self.layer(c)
                c.write(BG + 8, 5, 2); c.write(BG + 10, 7, 2)
                self.record(c, [10, 255], 1)
                self.render(c, fast=fast)
                xy, uv, wh = self.packets(c)[0]
                self.assertEqual((xy, uv & 65535, wh), ((30 << 16) | 20, 80, (7 << 16) | 5))
            with self.subTest(fast=fast, edge='culled-first-then-visible'):
                c = self.machine(); self.layer(c)
                c.write(BG + 8, 8, 2); c.write(BG + 10, 12, 2)
                c.write(BG + 12, 8, 2)
                self.record(c, [10, 11, 255], 2)
                self.render(c, fast=fast)
                packets = self.packets(c)
                self.assertEqual(len(packets), 1)
                xy, uv, wh = packets[0]
                self.assertEqual((xy, uv & 65535, wh), ((30 << 16) | 20, 92, (12 << 16) | 4))
            with self.subTest(fast=fast, edge='signed-origin'):
                c = self.machine(); self.layer(c)
                c.write(BG + 4, -5, 2); c.write(BG + 6, -3, 2)
                c.write(BG + 8, 8, 2); c.write(BG + 10, 8, 2)
                c.write(BG + 12, 2, 2); c.write(BG + 14, 1, 2)
                c.write(0x8005E63C, -4, 2); c.write(0x8005E640, 5, 2)
                self.record(c, [10, 255], 1)
                self.render(c, fast=fast)
                xy, uv, wh = self.packets(c)[0]
                self.assertEqual((xy, uv & 65535, wh), ((2 << 16) | 0xFFF7, (1 << 8) | 82, (8 << 16) | 6))
            for w, h in ((0, 12), (8, 0), (-1, 12), (8, -1)):
                with self.subTest(fast=fast, w=w, h=h):
                    c = self.machine(); self.layer(c)
                    c.write(BG + 8, w, 2); c.write(BG + 10, h, 2)
                    self.record(c, [10, 255], 1)
                    self.assertEqual(self.render(c, fast=fast), [])

    def test_overlay_owned_recording_does_not_touch_legacy_bss(self):
        c = self.machine()
        table = self.table(c)
        self.assertNotEqual(table, TABLE)
        self.assertNotEqual(self.scratch, TABLE)
        self.assertEqual(bytes(c.mem[c.offset(table):c.offset(table) + self.rows * 56]), bytes(self.rows * 56))
        self.assertEqual(bytes(c.mem[c.offset(self.scratch):c.offset(self.scratch) + 21]), bytes(21))
        sentinel = bytes([0xA5]) * (32 * 56 + 21)
        c.load(TABLE, sentinel)
        self.record(c, [10, 11, 255], 2)
        self.assertEqual(bytes(c.mem[c.offset(TABLE):c.offset(TABLE) + len(sentinel)]), sentinel)

    def test_all_culled_rows_restore_map_and_use_no_packets(self):
        c = self.machine(); self.layer(c, height=3)
        c.write(BG + 8, 112, 2); c.write(BG + 10, 8, 2)
        self.record(c, [10, 11, 255], 2, dst=INDEX + 80)
        self.assertEqual(self.render(c), [])
        self.assertEqual([c.read(INDEX + 80 + i * 2, 2) for i in range(2)], [10, 11])

    def test_culled_rows_do_not_consume_packet_reservations(self):
        c = self.machine(); self.layer(c, height=20)
        c.write(BG + 8, 320, 2); c.write(BG + 10, 12, 2)
        index = 0x80112000; c.write(MAP + 12, index)
        # Insert invisible rows first, then the visible row, to exercise reservation order.
        for row in range(1, 8):
            self.record(c, [10] * 30 + [255], 30, dst=index + row * 80, source=SOURCE + row * 32)
        self.record(c, [10] * 30 + [255], 30, dst=index, source=SOURCE)
        self.assertEqual(len(self.render(c)), 30)

    def test_more_than_32_live_rows_and_repeated_updates_preserve_static(self):
        c = self.machine(); self.layer(c, width=40, height=40)
        index = 0x80112000; c.write(MAP + 12, index)
        self.assertGreater(self.rows, 32)
        for row in range(40):
            self.record(c, [10, 255], 1, dst=index + row * 80, source=SOURCE + row * 2)
        for _ in range(self.rows + 2):
            self.record(c, [11, 255], 1, dst=index, source=SOURCE)
        addresses = {c.read(self.table(c) + slot * 56) for slot in range(self.rows)}
        self.assertTrue({index + row * 80 for row in range(40)} <= addresses)

    def test_fast_sorter_thunk_reaches_real_body_and_preserves_saved_registers(self):
        c = self.machine(); self.layer(c)
        self.record(c, [10, 11, 255], 2)
        saved = [0x12340000 + i for i in range(8)]
        c.r[16:24] = saved
        self.assertEqual(len(self.render(c, fast=True)), 2)
        self.assertEqual(c.r[16:24], saved)

    def test_saved_thunk_and_second_record_map_width(self):
        for bank in (0, 1, 3):
            with self.subTest(bank=bank):
                c = self.machine(); self.layer(c)
                self.record(c, [10, 11, 255], 2, bank, dst=INDEX)
                self.record(c, [12, 13, 255], 2, bank, dst=INDEX + 80, source=SOURCE + 64)
                points = self.render(c)
                self.assertEqual(sorted(p >> 16 for p in points), [30, 30, 42, 42])
                self.assertEqual(sorted(p & 0xFFFF for p in points), [20, 20, 24, 24])

    def test_multiple_ots_in_one_frame_do_not_create_dma_cycles(self):
        c = self.machine(); self.layer(c)
        self.record(c, [10, 11, 12, 255], 3)
        second_ot, second_org = OT + 0x20, ORG + 0x100
        c.write(second_ot + 4, second_org)
        c.write(second_ot + 8, 0)
        c.write(second_org, 0xFFFFFF)
        self.render(c, ot=OT)
        self.render(c, ot=second_ot)
        self.render(c, ot=OT)
        head = c.read(ORG) & 0xFFFFFF
        seen = set()
        while head != 0xFFFFFF:
            self.assertNotIn(head, seen, 'GPU linked list contains a cycle')
            seen.add(head)
            head = c.read(0x80000000 | head) & 0xFFFFFF

    def test_multiple_visible_rows_form_a_complete_gpu_command_chain(self):
        c = self.machine(); self.layer(c, height=5)
        for row in range(5):
            self.record(c, [10 + i for i in range(14)] + [255], 14,
                        dst=INDEX + row * 80, source=SOURCE + row * 32)
        self.render(c)
        head = c.read(ORG) & 0xFFFFFF
        visited = set()
        sprites = 0
        while head != 0xFFFFFF:
            self.assertNotIn(head, visited, 'GPU linked list contains a cycle')
            visited.add(head)
            addr = 0x80000000 | head
            tag = c.read(addr)
            words = tag >> 24
            if c.read(addr + 4) == 0xE100021E:
                self.assertEqual(words, 1)
            else:
                self.assertIn(words, (4, 8, 12), 'a packet must fit the GPU FIFO')
                for i in range(words // 4):
                    self.assertEqual(c.read(addr + 4 + i * 16) >> 24, 0x64)
                    self.assertEqual(c.read(addr + 16 + i * 16), 0x000C0008)
                    sprites += 1
            head = tag & 0xFFFFFF
        self.assertEqual((len(visited), sprites), (1 + 24, 70))

    def test_alternating_frame_ots_preserve_two_live_packet_buffers(self):
        c = self.machine(); self.layer(c)
        self.record(c, [10, 11, 255], 2)
        second_ot, second_org = OT + 0x20, ORG + 0x100
        c.write(second_ot + 4, second_org)
        c.write(second_ot + 8, 0)
        state = self.symbols['sf_state_adv']
        previous_base = previous_bytes = None
        for frame in range(8):
            ot = (OT, second_ot)[frame % 2]
            c.write(0x800642E8, frame % 2, 2)
            c.write((ORG, second_org)[frame % 2], 0xFFFFFF)
            points = self.render(c, ot=ot)
            self.assertEqual(points, [(30 << 16) | 20, (30 << 16) | 24])
            base = c.read(state + 0x20) + c.read(state + 8) * self.buf_size
            if previous_base is not None:
                self.assertNotEqual(base, previous_base)
                self.assertEqual(bytes(c.mem[c.offset(previous_base):c.offset(previous_base) + 48]), previous_bytes)
            previous_base = base
            previous_bytes = bytes(c.mem[c.offset(base):c.offset(base) + 48])

    def test_framebuffer_origin_offsets_follow_both_frame_ots(self):
        c = self.machine(); self.layer(c)
        self.record(c, [10, 11, 255], 2)
        second_ot, second_org = OT + 0x20, ORG + 0x100
        c.write(second_ot + 4, second_org)
        c.write(second_ot + 8, 0)
        for frame, (dx, dy) in enumerate(((0, 0), (0, 240), (-8, 240), (16, -12))):
            c.write(0x800642E8, frame % 2, 2)
            c.write(0x8005E63C, dx, 2)
            c.write(0x8005E640, dy, 2)
            c.write((ORG, second_org)[frame % 2], 0xFFFFFF)
            points = self.render(c, ot=(OT, second_ot)[frame % 2])
            self.assertEqual(points, [((30 + dy) & 0xFFFF) << 16 | ((x + dx) & 0xFFFF)
                                      for x in (20, 24)])

    def test_name_scratch_records_full_ff_text_beyond_caller_pixel_budget(self):
        scratch = self.scratch
        c = self.machine(); self.layer(c)
        codes = [10 + i for i in range(20)]
        ptr = self.record(c, codes + [255], 3, source=scratch)
        self.assertEqual(c.read(ptr + 4, 2) & 0x7FFF, 3)
        self.assertEqual(bytes(c.mem[c.offset(ptr + 8):c.offset(ptr + 8) + 21]),
                         bytes(codes + [255]))
        self.assertEqual([c.read(INDEX + i * 2, 2) for i in range(3)], codes[:3])
        self.assertEqual(c.read(INDEX + 6, 2), 0)
        before = bytes(c.mem[c.offset(INDEX):c.offset(INDEX) + 6])
        # Shared name scratch can hold a different name before the next sort.
        c.load(scratch, bytes([99, 255]))
        points = self.render(c)
        self.assertEqual(len(points), 20)
        self.assertEqual([p & 0xFFFF for p in points], list(range(20, 100, 4)))
        self.assertEqual(bytes(c.mem[c.offset(INDEX):c.offset(INDEX) + 6]), before)

    def test_full_name_with_simultaneous_ring_copies_is_unsupported(self):
        c = self.machine(); self.layer(c, width=4, height=1)
        ptr = self.record(c, [10] * 20 + [255], 3, source=self.scratch)
        points = self.render(c)
        self.assertEqual(points, [])
        self.assertFalse(c.read(ptr + 4, 2) & 0x8000)
        self.assertEqual([c.read(INDEX + i * 2, 2) for i in range(3)], [10, 10, 10])
        self.assertEqual(bytes(c.mem[c.offset(ptr + 8):c.offset(ptr + 29)]), bytes([10] * 20 + [255]))

    def test_capacity_reserves_entire_row_before_suppressing_retail_cells(self):
        c = self.machine(); self.layer(c, height=10)
        index = 0x80112000
        c.write(MAP + 12, index)
        # A full 40-cell map row is the widest row that fits the ring. The
        # pre-pass reserves 16 B/glyph plus n + ceil(n/2) for the sprite
        # packets' tags, and 24 B per call for the draw mode and the guard.
        # Rows 2..9 are visible in the default 30..150 viewport.
        for row in range(10):
            self.record(c, [10] * 40 + [255], 40, dst=index + row * 80,
                        source=SOURCE + row * 48)
        before = bytes(c.mem[c.offset(index):c.offset(index) + 10 * 80])
        points = self.render(c)
        row_bytes = 16 * 40 + 40 + 20
        fit = min(8, (self.buf_size - 24) // row_bytes)
        self.assertLess(fit, 8, 'the fixture must still exhaust the buffer')
        self.assertEqual(len(points), fit * 40)
        self.assertEqual(bytes(c.mem[c.offset(index):c.offset(index) + 10 * 80]), before)
        # Rows past the budget keep their complete retail fixed-cell row.
        self.assertEqual([c.read(index + 9 * 80 + i * 2, 2) for i in range(40)], [10] * 40)

    def test_render_preserves_logical_map_for_page_lifetime(self):
        c = self.machine(); self.layer(c)
        self.record(c, [10, 11, 255], 2)
        before = bytes(c.mem[c.offset(INDEX):c.offset(INDEX) + 4])
        self.render(c)
        self.assertEqual(bytes(c.mem[c.offset(INDEX):c.offset(INDEX) + 4]), before)

    def test_page_zero_clear_does_not_resurrect_recorded_rows(self):
        c = self.machine(); self.layer(c)
        self.record(c, [10, 11, 255], 2)
        self.render(c)
        c.load(INDEX, bytes(40 * 3 * 2))
        second_ot = OT + 0x20
        c.write(second_ot + 4, ORG + 0x100)
        c.write(ORG + 0x100, 0xFFFFFF)
        c.write(0x800642E8, 1, 2)
        self.assertEqual(self.render(c, ot=second_ot), [])

    def test_overwritten_row_cannot_revive_after_later_zero_clear(self):
        c = self.machine(); self.layer(c)
        self.record(c, [10, 11, 255], 2)
        c.write(INDEX, 99, 2)
        self.assertEqual(self.render(c), [])
        c.load(INDEX, bytes(4))
        self.assertEqual(self.render(c), [])

    def test_early_ff_short_write_preserves_untouched_adjacent_record(self):
        c = self.machine(); self.layer(c)
        adjacent = INDEX + 10  # cell five, outside the three-cell actual write
        self.record(c, [20, 21, 255], 2, dst=adjacent, source=SOURCE + 64)
        self.record(c, [10, 11, 12, 255], 10)
        self.assertTrue(any(c.read(self.table(c) + slot * 56) == adjacent for slot in range(self.rows)),
                        'early FF must bound ownership to cells actually written')
        points = self.render(c)
        self.assertEqual(sorted(p & 0xFFFF for p in points), [20, 24, 28, 60, 64])
        self.assertEqual([c.read(adjacent + i * 2, 2) for i in range(2)], [20, 21])

    def test_overlapping_matching_prefix_uses_latest_writer_layout(self):
        c = self.machine(); self.layer(c)
        self.record(c, [10, 11, 12, 13, 255], 4)
        self.record(c, [12, 13, 14, 255], 3, dst=INDEX + 4, source=SOURCE + 64)
        self.assertFalse(any(c.read(self.table(c) + slot * 56) == INDEX for slot in range(self.rows)))
        points = self.render(c)
        self.assertEqual(points, [(30 << 16) | x for x in (36, 40, 44)])
        self.assertEqual([c.read(INDEX + i * 2, 2) for i in range(5)], [10, 11, 12, 13, 14])

    def test_overlapping_verbatim_writer_retires_matching_old_prefix(self):
        for displacement in (0, 4):
            with self.subTest(displacement=displacement):
                c = self.machine(); self.layer(c)
                self.record(c, [10, 11, 12, 13, 255], 4)
                codes = [10, 11, 255] if displacement == 0 else [12, 13, 14, 255]
                atlas = c.read(self.symbols['sf_cfg_adv'] + 4)
                c.write(atlas + codes[0] * 8 + 6, 0, 2)  # non-font cell forces the real writer fallback
                with self.assertRaisesRegex(AssertionError, 'did not commit'):
                    self.record(c, codes, len(codes) - 1, dst=INDEX + displacement, source=SOURCE + 64)
                self.assertFalse(any(c.read(self.table(c) + slot * 56) == INDEX for slot in range(self.rows)))
                self.assertEqual(self.render(c), [])
                expected = [10, 11, 12, 13] if displacement == 0 else [10, 11, 12, 13, 14]
                self.assertEqual([c.read(INDEX + i * 2, 2) for i in range(len(expected))], expected)

    def test_blank_advance_does_not_emit_a_packet(self):
        c = self.machine(); self.layer(c)
        widths = c.read(self.symbols['sf_cfg_adv'] + 0x14)
        c.write(widths + 10, 0x11, 1)
        self.record(c, [10, 11, 255], 2)
        points = self.render(c)
        self.assertEqual(points, [(30 << 16) | 21])

    def test_packet_capacity_preserves_end_sentinel(self):
        c = self.machine(); self.layer(c, height=24)
        index = 0x80112000
        c.write(MAP + 12, index)
        for row in range(20):
            self.record(c, [10] * 10 + [255], 10, dst=index + row * 80,
                        source=SOURCE + row * 16)
        buffers = c.read(self.symbols['sf_cfg_adv'] + 0x10)
        end = buffers + self.buf_size * 2
        c.write(end, 0x12345678)
        points = self.render(c)
        self.assertEqual(len(points),
                         min(20, (self.buf_size - 24) // (16 * 10 + 10 + 5)) * 10)
        self.assertEqual(c.read(end), 0x12345678)

    def test_tab_advances_to_next_row_relative_stop(self):
        original_symbols, original_overlay = self.symbols, self.overlay
        try:
            for overlay in ('adv', 'dng', 's2d'):
                self.symbols = dict(original_symbols)
                for name in ('sf_cfg', 'sf_state', 'sf_record', 'sf_hook_bg', 'sf_hook_fastbg'):
                    self.symbols[name + '_adv'] = original_symbols[name + '_' + overlay]
                self.overlay = (ROOT / 'build' / (overlay.upper() + '.BIN')).read_bytes()
                for fast in (False, True):
                    with self.subTest(overlay=overlay, fast=fast):
                        c = self.machine(); self.layer(c)
                        self.record(c, [10, 11, 0xD7, 12, 0xD7, 13, 255], 6)
                        points = self.render(c, fast=fast)
                        self.assertEqual([p & 0xffff for p in points], [20, 24, 60, 100])
                        self.assertEqual([c.read(INDEX + i * 2, 2) for i in range(6)],
                                         [10, 11, 0xD7, 12, 0xD7, 13])
        finally:
            self.symbols, self.overlay = original_symbols, original_overlay

    def test_controller_layout_rows_fit_packet_budget(self):
        import sys
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import cfgtext
        names = [t for _, _, _, t in cfgtext.E[16:35]]
        source = (ROOT / 'references/persona-decomp/src/common/ui/padlayout.c').read_text()
        table = re.search(r'g_pad_layout_actions\[\]\s*=\s*\{([^}]+)\}', source)[1]
        actions = [int(n, 16) for n in re.findall(r'0x[0-9A-Fa-f]+', table)]
        self.assertEqual(len(actions), 80)
        for layout in range(4):
            with self.subTest(layout=layout):
                c = self.machine(); self.layer(c, height=24)
                c.load(c.read(self.symbols['sf_cfg_adv'] + 0x14),
                       (ROOT / 'build/sf_field_width.bin').read_bytes())
                index = 0x80112000
                c.write(MAP + 12, index)
                # Leave room for other visible screen labels, not just the
                # controller action names themselves.
                records = [self.record(c, [10] * 13 + [255], 13,
                                       dst=index + row * 40 * 2,
                                       source=SOURCE + 0x400 + row * 20)
                           for row in range(2)]
                for i, action in enumerate(actions[layout * 20:(layout + 1) * 20]):
                    codes = list(cfgtext.enc(names[action])) + [255]
                    records.append(self.record(c, codes, 13, bank=int(action == 0),
                                   dst=index + ((i % 10 + 6) * 40 + (i // 10) * 14 + 6) * 2,
                                   source=SOURCE + i * 32))
                self.render(c)
                self.assertTrue(all(c.read(ptr + 4, 2) & 0x8000 for ptr in records),
                                'every controller row must be claimed by the VWF')

    def test_config_tabs_match_marker_pitch_with_actual_font(self):
        import sys
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import cfgtext
        widths = (ROOT / 'build/sf_width.bin').read_bytes()
        for _, room, _, text in cfgtext.E:
            if '<TAB>' not in text:
                continue
            with self.subTest(text=text):
                c = self.machine(); self.layer(c)
                c.load(c.read(self.symbols['sf_cfg_adv'] + 0x14), widths)
                codes = list(cfgtext.enc(text))
                self.record(c, codes + [255], room)
                points = self.render(c)
                index = 0
                for i, part in enumerate(text.split('<TAB>')):
                    chars = [ch for ch in part if ch != ' ']
                    first = cfgtext.enc(chars[0])[0]
                    leading = len(part) - len(part.lstrip(' '))
                    expected = 20 + 40 * i + leading * (widths[0] & 15) - (widths[first] >> 4)
                    self.assertEqual(points[index] & 0xffff, expected)
                    index += len(chars)

    def test_full_config_slots_keep_a_safe_terminator(self):
        import sys
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import cfgtext
        for overlay in cfgtext.DELTA:
            data = (ROOT / 'build' / (overlay + '.BIN')).read_bytes()
            for address, room, has_ff, text in cfgtext.E:
                encoded = cfgtext.enc(text)
                if not has_ff or len(encoded) != room:
                    continue
                delta = (cfgtext.DELTA_LOW if address < 0x800b3000 else cfgtext.DELTA)[overlay]
                offset = address - cfgtext.B - delta
                self.assertEqual(data[offset:offset + room], encoded)
                tail = data[offset + room:offset + room + 8]
                end = tail.find(b'\xff')
                self.assertGreaterEqual(end, 0)
                self.assertFalse(any(tail[:end]))

    def test_padded_rows_preserve_fixed_cell_midpoint(self):
        original_symbols, original_overlay = self.symbols, self.overlay
        try:
            for overlay in ('adv', 'dng', 's2d'):
                self.symbols = dict(original_symbols)
                for name in ('sf_cfg', 'sf_state', 'sf_record', 'sf_hook_bg', 'sf_hook_fastbg'):
                    self.symbols[name + '_adv'] = original_symbols[name + '_' + overlay]
                self.overlay = (ROOT / 'build' / (overlay.upper() + '.BIN')).read_bytes()
                for fast in (False, True):
                    with self.subTest(overlay=overlay, fast=fast):
                        c = self.machine(); self.layer(c)
                        self.record(c, [0, 0, 10, 11, 0, 0, 255], 6 | 0x8000)
                        self.assertEqual([p & 0xffff for p in self.render(c, fast=fast)], [40, 44])
                        c = self.machine(); self.layer(c)
                        self.record(c, [0, 10, 11, 255], 3)
                        self.assertEqual([p & 0xffff for p in self.render(c, fast=fast)], [24, 28])
                        c = self.machine(); self.layer(c)
                        self.record(c, [0, 0, 10, 11, 0, 0, 255], 6)
                        self.assertEqual([p & 0xffff for p in self.render(c, fast=fast)], [28, 32])
        finally:
            self.symbols, self.overlay = original_symbols, original_overlay

    def test_retail_padded_heading_pair_shares_a_midpoint(self):
        import sys
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import cfgtext
        widths = (ROOT / 'build/sf_width.bin').read_bytes()
        original_symbols, original_overlay = self.symbols, self.overlay
        try:
            for overlay in ('adv', 'dng', 's2d'):
                self.symbols = dict(original_symbols)
                for name in ('sf_cfg', 'sf_state', 'sf_record', 'sf_hook_bg', 'sf_hook_fastbg'):
                    self.symbols[name + '_adv'] = original_symbols[name + '_' + overlay]
                self.overlay = (ROOT / 'build' / (overlay.upper() + '.BIN')).read_bytes()
                centers = []
                for address in (0x800b2390, 0x800b239c):
                    offset = address - cfgtext.B - cfgtext.DELTA_LOW[overlay.upper()]
                    codes = list(self.overlay[offset:offset + 11])
                    visible = [code for code in codes if code]
                    c = self.machine(); self.layer(c)
                    c.load(c.read(self.symbols['sf_cfg_adv'] + 0x14), widths)
                    self.record(c, codes + [255], 11 | 0x8000, bank=2)
                    points = self.render(c)
                    left = (points[0] & 0xffff) + (widths[visible[0]] >> 4)
                    right = ((points[-1] & 0xffff) + (widths[visible[-1]] >> 4)
                             + (widths[visible[-1]] & 15))
                    centers.append(left + right)  # twice the pixel midpoint
                with self.subTest(overlay=overlay):
                    self.assertLessEqual(abs(centers[0] - centers[1]), 2)
        finally:
            self.symbols, self.overlay = original_symbols, original_overlay

    def test_original_centered_producers_and_actual_fields(self):
        import sys
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import cfgtext
        widths = (ROOT / 'build/sf_width.bin').read_bytes()
        original_symbols, original_overlay = self.symbols, self.overlay
        try:
            for overlay in ('adv', 'dng', 's2d'):
                self.symbols = dict(original_symbols)
                for name in ('sf_cfg', 'sf_state', 'sf_record', 'sf_hook_bg', 'sf_hook_fastbg'):
                    self.symbols[name + '_adv'] = original_symbols[name + '_' + overlay]
                name = overlay.upper()
                self.overlay = (ROOT / 'build' / (name + '.BIN')).read_bytes()
                original = (ROOT / 'data/psx' / (name + '.BIN')).read_bytes()
                sites = cfgtext.centered_producers(original, name)
                self.assertEqual(len(sites), 4)
                for address, word in sites:
                    self.assertEqual(struct.unpack_from('<I', self.overlay, address - cfgtext.B)[0], word)
                for address, count, bank, delta in (
                        (0x800b9600, 10, 0, cfgtext.DELTA[name]),
                        (0x800b23b4, 11, 2, cfgtext.DELTA_LOW[name])):
                    with self.subTest(overlay=overlay, address=hex(address)):
                        offset = address - cfgtext.B - delta
                        codes = list(self.overlay[offset:offset + count])
                        codes = codes[:codes.index(255)] if 255 in codes else codes
                        c = self.machine(); self.layer(c)
                        c.load(c.read(self.symbols['sf_cfg_adv'] + 0x14), widths)
                        self.record(c, codes + [255], count | 0x8000, bank=bank)
                        points = self.render(c)
                        first = next(i for i, code in enumerate(codes) if code)
                        glyph = codes[first]
                        shift = (len(codes) * 8 - sum(widths[code] & 15 for code in codes)) // 2
                        expected = 20 + shift + sum(widths[code] & 15 for code in codes[:first])
                        self.assertEqual(points[0] & 0xffff, expected)
        finally:
            self.symbols, self.overlay = original_symbols, original_overlay

    def test_map_extent_and_mixed_blank_code_cursor(self):
        c = self.machine(); self.layer(c, width=4, height=1)
        c.write(BG + 8, 32, 2)
        # A literal glyph zero is valid only when it matches the recorded code.
        ptr = self.record(c, [0, 11, 255], 2)
        c.write(INDEX + 2, 11, 2)
        self.assertEqual(len(self.render(c)), 1)  # space advances but emits no packet
        self.assertEqual(c.read(ptr + 4, 2) & 0x7FFF, 2)
        c = self.machine(); self.layer(c, width=4, height=1)
        ptr = self.record(c, [10, 11, 255], 2, dst=INDEX + 6)
        c.write(INDEX + 8, 0xBEEF, 2)
        self.assertEqual(self.render(c), [])
        self.assertFalse(c.read(ptr + 4, 2) & 0x8000)
        self.assertEqual(c.read(INDEX + 8, 2), 0xBEEF)


if __name__ == '__main__':
    unittest.main()
