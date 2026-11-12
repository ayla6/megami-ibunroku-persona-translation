"""Dialogue pacing: glyphs per frame in the patched interpreters.

MsgStep (ADV / DNG / S2D) prints up to the overlay's MSG_PACE glyphs per
call, and only glyph steps continue; the dungeon script boxes batch their
glyphs before the frame waits. Both run on the assembled binaries with the
glyph renderers and FieldFrame stubbed.

Run after assembly:
    python -m unittest discover -s tools/tests -p test_text_pace.py -v
"""
from pathlib import Path
import re
import struct
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = 0x800643C4
STACK = 0x801FF000
RETURN = 0x801FF800
SCRIPT = 0x80180000
GLYPH = 0xA9                                # 'A' in the dialogue VWF encoding


def equ(name):
    text = (ROOT / 'src/asm/common/addresses.inc').read_text()
    return int(re.search(rf'^{name}\s+equ\s+(\w+)', text, re.M).group(1), 0)


def symbols():
    out = {}
    for line in (ROOT / 'build/persona.sym').read_text().splitlines():
        match = re.fullmatch(r'([0-9A-Fa-f]{8}) (\w+)', line)
        if match:
            out[match[2]] = int(match[1], 16)
    return out


class Paced(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / 'build/persona.sym').exists():
            raise unittest.SkipTest('requires assembled game files in build/')
        cls.sym = symbols()
        cls.exe = (ROOT / 'build/SLPS_005.00').read_bytes()

    def machine(self, ovl):
        c = CPU()
        c.load(OVERLAY, (ROOT / 'build' / f'{ovl}.BIN').read_bytes())
        base, size = struct.unpack_from('<II', self.exe, 0x18)
        c.load(base, self.exe[0x800:0x800 + size])
        return c

    # ---------------------------------------------------------- MsgStep
    MSG = {'ADV': 0x800669AC, 'DNG': 0x80076820, 'S2D': 0x800663C0}
    STATE = {'ADV': 'ADV_TEXT_STATE', 'DNG': 'DNG_TEXT_STATE', 'S2D': 'S2D_TEXT_STATE'}

    def msg_calls(self, ovl, script, speed, calls):
        """Glyphs printed by each of `calls` MsgStep calls."""
        c = self.machine(ovl)
        st = equ(self.STATE[ovl])
        c.write(st + 0, 0)                   # flags
        c.write(st + 4, 0, 2)                # wait
        c.write(st + 6, 0, 2)                # delay
        c.write(st + 8, speed, 2)            # speed
        c.write(st + 0xA, 0, 2)              # cursor
        c.write(st + 0xC, SCRIPT)
        c.load(SCRIPT, bytes(script))
        emit = self.sym[f'vwf_{ovl.lower()}_emit']
        activate = equ(f'{ovl}_CELL_ACTIVATE')
        per_call = []
        for _ in range(calls):
            printed = []

            def stub(cpu):
                # The emit stub counts a glyph; the cell activation and the
                # resident helpers a step reaches (uploads, slots) return.
                if cpu.pc == emit:
                    printed.append(cpu.r[REG['a2']] & 0xFF)
                elif cpu.pc != activate and not 0x80010000 <= cpu.pc < 0x80060000:
                    return False
                cpu.r[REG['v0']] = 0
                cpu.start(cpu.r[REG['ra']])
                return True
            c.r[REG['sp']], c.r[REG['ra']] = STACK, RETURN
            c.start(self.MSG[ovl])
            c.run(RETURN, intercept=stub, limit=200000)
            per_call.append(len(printed))
        return per_call

    def test_msgstep_prints_the_overlays_glyphs_per_call(self):
        for ovl in ('ADV', 'DNG', 'S2D'):
            k = equ(f'{ovl}_MSG_PACE')
            with self.subTest(ovl=ovl):
                calls = self.msg_calls(ovl, [GLYPH] * 12 + [0xFF, 0x02], 0, 4)
                self.assertEqual(calls, [k] * 4)

    def test_msgstep_keeps_the_speed_wait_between_batches(self):
        # Normal speed (delay 2): a batch, then two frames of waiting.
        for ovl in ('ADV', 'DNG', 'S2D'):
            k = equ(f'{ovl}_MSG_PACE')
            with self.subTest(ovl=ovl):
                calls = self.msg_calls(ovl, [GLYPH] * 12 + [0xFF, 0x02], 2, 6)
                self.assertEqual(calls, [k, 0, 0, k, 0, 0])

    def test_msgstep_stops_a_batch_at_a_key_prompt(self):
        # A key wait mid-batch ends the call; the glyph after it waits for a
        # press, so one frame can never pass two prompts.
        for ovl in ('ADV', 'DNG', 'S2D'):
            with self.subTest(ovl=ovl):
                calls = self.msg_calls(ovl, [GLYPH, 0xFF, 0x02, GLYPH, GLYPH], 0, 3)
                self.assertEqual(calls, [1, 0, 0])

    # ---------------------------------------------------------- S2D text objects
    def object_calls(self, speed, calls):
        c = self.machine('S2D')
        obj = 0x80170000
        c.load(obj, bytes(0x23C))
        c.write(obj + 2, 0x0001, 2)          # initialised, reading
        c.write(obj + 0xC, SCRIPT)
        c.write(obj + 0x16, speed, 2)
        c.write(obj + 0x1D8, 15, 2)          # the 15x3 dialogue object
        c.write(obj + 0x1DA, 3, 2)
        c.load(SCRIPT, bytes([GLYPH] * 24 + [0xFF, 0x01]))
        put = self.sym['s2d_txt_put']
        returns = {0x8008E68C: 0, 0x8009ADF0: 0, 0x8009B1FC: 1}
        per_call = []
        for _ in range(calls):
            printed = []

            def stub(cpu):
                if cpu.pc == put:
                    printed.append(1)
                    cpu.r[REG['v0']] = 0
                elif cpu.pc in returns:
                    cpu.r[REG['v0']] = returns[cpu.pc]
                else:
                    return False
                cpu.start(cpu.r[REG['ra']])
                return True
            c.r[REG['sp']], c.r[REG['ra']], c.r[REG['a0']] = STACK, RETURN, obj
            c.start(0x8009B2F4)
            c.run(RETURN, intercept=stub, limit=200000)
            per_call.append(len(printed))
        return per_call

    def test_text_objects_print_two_glyphs_per_call(self):
        # Speed 0: two glyphs a call. Speed 1 (retail: a glyph every second
        # call): one glyph a call.
        self.assertEqual(self.object_calls(0, 4), [2, 2, 2, 2])
        self.assertEqual(self.object_calls(1, 4), [1, 1, 1, 1])

    # ---------------------------------------------------------- DNG script boxes
    def script_events(self, speed, glyphs):
        c = self.machine('DNG')
        c.load(SCRIPT, bytes([0x41] * glyphs + [0x41] * 8))
        sp = STACK - 0x200
        c.write(sp + 0x38, 1)                # running
        c.write(sp + 0x40, 0)                # nowait
        c.write(sp + 0x48, 0)                # batch
        c.r[REG['sp']], c.r[REG['s5']], c.r[REG['fp']] = sp, SCRIPT, speed
        put = {self.sym['dng_txt_put'], self.sym['dng_txt_put_wide']}
        frame = 0x800659B4
        events = []

        def stub(cpu):
            if cpu.pc in put:
                events.append('g')
            elif cpu.pc == frame:
                events.append('f')
            else:
                return False
            if len(events) >= glyphs * 4:
                cpu.start(RETURN)
                return True
            cpu.start(cpu.r[REG['ra']])
            return True
        c.start(0x80073F90)
        c.run(RETURN, intercept=stub, limit=500000)
        return ''.join(events)

    def test_script_boxes_batch_glyphs_before_their_frame_waits(self):
        # Fast: three glyphs per frame; Normal / Slow: two glyphs, then the
        # setting's frames and the pass's own frame.
        for speed, unit in ((0, 'gggf'), (1, 'ggff'), (2, 'ggfff')):
            with self.subTest(speed=speed):
                events = self.script_events(speed, 12)
                self.assertTrue(events.startswith(unit * 3), events)


if __name__ == '__main__':
    unittest.main()
