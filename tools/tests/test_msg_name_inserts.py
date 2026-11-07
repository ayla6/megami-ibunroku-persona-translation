"""Execute the built message-insert stubs (ADV/DNG/S2D MsgStep cases 9-12).

Retail inserted only the ten-glyph record head. The stubs resolve the whole,
FF-terminated name into the overlay's name scratch and enter the retail insert
loop with left = 0xFF. This test drives the assembled stubs on the R3000 and
checks the scratch, s2, left and flags at the insert loop.

Run after assembly:
    python -m unittest discover -s tools/tests -p test_msg_name_inserts.py -v
"""
from pathlib import Path
import re
import struct
import sys
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import items      # noqa: E402
import name_tails  # noqa: E402
import personas   # noqa: E402
import skills     # noqa: E402
import slps       # noqa: E402
import toolbelt   # noqa: E402

OVERLAY_BASE = 0x800643C4
EXE_BASE = 0x80010000
STATE = 0x80180000                     # s1: a MsgState-like block
STACK = 0x801FF000
FLAGS = 0x00000005                     # an existing flag bit must survive
LOOPS = {'adv': 0x80066CF0, 'dng': 0x80076B20, 's2d': 0x800666D4}
# Every retail image that can link the script VM. The four case bodies are
# fingerprinted with j/jal targets masked (they differ per overlay) and data
# literals masked (the name tables are overlay-local).
RETAIL_BASES = {
    'ADV.BIN': 0x800643C4, 'DNG.BIN': 0x800643C4, 'S2D.BIN': 0x800643C4,
    'BTLP.BIN': 0x800643C4, 'CASINO.BIN': 0x800643C4,
    'SLPS_005.00': 0x80010000 - 0x800, 'OPEN.BIN': 0x80180000,
}

# The case site and the register that carries the record id at the diverted
# jump (see adv/msg_name.asm, dng/msg_name.asm and s2d/msg_name.asm).
SITES = {
    'adv': {'item': (0x80067158, 'v0'), 'skill': (0x8006717C, 'a0'),
            'demon': (0x800671AC, 'a0'), 'persona': (0x800671D0, 'v1')},
    'dng': {'item': (0x80076F14, 'v0'), 'skill': (0x80076F38, 'a0'),
            'demon': (0x80076F68, 'a0'), 'persona': (0x80076F8C, 'v1')},
    's2d': {'item': (0x80066AC8, 'v0'), 'skill': (0x80066AEC, 'a0'),
            'demon': (0x80066B1C, 'a0'), 'persona': (0x80066B40, 'v1')},
}


