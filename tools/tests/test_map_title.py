"""Execute the built map-screen title hook on the R3000.

The hook compares the map pack's 20-byte name field against the shared title
table and hands BgMapInit the full PSP wording. This test drives the assembled
code with mips_cpu, which models the R3000 load delay - the exact hazard that
once made every Japanese-keyed field miss and fall back to retail.

Run after assembly:
    python -m unittest discover -s tools/tests -p test_map_title.py -v
"""
from pathlib import Path
import re
import struct
import unittest

from mips_cpu import CPU, REG, clobber_bios_registers

ROOT = Path(__file__).resolve().parents[2]
DNG_BASE = 0x800643C4
ENTRY = 0x80096D2C
FALLBACK = 0x80096D34
PACK = 0x801DD000
CELLS = 0x800A0730
BZERO = 0x800412FC
BGMAP_INIT = 0x800765C4
RETURN = 0x801F0000
FIELD_OFF = 0x100
GUARD = CELLS - 0x30        # canary around the 0x22-byte script area
GUARD_LEN = 0xC0
CANARY = 0x5A
STACK = 0x801CEFE0          # the hook's frame (initial sp - 0x20)
POISON = 0xA5

# Every byte the hook (or the retail body it resumes) may write, as
# (start, length): its own frame, the map-name cells' 0x22-byte script area,
# the banner strip's x/y/w/h words, and the shown-bits word.
OWNED = ((STACK, 0x20), (CELLS, 0x22),
         (0x8009C1D8, 8), (0x800A0CCC, 4))


