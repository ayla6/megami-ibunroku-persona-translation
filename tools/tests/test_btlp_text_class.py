"""Battle object text: a row is VWF only when a producer range or a
translated-producer span owns it; unregistered text, numbers and non-text
artwork keep the retail 8 px path.

Runs the installed ownership lookup on the CPU, then drives the installed
flat bridge on an UNREGISTERED row (outside every producer range and span)
to prove the fallback reaches the real renderer.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'tests'))
sys.path.insert(0, str(ROOT / 'src' / 'injection_tools'))

import toolbelt  # noqa: E402


def symbols():
    return {m.group(2): int(m.group(1), 16)
            for line in (ROOT / 'build' / 'persona.sym').read_text().splitlines()
            if (m := re.match(r'^([0-9a-fA-F]{8})\s+(\S+)', line))}


SYM = symbols()
SLPS = (ROOT / 'build' / 'SLPS_005.00').read_bytes()[0x800:]


def enc(text):
    return bytes(toolbelt.smallfont_char(c) for c in text)


def cpu():
    from mips_cpu import CPU, REG
    c = CPU()
    c.load(0x80010000, SLPS)
    c.r[REG['sp']] = 0x801ff000
    c.r[REG['ra']] = 0x8000fff0
    return c, REG


def run(c, REG, entry, limit=1000):
    c.start(entry)
    for _ in range(limit):
        if c.pc == 0x8000fff0:
            return c.r[REG['v0']]
        c.step()
    raise AssertionError(f'{entry:#x} did not return')


def classify(text, count=None):
    """Call the installed btl_text_is_text with a real BtlGfxText row."""
    c, REG = cpu()
    TXT, ROW = 0x80100000, 0x80101000
    c.load(TXT, text)
    c.write(ROW, 0)
    c.write(ROW + 4, TXT)
    c.write(ROW + 8, len(text) if count is None else count, 1)
    c.r[REG['a0']] = TXT
    c.r[REG['t7']] = ROW
    return run(c, REG, SYM['btl_name_lookup'])


def lookup(text, count=None):
    """Call the installed shared lookup on a row outside every range."""
    c, REG = cpu()
    TXT, ROW = 0x80100000, 0x80101000
    c.load(TXT, text)
    c.write(ROW, 0)
    c.write(ROW + 4, TXT)
    c.write(ROW + 8, len(text) if count is None else count, 1)
    c.r[REG['a0']] = TXT
    c.r[REG['t7']] = ROW
    return run(c, REG, SYM['btl_name_lookup'])


class BattleTextClass(unittest.TestCase):
    def test_unregistered_letters_keep_fixed_width(self):
        for word in ('Yukino', 'Mark', 'Nemhain', 'Seimen Kongou', 'EMPTY'):
            self.assertEqual(classify(enc(word)), 0, word)

    def test_unregistered_punctuation_keeps_fixed_width(self):
        for word in ('Susano-o', "Yog-Sothoth Jr.", 'A/B', 'HP:SP', 'a.b'):
            self.assertEqual(classify(enc(word)), 0, word)

    def test_numbers_and_icons_stay_retail(self):
        self.assertEqual(classify(enc('Lv.12')), 0)
        self.assertEqual(classify(enc('120')), 0)
        self.assertEqual(classify(bytes([0xD9, 0xDA])), 0)      # gauge / icon cells
        self.assertEqual(classify(bytes([0x30, 0x31])), 0)      # kana cells
        self.assertEqual(classify(enc('Yukino9')), 0)

    def test_count_bounds_the_walk(self):
        self.assertEqual(classify(enc('Yukino'), count=3), 0)
        self.assertEqual(classify(enc('Yu9ino'), count=2), 0)
        self.assertEqual(classify(enc('Yukino'), count=0), 0)
        # FF ends the run: padding after it is not read.
        self.assertEqual(classify(enc('Yu') + b'\xFF' + enc('9'), count=8), 0)

    def test_lookup_refuses_unregistered_rows(self):
        self.assertEqual(lookup(enc('Yukino')), 0)
        self.assertEqual(lookup(enc('Lv.12')), 0)

    def test_registered_rows_are_answered_by_ownership(self):
        # A skill slot with its ownership bit clear stays retail even though
        # every glyph is text; setting the bit makes the same row VWF.
        c, REG = cpu()
        TXT, ROW = 0x80100000, 0x80101000
        text = enc('Agi')
        c.load(TXT, text)
        c.write(ROW, 0)
        c.write(ROW + 4, TXT)
        c.write(ROW + 8, len(text), 1)
        base = toolbelt.asm_equ('PERSONA_HDR_BUF')
        skill0 = toolbelt.asm_equ('SKILL_MENU_BUF')
        flags = toolbelt.asm_equ('SKILL_VWF_SLOTS_ADDR')
        slots = ((base, toolbelt.asm_equ('PERSONA_HDR_STRIDE'), 0),
                 (skill0, toolbelt.asm_equ('SKILL_MENU_STRIDE'),
                  toolbelt.asm_equ('SKILL_BIT_OFFSET')),
                 (skill0 + 6 * toolbelt.asm_equ('SKILL_MENU_STRIDE'),
                  toolbelt.asm_equ('SKILL_MENU_STRIDE'),
                  toolbelt.asm_equ('SKILL_BIT_OFFSET') + 6))
        for at, stride, bit in slots:
            c.load(at, text + bytes(stride - len(text)))
            c.write(flags, 0, 2)
            c.r[REG['a0']] = at
            c.r[REG['t7']] = ROW
            self.assertEqual(run(c, REG, SYM['btl_name_lookup']), 0, bit)
            c.write(flags, 1 << bit, 2)
            c.r[REG['a0']] = at
            c.r[REG['t7']] = ROW
            self.assertEqual(run(c, REG, SYM['btl_name_lookup']), 1, bit)
        # An item row is also answered by its producer byte, not the glyphs.
        item_base = toolbelt.asm_equ('BTLP_ITEM_FULL_ADDR')
        owner = SYM['btl_item_owner']
        c.load(item_base, text + bytes(10 - len(text)))
        c.write(toolbelt.asm_equ('BTLP_ITEM_IDS_ADDR'), 0, 2)
        c.write(owner, 0, 1)
        c.r[REG['a0']] = item_base
        c.r[REG['t7']] = ROW
        self.assertEqual(run(c, REG, SYM['btl_name_lookup']), 0)

    def test_battle_width_table_splits_text_from_retail_cells(self):
        widths = (ROOT / 'build' / 'btl_sf_width.bin').read_bytes()
        bits = (ROOT / 'build' / 'btl_text_bits.bin').read_bytes()
        for code in range(256):
            text = bool(bits[code >> 3] & (1 << (code & 7)))
            self.assertEqual(text, widths[code] != 0x08, hex(code))

    def test_art_mapper_keeps_non_text_cells_retail(self):
        """Owned rows remap only text cells; the `?` placeholder (0xd8) and
        numbers keep the original small-font cell."""
        from mips_cpu import CPU, REG
        btl = (ROOT / 'build' / 'BTLP.BIN').read_bytes()

        def mapped(code):
            c = CPU()
            c.load(0x80010000, SLPS)                # the selector is resident
            c.load(0x800643c4, btl)
            c.r[REG['at']] = 0                      # owned row
            c.r[REG['a0']] = code
            c.r[REG['sp']] = 0x801ff000
            c.r[REG['ra']] = 0x8000fff0
            c.start(SYM['btl_sf_art_code'])
            for _ in range(200):
                if c.pc == 0x8000fff0:
                    return c.r[REG['a0']]
                c.step()
            raise AssertionError('btl_sf_art_code did not return')

        self.assertEqual(mapped(0xD8), 0xD8)         # retail `?`
        self.assertEqual(mapped(0xC0), 0xC0)         # retail digit 0
        self.assertEqual(mapped(0xA6), 0x81)         # 'A' -> proportional run
        self.assertEqual(mapped(0x23), 0x52)         # 'a' -> proportional run

    def test_bridge_draws_unregistered_text_and_retails_numbers(self):
        """The installed flat bridge: an unregistered text row takes the packed
        advance, an unregistered number row keeps 8 px."""
        from mips_cpu import CPU, REG
        btl = (ROOT / 'build' / 'BTLP.BIN').read_bytes()
        widths = (ROOT / 'build' / 'sf_width.bin').read_bytes()
        SRC = 0x8002C400                     # outside every registered range
        DESC, SP = 0x800e0100, 0x801f0000
        def draw(codes):
            c = CPU()
            c.load(0x80010000, SLPS)
            c.load(0x800643c4, btl)
            c.load(SRC, bytes(codes))
            c.write(DESC, 0)
            c.write(DESC + 2, 0, 2)
            c.write(DESC + 4, SRC)
            c.write(DESC + 8, len(codes), 1)
            c.write(DESC + 9, 0x20, 1)
            c.write(DESC + 10, 12, 1)
            c.write(DESC + 11, 0, 1)
            for reg in range(1, 32):
                c.r[reg] = 0x23450000 + reg * 0x101
            c.r[REG['sp']] = SP
            c.r[REG['ra']] = 0x8000fff0
            origins = []
            pen = 0
            for i in range(len(codes)):
                c.r[REG['t3']] = DESC
                c.r[REG['t0']] = i
                c.r[REG['a3']] = SRC + i
                c.r[REG['v0']] = 100
                c.r[REG['a1']] = 200
                c.start(SYM['btl_sf_flat_entry'])
                for _ in range(300):
                    if c.pc == 0x80088f8c:
                        break
                    c.step()
                else:
                    raise AssertionError('flat bridge did not return')
                # The retail renderer keeps its glyph index, text object, OT
                # link masks and divide constant in t0-t6 across the hook: the
                # bridge must hand all of them back unchanged (clobbered link
                # masks sent the GPU DMA chain to address 0).
                for name in ('t0', 't1', 't2', 't3', 't4', 't5', 't6'):
                    want = {'t0': i, 't3': DESC}.get(name, 0x23450000 + REG[name] * 0x101)
                    self.assertEqual(c.r[REG[name]], want, (name, i))
                origin = c.r[REG['v0']] - 100
                origins.append((origin, pen, codes[i]))
                pen += widths[codes[i]] & 15
            return origins
        text = list(enc('Mark'))
        got = draw(text)
        pen = 0
        for i, (origin, _p, code) in enumerate(got):
            self.assertEqual(origin, i * 8, ('text', i))
            pen += widths[code] & 15
        nums = list(enc('12'))
        for i, (origin, _p, code) in enumerate(draw(nums)):
            self.assertEqual(origin, i * 8, ('number', i))


if __name__ == '__main__':
    unittest.main()
