"""Execute the optional save patch without a GPU, BIOS, cards or save states."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys
import struct
import re

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import opentext
import save_ui


class SavePatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='saves-', dir='/tmp/opencode')
        out = Path(cls.tmp.name)
        blob = ROOT / 'build/movie_subs_open.bin'
        blob_end = 0x80160000 + blob.stat().st_size if blob.exists() else 0x80170000
        save_ui.build()
        source = ['.psx', '.definelabel SLPS_FREE_START, 0x80055C10',
                  '.definelabel SLPS_FREE_END, 0x80056000',
                  '.definelabel BTLEVT_BUF_ADDR, 0x80057400',
                  '.definelabel BTLEVT_BUF_SIZE, 1024',
                  'OPEN_ADDR equ 0x80180000',
                  f'.definelabel SUBS_OBLOB_END, {blob_end}']
        cls.images = []
        for original, base, patch in [('SLPS_005.00', 0x8000F800, 'slps'),
                                      ('ADV.BIN', 0x800643C4, 'adv'),
                                      ('EXE/OPEN.EXE', 0x8007F800, 'open')]:
            dest = out / (patch + '.bin')
            cls.images.append((base, dest))
            source += [f'.open "{ROOT / "data/psx" / original}", "{dest}", {base}',
                       f'.include "qol/saves_{patch}.asm"', '.close']
        dest = out / 'open-data.bin'
        cls.images.append((0x80180000, dest))
        source += [f'.open "{ROOT / "data/psx/OPEN.BIN"}", "{dest}", 0x80180000',
                   '.include "../../build/qol_save_assets.asm"', '.close']
        # Armips omits include-guarded constant symbols from sym2. Ask the
        # assembler itself for the resolved runtime addresses, rather than
        # duplicating address arithmetic in the test.
        probes = ('qol_serial', 'qol_kinds', 'qol_valid', 'qol_list')
        source += [f'.create "{out / "probes.bin"}", 0', '.word ' + ', '.join(probes), '.close']
        asm = out / 'test.asm'
        asm.write_text('\n'.join(source))
        symbols = out / 'test.sym'
        result = subprocess.run([str(ROOT / 'external_tools/armips/armips'), str(asm),
                        '-sym2', str(symbols), '-erroronwarning'],
                       cwd=ROOT / 'src/asm', capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.symbols = {}
        for line in symbols.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2:
                try:
                    cls.symbols[parts[1]] = int(parts[0], 16)
                except ValueError:
                    pass
        cls.symbols.update(zip(probes, struct.unpack('<4I', (out / 'probes.bin').read_bytes())))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cpu(self, title=False):
        cpu = CPU()
        for base, path in (self.images[2:] if title else self.images[:2]):
            cpu.load(base, path.read_bytes())
        cpu.r[REG['sp']] = 0x801FF000
        cpu.r[REG['ra']] = 0x80001000
        if title:
            for address in (0x8008AA5C, 0x8008A834):
                cpu.load(address, struct.pack('<II', 0x03E00008, 0))
        return cpu

    def address(self, name):
        return self.symbols[name]

    def test_integrated_build_preserves_all_save_owned_code_and_state(self):
        symbols = ROOT / 'build/persona.sym'
        if not symbols.exists() or not any(parts[-1].upper() == 'QOL_SAVES'
                                           for parts in map(str.split, symbols.read_text().splitlines()) if parts):
            self.skipTest('requires a fully assembled QOL_SAVES build')
        opening = (ROOT / 'build/EXE/OPEN.EXE').read_bytes()
        self.assertEqual(struct.unpack_from('<I', opening, 0x1c)[0], len(opening) - 0x800)
        self.assertGreaterEqual(0x80080000 + len(opening) - 0x800,
                                self.address('qol_o_end'))
        ranges = [
            (0, 'build/SLPS_005.00', [(0x8001427C, 8), (0x80055C10, 0x3F0)]),
            (1, 'build/ADV.BIN', [(0x8009AB40, 4), (0x8009AB58, 8),
                                 (0x8009B658, 4), (0x8009B748, 4), (0x8009BDB4, 4),
                                 (0x8009BCE8, 8), (0x8009BD34, 8),
                                 (0x8009A720, 8), (0x8009A5D8, 8), (0x8009A860, 8),
                                 (0x8009B4FC, 8), (0x8009AB28, 8), (0x8009ACB4, 8),
                                 (0x8009A370, 4), (0x8009AB20, 4),
                                 (0x8009ACAC, 4), (0x8009ACC4, 4)]),
            (2, 'build/EXE/OPEN.EXE', [(self.address('qol_o_list'),
                                      self.address('qol_o_end') - self.address('qol_o_list')),
                                     (0x80084140, 8), (0x800862D8, 4),
                                     (0x800863F4, 4)]),
            (3, 'build/OPEN.BIN', [(self.address('qol_save_assets_start'),
                                  self.address('qol_save_assets_end') - self.address('qol_save_assets_start'))]),
        ]
        declarations = (ROOT / 'src/asm/qol/saves.inc').read_text()
        retired = {name: int(value, 16) for name, value in re.findall(
            r'\.definelabel\s+(QOL_ADV_RETIRED_\w+),\s*(0x[0-9A-Fa-f]+)', declarations)}
        self.assertEqual(len(retired), 12)
        for name, start in retired.items():
            if name.endswith('_START'):
                ranges[1][2].append((start, retired[name[:-6] + '_END'] - start))
        for index, path, spans in ranges:
            base, isolated_path = self.images[index]
            expected, actual = isolated_path.read_bytes(), (ROOT / path).read_bytes()
            for start, size in spans:
                offset = start - base
                with self.subTest(path=path, start=hex(start)):
                    self.assertEqual(actual[offset:offset + size], expected[offset:offset + size],
                                     'another build step overwrote save-owned code/state')

    def test_title_message_scratch_clears_the_panel_rows(self):
        # OpenMessageOpen uploads each message cell to y = 0x100 + i*16,
        # the top rows of the QoL panel, and samples it at v = i*16. The
        # save patch moves both to y=0x1c0 (448), the first free row.
        base, path = self.images[2]
        opening = path.read_bytes()
        retail = (ROOT / 'data/psx/EXE/OPEN.EXE').read_bytes()
        word = lambda ram: struct.unpack_from('<I', opening, ram - base)[0]
        self.assertEqual(struct.unpack_from('<I', retail, 0x6AD8)[0], 0x24620100)
        self.assertEqual(struct.unpack_from('<I', retail, 0x6BF4)[0], 0x3064FFFF)
        self.assertEqual(word(0x800862D8), 0x246201C0)  # addiu v0,v1,0x1C0
        self.assertEqual(word(0x800863F4), 0x246400C0)  # addiu a0,v1,0xC0
        # The tallest message ("Loading data" and the erase/error prompts
        # are three rows) must still end inside the 512-row texture page.
        rows = max(rows for _ram, _cols, rows in opentext.LAYOUT)
        self.assertLessEqual(0x1C0 + rows * 16, 512)

    def test_save_and_delete_use_card_local_slot_at_retail_call_sites(self):
        for row in range(14):
            for start, target in [(0x8009B644, 0x800144F4),
                                  (0x8009B734, 0x80013E2C)]:
                with self.subTest(row=row, start=hex(start)):
                    cpu = self.cpu()
                    menu = 0x801D0000
                    cpu.write(0x800BC43C, menu)
                    cpu.write(menu + 0x2C0, row)
                    cpu.write(menu + 0x2D0, row // 7)
                    cpu.write(menu + 0x20, 0xDEADBEEF)
                    cpu.r[REG['s0']] = row % 2
                    cpu.start(start)
                    cpu.run(target)
                    self.assertEqual(cpu.r[4:7], [row // 7, row % 7, row % 2])

    def test_scan_entry_is_the_retail_entry_and_preserves_registers(self):
        cpu = self.cpu()
        saved = {REG[name]: 0x12340000 + i for i, name in
                 enumerate('s0 s1 s2 s3 s4 s5 s6 s7 fp'.split())}
        for reg, value in saved.items():
            cpu.r[reg] = value
        calls = []

        def intercept(c):
            if c.pc == 0x80025C98:
                c.start(c.r[31])
                return True
            if c.pc == 0x800139A0:
                card, kind, dest = c.r[4:7]
                calls.append((card, kind, dest))
                for slot in range(7):
                    c.write(dest + slot * 26 + 8, 5, 1)
                    c.write(dest + slot * 26 + 24, card * 20 + slot + 1, 2)
                c.r[2] = 0x7F if kind == 0 else 0
                c.start(c.r[31])
                return True
            return False

        cpu.start(0x8009BB7C)
        cpu.run(0x80001000, intercept=intercept)
        self.assertEqual([(c, k) for c, k, _ in calls], [(0, 0), (0, 1), (1, 0), (1, 1)])
        self.assertEqual(len({d for _, _, d in calls}), 4)
        self.assertEqual(cpu.read(self.address('qol_serial')), 27)
        self.assertEqual(cpu.r[29], 0x801FF000)
        for reg, value in saved.items():
            self.assertEqual(cpu.r[reg], value)

    def test_first_frame_selects_the_available_card_and_positions_the_cursor(self):
        for first_state, column in [(0, 0), (2, 1)]:
            cpu = self.cpu()
            menu = 0x801D0000
            cpu.write(0x800BC43C, menu)
            cpu.write(0x800BD0F8, first_state, 2)

            def initialize(c):
                if c.pc != 0x80067DD4:
                    return False
                for offset, value in zip((0, 4, 8), c.r[5:8]):
                    c.write(c.r[4] + offset, value)
                c.start(c.r[31])
                return True

            cpu.start(self.address('qol_skip_port'))
            cpu.run(0x8009ABF4, intercept=initialize)
            self.assertEqual(cpu.read(menu + 0x2C0), column * 7)
            self.assertEqual(cpu.read(menu + 0x2D0), column)
            cpu.r[31] = 0x80001000
            cpu.start(self.address('qol_cursor_pos'))
            cpu.run(0x80065FDC)
            self.assertEqual(cpu.r[4:8], [4, 0x42, 8 + column * 160, 52])

    def test_draw_is_bounded_and_restores_the_entire_call_frame(self):
        cpu = self.cpu()
        for row in range(14):
            cpu.write(self.address('qol_kinds') + row * 2, 0, 2)
            cpu.write(self.address('qol_valid') + row, 1, 1)
            summary = self.address('qol_list') + row * 26
            cpu.load(summary, bytes([0xB6] * 5 + [0xFF] * 3 + [37, 12, 3, 4]))
        saved = {i: 0x12340000 + i for i in range(16, 24)}
        saved[30] = 0x12340030
        for reg, value in saved.items():
            cpu.r[reg] = value

        def intercept(c):
            if c.pc == 0x80067CEC:
                dst, value, width, height = c.r[4:8]
                stride = c.read(c.r[29] + 16)
                for y in range(height):
                    for x in range(width):
                        c.write(dst + (y * stride + x) * 2, value, 2)
            elif c.pc != 0x8007AF1C:
                return False
            c.start(c.r[31])
            return True

        cpu.start(0x8009BDD0)
        cpu.run(0x80001000, intercept=intercept)
        self.assertEqual(cpu.r[29], 0x801FF000)
        for reg, value in saved.items():
            self.assertEqual(cpu.r[reg], value)
        for row in range(14):
            line = 0x800EF580 + (row % 7) * 160 + (row // 7) * 40 + 80
            self.assertEqual([cpu.read(line + i * 2, 2) for i in range(2)], [0x383, 0x384])
            self.assertEqual([cpu.read(line + i * 2, 2) for i in range(6, 10)], list(range(0x364, 0x368)))
            self.assertEqual([cpu.read(line + i * 2, 2) for i in range(11, 16)],
                             [0xC1, 0xC2, 0xCB, 0xC0, 0xC3])

    def title_cpu(self):
        cpu = self.cpu(title=True)
        frame = 0x801D0000
        cpu.r[30] = frame
        cpu.r[28] = 0x801D1000
        cpu.write(self.address('qol_o_frame'), frame)
        for row in range(14):
            cpu.write(self.address('qol_o_kind') + row, 1, 1)
            cpu.load(self.address('qol_o_list') + row * 26,
                     bytes([0xB6] * 5 + [0xFF] * 3 + [37, 12, 3, 4]))
        cpu.load(self.address('qol_o_card'), b'\1\1')
        return cpu

    def sprite(self, row, cell):
        return 0x80111484 + (16 + row * 17 + cell) * 36

    def test_title_layout_and_atlas_labels_match_and_do_not_touch_messages(self):
        cpu = self.title_cpu()
        message_start = 0x80111484 + 262 * 36
        cpu.load(message_start, b'\xA5' * (76 * 36))
        saved = cpu.r[16:24] + [cpu.r[30], cpu.r[29]]
        cpu.start(self.address('qol_o_screen'))
        cpu.run(0x80001000, limit=500000)
        self.assertEqual(cpu.r[16:24] + [cpu.r[30], cpu.r[29]], saved)
        self.assertEqual(bytes(cpu.mem[cpu.offset(message_start):cpu.offset(message_start) + 76 * 36]),
                         b'\xA5' * (76 * 36))
        for row in range(14):
            for cell, offset, width, u, v in [(8, 0, 16, 8, 120), (11, 48, 32, 16, 108)]:
                p = self.sprite(row, cell)
                self.assertEqual([cpu.read(p + k, 2) for k in (4, 6, 8, 10)],
                                 [12 + (row // 7) * 160 + offset, 64 + (row % 7) * 24, width, 12])
                self.assertEqual([cpu.read(p + k, 1) for k in (14, 15)], [u, v])
            for cell, u in enumerate([56, 64, 136, 48, 72], 12):
                p = self.sprite(row, cell)
                self.assertEqual([cpu.read(p + k, 1) for k in (14, 15)], [u, 72])

    def test_title_newest_selection_ignores_bad_or_failed_scans(self):
        cpu = self.title_cpu()
        calls = []

        def intercept(c):
            if c.pc == self.address('qol_o_screen'):
                c.start(c.r[31])
                return True
            if c.pc in (0x80093708, 0x80087198):
                c.r[2] = 0
                c.start(c.r[31])
                return True
            if c.pc == 0x80087574:
                card, kind, dest = c.r[4:7]
                calls.append((card, kind))
                for slot in range(7):
                    c.write(dest + slot * 26 + 24, 10 * card + slot, 2)
                c.r[2] = 0x407F if card else 0x7F  # card 2's last row is corrupt
                c.start(c.r[31])
                return True
            return False

        cpu.r[4] = 1
        cpu.start(self.address('qol_o_build'))
        cpu.run(0x80001000, intercept=intercept)
        self.assertEqual(calls, [(0, 1), (1, 1)])
        self.assertEqual(cpu.read(0x801D001C), 1)
        self.assertEqual(cpu.read(0x801D0024), 5)
        self.assertEqual([cpu.read(0x801D0000 + x) for x in (0x38, 0x3C)], [0x81, 0x81])

    def test_corrupt_summaries_stay_occupied_but_never_supply_display_or_serial(self):
        cpu = self.cpu()

        def intercept(c):
            if c.pc == 0x80025C98:
                c.start(c.r[31])
                return True
            if c.pc == 0x800139A0:
                card, kind, dest = c.r[4:7]
                c.write(dest + 24, 0xFFFF, 2)
                c.r[2] = (0x101 if kind == 0 else 0) if card == 0 else 0xFFFFFFFF
                c.start(c.r[31])
                return True
            return False

        cpu.start(0x8009BB7C)
        cpu.run(0x80001000, intercept=intercept)
        self.assertEqual(cpu.read(self.address('qol_kinds'), 2), 0)
        self.assertEqual(cpu.read(self.address('qol_valid'), 1), 0)
        self.assertEqual(cpu.read(self.address('qol_serial')), 0)
        for row in range(1, 14):
            self.assertEqual(cpu.read(self.address('qol_kinds') + row * 2, 2), 255)

    def test_panel_is_one_bottom_aligned_surface_and_badge_is_preserved(self):
        cpu = self.title_cpu()
        cpu.write(0x8011E804 + 10 * 4, 0x80)
        cpu.write(0x8011E804 + 11 * 4, 0x80)
        cpu.start(self.address('qol_o_screen'))
        cpu.run(0x80001000, limit=500000)
        for col in range(2):
            p = 0x80111484 + (12 + col) * 36
            self.assertEqual([cpu.read(p + k, 2) for k in (4, 6, 8, 10, 12, 16, 18)],
                             [col * 160, 40, 160, 192, 0x9D + col, 288, 480])
            self.assertEqual(cpu.read(p + 14, 1), col * 32)
        for index in (10, 11):
            self.assertEqual(cpu.read(0x8011E804 + index * 4), 0x80)
        self.assertLess(16 + 14 * 17, 262)

    def test_zero_serial_legacy_save_on_second_card_is_selected(self):
        cpu = self.title_cpu()

        def intercept(c):
            if c.pc == self.address('qol_o_screen'):
                c.start(c.r[31])
                return True
            if c.pc in (0x80093708, 0x80087198):
                c.r[2] = 0
                c.start(c.r[31])
                return True
            if c.pc == 0x80087574:
                c.r[2] = 1 << 3 if c.r[4] else 0xFFFFFFFF
                c.write(c.r[6] + 3 * 26 + 24, 0, 2)
                c.start(c.r[31])
                return True
            return False

        cpu.start(self.address('qol_o_build'))
        cpu.run(0x80001000, intercept=intercept)
        self.assertEqual([cpu.read(0x801D0000 + x) for x in (0x1C, 0x24)], [1, 3])

    def test_serial_stamp_preserves_registers_and_saturates_before_checksum(self):
        for serial in (0, 42, 65533, 65534):
            cpu = self.cpu()
            cpu.load(0x80055C10, bytes([0xA5]) * 0x3F0)  # live CD-system writes
            cpu.r[30] = 0x801D0000
            cpu.r[8:10] = [0xAABBCCDD, 0x12345678]
            cpu.write(cpu.r[30] + 0x12, 1, 1)
            cpu.write(self.address('qol_serial'), serial)
            cpu.start(0x8001427C)
            cpu.run(0x80014284)
            self.assertEqual(cpu.r[8:10], [0xAABBCCDD, 0x12345678])
            self.assertEqual(cpu.r[29], 0x801FF000)
            self.assertEqual(cpu.r[2:4], [1, 2])
            self.assertEqual(cpu.read(0x8005E398, 2), min(serial + 1, 65534))

    def test_empty_title_rows_keep_labels_colons_and_dash_placeholders(self):
        cpu = self.title_cpu()
        cpu.load(self.address('qol_o_kind'), bytes(14))
        cpu.start(self.address('qol_o_screen'))
        cpu.run(0x80001000, limit=500000)
        for row in range(14):
            for cell in range(17):
                p = self.sprite(row, cell)
                expected = (8, 120) if cell == 8 else (16, 108) if cell == 11 else (136, 72) if cell == 14 else (144, 72)
                self.assertEqual(tuple(cpu.read(p + k, 1) for k in (14, 15)), expected)

    def test_title_panel_map_matches_the_retail_adv_frame_routines(self):
        cpu = self.cpu()
        cpu.r[4:8] = [0x800EE180, 40, 16, 40]
        cpu.start(0x8007AC30)
        cpu.run(0x80001000, limit=1000000)
        for col in (1, 21):
            for row in range(7):
                cpu.r[4:8] = [0x800EE180 + ((1 + row * 2) * 40 + col) * 2, 18, 2, 40]
                cpu.r[31] = 0x80001000
                cpu.start(0x8007AF1C)
                cpu.run(0x80001000)
        self.assertEqual([cpu.read(0x800EE180 + i * 2, 2) for i in range(640)], save_ui.panel_map())
        pixels, palette = save_ui.panel_pixels()
        self.assertEqual(len(pixels), 320 * 192)
        self.assertEqual(len(palette), 64)
        # A shared outer border, not a border around each card column.
        cells = save_ui.panel_map()
        self.assertEqual(cells[40 + 19:40 + 21], [7, 7])

    def test_label_uvs_are_proved_by_retail_cells_init_not_assumed(self):
        cpu = self.cpu()
        cpu.start(0x8008E224)
        cpu.run(0x80001000, limit=200000)
        for cell, u, v in [(0x383, 8, 120), (0x364, 16, 108)]:
            address = 0x800E3E4C + cell * 8
            self.assertEqual([cpu.read(address + i, 1) for i in (0, 1)], [u, v])

    def test_save_state_uses_exclusive_battle_scratch_and_cd_ram_cannot_corrupt_it(self):
        for name in ('qol_serial', 'qol_kinds', 'qol_valid', 'qol_list'):
            self.assertGreaterEqual(self.address(name), 0x80057400)
            self.assertLess(self.address(name), 0x80057800)
        self.assertLessEqual(self.address('qol_list') + 2 * 364, 0x80057800)
        self.assertGreaterEqual(self.address('qol_stamp'), 0x800643C4)
        self.assertLess(self.address('qol_stamp'), 0x800BC000)
        cpu = self.cpu()
        cpu.load(self.address('qol_list'), b'R' * 26)
        cpu.load(0x80055C10, bytes([0xA5]) * 0x3F0)
        self.assertEqual(bytes(cpu.mem[cpu.offset(self.address('qol_list')):cpu.offset(self.address('qol_list')) + 26]), b'R' * 26)

    def test_slot_label_shadow_palette_is_opaque_black(self):
        subprocess.run([sys.executable, str(ROOT / 'src/injection_tools/opentext.py')],
                       cwd=ROOT, check=True, capture_output=True)
        clut = (ROOT / 'build/gfx/open_474C0_clut.bin').read_bytes()
        self.assertEqual(int.from_bytes(clut[30:32], 'little'), 0x8000)
        self.assertEqual(clut[:2], b'\0\0')  # transparent background stays transparent

    def test_uploads_reconstruct_both_panel_halves_without_touching_resident_font(self):
        cpu = self.title_cpu()
        font = b'\xA5' * 0x10000
        cpu.load(0x801E0000, font)
        panels = [bytearray(160 * 192), bytearray(160 * 192)]
        uploads = []

        def intercept(c):
            if c.pc == 0x8008A834:
                c.start(c.r[31])
                return True
            if c.pc != 0x8008AA5C:
                return False
            x, y, w, h = [c.read(c.r[4] + i * 2, 2) for i in range(4)]
            uploads.append((x, y, w, h))
            if h == 12:
                self.assertIn(x, (832, 912))
                self.assertEqual(w, 80)
                self.assertTrue(256 <= y < 448)
                self.assertLess(c.r[5] + w * h * 2, 0x801E0000)
                raw = bytes(c.mem[c.offset(c.r[5]):c.offset(c.r[5]) + w * h * 2])
                panels[(x - 832) // 80][(y - 256) * 160:(y - 256 + h) * 160] = raw
            else:
                self.assertIn((x, y, w, h), ((288, 480, 32, 1), (320, 480, 16, 1)))
            c.start(c.r[31])
            return True

        cpu.start(self.address('qol_o_upload'))
        cpu.run(0x80001000, intercept=intercept)
        self.assertEqual(len(uploads), 34)
        pixels, _ = save_ui.panel_pixels()
        for col in range(2):
            expected = bytes(pixels[y * 320 + col * 160 + x] for y in range(192) for x in range(160))
            self.assertEqual(panels[col], expected)
        self.assertEqual(bytes(cpu.mem[cpu.offset(0x801E0000):cpu.offset(0x801E0000) + 0x10000]), font)

    def test_adv_viewports_end_at_panel_and_retail_cursor_is_cropped_to_row(self):
        cpu = self.cpu()
        cpu.start(self.address('qol_layers'))
        cpu.run(0x8009BC94)
        bg = 0x800B8E68
        self.assertEqual([cpu.read(bg + k, 2) for k in (4, 6, 8, 10)], [0, 40, 320, 192])
        self.assertEqual([cpu.read(bg + 36 + k, 2) for k in (4, 6, 8, 10)], [12, 52, 308, 168])
        cursor = self.address('qol_cursor_def')
        right = bottom = 0
        while cpu.read(cursor) != 0xFFFFFFFF:
            block = cpu.read(cursor)
            dx, dy = [cpu.read(cursor + k, 2) for k in (4, 6)]
            cols, rows = [cpu.read(block + k, 1) for k in (0, 1)]
            w, h = [cpu.read(block + k, 2) for k in (4, 6)]
            right, bottom = max(right, dx + cols * w), max(bottom, dy + rows * h)
            cursor += 12
        self.assertEqual((right, bottom), (144, 24))

    def test_title_entry_actually_initializes_the_load_badge_before_preserving_it(self):
        cpu = self.title_cpu()
        cpu.write(cpu.r[30] + 0x48, 0)

        def intercept(c):
            if c.pc in (0x8008AA5C, 0x8008A834, 0x80093708, 0x80087198):
                c.r[2] = 2 if c.pc == 0x80087198 else 0  # no cards required
                c.start(c.r[31])
                return True
            return False

        cpu.start(0x8008306C)
        cpu.run(0x800830B8, limit=500000, intercept=intercept)
        for index, x, y in ((10, 8, 16), (11, 16, 8)):
            p = 0x80111484 + index * 36
            self.assertEqual([cpu.read(p + k, 2) for k in (4, 6)], [x, y])
            self.assertEqual(cpu.read(0x8011E804 + index * 4), 0x80)

    def test_choice_arguments_are_bytes_not_visible_vwf_spaces(self):
        import etext
        for blank in (' ', '　', '<00>'):
            self.assertEqual(etext.encode('<FF0E>' + blank + '<FF01>'), b'\xff\x0e\x00\xff\x01')
        for command, args in ((5, b'\x00\x10'), (6, b'\x00'), (14, b'\x00'), (15, b'\x01')):
            raw = bytes((255, command)) + args + b'\xff\x01'
            self.assertEqual(etext.encode(etext.decode(raw)), raw)

    def test_choice_handler_reproduces_crash_signature_and_fixed_argument_is_bounded(self):
        import etext
        # The shipped translation owns the resident choice table; use its
        # actual bytes. Each entry's width byte (at +6) is what the handler
        # copies to message+0x34.
        slps = (ROOT / 'build/SLPS_005.00').read_bytes()
        table = 0x8004D760
        for argument in (0x88, etext.encode('<FF0E> <FF01>')[2]):
            # 0x88 lands outside the 32-entry table. The handler still
            # copies the width byte it reaches - that out-of-range read IS
            # the live crash signature - so the expected byte comes from the
            # shipped image, never from the layout of an unrelated file.
            count = slps[table + 6 - 0x8000F800 + argument * 8]
            cpu = self.cpu()
            cpu.load(table, slps[table - 0x8000F800:0x8004DC00 - 0x8000F800])
            message, argument_at = 0x801D0000, 0x801D1000
            cpu.r[17] = message
            cpu.r[18] = argument_at
            cpu.write(argument_at, argument, 1)
            start, size = 0x800B1B34, 0x440
            before = bytes(cpu.mem[cpu.offset(start):cpu.offset(start) + size])
            cpu.start(0x8006729C)  # real retail FF0E handler, not a mocked putter
            cpu.run(0x80066C50, limit=50000)
            self.assertEqual(cpu.read(message + 0x34, 1), count)
            after = bytes(cpu.mem[cpu.offset(start):cpu.offset(start) + size])
            if argument == 0x88:
                # Exact first bad writes captured through live GDB.
                self.assertEqual(after[:2], b'\x00\xb4')
                self.assertEqual(after[0x180:0x182], b'\x00\xb4')
            else:
                self.assertEqual(after, before)

    def test_warning_question_and_options_have_only_one_wait_and_fresh_page(self):
        import sysmsg
        import etext
        text = next(row['en'] for row in __import__('toolbelt').read_manual('ADV')
                    if '<FF0E>' in row['en'] and '<FF02><FF03>' in row['en'])
        normalized = sysmsg.choice_pages(text)
        self.assertEqual(normalized.count('<FF02>'), 1)
        self.assertIn('<FF02><FF04>', normalized)
        self.assertTrue(etext.encode(normalized).endswith(b'\xff\x03\xff\x0e\x00\xff\x01'))

    def test_confirmation_backing_cursor_and_labels_sort_above_all_rows(self):
        cpu = self.title_cpu()
        cpu.start(self.address('qol_o_screen'))
        cpu.run(0x80001000, limit=500000)
        # Execute the retail confirmation initializer in the original image.
        original = (ROOT / 'data/psx/EXE/OPEN.EXE').read_bytes()
        m = __import__('capstone')
        dis = m.Cs(m.CS_ARCH_MIPS, m.CS_MODE_MIPS32 + m.CS_MODE_LITTLE_ENDIAN)
        # Find the initializer from its unique first sprite argument.
        instructions = list(dis.disasm(original[0x80084CE4 - 0x8007F800:0x80085C30 - 0x8007F800], 0x80084CE4))
        first = next(i.address for i in instructions if i.mnemonic == 'ori' and i.op_str == '$a0, $zero, 0x106')
        entry = first
        while cpu.read(entry) >> 16 != 0x27BD:
            entry -= 4
        cpu.r[31] = 0x80001000
        cpu.start(entry)
        cpu.run(0x80001000, limit=50000)
        depths = [cpu.read(0x8011E804 + index * 4) & 0x7F for index in range(262, 269)]
        self.assertEqual(depths, [1, 0, 0, 0, 2, 2, 2])
        for index in range(16, 254):
            self.assertGreater(cpu.read(0x8011E804 + index * 4) & 0x7F, max(depths))

    def test_agastya_badge_uses_the_same_sphere_and_label_origin_as_load(self):
        cpu = self.cpu()
        cpu.r[19] = 16  # SaveScreenOpen's shared y constant
        cpu.start(0x8009A6B8)
        cpu.run(0x8009A6F4)
        sphere = 0x800DC10C + 60 * 0x44
        label = 0x800DC10C + 45 * 0x44
        self.assertEqual([cpu.read(sphere + k, 2) - 16 for k in (0x14, 0x16)], [16, 8])
        self.assertEqual([cpu.read(label + k, 2) for k in (0x14, 0x16)], [8, 16])

    def test_panel_keeps_both_retail_palettes_and_transparency(self):
        import tim
        data = (ROOT / 'data/psx/ADV/ADVCMD0.BIN').read_bytes()
        image = tim.parse(data, save_ui.FRAME_TIM)
        source = bytes(n for byte in data[image['at']:image['end']] for n in (byte & 15, byte >> 4))
        colors = struct.unpack_from('<48H', data, image['clut']['at'])
        pixels, packed = save_ui.panel_pixels()
        palette = struct.unpack('<32H', packed)
        self.assertEqual(palette[0], 0)  # GPU transparent index remains transparent
        for index, cell in enumerate(save_ui.panel_map()):
            for y in range(12):
                for x in range(8):
                    u, v = ((cell - 1) % 31) * 8 + x, ((cell - 1) // 31) * 12 + y
                    want = colors[(16 if cell >= 14 else 0) + source[v * 256 + u]]
                    at = ((index // 40) * 12 + y) * 320 + (index % 40) * 8 + x
                    self.assertEqual(palette[pixels[at]], want)

    def test_real_gpu_packets_use_8bpp_for_both_panel_halves(self):
        cpu = self.title_cpu()
        cpu.start(self.address('qol_o_screen'))
        cpu.run(0x80001000, limit=500000)
        packet, ot, tags = 0x801C0000, 0x801C1000, 0x801C1100
        cpu.write(ot + 4, tags)
        cpu.write(ot + 8, 0)
        for col in range(2):
            sprite = 0x80111484 + (12 + col) * 36
            cpu.write(0x801113DC, packet)
            cpu.r[4:7] = [sprite, ot, 6]
            cpu.r[31] = 0x80001000
            cpu.start(0x8008E164)  # actual GsSortFastSprite, not a mocked initializer
            cpu.run(0x80001000)
            mode = cpu.read(packet + 4)
            self.assertEqual(mode & 0x180, 0x80, 'tpage alone does not set the GPU texture depth')
            self.assertEqual(mode & 0x1F, 0x1D + col)
            self.assertEqual(cpu.read(packet + 16) & 0xFF, col * 32)

    def test_empty_title_dashes_use_grey_palette_not_brightness_reset_each_frame(self):
        cpu = self.title_cpu()
        cpu.load(self.address('qol_o_kind'), bytes(14))
        cpu.start(self.address('qol_o_screen'))
        cpu.run(0x80001000, limit=500000)
        for row in range(14):
            for cell in range(17):
                self.assertEqual(cpu.read(self.sprite(row, cell) + 16, 2),
                                 256 if cell in (8, 11, 14) else 320)
        import tim
        data = (ROOT / 'data/psx/ADV/ADVCMD0.BIN').read_bytes()
        at = tim.parse(data, 0x20)['clut']['at']
        grey = (ROOT / 'build/qol_save_grey_clut.bin').read_bytes()
        self.assertEqual(grey[2:4], data[at + 34:at + 36])

    def test_serial_round_trip_selects_each_new_save_not_erased_card_two_row(self):
        def summary(serial):
            data = bytearray(26)
            data[:8] = bytes([0xB6] * 8)
            data[8:12] = bytes([5, 1, 2, 3])
            data[24:26] = serial.to_bytes(2, 'little')
            return bytes(data)

        cards = {(0, 0, 6): summary(25), (0, 1, 6): summary(40),
                 (1, 0, 0): b'\xff' * 26,  # checksum-valid erased header, not a save
                 (1, 0, 1): summary(0xFFFF)}  # legacy unset serial, still a valid save

        def scan(c):
            if c.pc in (0x80025C98, 0x80093708, 0x80087198):
                c.r[2] = 0
            elif c.pc in (0x800139A0, 0x80087574):
                card, kind, dest = c.r[4:7]
                mask = 0
                for (port, typ, slot), data in cards.items():
                    if (port, typ) == (card, kind):
                        mask |= 1 << slot
                        c.load(dest + slot * 26, data)
                c.r[2] = mask
            elif c.pc == self.address('qol_o_screen'):
                pass
            else:
                return False
            c.start(c.r[31])
            return True

        for row in range(14):
            cpu = self.cpu()
            cpu.start(0x8009BB7C)
            cpu.run(0x80001000, intercept=scan)
            self.assertEqual(cpu.read(self.address('qol_serial')), 40 + row)
            if row == 0:
                self.assertEqual(cpu.read(self.address('qol_valid') + 7, 1), 0)
                self.assertEqual(cpu.read(self.address('qol_valid') + 8, 1), 1)
            cpu.r[30] = 0x801D0000
            cpu.write(cpu.r[30] + 0x12, 0, 1)
            cpu.start(0x8001427C)
            cpu.run(0x80014284)
            number = cpu.read(0x8005E398, 2)
            self.assertEqual(number, 41 + row)
            cards[(row // 7, 0, row % 7)] = summary(number)

            title = self.title_cpu()
            title.r[4] = 0
            title.start(self.address('qol_o_build'))
            title.run(0x80001000, intercept=scan)
            self.assertEqual([title.read(0x801D0000 + x) for x in (0x1C, 0x24)],
                             [row // 7, row % 7], f'save {number} must select combined row {row}')
            if row == 0:
                self.assertEqual(title.read(self.address('qol_o_kind') + 7, 1), 0)

    def test_save_patch_is_opt_in_and_exclusions_win(self):
        import build
        self.assertEqual(build.qol_patches([]), [])
        self.assertEqual(build.qol_patches(['--qol']), ['saves'])
        self.assertNotIn('credits', build.QOL_PATCHES)   # base game, not a QoL patch
        self.assertEqual(build.qol_patches(['--qol=60fps']), ['60fps'])
        self.assertEqual(build.qol_patches(['--qol=saves,60fps']), ['saves', '60fps'])
        self.assertEqual(build.qol_patches(['--no-qol=saves']), [])
        self.assertEqual(build.qol_patches(['--qol=all', '--no-qol=saves']),
                         [name for name in build.QOL_PATCHES if name != 'saves'])
        self.assertEqual(build.qol_patches(['--no-qol', 'saves', '--qol', '60fps']), ['60fps'])
        self.assertEqual(build.qol_patches(['--qol=saves,saves']), ['saves'])
        for args in (['--no-qol'], ['--no-qol=typo'], ['--qol=typo'],
                     ['--qol=credits']):
            with self.assertRaises(SystemExit):
                build.qol_patches(args)

    def test_save_disabled_build_leaves_retail_save_hooks_intact(self):
        symbols = ROOT / 'build/persona.sym'
        if not symbols.exists():
            self.skipTest('requires an assembled build')
        if re.search(r'^\S+\s+QOL_SAVES\s*$', symbols.read_text(), re.MULTILINE | re.IGNORECASE):
            self.skipTest('checks the default retail-save variant')
        for name, base, hook in [('SLPS_005.00', 0x8000F800, 0x8001427C),
                                 ('ADV.BIN', 0x800643C4, 0x8009B0B4),
                                 ('EXE/OPEN.EXE', 0x8007F800, 0x8008306C)]:
            original = (ROOT / 'data/psx' / name).read_bytes()
            built = (ROOT / 'build' / name).read_bytes()
            offset = hook - base
            self.assertEqual(built[offset:offset + 8], original[offset:offset + 8], name)

    def test_agastya_opens_the_list_in_one_tick_without_top_menu_or_accept(self):
        for states, format_answer, error in (
                ((0, 0, 0), None, None), ((2, 0, 0), None, None),
                ((2, 2), None, 0), ((0, 0, 1, 1), None, 3),
                ((0, 0, 2), None, 0), ((4, 2, 4), 0, None),
                ((4, 2, 4, 0), 1, None)):
            cpu = self.cpu()
            menu = 0x801D0000
            cpu.write(0x800BC43C, menu)
            cpu.write(menu + 0x2E0, 1)  # a remembered GAME END choice must be irrelevant
            cpu.write(0x800BCB3C, 0, 2)
            calls, slots, reads = [], [], iter(states)

            def intercept(c):
                if c.pc == 0x8008F104:
                    self.fail('direct save entry must not ask for Accept')
                if c.pc == 0x80065EB0:
                    slots.append(c.r[5])
                elif c.pc in (0x80067CEC, 0x80066254, 0x800ABB94, 0x80025C98, 0x8008B8A0):
                    pass
                elif c.pc == 0x800135C4:
                    calls.append(('card', c.r[4]))
                    c.r[2] = next(reads)
                elif c.pc == 0x800139A0:
                    calls.append(('scan', c.r[4], c.r[5]))
                    c.r[2] = 0
                elif c.pc == 0x8009BC78:
                    calls.append(('list',))
                elif c.pc == 0x8009C1A8:
                    calls.append(('error', c.r[4]))
                elif c.pc == 0x8009B9D4:
                    calls.append(('format',))
                    self.assertIsNotNone(format_answer)
                    c.r[2] = format_answer
                elif c.pc == 0x8008BCAC:
                    calls.append(('fade',))
                else:
                    return False
                c.start(c.r[31])
                return True

            cpu.start(0x8009A580)
            cpu.run(0x80001000, limit=100000, intercept=intercept)
            self.assertEqual(slots, [60, 45], 'only sphere and AGASTYA badge are initialized')
            if error is not None or format_answer == 0:
                self.assertEqual(cpu.read(0x800BCB3C, 2), 0xFF)
                if error is not None:
                    self.assertIn(('error', error), calls)
                    self.assertLess(calls.index(('fade',)), calls.index(('error', error)))
                if states == (2, 2):
                    self.assertEqual(calls, [('card', 0), ('card', 1), ('fade',), ('error', 0)])
            else:
                self.assertEqual(cpu.read(0x800BCB3C, 2), 4)
                self.assertEqual(sum(call[0] == 'scan' for call in calls),
                                 8 if format_answer == 1 else 4)
                self.assertIn(('list',), calls)
                self.assertNotIn(('error', 0), calls)
            if format_answer is not None:
                self.assertLess(calls.index(('fade',)), calls.index(('format',)))

    def test_facility_prepares_the_complete_save_list_before_fading_in(self):
        cpu = self.cpu()
        cpu.write(0x800BC43C, 0x801D0000)
        cpu.write(0x800BCB3C, 0, 2)
        events = []

        def intercept(c):
            if c.pc in (0x80067CEC, 0x80066254, 0x80065EB0, 0x800ABB94, 0x80025C98, 0x8008B8A0):
                pass
            elif c.pc in (0x800135C4, 0x800139A0):
                events.append('card')
                c.r[2] = 0
            elif c.pc == 0x8009BC78:
                events.append('list')
            elif c.pc == 0x8008BCAC:
                self.assertEqual(cpu.read(0x800BCB3C, 2), 4)
                self.assertEqual(events.count('list'), 1)
                self.assertEqual(c.r[4:6], [4, 0x80])
                events.append('fade')
            elif c.pc == 0x8008F104:
                self.fail('opening the facility must not wait for Accept')
            else:
                return False
            c.start(c.r[31])
            return True

        cpu.start(0x8009A370)  # FacilityOpen's actual save-facility initialization call
        cpu.run(0x8009A384, limit=100000, intercept=intercept)
        self.assertLess(events.index('list'), events.index('fade'))
        self.assertEqual(events[-1], 'fade')
        self.assertEqual(events.count('fade'), 1)
        self.assertEqual(cpu.read(0x8009A378), 0x34040004,
                         'save entry uses the unchanged retail step=4 setup')
        retail = (ROOT / 'data/psx/ADV.BIN').read_bytes()
        offset = 0x8009A378 - 0x800643C4
        self.assertEqual(bytes(cpu.read(0x8009A378 + n, 1) for n in range(12)),
                         retail[offset:offset + 12],
                         'the original fade arguments and call must remain byte-for-byte intact')

    def test_prepared_menu_keeps_a_real_multiframe_fade_with_inherited_bright_layers(self):
        cpu = self.cpu()
        cpu.write(0x800BC43C, 0x801D0000)
        cpu.write(0x800BCB3C, 0, 2)
        for layer in range(6):
            cpu.load(0x800B8E78 + layer * 36, b'\x80' * 3)
        cpu.write(0x800DC00C, 0, 1)  # retail FadeBlackout does not clear BG RGB
        frames, lists, hidden_frames = [], [], []
        fast_forward_remaining = [0]

        def intercept(c):
            if c.pc in (0x80067CEC, 0x80066254, 0x80065EB0, 0x800ABB94, 0x80025C98):
                pass
            elif c.pc in (0x800135C4, 0x800139A0):
                self.assertFalse(hidden_frames or frames, 'all card activity must finish before reveal preparation')
                fast_forward_remaining[0] = 30
                c.r[2] = 0
            elif c.pc == 0x8009BC78:
                lists.append(1)
            elif c.pc == 0x8008B8A0:  # real RenderFrames loop; only intercept its renderer
                self.assertEqual(len(lists), 1)
                self.assertEqual(cpu.read(0x800DC00C, 1), 0)
                for layer in range(6):
                    self.assertEqual(cpu.read(0x800B8E78 + layer * 36, 1), 0)
                hidden_frames.append(1)
                fast_forward_remaining[0] = max(0, fast_forward_remaining[0] - 1)
            elif c.pc == 0x8007D384:  # RunFrame only; execute the real fade and both real steppers
                self.assertEqual(fast_forward_remaining[0], 0,
                                 'the emulator card-access acceleration must expire before visible fade frames')
                self.assertEqual(cpu.read(0x800BCB3C, 2), 4)
                self.assertEqual(len(lists), 1)
                rgb = bytes(cpu.read(0x800B8E78 + layer * 36 + channel, 1)
                            for layer in range(6) for channel in range(3))
                self.assertEqual(len(set(rgb)), 1)
                frames.append((rgb[0], cpu.read(0x800DC00C, 1)))
            else:
                return False
            c.start(c.r[31])
            return True

        cpu.start(0x8009A370)
        cpu.run(0x8009A384, limit=100000, intercept=intercept)
        self.assertEqual(len(hidden_frames), 30)
        expected = [(level, level) for level in range(4, 129, 4)] + [(128, 128)]
        self.assertEqual(len(frames), 33, 'use the original game fade duration without a speed override')
        self.assertEqual(frames, expected, 'the completed menu must visibly ramp, not jump in one frame')

    def test_initial_warning_really_fades_up_and_is_not_blacked_out_afterwards(self):
        cpu = self.cpu()
        cpu.write(0x800BC43C, 0x801D0000)
        cpu.write(0x800BCB3C, 0, 2)
        for layer in range(6):
            cpu.load(0x800B8E78 + layer * 36, b'\x80' * 3)
        cpu.write(0x800DC00C, 0, 1)
        frames, warnings, hidden_frames = [], [], []

        def intercept(c):
            if c.pc in (0x80067CEC, 0x80066254, 0x80065EB0, 0x80025C98):
                pass
            elif c.pc == 0x800135C4:
                c.r[2] = 2
            elif c.pc == 0x8008B8A0:
                self.assertEqual(c.read(0x800B8E78, 1), 0)
                self.assertEqual(c.read(0x800DC00C, 1), 0)
                hidden_frames.append(1)
            elif c.pc == 0x8007D384:
                frames.append((c.read(0x800B8E78, 1), c.read(0x800DC00C, 1)))
            elif c.pc == 0x8009C1A8:
                self.assertEqual(c.r[4:6], [0, 0])
                self.assertEqual(frames[-1], (128, 128))
                warnings.append(1)
            else:
                return False
            c.start(c.r[31])
            return True

        cpu.start(0x8009A370)
        cpu.run(0x8009A384, limit=100000, intercept=intercept)
        self.assertEqual(warnings, [1])
        self.assertEqual(len(hidden_frames), 30, 'visible prompts must not restart hidden preparation')
        self.assertEqual(frames, [(x, x) for x in range(4, 129, 4)] + [(128, 128)] * 2)

    def test_cancel_from_save_list_closes_facility_without_reopening_parent(self):
        for column in (0, 1):
            cpu = self.cpu()
            menu = 0x801D0000
            cpu.write(0x800BC43C, menu)
            cpu.write(menu + 0x2D4, column)
            cpu.write(menu + 0x2D8, column)
            cpu.write(0x800BCB3C, 4, 2)
            # Start at the retail Cancel-input gate after the list's draw/step.
            def intercept(c):
                if c.pc == 0x8008F180:
                    c.r[2] = 1
                    c.start(c.r[31])
                    return True
                if c.pc in (0x8009A638, 0x8009C298):
                    self.fail('Cancel must not reopen the top or card selector')
                return False
            # SaveSlotStep's epilogue restores its real callee-save frame.
            cpu.r[29] -= 0x38
            cpu.write(cpu.r[29] + 0x30, 0x80001000)
            cpu.start(0x8009B4D4)
            cpu.run(0x80001000, intercept=intercept)
            self.assertEqual(cpu.read(0x800BCB3C, 2), 0xFF)


if __name__ == '__main__':
    unittest.main()
