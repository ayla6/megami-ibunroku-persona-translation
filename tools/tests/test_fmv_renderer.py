"""Execute the assembled FMV loops, including R3000 load/branch delays.

Requires the normal renderer armips pass (build/movie_subs_code.bin + .sym).
No GPU, savestate, or retail-only fallback is used.
"""
from pathlib import Path
import re
import sys
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]


class LoadCountCPU(CPU):
    def __init__(self):
        super().__init__()
        self.ram_loads = 0

    def step(self):
        word = self.read(self.pc)
        if word >> 26 in (32, 33, 34, 35, 36, 37, 38):
            self.ram_loads += 1
        super().step()


class Renderer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = (ROOT / 'build/movie_subs_code.bin').read_bytes()
        cls.sym = {m[2]: int(m[1], 16)
                   for line in (ROOT / 'build/movie_subs.sym').read_text().splitlines()
                   if (m := re.fullmatch(r'([0-9A-Fa-f]{8}) (\S+)', line))}
        cls.sym.update({m[1].lower(): int(m[2], 16) for m in re.finditer(
            r'^(S_\w+)\s+equ\s+(0x[0-9A-Fa-f]+)',
            (ROOT / 'src/asm/movie_exe/subs_code.asm').read_text(), re.M)})

    def cpu(self, cls=CPU):
        c = cls()
        c.load(0x80160000, self.code)
        c.r[REG['sp']] = 0x801ff000
        return c

    def run_until(self, c, start, stop, bound=20000):
        c.start(self.sym[start])
        for _ in range(bound):
            if c.pc == stop:
                return
            c.step()
        self.fail(f'{start} did not finish')

    def test_patch_runs_are_byte_exact_and_preserve_neighbors(self):
        palette = [bytes((i, (i * 37) & 255, 255 - i, 0)) for i in range(256)]
        for alignment in range(4):
            for length in (1, 2, 3, 4, 5, 7, 8, 15, 127, 320):
                with self.subTest(alignment=alignment, length=length):
                    c = self.cpu(LoadCountCPU)
                    src, dest, pal = 0x80020000, 0x80030000 + alignment, 0x80140200
                    indices = bytes((i * 53 + 17) & 255 for i in range(length))
                    c.load(pal, b''.join(palette))
                    # pp_run consumes x0,len,indices then stops at pp_row.
                    c.load(src, b'\0\0' + length.to_bytes(2, 'little') + indices)
                    c.load(dest - 4, b'\xa5' * (length * 3 + 8))
                    for reg, value in dict(s1=pal, s4=src, s5=dest, t2=1).items():
                        c.r[REG[reg]] = value
                    self.run_until(c, 'pp_run', self.sym['pp_row'])
                    actual = bytes(c.read(dest - 4 + i, 1) for i in range(length * 3 + 8))
                    expected = b'\xa5' * 4 + b''.join(palette[i][:3] for i in indices) + b'\xa5' * 4
                    self.assertEqual(actual, expected)
                    if length == 320:
                        self.assertLess(c.steps, 8.5 * length)
                        # 80 source words + 320 palette words + run metadata,
                        # rather than 320 individual source-byte loads.
                        self.assertLessEqual(c.ram_loads, 410)

    def test_probe_sum_matches_every_byte_without_lane_carries(self):
        for offset in range(4):
            for count in (0, 1, 3, 4, 15, 16, 17, 511, 512, 513, 1024, 3384, 3840):
                for solid in (False, True):
                    with self.subTest(offset=offset, count=count, solid=solid):
                        c = self.cpu()
                        src = 0x80020000 + offset
                        data = bytes([255]) * count if solid else bytes(
                            (i * 53 + 17) & 255 for i in range(count))
                        c.load(src, data + b'\xa5' * 16)
                        c.r[REG['t0']], c.r[REG['t4']] = src, count
                        c.r[REG['ra']] = 0x80001000
                        self.run_until(c, 'sum_bytes', 0x80001000)
                        self.assertEqual(c.r[REG['t5']], sum(data))
                        self.assertEqual(c.r[REG['t0']], src + count)
                        self.assertEqual(c.r[REG['t4']], 0)

    def test_padded_patch_runs_clip_pan_rows_and_preserve_gaps(self):
        import struct
        palette = [bytes((i, (i * 37) & 255, 255 - i)) for i in range(256)]
        patch = bytearray(b''.join(palette) + b'\xff\0\0\0\0\1\xff\0')
        rows = []
        for y in range(2, 9):
            runs = [(2, bytes((y * 11 + i) & 255 for i in range(3))),
                    (10, bytes((y * 19 + i) & 255 for i in range(7))),
                    (22, bytes((y * 23 + i) & 255 for i in range(2)))]
            rows.append((y, runs))
            patch.extend((y, len(runs)))
            for x, indices in runs:
                patch.extend(struct.pack('<HH', x, len(indices)))
                while len(patch) & 3:
                    patch.append(0)
                patch.extend(indices)
                while len(patch) & 3:
                    patch.append(0)
        patch.append(255)
        for pan in (-2, 0, 2):
            for scale in (1, 128, 256, 400):
                with self.subTest(pan=pan, scale=scale):
                    c = self.cpu()
                    scratch = 0x80140640
                    size = 24 * 3 * 3
                    c.load(scratch, b'\xa5' * (size + 16))
                    c.load(0x80020000, patch)
                    for name, value in dict(s_scale=scale, s_cur_p=pan, s_cur_l=0,
                                            s_bandy0=4, s_bandrows=3,
                                            s_stride=72, s_xoff=0).items():
                        c.write(self.sym[name], value)
                    c.r[REG['a0']] = 0x80020000
                    c.r[REG['s0']] = 0x80023000
                    c.r[REG['ra']] = 0x80001000
                    self.run_until(c, 'patch_pass', 0x80001000, 30000)
                    expected = bytearray(b'\xa5' * (size + 16))
                    for y, runs in rows:
                        if not 4 <= y + pan < 7:
                            continue
                        for x, indices in runs:
                            for i, index in enumerate(indices):
                                at = ((y + pan - 4) * 24 + x + i) * 3
                                expected[at:at + 3] = bytes(
                                    min(255, (v * scale + 128) >> 8) for v in palette[index])
                    actual = bytes(c.read(scratch + i, 1) for i in range(size + 16))
                    self.assertEqual(actual, expected)

    def test_open_zoom_levels_are_uniform_and_safe_in_both_banks(self):
        import struct
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import fmv_subgen as gen
        import fmv_ink
        data = (ROOT / 'build/movie_subs_open_data.bin').read_bytes()
        aux = (ROOT / 'build/movie_subs_open_zoom.bin').read_bytes()

        def read(address, count):
            if gen.ZOOM_AUX_BASE <= address < gen.ZOOM_AUX_END:
                offset = address - gen.ZOOM_AUX_BASE
                self.assertLessEqual(offset + count, len(aux))
                return aux[offset:offset + count]
            offset = address - gen.DATA_BASE
            self.assertGreaterEqual(offset, 0)
            self.assertLessEqual(offset + count, len(data))
            return data[offset:offset + count]

        self.assertLessEqual(0x80128000 + 8 * fmv_ink.MAX_RECIPES * 4, gen.ZOOM_AUX_BASE)
        self.assertLessEqual(gen.ZOOM_AUX_BASE + len(aux), gen.ZOOM_AUX_END)
        zoom_entries = 0
        for number in range(gen.MOVIE_COUNT):
            entry, = struct.unpack_from('<I', data, 0x18 + 4 * number)
            while entry:
                record = read(entry, 32)
                first, last, lines, flags, y, height = struct.unpack_from('<HHBBBB', record)
                if first == 0xffff:
                    break
                if flags & gen.F_ZOOM:
                    zoom_entries += 1
                    patch, _, _, = struct.unpack_from('<III', record, 8)
                    count, = struct.unpack('<H', read(patch + 776, 2))
                    self.assertEqual(count, gen.OPEN_ZOOM_LEVELS)
                    x, = struct.unpack_from('<H', record, 22)
                    width, = struct.unpack_from('<H', record, 26)
                    palette = read(patch, 768)
                    stride = (((width + 3) & ~3) + 8) * height + 4
                    pointers = struct.unpack('<' + 'I' * count, read(patch + 780, 4 * count))
                    self.assertTrue(any(gen.ZOOM_AUX_BASE <= p < gen.ZOOM_AUX_END for p in pointers))
                    self.assertTrue(any(p >= gen.DATA_BASE for p in pointers))
                    for level, pointer in enumerate(pointers):
                        with self.subTest(level=level):
                            c = self.cpu()
                            c.load(gen.DATA_BASE, data)
                            c.load(gen.ZOOM_AUX_BASE, aux)
                            size = width * height * 3
                            c.load(gen.SCRATCH, b'\xa5' * (size + 16))
                            for name, value in dict(s_scale=128, s_cur_p=0, s_cur_l=level,
                                                    s_bandy0=y, s_bandrows=height,
                                                    s_stride=width * 3, s_xoff=-x * 3).items():
                                c.write(self.sym[name], value)
                            c.r[REG['a0']], c.r[REG['s0']] = patch, entry
                            c.r[REG['ra']] = 0x80001000
                            self.run_until(c, 'patch_pass', 0x80001000, 400000)
                            source = read(pointer, stride)
                            cursor = 0
                            expected = bytearray()
                            while source[cursor] != 255:
                                row, nruns = source[cursor:cursor + 2]
                                self.assertEqual(nruns, 1)
                                left, length = struct.unpack_from('<HH', source, cursor + 2)
                                self.assertEqual((left, length), (x, width))
                                cursor = (cursor + 6 + 3) & ~3
                                for index in source[cursor:cursor + length]:
                                    expected.extend((v * 128 + 128) >> 8 for v in palette[index * 3:index * 3 + 3])
                                cursor = (cursor + length + 3) & ~3
                            actual = bytes(c.read(gen.SCRATCH + i, 1) for i in range(size + 16))
                            self.assertEqual(actual, expected + b'\xa5' * 16)
                    timing = [256] * (last - first + 1)
                    measured = gen.load_zoom(f'MV{number:02X}')
                    levels, indices = gen.zoom_levels(measured, timing, first, last,
                                                      max_levels=gen.OPEN_ZOOM_LEVELS)
                    # Same scalar in both affine axes, anchored on the actual
                    # plate size rather than a frozen median at the final frame.
                    self.assertIn(1000.0, levels)
                    self.assertLessEqual(abs(levels[indices[-1]] - measured[last]), gen.ZOOM_STEP)
                entry += 32 + 8 * lines
        self.assertGreater(zoom_entries, 0)

    def test_alpha_changes_on_every_frame_including_small_steps(self):
        c = self.cpu()
        entry, table = 0x80020000, 0x80021000
        values = bytes((0, 1, 8, 16, 17, 24, 32, 48, 64, 128, 254, 255, 254, 248, 240, 0))
        c.write(entry, 0, 2)
        c.write(entry + 2, len(values) - 1, 2)
        c.write(entry + 4, 1, 1)
        c.write(entry + 16, table)
        c.load(table, values)
        c.write(self.sym['s_hold'], 1)
        c.r[REG['s0']] = entry
        c.r[REG['ra']] = 0x80001000
        for frame, value in enumerate(values):
            c.r[REG['s2']] = frame
            self.run_until(c, 'sig_fill', 0x80001000)
            self.assertEqual(c.read(self.sym['s_cur_a'], 1), value)

    def test_common_restores_callee_saved_registers(self):
        c = self.cpu()
        c.write(0x80162000, 0x34534d46)
        # No active list: exercise entry/exit without GPU stubs.
        c.write(self.sym['s_frame'], 0)
        c.write(self.sym['s_no'], 0)
        c.write(self.sym['s_tailfn'], 0x80001000)
        expected = {reg: 0x12340000 + i for i, reg in enumerate(
            ('s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7', 'ra'))}
        for reg, value in expected.items():
            c.r[REG[reg]] = value
        self.run_until(c, 'common', 0x80001000)
        for reg, value in expected.items():
            self.assertEqual(c.r[REG[reg]], value)
        self.assertEqual(c.r[REG['sp']], 0x801ff000)

    def test_idle_poll_only_draws_finished_frames_and_preserves_sdk_results(self):
        import struct
        for driver, sdk, done_address, normal_tail in (
                ('movie', 0x80089ED0, 0x800FF8F0, 0x8008A910),
                ('open', 0x80092850, 0x801146EC, 0x80093708)):
            for status in (0, 1):
                for done in (0, 1):
                    for rendered in (0, 1):
                        with self.subTest(driver=driver, status=status, done=done, rendered=rendered):
                            c = self.cpu()
                            # Leaf SDK stand-in writes its argument home slots,
                            # as a real C callee is entitled to do.
                            words = [0xAFA40000, 0xAFA50004, 0xAFA60008, 0xAFA7000C,
                                     0x24020000 | status, 0x3C031357, 0x34632468,
                                     0x03E00008, 0]
                            c.load(sdk, struct.pack('<' + 'I' * len(words), *words))
                            c.write(0x80162000, 0x34534d46)
                            c.write(done_address, done)
                            c.write(self.sym['s_true'], 145)
                            c.write(self.sym['s_disp'], 144)
                            c.write(self.sym['s_rendered'], rendered)
                            c.r[REG['a0']], c.r[REG['a1']] = 0x801fe100, 0x801fe104
                            c.r[REG['ra']] = 0x80001000
                            preserved = {i: 0x12340000 + i for i in [*range(16, 24), 28, 30]}
                            for reg, value in preserved.items():
                                c.r[reg] = value
                            calls = []

                            def intercept(cpu):
                                if cpu.pc == self.sym['entry_' + driver]:
                                    calls.append(cpu.pc)
                                return False

                            c.start(self.sym['poll_entry_' + driver])
                            c.run(0x80001000, 3000, intercept)
                            should_draw = status != 0 and done != 0 and rendered == 0
                            self.assertEqual(len(calls), int(should_draw))
                            self.assertEqual(c.r[REG['v0']], status)
                            self.assertEqual(c.r[REG['v1']], 0x13572468)
                            self.assertEqual(c.r[REG['sp']], 0x801ff000)
                            self.assertEqual(c.r[REG['ra']], 0x80001000)
                            self.assertEqual(c.read(done_address), done)
                            self.assertEqual(c.read(self.sym['s_early']), 0)
                            self.assertEqual(c.read(self.sym['s_rendered']), int(rendered or should_draw))
                            self.assertEqual(c.read(self.sym['s_disp']), 145)
                            self.assertEqual(c.read(0x801ff000 - 0x30), 0x801fe100)
                            self.assertEqual(c.read(0x801ff000 - 0x30 + 4), 0x801fe104)
                            for reg, value in preserved.items():
                                self.assertEqual(c.r[reg], value)
                            if should_draw:
                                # The original StrSync remains the sole owner of
                                # dec.done. Model it consuming done, then the next
                                # header being captured before the regular hook.
                                c.write(done_address, 0)
                                c.write(self.sym['s_true'], 149)  # dropped stream frames remain correctly indexed
                                c.r[REG['ra']] = 0x80001000
                                self.run_until(c, 'frame_entry' + ('_open' if driver == 'open' else ''), normal_tail)
                                self.assertEqual(c.read(self.sym['s_rendered']), 0)
                                self.assertEqual(c.read(self.sym['s_disp']), 149)
                                self.assertEqual(c.r[REG['a0']], 0 if driver == 'open' else 1)

    def test_black_band_clear_is_bounded(self):
        for width, rows in ((2, 1), (20, 1), (22, 1), (236, 20), (282, 79), (290, 108)):
            c = self.cpu()
            count = (width * rows * 3 + 15) & ~15
            scratch = 0x80140640
            c.load(scratch - 4, b'\xa5' * (count + 8))
            c.write(self.sym['s_stride'], width * 3)
            c.write(self.sym['s_bandrows'], rows)
            self.run_until(c, 'clear_band', self.sym['text'], 100000)
            actual = bytes(c.read(scratch - 4 + i, 1) for i in range(count + 8))
            self.assertEqual(actual, b'\xa5' * 4 + bytes(count) + b'\xa5' * 4)

    def test_text_ramp_matches_scalar_blend(self):
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import fmv_subgen as gen
        (_, height), advances, cells, _ = gen.render_atlas()
        text = ''.join(chr(i) for i in range(0x21, 0x7f))
        # A short repeated run also exercises overlapping glyph outlines.
        text = text[::17] * 2
        width = 320
        for additive in (False, True):
            for alpha in (0, 1, 16, 128, 254, 255):
                with self.subTest(additive=additive, alpha=alpha):
                    c = self.cpu()
                    c.load(gen.DATA_BASE, (ROOT / 'build/movie_subs_data.bin').read_bytes())
                    bg = bytes((i * 31 + 13) & 255 for i in range(width * height * 3))
                    c.load(gen.SCRATCH, bg)
                    for name, value in dict(s_bandy0=0, s_stride=width * 3,
                                            s_xoff=0, s_scale=256).items():
                        c.write(self.sym[name], value)
                    c.load(0x80020000, text.encode() + b'\0')
                    for reg, value in dict(a0=0x80020000, a1=8, a2=0,
                                           s4=int(additive), s6=alpha, ra=0x80001000).items():
                        c.r[REG[reg]] = value
                    self.run_until(c, 'draw_line', 0x80001000, 200000)
                    expected = bytearray(bg)
                    pen = 8
                    for ch in text:
                        gi = ord(ch) - gen.GLYPH_FIRST
                        for y, row in enumerate(cells[gi]):
                            for x, (gray, cov) in enumerate(row):
                                if not cov:
                                    continue
                                eff = cov * alpha >> 8
                                at = (y * width + pen + x) * 3
                                for channel in range(3):
                                    old = expected[at + channel]
                                    expected[at + channel] = (
                                        min(255, old + ((gray * eff + 128) >> 8)) if additive else
                                        gray if cov == 255 and alpha == 255 else
                                        old + ((gray * eff) >> 8) - ((old * eff) >> 8))
                        pen += advances[gi]
                    actual = bytes(c.read(gen.SCRATCH + i, 1) for i in range(len(bg)))
                    self.assertEqual(actual, expected)

    def test_compiled_ink_is_exact_for_fades_and_overlaps(self):
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import fmv_subgen as gen
        import fmv_ink
        (_, height), advances, cells, _ = gen.render_atlas()
        text = ''.join(chr(i) for i in range(0x21, 0x7f))[::17] * 2
        ink = fmv_ink.compile_line(text, 8, 0, cells, advances)
        width = 320
        for black, carry_free, overlap in ((False, False, False), (False, True, False),
                                          (True, False, False), (True, False, True)):
            for floor in (False, True):
                for alpha in (0, 1, 8, 16, 128, 254, 255):
                    with self.subTest(black=black, floor=floor, alpha=alpha,
                                      carry_free=carry_free, overlap=overlap):
                        c = self.cpu()
                        c.load(gen.DATA_BASE, (ROOT / 'build/movie_subs_data.bin').read_bytes())
                        bg = bytes(width * height * 3) if black and not overlap else bytes(
                            (i * 31 + 13) % (96 if carry_free else 256)
                            for i in range(width * height * 3))
                        c.load(gen.SCRATCH, bg + b'\xa5' * 4)
                        for name, value in dict(s_bandy0=0, s_stride=width * 3,
                                                s_xoff=0, s_scale=0 if black else 86).items():
                            c.write(self.sym[name], value)
                        c.write(self.sym['s_headroom'], 255 - max(bg))
                        c.load(0x80020000, ink)
                        entry, line = 0x80022000, 0x80022020
                        c.write(entry + 5, gen.F_INK | (gen.F_FLOOR if floor else 0), 1)
                        c.write(line + 7, int(overlap), 1)
                        for reg, value in dict(a0=0x80020000, s0=entry, s1=line,
                                               s6=alpha, ra=0x80001000).items():
                            c.r[REG[reg]] = value
                        self.run_until(c, 'draw_ink', 0x80001000, 300000)
                        expected = bytearray(bg)
                        for (y, x), terms in fmv_ink.line_pixels(text, 8, 0, cells, advances).items():
                            p = sum((gray * (cov * alpha >> 8) + (0 if floor else 128)) >> 8
                                    for gray, cov in terms)
                            for channel in range(3):
                                at = (y * width + x) * 3 + channel
                                expected[at] = min(255, expected[at] + p)
                        actual = bytes(c.read(gen.SCRATCH + i, 1) for i in range(len(bg) + 4))
                        self.assertEqual(actual, expected + b'\xa5' * 4)
                        self.assertEqual(c.r[REG['s1']], line)
                        first_steps = c.steps
                        c.load(gen.SCRATCH, bg + b'\xa5' * 4)
                        self.run_until(c, 'draw_ink', 0x80001000, 300000)
                        cached_steps = c.steps - first_steps
                        actual = bytes(c.read(gen.SCRATCH + i, 1) for i in range(len(bg) + 4))
                        self.assertEqual(actual, expected + b'\xa5' * 4)
                        self.assertLess(cached_steps, first_steps)


if __name__ == '__main__':
    unittest.main()
