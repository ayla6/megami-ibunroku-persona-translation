"""Execute Rev 0 battle interpreters with the assembled glyph batching hook."""
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest

import toolpath
from mips_cpu import CPU, REG

ROOT = Path(toolpath.ROOT)
BASE = 0x800643C4
EMIT = 0x80002000
STOP = 0x80001000
WINDOW = 0x80190000
TEXT = 0x80198000
STACK = 0x801EF000


class BattleTextPace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = TemporaryDirectory()
        work = Path(cls.workspace.name)
        source = work/'fixture.asm'
        source.write_text('.psx\n.definelabel SF_VWF, 1\n'
            f'.include "{ROOT}/src/mods/base/asm/common/addresses.inc"\n'
            f'.definelabel btlp_vwf_emit, {EMIT}\n'
            f'.definelabel btlp_str16, {STOP}\n.definelabel btl_name_copy, {STOP}\n'
            f'.open "{ROOT}/data/psx/BTLP.BIN", "{work}/patched.bin", {BASE}\n'
            f'.include "{ROOT}/src/mods/latin-alphabet/asm/btlp/vwf_hooks.asm"\n'
            f'.close\n.open "{ROOT}/data/psx/SLPS_005.00", "{work}/resident.bin", 0x8000F800\n'
            f'.include "{ROOT}/src/mods/latin-alphabet/asm/btlp/msg_pace.asm"\n.close\n')
        subprocess.run([str(ROOT/'external_tools/armips/armips'), '-erroronwarning', str(source)],
                       check=True, capture_output=True)
        cls.image = (work/'patched.bin').read_bytes()
        cls.resident = (work/'resident.bin').read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def execute(self, text, *, window=WINDOW, entry=0x8007C9E0, state=1, placed=0, delay=0, defer=False):
        cpu = CPU()
        cpu.load(BASE, self.image)
        cpu.load(0x8000F800, self.resident)
        cpu.load(TEXT, text)
        cpu.write(window+2, state, 2)
        cpu.write(window+8, TEXT)
        cpu.write(window+12, TEXT)
        cpu.write(window+0x1C, placed)
        cpu.write(window+0x18, delay)
        cpu.r[REG['a0']] = window
        cpu.r[REG['a1']] = TEXT if entry == 0x8007C9E0 else 1
        cpu.r[REG['a2']] = 1
        cpu.r[REG['sp']] = STACK
        cpu.r[REG['ra']] = STOP
        for reg in ('s0', 's1', 's2'):
            cpu.r[REG[reg]] = 0x12340000 + REG[reg]
        emitted = []
        def intercept(active):
            if active.pc != EMIT:
                return False
            pointer = active.r[REG['a1']]
            target = active.r[REG['a0']]
            glyph = active.read(pointer, 1)
            self.assertNotEqual(glyph, 0xFF, 'a control token was emitted as text')
            emitted.append(pointer)
            active.r[REG['v0']] = pointer if defer else pointer + (2 if 0x80 <= glyph < 0x88 else 1)
            if not defer:
                active.write(target+0x1C, active.read(target+0x1C)+1)
            active.pc = active.r[REG['ra']]
            active.next_pc = active.pc+4
            active.pending = None
            return True
        cpu.start(entry)
        cpu.run(STOP, limit=4000, intercept=intercept)
        self.assertEqual(cpu.r[REG['sp']], STACK)
        for reg in ('s0', 's1', 's2'):
            self.assertEqual(cpu.r[REG[reg]], 0x12340000+REG[reg])
        return cpu, emitted

    def test_both_windows_batch_ascii_and_two_byte_glyphs(self):
        for window in (WINDOW, WINDOW+0x400):
            for text, advance in ((b'AB\xff\xf5', 2), (b'\x87\x23B\xff\xf5', 3)):
                with self.subTest(window=window, text=text):
                    cpu, emitted = self.execute(text, window=window)
                    self.assertEqual(len(emitted), 2)
                    self.assertEqual(cpu.r[REG['v0']], TEXT+advance)
                    self.assertEqual(cpu.read(window+0x1C), 2)

    def test_control_boundary_full_page_and_deferred_glyph_stop_the_batch(self):
        for kwargs in ({}, {'placed': 44}, {'defer': True}):
            text = b'A\xff\xfc' if not kwargs else b'AB\xff\xf5'
            cpu, emitted = self.execute(text, **kwargs)
            self.assertEqual(len(emitted), 1)
        self.assertEqual(self.execute(b'A\xff\xfc')[0].read(WINDOW+2, 2), 1)

    def test_wait_choice_and_speed_codes_emit_nothing(self):
        for text, state in ((b'\xff\xfcA', 2), (b'\xff\xff\x03A', 2),
                            (b'\xff\xf1A', 11), (b'\xff\xf5A', 8)):
            with self.subTest(text=text):
                cpu, emitted = self.execute(text)
                self.assertEqual(emitted, [])
                self.assertEqual(cpu.read(WINDOW+2, 2), state)

    def test_configured_delay_is_kept_after_the_two_glyph_batch(self):
        cpu, emitted = self.execute(b'ABC\xff\xf5', delay=3)
        self.assertEqual(len(emitted), 2)
        self.assertEqual(cpu.read(WINDOW+0x14), 3)
        self.assertEqual(cpu.read(WINDOW+2, 2), 2)

    def test_insert_typing_advances_two_without_consuming_script(self):
        cpu, emitted = self.execute(b'AB\xff', entry=0x8007CD38, state=7)
        self.assertEqual(len(emitted), 2)
        self.assertEqual(cpu.read(WINDOW+12), TEXT+2)
        self.assertEqual(cpu.read(WINDOW+8), TEXT)
        self.assertEqual(cpu.read(WINDOW+2, 2), 1)
