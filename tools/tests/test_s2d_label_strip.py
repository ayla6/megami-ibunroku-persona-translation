"""The S2D 1-row text path owns exactly its cols*16 px strip.

``s2d_txt_put`` routes the 8x1 area label and the 15x1 arrival banner through
a dedicated one-row path. Each string start rebuilds the object's whole strip:
every cell is blanked, uploaded and given its sprite record, so a shorter
string cannot inherit ink or a sprite record from a longer text drawn earlier
in the same object. That is the map corruption the labels showed - an extra
record sampled the neighbouring label's VRAM strip (labels 0 and 1 sit at
x 0x280 / 0x2A0 on the same rows).

The test drives the assembled putter glyph by glyph on the R3000, lets the
real upload queue and flush run, and paints only the GPU LoadImage call
(0x8002B810) into a 4bpp VRAM map. The final strip is compared with a
reference compositor built from the shipped font, so the assertions never
name a label or a glyph.

Run after assembly:
    python -m unittest discover -s tools/tests -p test_s2d_label_strip.py -v
"""
from pathlib import Path
import re
import struct
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
S2D_BASE = 0x800643C4
FONT_BASE = 0x801E0000
LOAD_IMAGE = 0x8002B810
STACK, RETURN = 0x801CF000, 0x801F0000
LABEL_OBJ = 0x801B0000
BANNER_OBJ = 0x801B0400
VOLATILE = ('v0', 'v1', 'a0', 'a1', 'a2', 'a3',
            't0', 't1', 't2', 't3', 't4', 't5', 't6', 't7', 't8', 't9')
MARKER = 0x4444                 # a nibble pair the font never writes (ink is 1/2)


