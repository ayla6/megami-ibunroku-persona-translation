import re, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools/tests')]
import toolbelt  # noqa: E402

class BattlePersonaOwnership(unittest.TestCase):
    def test_persona_registration_uses_canonical_ids_and_preserves_other_slots(self):
        from mips_cpu import CPU, REG
        import btlfont
        image = (ROOT / 'build/BTLP.BIN').read_bytes()
        resident = (ROOT / 'build/SLPS_005.00').read_bytes()
        symbols = {m.group(2): int(m.group(1), 16)
                   for line in (ROOT / 'build/persona.sym').read_text().splitlines()
                   if (m := re.fullmatch(r'([0-9a-fA-F]{8})\s+(\S+)', line))}
        flags = btlfont.persona_vwf_flags()
        persona_buf = toolbelt.asm_equ('PERSONA_HDR_BUF')
        persona_stride = toolbelt.asm_equ('PERSONA_HDR_STRIDE')
        slots_addr = toolbelt.asm_equ('SKILL_VWF_SLOTS_ADDR')
        all_bits = (1 << toolbelt.asm_equ('BATTLE_NAME_BITS')) - 1
        for ident in range(256):
            for slot in (0, 1, 2):
                c = CPU(); c.load(0x800643c4, image); c.load(0x80010000, resident[0x800:])
                c.write(slots_addr, all_bits, 2)
                c.r[REG['a0']] = persona_buf + slot * persona_stride
                c.r[REG['a1']] = ident; c.r[REG['a2']] = slot
                c.r[REG['sp']] = 0x801ff000; c.r[REG['ra']] = 0x8000fff0
                before = c.r.copy(); c.start(symbols['persona_flag_register'])
                for _ in range(100):
                    if c.pc == 0x8000fff0: break
                    c.step()
                else: self.fail('Persona registration did not return')
                owned = ((flags[ident >> 3] >> (ident & 7)) & 1) if ident <= 100 else 0
                self.assertEqual(c.read(slots_addr, 2),
                                 (all_bits & ~(1 << slot)) | (owned << slot))
                for reg in ('a0', 'a1', 't0', 't1', 't2', 't3', 'sp'):
                    self.assertEqual(c.r[REG[reg]], before[REG[reg]])

    def test_static_cost_label_is_fixed_width_and_pointed_at(self):
        import struct
        from mips_cpu import CPU, REG
        image = (ROOT / 'build/BTLP.BIN').read_bytes()
        full = (ROOT / 'build/SLPS_005.00').read_bytes()
        elf_base = struct.unpack_from('<I', full, 0x18)[0]
        resident = full[0x800:]
        symbols = {m.group(2): int(m.group(1), 16)
                   for line in (ROOT / 'build/persona.sym').read_text().splitlines()
                   if (m := re.fullmatch(r'([0-9a-fA-F]{8})\s+(\S+)', line))}
        label = toolbelt.asm_equ('BATTLE_LABEL_BUF')
        slots_addr = toolbelt.asm_equ('SKILL_VWF_SLOTS_ADDR')
        # No name slot is owned at boot.
        self.assertEqual(resident[slots_addr - elf_base:slots_addr - elf_base + 2],
                         b'\x00\x00')
        # The label sits in the Persona bank's fourth slot, just past the
        # three owned slots, and its descriptor points there with its count.
        self.assertEqual(label, toolbelt.asm_equ('PERSONA_HDR_BUF')
                         + 3 * toolbelt.asm_equ('PERSONA_HDR_STRIDE'))
        desc = toolbelt.asm_equ('BTLP_HDR_LABEL_DESC')
        ptr, count = struct.unpack_from('<IB', image, desc - 0x800643c4 + 4)
        self.assertEqual((ptr, count), (label, 4))
        self.assertEqual(resident[label - elf_base:label - elf_base + 5],
                         bytes((0xA8, 0x3A, 0x3E, 0x3F, 0xFF)))
        # The lookup leaves the row fixed for every value the runtime can
        # reach: boot, all skills owned, and any single skill bit cleared.
        all_bits = (1 << toolbelt.asm_equ('BATTLE_NAME_BITS')) - 1
        for bits in (0, all_bits,
                     *[all_bits & ~(1 << bit) for bit in range(
                         toolbelt.asm_equ('SKILL_BIT_OFFSET'),
                         toolbelt.asm_equ('BATTLE_NAME_BITS'))]):
            c = CPU(); c.load(0x800643c4, image); c.load(elf_base, resident)
            c.write(slots_addr, bits, 2)
            c.r[REG['a0']] = label
            c.r[REG['sp']] = 0x801ff000; c.r[REG['ra']] = 0x8000fff0
            c.start(symbols['btl_name_lookup'])
            # The resident lookup walks the whole battle-owned span directory
            # (15 entries), so the step budget must not bound its size.
            for _ in range(1000):
                if c.pc == 0x8000fff0: break
                c.step()
            else: self.fail('name lookup did not return')
            self.assertEqual(c.r[REG['v0']], 0, bits)
