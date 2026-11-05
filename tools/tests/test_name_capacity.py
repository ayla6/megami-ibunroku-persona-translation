"""Name storage bounds and real R3000 copy helpers, with temporary assembly only."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
sys.path.insert(0, str(ROOT / 'src/extraction_tools/matching'))
import items
import demons
import skills
import personas
import name_tails
import slps
import port_caps
from mips_cpu import CPU, REG


def wording(length):
    return ''.join(chr(ord('A') + i % 26) for i in range(length))


class Capacity(unittest.TestCase):
    def test_head_and_tail_preserve_every_glyph_to_capacity(self):
        for family, maximum in (('items', items.MAXLEN), ('demons', demons.MAXLEN)):
            for length in range(1, maximum + 1):
                text = wording(length)
                head, tail = name_tails.split(text, 10, maximum, family)
                self.assertEqual(head + tail, items.encode(text))
                self.assertLessEqual(len(head), 10)
            with self.assertRaises(SystemExit):
                name_tails.split(wording(maximum + 1), 10, maximum, family)

    def test_family_measure_uses_its_own_capacity_not_skill_capacity(self):
        # Item and demon names are bounded by the row they are drawn in -
        # ten 8-px cells - not by the shared 20-glyph scratch. A 14-glyph
        # name reaches the row exactly, 20 wide glyphs are refused for
        # width, and 20 narrow glyphs still fit.
        for family, module in (('items', items), ('demons', demons)):
            with self.subTest(family=family):
                self.assertEqual(module.ROW_PX, module.FIELD * 8)
                self.assertTrue(port_caps.measure(family, wording(14))[0])
                fits, amount, cap, unit, _reason = port_caps.measure(
                    family, wording(module.MAXLEN))
                self.assertFalse(fits)
                self.assertEqual((unit, cap), ('px', module.ROW_PX))
                self.assertEqual(amount, module.name_px(wording(module.MAXLEN)))
                self.assertGreater(amount, module.ROW_PX)
                self.assertTrue(port_caps.measure(family, 'I' * module.MAXLEN)[0])
        self.assertTrue(port_caps.measure('personas', wording(personas.MAXLEN))[0])
        self.assertFalse(port_caps.measure('personas', wording(personas.MAXLEN + 1))[0])
        self.assertEqual(name_tails.DEMON_MAXLEN, demons.MAXLEN)
        self.assertEqual(name_tails.ITEM_MAXLEN, items.MAXLEN)

    def test_skill_measure_is_pixel_width_not_a_character_count(self):
        # A short name is accepted; a 31-character name (the storage bound)
        # is refused only because it is 186px, not because of its length.
        self.assertTrue(port_caps.measure('skills', 'Agi')[0])
        fits, amount, cap, unit, _reason = port_caps.measure('skills', wording(skills.MAXLEN))
        self.assertFalse(fits)
        self.assertEqual((unit, cap), ('px', skills.NAME_PX))
        self.assertEqual(amount, skills.width_px(wording(skills.MAXLEN)))
        # 31 narrow glyphs stay inside the 120px column even at MAXLEN.
        narrow = 'I' * skills.MAXLEN
        self.assertLessEqual(skills.width_px(narrow), skills.NAME_PX)
        self.assertTrue(port_caps.measure('skills', narrow)[0])

    def test_glyph_encoder_does_not_impose_skill_copy_buffer(self):
        text = wording(demons.MAXLEN)
        self.assertEqual(skills.encode_glyphs(0, text), items.encode(text))
        with self.assertRaises(SystemExit):
            skills.encode(0, wording(skills.MAXLEN + 1))
        with self.assertRaises(SystemExit):
            skills.encode_glyphs(0, '\u2603')


class CanonicalBuilder(unittest.TestCase):
    def build_rows(self, lengths, item=False, unique=False):
        first = slps.IT_FIRST if item else slps.SK_FIRST
        stride = slps.IT_STRIDE if item else slps.SK_STRIDE
        rows = [{'id': str(i), 'pos': hex(first - slps.BASE + i * stride),
                 'en': (wording(length)[:-2] + chr(65 + i // 26) + chr(65 + i % 26)
                        if unique else wording(length))} for i, length in enumerate(lengths)]
        writes = {}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'tails.asm'
            with patch.object(slps.toolbelt, 'merged_rows', return_value=rows), \
                    patch.object(slps, 'OUT_TAILS', str(target)), \
                    patch.object(slps, 'Patch') as patcher, redirect_stdout(StringIO()):
                patcher.return_value.org.side_effect = lambda addr, data, *args: writes.update({addr: bytes(data)})
                patcher.return_value.write.return_value = len(rows)
                slps.build()
            tail_text = target.read_text()
        tail_bytes = bytes(int(token, 16) for line in tail_text.splitlines()
                           if line.strip().startswith('.byte ')
                           for token in line.split('.byte ', 1)[1].split(', '))
        return rows, writes, tail_bytes

    def test_variable_skill_tails_use_byte_offsets_not_entry_indexes(self):
        rows, writes, tails = self.build_rows([14, 15, 13])
        for row in rows[:2]:
            address = int(row['pos'], 16) + slps.BASE
            spare = writes[address + slps.SK_SPARE]
            self.assertEqual(spare[0], 0xFE)
            offset = spare[1]
            expected = items.encode(row['en'])[10:] + b'\xff'
            self.assertEqual(tails[offset:offset + len(expected)], expected)
            self.assertEqual(len(writes[address]), slps.SK_FIELD)
        address = int(rows[2]['pos'], 16) + slps.BASE
        self.assertEqual(writes[address + slps.SK_SPARE], items.encode(wording(13))[10:])

    def test_skill_ownership_follows_written_english_records(self):
        _, writes, _ = self.build_rows([14, 15, 13])
        self.assertEqual(writes[slps.toolbelt.asm_equ('SKILL_VWF_FLAGS_ADDR')],
                         skills.vwf_ownership([1, 2, 3]))
        # No name slot is owned before a producer writes one.
        self.assertEqual(writes[slps.toolbelt.asm_equ('SKILL_VWF_SLOTS_ADDR')],
                         b'\x00\x00')
        self.assertEqual(len(skills.vwf_ownership([1, skills.COUNT])), 31)
        with self.assertRaises(ValueError):
            skills.vwf_ownership([0])
        with self.assertRaises(ValueError):
            skills.vwf_ownership([skills.COUNT + 1])

    def test_full_skill_bank_fits_but_no_byte_can_overflow(self):
        cap = slps.toolbelt.asm_equ('SKILL_TAILS_SIZE')
        # A 14-glyph name uses five tail bytes including the terminator.
        self.assertEqual(cap % 5, 0)
        lengths = [14] * (cap // 5)
        _, _, tails = self.build_rows(lengths, unique=True)
        self.assertEqual(len(tails), cap)
        with self.assertRaises(SystemExit):
            self.build_rows(lengths + [14], unique=True)

    def test_canonical_encoders_enforce_physical_family_bounds(self):
        self.assertEqual(slps.encode_skill(wording(skills.MAXLEN)), skills.encode(0, wording(skills.MAXLEN)))
        self.assertEqual(len(slps.encode_items(wording(items.MAXLEN))), items.MAXLEN)
        with self.assertRaises(SystemExit):
            slps.encode_skill(wording(skills.MAXLEN + 1))
        with self.assertRaises(SystemExit):
            slps.encode_items(wording(items.MAXLEN + 1))

    def test_item_head_does_not_overwrite_following_stats(self):
        rows, writes, tails = self.build_rows([items.MAXLEN], item=True)
        self.assertEqual(tails, b'')
        address = int(rows[0]['pos'], 16) + slps.BASE
        self.assertEqual(writes, {address: items.encode(rows[0]['en'])[:slps.IT_FIELD],
                                  slps.toolbelt.asm_equ('SKILL_VWF_FLAGS_ADDR'): skills.vwf_ownership([]),
                                  slps.toolbelt.asm_equ('SKILL_VWF_SLOTS_ADDR'): b'\x00\x00'})
        head, tail = name_tails.split(rows[0]['en'], slps.IT_FIELD, items.MAXLEN, 'item')
        self.assertEqual(head + tail, items.encode(rows[0]['en']))


class AssembledNameCopies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        armips = ROOT / 'external_tools/armips/armips'
        if not armips.exists():
            armips = shutil.which('armips')
        if not armips:
            raise unittest.SkipTest('requires armips')
        cls.item_rows = [(1, wording(7)), (2, wording(10)),
                         (3, wording(11)), (5, wording(items.MAXLEN))]
        cls.demon_rows = [(1, wording(4)), (2, wording(16)),
                          (4, wording(10)), (6, wording(demons.MAXLEN))]
        generated = {}
        with patch.object(name_tails, 'item_rows', return_value=cls.item_rows), \
                patch.object(name_tails, 'demon_rows', return_value=cls.demon_rows), \
                patch.object(name_tails.toolbelt, 'write_asm',
                             side_effect=lambda path, tag, body: generated.update({Path(path).name: body})), \
                redirect_stdout(StringIO()):
            name_tails.build()
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / 'banks.asm').write_text(generated['name_tails_adv.asm'])
            (directory / 'helpers.asm').write_text(generated['item_names_adv.asm'])
            (directory / 'fixture.asm').write_text(
                '.psx\n.create "fixture.bin", 0x80100000\n'
                f'ITEM_NAME_BASE equ {items.FIRST - items.STRIDE:#x}\n'
                f'ITEM_NAME_FIELD equ {items.FIELD}\n'
                f'DEMON_NAME_BASE equ {demons.REC0:#x}\n'
                f'DEMON_NAME_FIELD equ {demons.FIELD}\n'
                'SF_NAME_SCRATCH equ 0x80110000\n'
                '.include "helpers.asm"\n.include "banks.asm"\n.close\n')
            result = subprocess.run([str(armips), 'fixture.asm', '-sym2', 'fixture.sym'],
                                    cwd=directory, capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.binary = (directory / 'fixture.bin').read_bytes()
            cls.symbols = {}
            for line in (directory / 'fixture.sym').read_text().splitlines():
                match = re.fullmatch(r'([0-9A-Fa-f]{8}) (\w+)', line)
                if match:
                    cls.symbols[match[2]] = int(match[1], 16)

    def test_full_name_copies_terminate_and_preserve_abi_and_record_stats(self):
        for family, rows, base, stride in (
                ('item', self.item_rows, items.FIRST - items.STRIDE, items.STRIDE),
                ('demon', self.demon_rows, demons.REC0, demons.STRIDE)):
            for ident, text in rows:
                with self.subTest(family=family, ident=ident, length=len(text)):
                    c = CPU()
                    c.load(0x80100000, self.binary)
                    for row_id, row_text in rows:
                        record = bytearray([0xA5] * stride)
                        head = items.encode(row_text)[:10]
                        record[:len(head)] = head
                        if len(head) < 10:
                            record[len(head)] = 255
                        c.load(base + row_id * stride, record)
                    before = bytes(c.mem[c.offset(base):c.offset(base) + (max(i for i, _ in rows) + 1) * stride])
                    destination, stop, stack = 0x80110000, 0x801F0000, 0x801FF000
                    c.load(destination - 1, bytes([0xA5]) * 23)
                    for reg in ('t0', 't1', 't2', 't3', 't4', 't5', 't6', 't7',
                                's0', 's1', 's2', 's3', 'a3'):
                        c.r[REG[reg]] = 0x12340000 + REG[reg]
                    saved = c.r.copy()
                    c.r[REG['a0']], c.r[REG['a1']] = destination, ident
                    c.r[REG['sp']], c.r[REG['ra']] = stack, stop
                    c.start(self.symbols[f'{family}_name_copy_adv'])
                    c.run(stop)
                    actual = bytes(c.mem[c.offset(destination):c.offset(destination) + len(text) + 1])
                    self.assertEqual(actual, items.encode(text) + b'\xff')
                    self.assertEqual(c.read(destination - 1, 1), 0xA5)
                    self.assertEqual(c.read(destination + len(text) + 1, 1), 0xA5)
                    self.assertEqual(c.r[REG['sp']], stack)
                    for reg in ('t0', 't1', 't2', 't3', 't4', 't5', 't6', 't7',
                                's0', 's1', 's2', 's3', 'a3'):
                        self.assertEqual(c.r[REG[reg]], saved[REG[reg]], reg)
                    after = bytes(c.mem[c.offset(base):c.offset(base) + len(before)])
                    self.assertEqual(after, before)


if __name__ == '__main__':
    unittest.main()
