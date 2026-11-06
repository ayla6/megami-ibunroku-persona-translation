"""Execute the built pause-title hook on the R3000; capture its GPU upload.

Run after assembly: python -m unittest discover -s tools/tests -p test_field_pause_title.py -v
"""
from pathlib import Path
import os
import re
import struct
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
DNG_BASE = 0x800643C4
FONT_BASE = 0x801E0000
ENTRY = 0x8006E700
FALLBACK = 0x8006E708
FLOOR_PTR = 0x800A06C0
LOAD_IMAGE = 0x8002B810
DRAW_SYNC = 0x8002B5E8
FLOOR = 0x801C8000
STACK = 0x801CF000
RETURN = 0x801F0000
PIXELS = 160 * 16 // 2
VWF_GLYPHS = len((ROOT / "src/asm/font/vwf_width.bin").read_bytes())
VOLATILE = ('at', 'v0', 'v1', 'a0', 'a1', 'a2', 'a3',
            't0', 't1', 't2', 't3', 't4', 't5', 't6', 't7', 't8', 't9')
SAVED = ('s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7', 'gp', 'fp')


class BuiltPauseTitle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [ROOT / 'build' / n for n in
                 ('DNG.BIN', 'SLPS_005.00', 'FONT.BIN', 'persona.sym')]
        if not all(p.exists() for p in paths):
            raise unittest.SkipTest('requires assembled game files in build/')
        cls.dng, cls.slps, cls.font = (p.read_bytes() for p in paths[:3])
        cls.sym = {}
        for line in paths[3].read_text().splitlines():
            m = re.fullmatch(r'([0-9A-Fa-f]{8}) (\w+)', line)
            if m:
                cls.sym[m[2]] = int(m[1], 16)
        required = ('dng_field_title_hook', 'dng_field_title_pixels',
                    'dng_title_idx', 'dng_title_blob', 'vwf_font_index', 'vwf_font_width')
        missing = [name for name in required if name not in cls.sym]
        if missing:
            raise unittest.SkipTest('build predates pause-title hook: ' + ', '.join(missing))
        count, rem = divmod(cls.sym['dng_title_blob'] - cls.sym['dng_title_idx'], 24)
        if rem or not count:
            raise AssertionError('invalid title table bounds')
        cls.count = count

    def machine(self):
        c = CPU()
        c.load(DNG_BASE, self.dng)
        base, size = struct.unpack_from('<II', self.slps, 0x18)
        c.load(base, self.slps[0x800:0x800 + size])
        c.load(FONT_BASE, self.font)
        c.write(FLOOR_PTR, FLOOR)
        for reg in VOLATILE + SAVED:
            c.r[REG[reg]] = 0x13570000 + REG[reg] * 0x101
        c.r[REG['sp']], c.r[REG['ra']] = STACK, RETURN
        return c

    def row(self, c, i):
        addr = self.sym['dng_title_idx'] + i * 24
        key = bytes(c.mem[c.offset(addr, 20):c.offset(addr, 20) + 20])
        width, offset = c.read(addr + 20, 1), c.read(addr + 22, 2)
        addr = self.sym['dng_title_blob'] + offset
        script = bytearray()
        while c.read(addr, 1) != 0xff:
            script.append(c.read(addr, 1))
            addr += 1
            if len(script) > 255:
                self.fail('unterminated title')
        self.assertEqual(c.read(addr + 1, 1), 1)
        return key, width, bytes(script)

    def reference(self, c, width, script):
        self.assertLessEqual(width, 160)
        result = bytearray(PIXELS)
        pen = (160 - width) // 2
        widths = self.sym['vwf_font_width']
        index = self.sym['vwf_font_index']
        advance = 0
        def plot(x, y, color):
            if 0 <= x < 160 and 0 <= y < 16:
                off = y * 80 + x // 2
                result[off] |= color << (4 * (x & 1))
        for code in script:
            glyph = code - 0x88
            self.assertTrue(0 <= glyph < VWF_GLYPHS)
            off = c.read(index + glyph * 2, 2)
            for y in range(16):
                bits = c.read(FONT_BASE + off + y, 1)
                for x in range(8):
                    if bits & (0x80 >> x):
                        plot(pen + x, y, 1)
                        plot(pen + x + 1, y + 1, 2)
            step = c.read(widths + glyph, 1)
            advance += step
            pen += step
        self.assertEqual(advance, width, 'table width differs from font advances')
        return bytes(result)

    def execute(self, c, key):
        c.load(FLOOR, key)
        scratch = self.sym['dng_field_title_pixels']
        before = bytes(c.mem[c.offset(scratch - 16, PIXELS + 32):
                             c.offset(scratch - 16, PIXELS + 32) + PIXELS + 32])
        saved = {reg: c.r[REG[reg]] for reg in SAVED}
        calls = []
        def intercept(cpu):
            if cpu.pc not in (LOAD_IMAGE, DRAW_SYNC, FALLBACK):
                return False
            if cpu.pc == FALLBACK:
                calls.append(('fallback',))
                cpu.pc, cpu.next_pc = RETURN, RETURN + 4
                return True
            if cpu.pc == LOAD_IMAGE:
                rect = cpu.r[REG['a0']]
                coords = tuple(cpu.read(rect + i * 2, 2) for i in range(4))
                data = cpu.r[REG['a1']]
                off = cpu.offset(data, PIXELS)
                calls.append(('upload', coords, bytes(cpu.mem[off:off + PIXELS])))
            else:
                calls.append(('sync', cpu.r[REG['a0']]))
            ret = cpu.r[REG['ra']]
            for reg in VOLATILE:
                cpu.r[REG[reg]] = 0xC1000000 + REG[reg] * 0x101
            cpu.pc, cpu.next_pc = ret, ret + 4
            return True
        c.writes.clear()
        c.track_writes = True
        c.start(ENTRY)
        c.run(RETURN, limit=2000000, intercept=intercept)
        # The crash-class invariant: the renderer may write its own frame,
        # the floor key it reads, and the 160x16 pixel scratch - nowhere
        # else. A title that widened the scratch would show up here.
        owned = ((STACK - 0x68, 0x68), (FLOOR, 20), (scratch, PIXELS))
        for address, size in c.writes:
            inside = any(start <= address and address + size <= start + length
                         for start, length in owned)
            if not inside:
                self.fail(f'write outside owned regions: {address:#010x}+{size}')
        after = bytes(c.mem[c.offset(scratch - 16, PIXELS + 32):
                            c.offset(scratch - 16, PIXELS + 32) + PIXELS + 32])
        self.assertEqual(after[:16], before[:16])
        self.assertEqual(after[-16:], before[-16:])
        self.assertEqual(bytes(c.mem[c.offset(FLOOR, 20):c.offset(FLOOR, 20) + 20]), key)
        for reg in SAVED:
            self.assertEqual(c.r[REG[reg]], saved[reg], reg)
        if calls and calls[-1][0] == 'fallback':
            self.assertEqual(c.r[REG['sp']], STACK - 0x28)
            self.assertEqual(c.read(STACK - 0x28 + 0x18), saved['s0'])
        else:
            self.assertEqual(c.r[REG['sp']], STACK)
        return calls

    def test_all_shipped_rows_upload_exact_composited_pixels(self):
        c = self.machine()
        rows = [self.row(c, i) for i in range(self.count)]
        self.assertTrue(rows)
        for i, (key, width, script) in enumerate(rows):
            with self.subTest(row=i, width=width, length=len(script)):
                c = self.machine()
                expected = self.reference(c, width, script)
                calls = self.execute(c, key)
                self.assertEqual(calls, [('upload', (320, 72, 40, 16), expected), ('sync', 0)])

    def test_synthetic_width_boundaries_and_empty_title(self):
        seed = self.machine()
        widths = [seed.read(self.sym['vwf_font_width'] + i, 1) for i in range(95)]
        # Derive representable widths from the actual font, preferring ink over spaces.
        paths = {0: b''}
        for total in range(161):
            if total not in paths:
                continue
            for glyph in range(1, 95):
                nxt = total + widths[glyph]
                if widths[glyph] and nxt <= 160 and nxt not in paths:
                    paths[nxt] = paths[total] + bytes([glyph + 0x88])
        for width in (0, 15, 16, 31, 32, 159, 160):
            if width not in paths:
                continue
            with self.subTest(width=width):
                c = self.machine()
                row = self.sym['dng_title_idx']
                key = self.row(c, 0)[0]
                script = paths[width]
                c.write(row + 20, width, 1)
                c.write(row + 22, 0, 2)
                c.load(self.sym['dng_title_blob'], script + b'\xff\x01')
                expected = self.reference(c, width, script)
                self.assertEqual(self.execute(c, key),
                                 [('upload', (320, 72, 40, 16), expected), ('sync', 0)])

    def test_shared_extended_glyph_codes(self):
        c = self.machine()
        key = self.row(c, 0)[0]
        script = bytes(range(0x88 + 95, 0x88 + VWF_GLYPHS))
        width = sum(c.read(self.sym['vwf_font_width'] + b - 0x88, 1) for b in script)
        row = self.sym['dng_title_idx']
        c.write(row + 20, width, 1)
        c.write(row + 22, 0, 2)
        c.load(self.sym['dng_title_blob'], script + b'\xff\x01')
        expected = self.reference(c, width, script)
        self.assertEqual(self.execute(c, key),
                         [('upload', (320, 72, 40, 16), expected), ('sync', 0)])

    def test_captured_held_start_floor_matches_and_draws_full_title(self):
        path = os.environ.get('FIELD_PAUSE_RAM')
        if not path:
            self.skipTest('set FIELD_PAUSE_RAM to a captured held-START RAM image')
        ram = Path(path).read_bytes()
        floor = struct.unpack_from('<I', ram, FLOOR_PTR & 0x1fffff)[0]
        key = ram[floor & 0x1fffff:(floor & 0x1fffff) + 20]
        self.assertEqual(len(key), 20)
        c = self.machine()
        rows = [self.row(c, i) for i in range(self.count)]
        matches = [(width, script) for row_key, width, script in rows if row_key == key]
        self.assertEqual(len(matches), 1, 'captured field must identify exactly one table entry')
        width, script = matches[0]
        expected = self.reference(c, width, script)
        self.assertEqual(self.execute(c, key),
                         [('upload', (320, 72, 40, 16), expected), ('sync', 0)])

    def test_every_key_byte_mismatch_uses_retail_fallback(self):
        c = self.machine()
        rows = [self.row(c, i)[0] for i in range(self.count)]
        for pos in range(20):
            candidate = bytearray(rows[-1])
            for value in range(256):
                candidate[pos] = value
                if bytes(candidate) not in rows:
                    break
            else:
                self.fail('cannot construct unmatched key')
            with self.subTest(byte=pos):
                calls = self.execute(self.machine(), bytes(candidate))
                self.assertEqual(calls, [('fallback',)])


if __name__ == '__main__':
    unittest.main()
