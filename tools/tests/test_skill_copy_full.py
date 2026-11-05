"""Assembled skill copier: legacy ABI and explicit-capacity full-name entry."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools/tests')]
import skills
import slps
import toolbelt
from mips_cpu import CPU, REG

class SkillCopyFull(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = (ROOT / 'build/SLPS_005.00').read_bytes()
        cls.symbols = {}
        for line in (ROOT / 'build/persona.sym').read_text().splitlines():
            fields = line.split()
            if len(fields) == 2 and re.fullmatch(r'[0-9A-Fa-f]{8}', fields[0]):
                cls.symbols[fields[1]] = int(fields[0], 16)

    def execute(self, mode, name, cap):
        code = skills.encode_glyphs(0, name)
        head = code[:10]
        if len(head) < 10:
            head += b'\xff'
        head = head.ljust(10, b'\0')
        tail = code[10:]
        bank, offsets = skills.pack_tails([tail] if len(tail) > 3 else [])
        spare = bytes([0xfe, offsets[tail], 0]) if len(tail) > 3 else (tail+b'\xff\0\0')[:3]
        cpu = CPU(); cpu.load(0x80010000, self.image[0x800:])
        cpu.load(0x80047d58, head + bytes(7) + spare)
        cpu.load(0x8004ce6f, bank)
        for reg in range(1, 32): cpu.r[reg] = 0x11100000 + reg * 0x101
        cpu.r[REG['sp']] = 0x801ff000; cpu.r[REG['ra']] = 0x8000fff0
        cpu.r[REG['a0']] = 0x801f0000; cpu.r[REG['a1']] = 1; cpu.r[REG['a2']] = cap
        cpu.write(0x801effff, 0xa5, 1); cpu.write(0x801f0000 + cap, 0x5a, 1)
        before = cpu.r.copy(); hi, lo = cpu.hi, cpu.lo
        cpu.start(self.symbols['skill_name_copy' if mode == 'legacy' else 'skill_name_copy_full'])
        for _ in range(1000):
            if cpu.pc == 0x8000fff0: break
            cpu.step()
        else: self.fail('skill copy did not return')
        actual = bytes(cpu.read(0x801f0000+i, 1) for i in range(cap))
        # The copy writes the name then one FF terminator; a name that fills
        # the destination has no room for the terminator. Bytes past the
        # terminator stay untouched (the buffer starts zeroed).
        self.assertEqual(actual[:min(len(code), cap)], code[:cap])
        if len(code) < cap:
            self.assertEqual(actual[len(code)], 0xFF)
            self.assertEqual(actual[len(code)+1:], bytes(cap-len(code)-1))
        self.assertEqual(cpu.read(0x801effff, 1), 0xa5)
        self.assertEqual(cpu.read(0x801f0000 + cap, 1), 0x5a)
        clobbered = {REG[r] for r in ('v0', 'v1', 'a0', 'a1', 'a2', 'at')}
        for reg in range(1, 32):
            if reg not in clobbered:
                self.assertEqual(cpu.r[reg], before[reg], f'{mode} {name!r} register {reg}')
        self.assertEqual((cpu.hi, cpu.lo), (hi, lo))

    def test_assembled_ownership_tracks_written_english_skills(self):
        first = slps.SK_FIRST - slps.BASE
        ids = []
        for row in toolbelt.merged_rows(slps.REL):
            pos = int(row['pos'], 16)
            if (row['en'].strip() and first <= pos < first + slps.SK_STRIDE * slps.SK_COUNT
                    and (pos - first) % slps.SK_STRIDE == 0):
                ids.append((pos - first) // slps.SK_STRIDE + 1)
        expected = skills.vwf_ownership(ids)
        offset = toolbelt.asm_equ('SKILL_VWF_FLAGS_ADDR') - slps.BASE
        self.assertEqual(self.image[offset:offset + len(expected)], expected)

    def test_full_copy_never_crosses_small_destination(self):
        for name in ('A', 'ABCDEFGHIJ', 'ABCDEFGHIJKL', 'ABCDEFGHIJKLMN',
                     'ABCDEFGHIJKLMNOPQRS'):
            for cap in range(0, 16):
                with self.subTest(name=name, cap=cap):
                    self.execute('full', name, cap)

    def test_copies_and_pads_without_touching_adjacent_buffers(self):
        for name in ('A', 'ABCDEFGHI', 'ABCDEFGHIJ', 'ABCDEFGHIJKLM',
                     'ABCDEFGHIJKLMN', 'ABCDEFGHIJKLMNOPQRS'):
            for mode, cap in (('legacy', skills.MAXLEN), ('full', 24), ('full', 32)):
                with self.subTest(name=name, mode=mode, cap=cap):
                    self.execute(mode, name, cap)

if __name__ == '__main__':
    unittest.main()
