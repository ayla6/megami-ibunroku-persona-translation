"""DrawSpellName (ADV, DNG, S2D): the skill row reads the FULL name.

Retail cleared the caller's ten cells and copied the spell record's
ten-glyph head, so translated skill names over ten glyphs were cut. The
rewrite builds the complete name with skill_name_copy in the overlay's
small-font scratch and hands that scratch to the recorder, whose tiered
row still occupies the caller's ten-cell (80 px) footprint.

The runtime cases run the real assembled function against the real
skill_name_copy in the built SLPS image; the recorder entry is replaced
by a probe that records its arguments, so the wiring (source, count,
registers, empty-slot rule) is checked without the sorter.

Run after assembly:
    python -m unittest discover -s tools/tests -p test_draw_spell.py -v
"""
from pathlib import Path
import re
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools/tests')]
import skills                                          # noqa: E402
import toolbelt                                        # noqa: E402
import slps                                            # noqa: E402
from mips_cpu import CPU, REG                          # noqa: E402

OVERLAY_BASE = 0x800643C4
EXE_BASE = 0x80010000
STACK = 0x801FF000
RETURN = 0x801FF800
DST = 0x80180000
PROBE = 0x801E0000
REC = 0x801E0100

SKILL_NAME_COPY = 0x80011FBC

ADV = dict(name='ADV', func=0x8007BA94, fill=0x80067CEC, hook=0x80067C00,
           scratch=0x800BFB8C, rule=0x800B2F74)
DNG = dict(name='DNG', func=0x8008A8A4, fill=0x80077918, hook=0x8007782C,
           scratch=0x800B54D0, rule=0x8009BA64)
S2D = dict(name='S2D', func=0x8007A908, fill=0x800674CC, hook=0x800673E0,
           scratch=0x800BE614, rule=0x800AE5F4)
CASES = (ADV, DNG, S2D)


def jal(target):
    return 0x0C000000 | ((target >> 2) & 0x03FFFFFF)


def jump(target):
    return 0x08000000 | ((target >> 2) & 0x03FFFFFF)


def hi(value):
    return ((value + 0x8000) >> 16) & 0xFFFF


def lui_word(rt, value):
    return 0x3C000000 | (rt << 16) | hi(value)


