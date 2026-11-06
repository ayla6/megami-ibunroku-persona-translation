"""Exhaustive actual R3000 lookup checks for the compact small-font map."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/injection_tools'), str(ROOT / 'tools/tests')]
import fusionmsg
import skills
import toolbelt
from mips_cpu import CPU, REG

class CompactMap(unittest.TestCase):
    def test_all_byte_codes_reconstruct_the_source_table(self):
        table = bytearray(fusionmsg.MAP_LEN)
        for code in range(32, 127):
            c = chr(code)
            if c.isalnum() or c in " .'/:-":
                table[skills.glyph(c)] = code
        pages, data = fusionmsg.compact_map(table)
        self.assertLessEqual(len(pages) + len(data), 115)
        for code in range(len(table)):
            base = pages[code // fusionmsg.MAP_PAGE_SIZE]
            got = data[base - 1 + code % fusionmsg.MAP_PAGE_SIZE] if base else 0
            self.assertEqual(got, table[code], f'{code:#x}')

    def test_assembled_lookup_and_party_path(self):
        image = (ROOT / 'build/SLPS_005.00').read_bytes()
        symbols = {}
        for line in (ROOT / 'build/persona.sym').read_text().splitlines():
            fields = line.split()
            if len(fields) == 2 and re.fullmatch(r'[0-9A-Fa-f]{8}', fields[0]):
                symbols[fields[1]] = int(fields[0], 16)
        for name in ('vwf_glyph_map_party', 'vwf_glyph_map_small', 'vwf_name_map'):
            self.assertIn(name, symbols)
        table = bytearray(fusionmsg.MAP_LEN)
        for ascii_code in range(32, 127):
            c = chr(ascii_code)
            if c.isalnum() or c in " .'/:-":
                table[skills.glyph(c)] = ascii_code
        party = toolbelt.asm_equ('PARTY_NAMES_ADDR')
        bias = toolbelt.asm_equ('VWF_CHAR_BIAS', str(ROOT / 'src/asm/vwf/vwf_dialog.asm'))
        for kind in ('small', 'party', 'nonparty', 'text'):
            for code in range(256):
                cpu = CPU(); cpu.load(0x80010000, image[0x800:])
                cpu.r[REG['sp']] = 0x801ff000; cpu.r[REG['ra']] = 0x8000fff0
                cpu.r[REG['a0']] = code; cpu.r[REG['a1']] = int(kind != 'text')
                cpu.write(0x801ff018, party if kind == 'party' else party - 1)
                cpu.start(symbols['vwf_glyph_map_small' if kind == 'small' else 'vwf_glyph_map_party'])
                # The party path tail-jumps into vwf_name_map, so run through it.
                stops = (0x8000fff0,) if kind == 'party' else (0x8000fff0, symbols['vwf_name_map'])
                for _ in range(200):
                    if cpu.pc in stops:
                        break
                    cpu.step()
                else:
                    self.fail(f'lookup failed to terminate: {kind} {code:#x}')
                if kind == 'party':
                    self.assertEqual(cpu.pc, 0x8000fff0)
                    ref = CPU(); ref.load(0x80010000, image[0x800:])
                    ref.r[REG['sp']] = 0x801ff000; ref.r[REG['ra']] = 0x8000fff0
                    ref.r[REG['a0']] = code
                    ref.start(symbols['vwf_name_map'])
                    for _ in range(80):
                        if ref.pc == 0x8000fff0:
                            break
                        ref.step()
                    else:
                        self.fail(f'vwf_name_map failed to terminate: {code:#x}')
                    self.assertEqual(cpu.r[REG['v0']], ref.r[REG['v0']], f'{kind} {code:#x}')
                elif kind == 'text' or code >= len(table) or not table[code]:
                    self.assertEqual(cpu.pc, symbols['vwf_name_map'], f'{kind} {code:#x}')
                else:
                    self.assertEqual(cpu.pc, 0x8000fff0, f'{kind} {code:#x}')
                    self.assertEqual(cpu.r[REG['v0']], table[code] + bias, f'{kind} {code:#x}')

if __name__ == '__main__':
    unittest.main()