class BuiltMapTitle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [ROOT / 'build' / name for name in
                 ('DNG.BIN', 'persona.sym', 'dng_titles.bin')]
        if not all(p.exists() for p in paths):
            raise unittest.SkipTest('requires assembled map-title output')
        cls.dng, cls.title = paths[0].read_bytes(), paths[2].read_bytes()
        cls.sym = {}
        for line in paths[1].read_text(encoding='utf-8').splitlines():
            m = re.fullmatch(r'([0-9A-Fa-f]{8}) (\w+)', line)
            if m:
                cls.sym[m[2]] = int(m[1], 16)
        if 'dng_title_idx' not in cls.sym:
            raise unittest.SkipTest('build predates map-title hook')
        idx, blob = cls.sym['dng_title_idx'], cls.sym['dng_title_blob']
        count, rem = divmod(blob - idx, 24)
        if rem or not count:
            raise AssertionError('invalid title table bounds')
        cls.rows = []
        for i in range(count):
            entry = cls.title[i * 24:(i + 1) * 24]
            key = entry[:20]
            width = entry[20]
            offset = struct.unpack_from('<H', entry, 22)[0]
            start = (blob - idx) + offset
            end = cls.title.index(b'\xff\x01', start) + 2
            cls.rows.append((key, width, cls.title[start:end]))

    def machine(self, key, fake_row=None, poison=None, r=None):
        """A map pack whose entry 0 names the field that holds `key`.

        `fake_row` replaces title row 0, so the defensive checks can be
        exercised without touching the generated table. `poison` fills RAM
        with that byte before the code/data is loaded, so anything the hook
        reads without writing is visibly garbage. `r` seeds caller-saved
        registers to prove the outcome never depends on their leftovers.
        """
        c = CPU()
        if poison is not None:
            c.fill(poison)
        c.load(DNG_BASE, self.dng)
        if fake_row is not None:
            c.load(self.sym['dng_title_idx'], fake_row)
        pack = bytearray(FIELD_OFF + len(key))
        struct.pack_into('<I', pack, 8, FIELD_OFF)   # entry table: map 0
        pack[FIELD_OFF:FIELD_OFF + len(key)] = key
        c.load(PACK, bytes(pack))
        # Canary around the name cells: the hook must never write past
        # cells + 0x22 (the script area MapDrawName zeroes).
        c.load(GUARD, bytes([CANARY]) * GUARD_LEN)
        for name, value in (r or {}).items():
            c.r[REG[name]] = value
        c.r[REG['sp']], c.r[REG['ra']] = 0x801CF000, RETURN
        c.r[REG['a0']] = 0
        return c

    def execute(self, c, track=False):
        calls = []

        def intercept(cpu):
            if cpu.pc == FALLBACK:
                calls.append(('fallback',))
                return False                    # run the retail body too
            if cpu.pc == BZERO:
                a0, a1 = cpu.r[REG['a0']], cpu.r[REG['a1']]
                for i in range(a1):
                    cpu.write(a0 + i, 0, 1)
                # A BIOS call does not preserve the caller-saved registers;
                # the real bzero returns with t0=0xBFC01ACC and t1=t2=0xA0.
                clobber_bios_registers(cpu)
                ret = cpu.r[REG['ra']]
                cpu.pc, cpu.next_pc = ret, ret + 4
                return True
            if cpu.pc == BGMAP_INIT:
                calls.append(('bgmap', cpu.r[REG['a0']], cpu.r[REG['a1']],
                              bytes(cpu.mem[cpu.offset(CELLS, 0x22):
                                            cpu.offset(CELLS, 0x22) + 0x22])))
                ret = cpu.r[REG['ra']]
                cpu.pc, cpu.next_pc = ret, ret + 4
                return True
            return False

        c.writes.clear()
        c.track_writes = track
        c.start(ENTRY)
        c.run(RETURN, limit=2000000, intercept=intercept)
        return calls, c

    @staticmethod
    def cells(cpu, offset, length):
        """Read `length` bytes of the map-name cells (CPU.read returns ints)."""
        return bytes(cpu.read(CELLS + offset + i, 1) for i in range(length))

    def assert_cells_bounded(self, cpu):
        """Nothing outside the 0x22-byte script area was written."""
        guard = bytes(cpu.read(GUARD + i, 1) for i in range(GUARD_LEN))
        for off, value in enumerate(guard):
            if CELLS <= GUARD + off < CELLS + 0x22:
                continue
            self.assertEqual(value, CANARY,
                             f'stray write at {GUARD + off:#x}')
        self.assert_owned_writes(cpu)

    def assert_owned_writes(self, cpu):
        """Every write landed in a span this hook owns, and the ABI is intact.

        This is the crash-class invariant: the old bug copied a garbage row
        across memory and returned through a clobbered pointer, and neither
        the cells nor a narrow canary alone could see it. The ledger catches
        any write anywhere else, and the stack/return checks catch a broken
        frame even when the copy stayed in bounds.
        """
        for address, size in cpu.writes:
            inside = any(start <= address and address + size <= start + length
                         for start, length in OWNED)
            if not inside:
                self.fail(f'write outside owned regions: {address:#010x}+{size}')
        self.assertEqual(cpu.r[REG['sp']], 0x801CF000, 'stack not balanced')
        self.assertEqual(cpu.r[REG['ra']], RETURN, 'ra not restored')

    def test_every_title_row_hits_and_copies_its_full_title(self):
        for i, (key, width, script) in enumerate(self.rows):
            with self.subTest(row=i, width=width):
                calls, cpu = self.execute(self.machine(key), track=True)
                self.assertEqual([c[0] for c in calls], ['bgmap'],
                                 'Japanese field fell back to retail')
                self.assertEqual(calls[0][1:3], (CELLS, 0))
                self.assertEqual(calls[0][3][:len(script)], script)
                self.assertEqual(calls[0][3][len(script)], 0)
                self.assert_cells_bounded(cpu)

    def test_unknown_field_uses_the_retail_fallback(self):
        keys = {row[0] for row in self.rows}
        key = bytearray(self.rows[-1][0])
        for pos in range(20):
            for value in range(256):
                key[pos] = value
                if bytes(key) not in keys:
                    break
            else:
                continue
            break
        self.assertNotIn(bytes(key), keys)
        calls, cpu = self.execute(self.machine(bytes(key)), track=True)
        self.assertEqual([c[0] for c in calls], ['fallback', 'bgmap'])
        # retail's ten-pair path always ends the script at cells[20:22]
        self.assertEqual(self.cells(cpu, 20, 2), b'\xff\x01')
        self.assert_cells_bounded(cpu)

    def test_corrupt_row_falls_back_before_the_copy(self):
        key = bytes(range(20))
        for width, offset in ((0xA1, 0), (100, 0xFFFF)):
            with self.subTest(width=width, offset=offset):
                row = key + bytes([width, 0]) + struct.pack('<H', offset)
                calls, cpu = self.execute(self.machine(key, fake_row=row), track=True)
                self.assertEqual([c[0] for c in calls], ['fallback', 'bgmap'])
                self.assertEqual(self.cells(cpu, 20, 2), b'\xff\x01')
                self.assert_cells_bounded(cpu)

    def test_oversized_title_cannot_overrun_the_cells(self):
        key = bytes(range(20, 40))
        row = key + bytes([100, 0]) + struct.pack('<H', 0)
        c = self.machine(key, fake_row=row)
        c.load(self.sym['dng_title_blob'], bytes([0x90]) * 33 + b'\xff\x01')
        calls, cpu = self.execute(c, track=True)
        self.assertEqual([item[0] for item in calls], ['fallback', 'bgmap'])
        self.assertEqual(self.cells(cpu, 20, 2), b'\xff\x01')
        self.assert_cells_bounded(cpu)

    def test_every_title_row_survives_poisoned_ram(self):
        """Reads must come from the hook's inputs, not zeroed BSS leftovers."""
        for i, (key, width, script) in enumerate(self.rows):
            with self.subTest(row=i, width=width):
                calls, cpu = self.execute(
                    self.machine(key, poison=POISON), track=True)
                self.assertEqual([c[0] for c in calls], ['bgmap'])
                self.assertEqual(calls[0][3][:len(script)], script)
                self.assert_cells_bounded(cpu)

    def test_mutated_key_always_falls_back_and_never_copies(self):
        keys = {row[0] for row in self.rows}
        for i, (key, _width, _script) in enumerate(self.rows):
            bad = bytearray(key)
            bad[-1] ^= 0xFF
            if bytes(bad) in keys:
                continue
            with self.subTest(row=i):
                calls, cpu = self.execute(
                    self.machine(bytes(bad), poison=POISON), track=True)
                self.assertEqual([c[0] for c in calls], ['fallback', 'bgmap'])
                self.assertEqual(self.cells(cpu, 20, 2), b'\xff\x01')
                self.assert_cells_bounded(cpu)

    def test_width_and_offset_sweep_never_escapes_the_cells(self):
        key = bytes(range(20))
        blob_len = self.sym['dng_title_blob_end'] - self.sym['dng_title_blob']
        # (offset, the hook can copy a well-formed script there)
        cases = ((0, True), (blob_len - 2, True),
                 (blob_len, False), (0xFFFF, False))
        for width in range(0x100):
            for offset, well_formed in cases:
                hit = well_formed and width <= 0xA0
                with self.subTest(width=width, offset=offset):
                    row = key + bytes([width, 0]) + struct.pack('<H', offset)
                    calls, cpu = self.execute(
                        self.machine(key, fake_row=row, poison=POISON),
                        track=True)
                    self.assertEqual([c[0] for c in calls],
                                     ['bgmap'] if hit
                                     else ['fallback', 'bgmap'])
                    self.assert_cells_bounded(cpu)

    def test_incoming_caller_saved_garbage_cannot_change_the_outcome(self):
        junk = {name: 0xC0DE0000 | (REG[name] & 0xFF)
                for name in ('v0', 'v1', 'a1', 'a2', 'a3',
                             't0', 't1', 't2', 't3', 't4', 't5',
                             't6', 't7', 't8', 't9')}
        for i, (key, width, script) in enumerate(self.rows):
            with self.subTest(row=i, width=width):
                clean, _ = self.execute(self.machine(key, poison=POISON))
                dirty, cpu = self.execute(
                    self.machine(key, poison=POISON, r=junk), track=True)
                self.assertEqual([c[0] for c in dirty],
                                 [c[0] for c in clean])
                self.assertEqual(dirty[0][3][:len(script)], script)
                self.assert_cells_bounded(cpu)

    def test_mikage_subway_fields_show_the_full_names(self):
        pack = ROOT / 'build/D01/D0DM.BIN'
        if not pack.exists():
            self.skipTest('requires the built D01 pack')
        data = pack.read_bytes()
        expected = {'Mikage Subway West': 0x6a0,
                    'West Subway Entrance': 0x764,
                    'Mikage Subway East': 0x828,
                    'East Subway Entrance': 0x8ec}
        found = {}
        for key, _width, script in self.rows:
            text = ''.join(' ' if b == 0x88 else chr(b - 0x68)
                           for b in script[:-2])
            if text in expected:
                found[text] = key
        for text, off in expected.items():
            with self.subTest(name=text):
                self.assertIn(text, found, 'title table lost the PSP-US name')
                self.assertEqual(data[off:off + 20], found[text],
                                 'built pack field does not carry the title key')
                calls, cpu = self.execute(self.machine(found[text]))
                self.assertEqual([c[0] for c in calls], ['bgmap'])
                self.assert_cells_bounded(cpu)


if __name__ == '__main__':
    unittest.main()
