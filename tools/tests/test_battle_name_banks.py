"""The battle name banks are carved out of dead retail code: nothing on the
disc may reference any byte inside them.

The 2026-10-29 crash: the skill slot bank was widened past its dead run and
covered the live function at 0x8002C2F0 (BTLP calls it 8 times), so opening
the skill menu executed skill-name bytes as MIPS. This test pins the rule:
a bank may only grow where the retail disc has no jump, no address word and
no lui/addiu pair pointing into it.
"""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src' / 'injection_tools'))
import toolbelt  # noqa: E402


def words(data):
    return struct.unpack_from(f'<{len(data) // 4}I', data, 0)


def lui_pairs(w):
    """Addresses formed by lui rX followed (within 8 instr) by addiu/ori rY, rX."""
    out = set()
    for i, x in enumerate(w):
        if x >> 26 != 0x0F:
            continue
        rt, hi = (x >> 16) & 31, (x & 0xFFFF) << 16
        for y in w[i + 1:i + 9]:
            op = y >> 26
            if op in (0x09, 0x0D) and (y >> 21) & 31 == rt:
                imm = y & 0xFFFF
                if op == 0x09 and imm & 0x8000:
                    imm -= 0x10000
                out.add((hi + imm) & 0xFFFFFFFF)
    return out


class BattleNameBanks(unittest.TestCase):
    def test_no_disc_reference_lands_inside_a_name_bank(self):
        ranges = [(toolbelt.asm_equ('PERSONA_HDR_BUF'), toolbelt.asm_equ('PERSONA_HDR_BUF_END'),
                   'PERSONA_HDR_BUF'),
                  (toolbelt.asm_equ('SKILL_MENU_BUF'), toolbelt.asm_equ('SKILL_MENU_BUF_END'),
                   'SKILL_MENU_BUF')]
        inside = lambda a: next((name for lo, hi, name in ranges if lo <= a < hi), None)
        binaries = ([ROOT / 'data' / 'local' / 'original' / 'SLPS_005.00']
                    + sorted((ROOT / 'data' / 'local' / 'original').glob('*.BIN'))
                    + sorted((ROOT / 'data' / 'local' / 'original' / 'EXE').glob('*.EXE')))
        hits = []
        for path in binaries:
            if not path.exists() or path.stat().st_size > 3_000_000:
                continue
            ww = words(path.read_bytes()[:path.stat().st_size & ~3])
            for x in ww:
                if x >> 26 in (2, 3):                       # j / jal
                    target = 0x80000000 | ((x & 0x3FFFFFF) << 2)
                    name = inside(target)
                    if name:
                        hits.append((path.name, 'jump', hex(target), name))
                elif 0x80010000 <= x < 0x80056000:          # address as a data word
                    name = inside(x)
                    if name:
                        hits.append((path.name, 'word', hex(x), name))
            for a in lui_pairs(ww):                          # function pointer pair
                name = inside(a)
                if name:
                    hits.append((path.name, 'lui/addiu', hex(a), name))
        self.assertEqual(hits, [])

    def test_banks_end_where_their_dead_runs_end(self):
        # Each bank must fill (not pass) the dead run it was carved from; the
        # skill run ends at the live function 0x8002C2F0, the Persona run at
        # the next dead function boundary. The Persona run holds three name
        # slots plus the static header label slot (BATTLE_LABEL_BUF).
        self.assertEqual(toolbelt.asm_equ('PERSONA_HDR_BUF') + 4 * toolbelt.asm_equ('PERSONA_HDR_STRIDE'),
                         toolbelt.asm_equ('PERSONA_HDR_BUF_END'))
        self.assertLessEqual(toolbelt.asm_equ('PERSONA_HDR_BUF_END'),
                             toolbelt.asm_equ('PERSONA_HDR_LIMIT'))
        self.assertEqual(toolbelt.asm_equ('SKILL_MENU_BUF') + 7 * toolbelt.asm_equ('SKILL_MENU_STRIDE'),
                         toolbelt.asm_equ('SKILL_MENU_BUF_END'))


if __name__ == '__main__':
    unittest.main()
