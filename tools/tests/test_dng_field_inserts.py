"""Execute the assembled dungeon field-script FF09 / FF0B name inserts.

Retail printed the ten-glyph record head (printer count 10). The patched case
heads divert to stubs that resolve the whole, FF-terminated name into the
overlay's name scratch (item_name_copy_dng / demon_name_copy_dng) and call the
printer with the name bound, then join the retail continuation. This test
drives the assembled stubs on the R3000: the scratch, the printer arguments,
the printed glyphs and the read pointer's advance.

Run after assembly:
    python -m unittest discover -s tools/tests -p test_dng_field_inserts.py -v
"""
from pathlib import Path
import re
import struct
import sys
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import items       # noqa: E402
import name_tails  # noqa: E402
import toolbelt    # noqa: E402

OVERLAY_BASE = 0x800643C4
EXE_BASE = 0x80010000
SCRIPT = 0x801F0000                    # a synthetic command stream
STACK = 0x801FF000
PRINTER = 0x800753AC                   # the dungeon field-script name printer
MAINLOOP = 0x80074ECC                  # where the common tail rejoins the interpreter
# the field-script case heads the dispatch table points at, and the byte the
# command stream carries for them (FF09 item with a 16-bit id, FF0B demon)
SITES = {'item': (0x800741C8, 0x09), 'demon': (0x80074214, 0x0B)}
MAXLEN = {'item': toolbelt.asm_equ('ITEM_NAME_MAXLEN'),
          'demon': toolbelt.asm_equ('DEMON_NAME_MAXLEN')}


def samples(rows, limit=3):
    """Longest rows plus the first row whose name holds a space."""
    picked = {}
    for ident, text in sorted(rows, key=lambda row: (-len(row[1]), row[0])):
        if len(picked) >= limit:
            break
        picked[ident] = text
    for ident, text in rows:
        if ' ' in text and len(picked) < limit + 1:
            picked[ident] = text
            break
    return sorted(picked.items())


class DungeonFieldInserts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [ROOT / 'build' / name for name in
                 ('DNG.BIN', 'SLPS_005.00', 'persona.sym')]
        if not all(path.exists() for path in paths):
            raise unittest.SkipTest('requires assembled DNG output')
        cls.overlay = paths[0].read_bytes()
        cls.exe = paths[1].read_bytes()
        cls.sym = {}
        for line in paths[2].read_text(encoding='utf-8').splitlines():
            match = re.fullmatch(r'([0-9A-Fa-f]{8}) (\w+)', line)
            if match:
                cls.sym[match[2]] = int(match[1], 16)
        if 'dng_item_name' not in cls.sym:
            raise AssertionError('assembled symbols missing field-script name stubs')
        cls.rows = {'item': name_tails.item_rows(),
                    'demon': name_tails.demon_rows()}

    def machine(self):
        cpu = CPU()
        cpu.load(OVERLAY_BASE, self.overlay)
        size = struct.unpack_from('<I', self.exe, 0x1C)[0]
        cpu.load(EXE_BASE, self.exe[0x800:0x800 + size])
        cpu.r[REG['sp']] = STACK
        return cpu

    def drive(self, kind, ident):
        """Run the case from its dispatch head; (cpu, printer args, glyphs)."""
        site, op = SITES[kind]
        stream = (bytes((op, ident & 0xFF, ident >> 8)) if kind == 'item'
                  else bytes((op, ident)))
        cpu = self.machine()
        cpu.load(SCRIPT, stream)
        cpu.r[REG['s5']] = SCRIPT
        seen = {'glyphs': [], 'frames': 0, 'stream': stream}

        def intercept(cpu):
            if cpu.pc == PRINTER:
                seen['a0'] = cpu.r[REG['a0']]
                seen['a1'] = cpu.r[REG['a1']]
                seen['s5'] = cpu.r[REG['s5']]
                return False          # recorded; now let the printer print
            if cpu.pc == self.sym['dng_txt_put_name']:
                seen['glyphs'].append(cpu.r[REG['a0']])
                cpu.start(cpu.r[REG['ra']])
                return True
            if cpu.pc == 0x800659B4:
                seen['frames'] += 1
                cpu.start(cpu.r[REG['ra']])
                return True
            return False

        cpu.start(self.sym[f'dng_{kind}_name'])
        cpu.run(MAINLOOP, limit=2000000, intercept=intercept)
        return cpu, seen

    def check(self, kind, ident, text):
        site, _op = SITES[kind]
        want = items.encode(text)
        with self.subTest(kind=kind, ident=ident, text=text):
            # the case head is a jump to the stub (nothing else runs there)
            word, _delay = struct.unpack_from('<II', self.overlay, site - OVERLAY_BASE)
            self.assertEqual(word >> 26, 2, f'{site:#x}: not a j')
            self.assertEqual((site & 0xF0000000) | ((word & 0x03FFFFFF) << 2),
                             self.sym[f'dng_{kind}_name'])
            cpu, seen = self.drive(kind, ident)
            stream = seen['stream']
            scratch = self.sym['sf_name_scratch_dng']
            self.assertEqual(seen['a0'], scratch)
            self.assertEqual(seen['a1'], MAXLEN[kind])
            # s5 sits just past the parameters when the printer runs; the
            # command byte itself is still counted by the common tail
            self.assertEqual(seen['s5'] - SCRIPT, len(stream) - 1)
            self.assertEqual(seen['glyphs'], list(want))
            self.assertEqual(seen['frames'], len(want))
            raw = bytes(cpu.read(scratch + i, 1) for i in range(len(want) + 1))
            self.assertEqual(raw, want + b'\xff')
            # the common tail consumed the command byte: params (pre-advance)
            # + command (tail) = the whole stream
            self.assertEqual(cpu.r[REG['s5']] - SCRIPT, len(stream))
            self.assertEqual(cpu.r[REG['sp']], STACK)

    def test_every_sampled_name_resolves_full_length(self):
        for kind, rows in self.rows.items():
            for ident, text in samples(rows):
                self.check(kind, ident, text)

    def test_longest_and_spaced_names_are_in_the_sample(self):
        for kind, rows in self.rows.items():
            longest = max(rows, key=lambda row: len(items.encode(row[1])))
            picked = dict(samples(rows))
            self.assertIn(longest[0], picked)
            self.assertTrue(any(' ' in text for text in picked.values()))


if __name__ == '__main__':
    unittest.main()