def skill_rows():
    """[(id, en)] of translated skill records (id 1-based, base 0x80047D44)."""
    out = []
    first = slps.SK_FIRST - slps.BASE
    for row in toolbelt.merged_rows(slps.REL):
        pos = int(row['pos'], 16)
        if not (first <= pos < first + slps.SK_STRIDE * slps.SK_COUNT):
            continue
        if (pos - first) % slps.SK_STRIDE:
            continue
        text = (row.get('en') or '').strip()
        if text:
            out.append(((pos - first) // slps.SK_STRIDE + 1, text))
    return sorted(out)


def persona_rows():
    return sorted((ident, text) for ident, text in personas.record_en().items()
                  if text.strip())


def encoded(kind, ident, text):
    if kind in ('item', 'demon'):
        return items.encode(text)
    if kind == 'skill':
        return slps.encode_skill(text)
    return skills.encode_glyphs(ident, text)


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


class MessageNameInserts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [ROOT / 'build' / name for name in
                 ('ADV.BIN', 'DNG.BIN', 'S2D.BIN', 'SLPS_005.00', 'persona.sym')]
        if not all(path.exists() for path in paths):
            raise unittest.SkipTest('requires assembled message-name output')
        cls.sym = {}
        for line in paths[4].read_text(encoding='utf-8').splitlines():
            match = re.fullmatch(r'([0-9A-Fa-f]{8}) (\w+)', line)
            if match:
                cls.sym[match[2]] = int(match[1], 16)
        if 'sf_msg_item_s2d' not in cls.sym:
            raise unittest.SkipTest('build predates the message-name stubs')
        cls.overlays = {'adv': paths[0].read_bytes(), 'dng': paths[1].read_bytes(),
                        's2d': paths[2].read_bytes()}
        cls.exe = paths[3].read_bytes()
        cls.retail = {name: (ROOT / 'data/psx' / name).read_bytes()
                      for name in RETAIL_BASES}
        cls.rows = {
            'item': name_tails.item_rows(),
            'demon': name_tails.demon_rows(),
            'skill': skill_rows(),
            'persona': persona_rows(),
        }

    def machine(self, family):
        cpu = CPU()
        cpu.load(OVERLAY_BASE, self.overlays[family])
        size = struct.unpack_from('<I', self.exe, 0x1C)[0]
        cpu.load(EXE_BASE, self.exe[0x800:0x800 + size])
        cpu.r[REG['sp']] = STACK
        return cpu

    def drive(self, family, kind, ident):
        cpu = self.machine(family)
        scratch = self.sym[f'sf_name_scratch_{family}']
        loop = LOOPS[family]
        cpu.load(STATE, bytes(0x40))
        cpu.write(STATE, FLAGS, 4)
        cpu.r[REG['s1']] = STATE
        cpu.r[REG['a1']] = ident
        seen = {}

        def intercept(cpu):
            if cpu.pc != loop:
                return False
            seen['s2'] = cpu.r[REG['s2']]
            seen['left'] = cpu.read(STATE + 0x35, 1)
            seen['flags'] = cpu.read(STATE, 4)
            cpu.pc, cpu.next_pc = 0x801F0000, 0x801F0004
            return True

        cpu.start(self.sym[f'sf_msg_{kind}_{family}'])
        cpu.run(0x801F0000, limit=2000000, intercept=intercept)
        self.assertIn('s2', seen, f'{family} {kind} {ident} never reached the insert loop')
        raw = bytes(cpu.read(scratch + i, 1) for i in range(24))
        name = raw.split(b'\xff')[0]
        return name, seen

    def check(self, family, kind, ident, text):
        want = encoded(kind, ident, text)
        name, seen = self.drive(family, kind, ident)
        with self.subTest(family=family, kind=kind, ident=ident, text=text):
            self.assertEqual(name, want)
            self.assertEqual(seen['s2'], self.sym[f'sf_name_scratch_{family}'])
            self.assertEqual(seen['left'], 0xFF)
            self.assertEqual(seen['flags'], FLAGS | 0x4001)

    def test_every_name_resolves_in_every_overlay(self):
        for family in ('adv', 'dng', 's2d'):
            for kind, rows in self.rows.items():
                chosen = rows if family == 'adv' else samples(rows)
                for ident, text in chosen:
                    self.check(family, kind, ident, text)

    def test_case_sites_jump_to_the_stubs_with_the_id_register(self):
        registers = {'v0': REG['v0'], 'a0': REG['a0'], 'v1': REG['v1']}
        for family, sites in SITES.items():
            data = self.overlays[family]
            for kind, (site, register) in sites.items():
                target = self.sym[f'sf_msg_{kind}_{family}']
                word, delay = struct.unpack_from('<II', data, site - OVERLAY_BASE)
                with self.subTest(family=family, kind=kind):
                    self.assertEqual(word >> 26, 2, 'not a j')
                    self.assertEqual((site + 4) & 0xF0000000 | (word & 0x03FFFFFF) << 2,
                                     target)
                    self.assertEqual((delay >> 26, (delay >> 21) & 31,
                                      (delay >> 16) & 31, (delay >> 11) & 31),
                                     (0, registers[register], 0, REG['a1']))

    def test_every_compiled_copy_is_a_declared_patch_site(self):
        # The script VM is linked into several overlays, just like the menu
        # screens: S2D carried the same four insert cases but had no stub
        # while ADV and DNG did, so its messages kept the ten-glyph head.
        # Fingerprint each case body (j/jal targets and data literals
        # masked) and require every retail copy to be a declared site.
        literals = {9, 13, 15}          # addiu, ori, lui

        def signature(word):
            op = word >> 26
            if op in literals:
                return (op, (word >> 21) & 31, (word >> 16) & 31, None)
            if op == 0:
                return (0, word & 63, (word >> 6) & 31,
                        (word >> 11) & 31, (word >> 16) & 31)
            if op in (2, 3):            # j / jal: the target differs per overlay
                return (op, (word >> 21) & 31, (word >> 16) & 31, None)
            return (op, (word >> 21) & 31, (word >> 16) & 31, word & 0xFFFF)

        length = 0x14
        for kind in ('item', 'skill', 'demon', 'persona'):
            probe = SITES['adv'][kind][0] - OVERLAY_BASE
            want = [signature(struct.unpack_from(
                '<I', self.retail['ADV.BIN'], probe + k)[0])
                for k in range(0, length, 4)]
            found = set()
            for name, base in RETAIL_BASES.items():
                data = self.retail[name]
                for offset in range(0, len(data) - length + 1, 4):
                    if all(signature(struct.unpack_from(
                               '<I', data, offset + k)[0]) == want[k // 4]
                           for k in range(0, length, 4)):
                        found.add((name, base + offset))
            declared = {(f'{family.upper()}.BIN', sites[kind][0])
                        for family, sites in SITES.items()}
            with self.subTest(kind=kind):
                self.assertEqual(
                    sorted(found), sorted(declared),
                    f'{kind}: retail copies outside the declared patch '
                    f'sites: {sorted(found - declared)}; declared but not '
                    f'found (wrong span?): {sorted(declared - found)}')

    def test_longest_and_spaced_names_are_in_the_sample(self):
        for kind, rows in self.rows.items():
            longest = max(rows, key=lambda row: len(encoded(kind, row[0], row[1])))
            picked = dict(samples(rows))
            self.assertIn(longest[0], picked)
            if kind == 'persona':
                spaced = [row for row in rows if ' ' in row[1]]
                self.assertTrue(spaced)
                self.assertTrue(any(ident in picked for ident, _ in spaced))
                self.assertIn('Cu Chulainn', [text for _, text in spaced])


if __name__ == '__main__':
    unittest.main()