class Vram:
    """A 4bpp VRAM map painted by the GPU LoadImage call."""

    def __init__(self):
        self.words = {}         # (u16 word, row) -> 2 bytes
        self.log = []           # (x, y, w, h, data) in drain order

    def marker(self, x, y, words, rows=16, value=MARKER):
        for row in range(rows):
            for i in range(words):
                self.words[(x + i, y + row)] = value.to_bytes(2, 'little')

    def marker_intact(self, x, y, words, rows=16, value=MARKER):
        return all(self.words.get((x + i, y + r)) == value.to_bytes(2, 'little')
                   for r in range(rows) for i in range(words))

    def hook(self, cpu):
        if cpu.pc == 0x8002B5E8:  # synchronous model has no pending transfers
            ret = cpu.r[REG['ra']]
            for name in VOLATILE:
                cpu.r[REG[name]] = 0
            cpu.pc, cpu.next_pc = ret, ret + 4
            return True
        if cpu.pc != LOAD_IMAGE:
            return False
        rect = cpu.r[REG['a0']]
        src = cpu.r[REG['a1']]
        x, y, w, h = (cpu.read(rect + 2 * i, 2) for i in range(4))
        off = cpu.offset(src, w * 2 * h)
        data = bytes(cpu.mem[off:off + w * 2 * h])
        self.log.append((x, y, w, h, data))
        for row in range(h):
            for i in range(w):
                self.words[(x + i, y + row)] = data[(row * w + i) * 2:(row * w + i) * 2 + 2]
        ret = cpu.r[REG['ra']]
        for name in VOLATILE:
            cpu.r[REG[name]] = 0
        cpu.pc, cpu.next_pc = ret, ret + 4
        return True

    def nibbles(self, x, y, width, rows=16):
        out = []
        for row in range(rows):
            line = []
            for word in range(width // 4):
                b = self.words.get((x + word, y + row), b'\0\0')
                line += [b[0] & 0xF, b[0] >> 4, b[1] & 0xF, b[1] >> 4]
            out.append(line)
        return out


class DeferredVram(Vram):
    """LoadImage queues pointers; DrawSync completes the pending DMA reads."""
    def __init__(self):
        super().__init__()
        self.pending = []

    def complete(self, cpu):
        for x, y, w, h, src in self.pending:
            off = cpu.offset(src, w * 2 * h)
            data = bytes(cpu.mem[off:off + w * 2 * h])
            self.log.append((x, y, w, h, data))
            for row in range(h):
                for i in range(w):
                    self.words[x + i, y + row] = data[(row * w + i) * 2:(row * w + i) * 2 + 2]
        self.pending.clear()

    def hook(self, cpu):
        if cpu.pc == LOAD_IMAGE:
            rect = cpu.r[REG['a0']]
            self.pending.append((*[cpu.read(rect + 2 * i, 2) for i in range(4)],
                                 cpu.r[REG['a1']]))
        elif cpu.pc == 0x8002B5E8:
            self.complete(cpu)
        else:
            return False
        ret = cpu.r[REG['ra']]
        for name in VOLATILE:
            cpu.r[REG[name]] = 0
        cpu.pc, cpu.next_pc = ret, ret + 4
        return True


class S2DOneRowStrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [ROOT / 'build' / name for name in
                 ('S2D.BIN', 'SLPS_005.00', 'FONT.BIN', 'persona.sym')]
        if not all(path.exists() for path in paths):
            raise unittest.SkipTest('requires the assembled overlay and symbols')
        cls.s2d, cls.slps, cls.font = (path.read_bytes() for path in paths[:3])
        cls.sym = {}
        for line in paths[3].read_text().splitlines():
            m = re.fullmatch(r'([0-9A-Fa-f]{8}) (\w+)', line)
            if m:
                cls.sym[m[2]] = int(m[1], 16)
        required = ('s2d_txt_put', 's2d_txt_activate', 's2d_txt_cfg',
                    'vwf_font_index', 'vwf_font_width', 'vwf_dlg_ring')
        missing = [name for name in required if name not in cls.sym]
        if missing:
            raise unittest.SkipTest('build predates the 1-row path: ' + ', '.join(missing))

    # -------------------------------------------------------------
    # machine and object setup
    # -------------------------------------------------------------

    def machine(self):
        c = CPU()
        c.load(S2D_BASE, self.s2d)
        base, size = struct.unpack_from('<II', self.slps, 0x18)
        c.load(base, self.slps[0x800:0x800 + size])
        c.load(FONT_BASE, self.font)
        c.write(0x800A8A2C, 0)                  # LoadImage queue B count (boot BSS)
        c.write(0x800A8A30, 0)                  # LoadImage queue A count (boot BSS)
        c.r[REG['sp']], c.r[REG['ra']] = STACK, RETURN
        return c

    def text_object(self, c, addr, cols, x, y):
        """The state retail's object create (0x8009A984) leaves behind."""
        c.load(addr, bytes(0x23C))
        c.write(addr + 0x00, 5, 2)          # flags passed by the label / banner draw
        c.write(addr + 0x1C4, x, 2)
        c.write(addr + 0x1C6, y, 2)
        c.write(addr + 0x1C8, 0x200, 2)     # attr args (retail 0x200 / 0xF8)
        c.write(addr + 0x1CA, 0xF8, 2)
        c.write(addr + 0x1D8, cols, 2)
        c.write(addr + 0x1DA, 1, 2)

    def recreate(self, c, addr):
        """Next frame: the draw creates the object again before the string."""
        for off in (0x02, 0x04, 0x06, 0x12):
            c.write(addr + off, 0, 2)

    def count(self, c, obj):
        return c.read(obj + 6, 2)

    def records(self, c, obj):
        out = []
        for i in range(self.count(c, obj)):
            rec = obj + 0x1C + i * 8
            out.append((c.read(rec, 1), c.read(rec + 1, 1),
                        c.read(rec + 4, 2), c.read(rec + 6, 2)))
        return out

    # -------------------------------------------------------------
    # execution
    # -------------------------------------------------------------

    def call(self, c, v, address, a0=None):
        c.r[REG['sp']], c.r[REG['ra']] = STACK, RETURN
        if a0 is not None:
            c.r[REG['a0']] = a0
        c.start(address)
        c.run(RETURN, limit=400000, intercept=v.hook)

    def put(self, c, v, obj, code):
        c.r[REG['a0']] = obj
        c.r[REG['a1']] = code
        self.call(c, v, self.sym['s2d_txt_put'])

    def flush(self, c, v):
        """The label / banner draw drains the queue once the string is laid."""
        self.call(c, v, 0x80099050)

    def draw(self, c, v, obj, codes):
        for code in codes:
            self.put(c, v, obj, code)
        self.flush(c, v)

    # -------------------------------------------------------------
    # the shipped font, as an independent reference compositor
    # -------------------------------------------------------------

    def glyph(self, c, code):
        """(advance, wide?, byte offset in FONT.BIN) for an encoded glyph byte."""
        if code & 0x8000:
            return 16, True, (code & 0x7FF) * 32
        index = code - 0x88
        if index == 0:                      # 0x88 = space (SPACE_ADVANCE)
            return 4, False, None
        advance = c.read(self.sym['vwf_font_width'] + index, 1)
        offset = c.read(self.sym['vwf_font_index'] + 2 * index, 2)
        return advance, False, offset

    def reference(self, c, codes, width):
        rows = [[0] * width for _ in range(16)]
        pen = 0
        for code in codes:
            advance, wide, offset = self.glyph(c, code)
            if offset is not None and pen + advance <= width:
                for row in range(16):
                    bits = (c.read(FONT_BASE + offset + 2 * row, 2) if wide
                            else c.read(FONT_BASE + offset + row, 1))
                    mask = 0x8000 if wide else 0x80
                    for bit in range(16 if wide else 8):
                        if not bits & (mask >> bit):
                            continue
                        x = pen + bit
                        if x < width:
                            rows[row][x] |= 1
                        if row < 15 and x + 1 < width:
                            rows[row + 1][x + 1] |= 2
            pen += advance
        return rows

    def codes(self, c):
        """Glyph codes derived from the shipped advances: the widest inked
        glyph and a 5 px inked one (the test never names a character)."""
        def inked(i):
            advance, _wide, offset = self.glyph(c, 0x88 + i)
            return (offset is not None and advance > 0 and
                    any(c.read(FONT_BASE + offset + row, 1) for row in range(16)))

        widths = [c.read(self.sym['vwf_font_width'] + i, 1) for i in range(99)]
        widest = next(0x88 + i for i in sorted(range(1, 99), key=lambda i: -widths[i])
                      if inked(i))
        small = next((0x88 + i for i in range(1, 99)
                      if widths[i] == 5 and inked(i)), None)
        self.assertIsNotNone(small, 'no 5 px inked glyph in the shipped font')
        return widest, small

    # -------------------------------------------------------------
    # the map label: 8 cells, beside another label's strip
    # -------------------------------------------------------------

    def test_label_strip_is_rebuilt_for_a_shorter_string(self):
        c = self.machine()
        v = Vram()
        widest, small = self.codes(c)
        self.text_object(c, LABEL_OBJ, 8, 0x280, 0x100)
        v.marker(0x2A0, 0x100, 32)                  # the next label's strip

        # a longer text: twenty widest glyphs overflow the 128 px strip
        long_codes = [widest] * 20
        self.draw(c, v, LABEL_OBJ, long_codes)
        self.assertEqual(v.nibbles(0x280, 0x100, 128), self.reference(c, long_codes, 128))
        self.assertEqual(self.count(c, LABEL_OBJ), 8, 'one record per strip cell')
        self.assertEqual(self.records(c, LABEL_OBJ),
                         [(((0x280 & 63) << 2) + 16 * cell, 0, 16 * cell, 0)
                          for cell in range(8)])
        self.assertTrue(v.marker_intact(0x2A0, 0x100, 32), 'nothing drew into the next strip')

        # next frame: a much shorter string in the same object
        self.recreate(c, LABEL_OBJ)
        short = [small] * 4
        pen = sum(self.glyph(c, code)[0] for code in short)
        start = len(v.log)
        self.draw(c, v, LABEL_OBJ, short)
        # the frame began by blanking and re-uploading all eight cells
        self.assertEqual([entry[:4] for entry in v.log[start:start + 8]],
                         [(0x280 + 4 * cell, 0x100, 4, 16) for cell in range(7, -1, -1)])
        self.assertTrue(all(entry[4] == bytes(128) for entry in v.log[start:start + 8]))
        self.assertEqual(v.nibbles(0x280, 0x100, 128), self.reference(c, short, 128))
        self.assertEqual(self.count(c, LABEL_OBJ), 8)
        self.assertTrue(v.marker_intact(0x2A0, 0x100, 32))
        # everything past the short text is blank, cells with a record too
        self.assertFalse(any(any(row[pen + 2:]) for row in v.nibbles(0x280, 0x100, 128)))

    # -------------------------------------------------------------
    # the arrival banner: 15 cells, longer than the compositor ring
    # -------------------------------------------------------------

    def test_banner_blank_uploads_do_not_alias_deferred_glyphs(self):
        c, v = self.machine(), DeferredVram()
        widest, small = self.codes(c)
        self.text_object(c, BANNER_OBJ, 15, 0x1C0, 0x100)
        codes = [widest, small] * 8
        self.draw(c, v, BANNER_OBJ, codes)
        v.complete(c)
        self.assertEqual(v.nibbles(0x1C0, 0x100, 240), self.reference(c, codes, 240))

    def test_banner_strip_is_rebuilt_and_stays_inside_15_cells(self):
        c = self.machine()
        v = Vram()
        widest, small = self.codes(c)
        self.text_object(c, BANNER_OBJ, 15, 0x1C0, 0x100)
        v.marker(0x1FC, 0x100, 32)                  # past the banner's strip

        # thirty widest glyphs: 270 px, clipped at the 240 px strip
        long_codes = [widest] * 30
        self.draw(c, v, BANNER_OBJ, long_codes)
        self.assertEqual(v.nibbles(0x1C0, 0x100, 240), self.reference(c, long_codes, 240))
        self.assertEqual(self.count(c, BANNER_OBJ), 15)
        self.assertEqual(self.records(c, BANNER_OBJ),
                         [(((0x1C0 & 63) << 2) + 16 * cell, 0, 16 * cell, 0)
                          for cell in range(15)])
        self.assertTrue(v.marker_intact(0x1FC, 0x100, 32), 'nothing drew past 15 cells')

        # next banner: a short name must not inherit the long one
        self.recreate(c, BANNER_OBJ)
        short = [small] * 3
        pen = sum(self.glyph(c, code)[0] for code in short)
        start = len(v.log)
        self.draw(c, v, BANNER_OBJ, short)
        self.assertEqual([entry[:4] for entry in v.log[start:start + 15]],
                         [(0x1C0 + 4 * cell, 0x100, 4, 16) for cell in range(14, -1, -1)])
        self.assertTrue(all(entry[4] == bytes(128) for entry in v.log[start:start + 15]))
        self.assertEqual(v.nibbles(0x1C0, 0x100, 240), self.reference(c, short, 240))
        self.assertEqual(self.count(c, BANNER_OBJ), 15)
        self.assertTrue(v.marker_intact(0x1FC, 0x100, 32))
        self.assertFalse(any(any(row[pen + 2:]) for row in v.nibbles(0x1C0, 0x100, 240)))

    # -------------------------------------------------------------
    # the object owns its grid: no cell outside cols*rows
    # -------------------------------------------------------------

    def test_activate_ignores_cells_outside_the_object_grid(self):
        c = self.machine()
        v = Vram()
        self.text_object(c, LABEL_OBJ, 8, 0x280, 0x100)
        cfg = self.sym['s2d_txt_cfg']
        c.write(cfg + 0x10, LABEL_OBJ)              # S2DT_STRUCT
        c.write(cfg + 0x18, self.sym['vwf_dlg_ring'])   # S2DT_ENTRY (src)
        c.write(cfg + 0x14, 0)                      # S2DT_COUNT

        # cell 8 is the first cell past an 8x1 grid: no upload, no record
        self.call(c, v, self.sym['s2d_txt_activate'], 8)
        self.flush(c, v)
        self.assertEqual(v.log, [])
        self.assertEqual(self.count(c, LABEL_OBJ), 0)
        # cell 7 is the last one the object owns
        self.call(c, v, self.sym['s2d_txt_activate'], 7)
        self.flush(c, v)
        self.assertEqual([entry[:4] for entry in v.log], [(0x280 + 28, 0x100, 4, 16)])
        self.assertEqual(self.records(c, LABEL_OBJ), [(112, 0, 112, 0)])


if __name__ == '__main__':
    unittest.main()