class DrawSpellName(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        needed = [ROOT / 'build' / n for n in ('ADV.BIN', 'DNG.BIN', 'S2D.BIN',
                                               'SLPS_005.00', 'persona.sym')]
        needed += [ROOT / 'data/psx' / n for n in ('ADV.BIN', 'DNG.BIN', 'S2D.BIN')]
        if not all(p.exists() for p in needed):
            raise unittest.SkipTest('requires the assembled overlays')
        cls.built = {n: (ROOT / 'build' / f'{n}.BIN').read_bytes()
                     for n in ('ADV', 'DNG', 'S2D')}
        cls.retail = {n: (ROOT / 'data/psx' / f'{n}.BIN').read_bytes()
                      for n in ('ADV', 'DNG', 'S2D')}
        cls.slps = (ROOT / 'build/SLPS_005.00').read_bytes()
        cls.symbols = {}
        for line in (ROOT / 'build/persona.sym').read_text().splitlines():
            fields = line.split()
            if len(fields) == 2 and re.fullmatch(r'[0-9A-Fa-f]{8}', fields[0]):
                cls.symbols[fields[1]] = int(fields[0], 16)

    def word(self, data, address):
        return struct.unpack_from('<I', data, address - OVERLAY_BASE)[0]

    def half(self, data, address):
        return struct.unpack_from('<H', data, address - OVERLAY_BASE)[0]

    # -------------------------------------------------------------
    # assembled bytes
    # -------------------------------------------------------------
    def test_each_copy_uses_the_full_name_and_keeps_its_registers(self):
        for case in CASES:
            with self.subTest(overlay=case['name']):
                data = self.built[case['name']]
                f = case['func']
                # the full name is built in THIS overlay's scratch
                self.assertEqual(self.word(data, f + 0x58), jal(SKILL_NAME_COPY))
                self.assertEqual(self.word(data, f + 0x60), lui_word(4, case['scratch']))
                self.assertEqual(self.half(data, f + 0x64), case['scratch'] & 0xFFFF)
                # ... and the scratch (not the record) is the recorder source
                self.assertEqual(self.word(data, f + 0x94), jal(case['hook']))
                self.assertEqual(self.half(data, f + 0x74), 10)
                self.assertEqual(self.word(data, f + 0x70), jump(f + 0x94))
                # the empty-slot rule still tests the fourth argument
                self.assertEqual(self.word(data, f + 0x78), 0x00131400)  # sll v0,s3,16
                self.assertEqual(self.word(data, f + 0x84), lui_word(4, case['rule']))
                self.assertEqual(self.half(data, f + 0x88), case['rule'] & 0xFFFF)
                # the frame keeps the fifth argument at 0x10(sp) and the
                # saved registers above it (s2 must never share that slot)
                self.assertEqual(self.half(data, f + 0x2C), 0x0028)      # ori v0,0x28
                self.assertEqual(self.word(data, f + 0x44), 0xAFA20010)  # sw v0,0x10(sp)
                self.assertEqual(self.word(data, f + 0x9C), 0x8FBF0028)  # lw ra,0x28(sp)
                self.assertEqual(self.word(data, f + 0xA0), 0x8FB30024)  # lw s3,0x24(sp)
                self.assertEqual(self.word(data, f + 0xA4), 0x8FB20020)  # lw s2,0x20(sp)
                self.assertEqual(self.word(data, f + 0xB4), 0x27BD0030)  # addiu sp,0x30
                # the filler to the next retail function, and that function
                self.assertEqual(data[f + 0xB8 - OVERLAY_BASE:f + 0xBC - OVERLAY_BASE],
                                 bytes(4))
                self.assertEqual(self.word(data, f + 0xBC),
                                 self.word(self.retail[case['name']], f + 0xBC))

    # -------------------------------------------------------------
    # runtime: the real copier, a probe in place of the recorder
    # -------------------------------------------------------------
    def machine(self, case):
        cpu = CPU()
        cpu.load(OVERLAY_BASE, self.built[case['name']])
        size = struct.unpack_from('<I', self.slps, 0x1C)[0]
        cpu.load(EXE_BASE, self.slps[0x800:0x800 + size])
        # probe: record a0-a3 and bump a call counter, then return
        cpu.load(PROBE, struct.pack('<12I',
            0x3C08801E,       # lui t0,0x801E
            0xAD040100,       # sw a0,0x100(t0)
            0xAD050104,       # sw a1,0x104(t0)
            0xAD060108,       # sw a2,0x108(t0)
            0xAD07010C,       # sw a3,0x10C(t0)
            0x8D090110,       # lw t1,0x110(t0)
            0x00000000,       # nop
            0x25290001,       # addiu t1,t1,1
            0xAD090110,       # sw t1,0x110(t0)
            0x03E00008,       # jr ra
            0x00000000,
            0x00000000))
        cpu.load(case['hook'], struct.pack('<II', jump(PROBE), 0))
        cpu.r[REG['sp']] = STACK
        cpu.r[REG['ra']] = RETURN
        cpu.load(REC, bytes(0x20))
        cpu.load(DST, bytes(0x100))
        return cpu

    def long_skill(self):
        """The longest written skill name: (1-based id, encoded glyphs)."""
        first = slps.SK_FIRST - slps.BASE
        rows = []
        for row in toolbelt.merged_rows(slps.REL):
            pos = int(row['pos'], 16)
            if (row['en'].strip()
                    and first <= pos < first + slps.SK_STRIDE * slps.SK_COUNT
                    and (pos - first) % slps.SK_STRIDE == 0):
                rows.append(((pos - first) // slps.SK_STRIDE + 1,
                             row['en'].strip()))
        rows.sort(key=lambda item: len(item[1]), reverse=True)
        ident, text = rows[0]
        return ident, skills.encode_glyphs(ident, text)

    def test_runtime_full_name_reaches_the_recorder(self):
        ident, codes = self.long_skill()
        self.assertGreater(len(codes), 10)
        for case in CASES:
            with self.subTest(overlay=case['name']):
                cpu = self.machine(case)
                cpu.r[REG['a0']] = ident
                cpu.r[REG['a1']] = DST
                cpu.r[REG['a2']] = 0
                cpu.r[REG['a3']] = 1
                cpu.r[REG['s2']] = 0x11112222
                cpu.r[REG['s3']] = 0x33334444
                cpu.start(case['func'])
                cpu.run(RETURN, limit=200000)

                # one recorder call, sourced from the scratch with count 10
                self.assertEqual(cpu.read(REC, 4), case['scratch'])
                self.assertEqual(cpu.read(REC + 4, 4), DST)
                self.assertEqual(cpu.read(REC + 8, 4), 0)
                self.assertEqual(cpu.read(REC + 12, 4), 10)
                self.assertEqual(cpu.read(REC + 16, 4), 1)

                # the scratch holds the whole name and its terminator
                actual = bytes(cpu.read(case['scratch'] + i, 1)
                               for i in range(len(codes) + 1))
                self.assertEqual(actual, codes + b'\xff')

                # the function keeps the caller's callee-saved registers
                self.assertEqual(cpu.r[REG['s2']], 0x11112222)
                self.assertEqual(cpu.r[REG['s3']], 0x33334444)
                self.assertEqual(cpu.r[REG['sp']], STACK)

    def test_runtime_empty_slot_rule(self):
        for case in CASES:
            with self.subTest(overlay=case['name']):
                # flag set: retail's eight-glyph rule, one cell right
                cpu = self.machine(case)
                cpu.r[REG['a0']] = 0
                cpu.r[REG['a1']] = DST
                cpu.r[REG['a2']] = 0
                cpu.r[REG['a3']] = 1
                cpu.start(case['func'])
                cpu.run(RETURN, limit=20000)
                self.assertEqual(cpu.read(REC, 4), case['rule'])
                self.assertEqual(cpu.read(REC + 4, 4), DST + 2)
                self.assertEqual(cpu.read(REC + 8, 4), 0xD7)
                self.assertEqual(cpu.read(REC + 12, 4), 8)
                self.assertEqual(cpu.read(REC + 16, 4), 1)

                # flag clear: the cells are only cleared, no rule row
                cpu = self.machine(case)
                cpu.r[REG['a0']] = 0
                cpu.r[REG['a1']] = DST
                cpu.r[REG['a2']] = 0
                cpu.r[REG['a3']] = 0
                cpu.start(case['func'])
                cpu.run(RETURN, limit=20000)
                self.assertEqual(cpu.read(REC + 16, 4), 0)


if __name__ == '__main__':
    unittest.main()
