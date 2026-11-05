"""Execute the assembled battle reader, not a replacement Python unpacker.

Run after assembly:
  python -m unittest discover -s tools/tests -p test_btlp_unpacker_ownership.py -v

The CPU models R3000 load and branch delays. No GPU/BIOS interception is
needed: both reader callees (queue insertion and text reset) execute for real.
"""
from pathlib import Path
import re
import struct
import sys
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
BASE = 0x800643C4
READER, HOOK, READER_END = 0x8007D078, 0x8007D0B4, 0x8007D0D8
CRASH_INPUT = 0x800D06A6
ZONE_START, ZONE_END = 0x800CFA14, 0x800D0AE4
BUFFER, BUFFER_SIZE = 0x80057400, 1024
READ_PTR, TEXT_STATE = 0x800EB898, 0x800EB892
QUEUE_COUNT = 0x800C8744
STACK, RETURN = 0x801CF000, 0x801F0000
SAVED = ('s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7', 'gp', 'fp')
PAIR_CODES = tuple(range(1, 0x88)) + tuple(range(0xEA, 0xFF))


def region(cpu, address, size):
    offset = cpu.offset(address, size)
    return bytes(cpu.mem[offset:offset + size])


def decode_message(cpu, address, pairs):
    """Independent bounded format oracle, including resident spill markers."""
    if cpu.read(address, 2) == 0x00FF:
        address = (cpu.read(address + 2, 2) << 16) | cpu.read(address + 4, 2)
    indices = dict(zip(PAIR_CODES, range(len(PAIR_CODES))))
    out = bytearray()

    def expand(symbol, depth=0):
        if depth > 28:
            raise AssertionError('recursive/corrupt pair table')
        if symbol in indices:
            index = indices[symbol]
            if index >= len(pairs):
                raise AssertionError('missing pair')
            left, right = pairs[index]
            return expand(left, depth + 1) + expand(right, depth + 1)
        return bytes([symbol])

    for _ in range(BUFFER_SIZE):
        symbol = cpu.read(address, 1)
        address += 1
        if symbol == 0xFF:
            code = cpu.read(address, 1)
            address += 1
            out.extend((symbol, code))
            if code in (0xF5, 0xEF):
                return bytes(out)
        elif symbol == 0:
            out.append(cpu.read(address, 1))
            address += 1
        else:
            out.extend(expand(symbol))
        if len(out) > BUFFER_SIZE:
            raise AssertionError('unpacked text exceeds runtime buffer')
    raise AssertionError('unterminated packed text')


class BuiltBattleUnpacker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ('BTLP.BIN', 'SLPS_005.00', 'persona.sym', 'btlevt_pairs.asm')
        paths = [ROOT / 'build' / name for name in names]
        if not all(path.exists() for path in paths):
            raise unittest.SkipTest('requires assembled battle files in build/')
        cls.btlp, cls.slps = (path.read_bytes() for path in paths[:2])
        cls.sym = {match[2]: int(match[1], 16)
                   for line in paths[2].read_text().splitlines()
                   if (match := re.fullmatch(r'([0-9A-Fa-f]{8}) (\w+)', line))}
        for name in ('btl_unpack', 'btlevt_pairs'):
            if name not in cls.sym:
                raise AssertionError('missing assembled symbol: ' + name)
        cls.pairs = [tuple(int(value, 16) for value in match.groups())
                     for line in paths[3].read_text().splitlines()
                     if (match := re.fullmatch(r'\s*\.byte (0x[0-9a-fA-F]+), (0x[0-9a-fA-F]+)', line))]
        if not cls.pairs:
            raise AssertionError('no generated story-battle pairs')

    def machine(self):
        cpu = CPU()
        base, size = struct.unpack_from('<II', self.slps, 0x18)
        cpu.load(base, self.slps[0x800:0x800 + size])
        cpu.load(BASE, self.btlp)
        cpu.write(QUEUE_COUNT, 0)
        cpu.load(BUFFER - 16, bytes([0xA5]) * (BUFFER_SIZE + 32))
        for reg in SAVED:
            cpu.r[REG[reg]] = 0x13570000 + REG[reg] * 0x101
        cpu.r[REG['sp']], cpu.r[REG['ra']] = STACK, RETURN
        return cpu

    def execute(self, cpu, address, expected, packed=True):
        saved = {reg: cpu.r[REG[reg]] for reg in SAVED}
        original = region(cpu, address, 6)
        cpu.r[REG['a0']] = address
        cpu.start(READER)
        cpu.run(RETURN, limit=100000)
        self.assertEqual(cpu.r[REG['sp']], STACK)
        self.assertEqual(cpu.r[REG['v0']], 1)
        for reg, value in saved.items():
            self.assertEqual(cpu.r[REG[reg]], value, reg)
        self.assertEqual(cpu.read(READ_PTR), BUFFER if packed else address)
        self.assertEqual(cpu.read(TEXT_STATE, 2), 1)
        self.assertEqual(cpu.read(QUEUE_COUNT), 1, 'retail reader queue call did not complete')
        self.assertEqual(region(cpu, BUFFER - 16, 16), bytes([0xA5]) * 16)
        self.assertEqual(region(cpu, BUFFER + BUFFER_SIZE, 16), bytes([0xA5]) * 16)
        self.assertEqual(region(cpu, address, 6), original, 'source text was overwritten')
        if packed:
            self.assertEqual(region(cpu, BUFFER, len(expected)), expected)
            self.assertEqual(region(cpu, BUFFER + len(expected), BUFFER_SIZE - len(expected)),
                             bytes([0xA5]) * (BUFFER_SIZE - len(expected)))
        else:
            self.assertEqual(region(cpu, BUFFER, BUFFER_SIZE), bytes([0xA5]) * BUFFER_SIZE)

    def test_built_hook_and_reader_preserve_retail_control_flow(self):
        cpu = self.machine()
        entry = self.sym['btl_unpack']
        self.assertEqual(cpu.read(HOOK), 0x0C000000 | ((entry >> 2) & 0x03FFFFFF))
        self.assertEqual(cpu.read(HOOK + 4), 0x02002021, 'hook delay must move a0,s0')
        self.assertEqual(cpu.read(self.sym['btl_unpack_window']), 0x27BDFFD8,
                         'unpacker prologue was overwritten')
        retail = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        self.assertEqual(region(cpu, READER, HOOK - READER), retail[READER-BASE:HOOK-BASE])
        self.assertEqual(region(cpu, HOOK + 8, READER_END - HOOK - 8),
                         retail[HOOK+8-BASE:READER_END-BASE])

    def test_built_pair_table_matches_generated_bytes(self):
        cpu = self.machine()
        expected = bytes(value for pair in self.pairs for value in pair)
        self.assertEqual(region(cpu, self.sym['btlevt_pairs'], len(expected)), expected)
        self.assertLessEqual(self.sym['btlevt_pairs'] + len(expected), ZONE_END)

    def test_second_window_decodes_all_translated_status_messages(self):
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import btlp
        import etext
        import toolbelt
        stock = btlp.data()
        rows = {row['pos']: row for row in toolbelt.merged_rows('BTLP')}
        refs = btlp._zone_refs(stock, btlp.NEG_ZONE)
        second_buffer = btlp._equ('BTL_SECOND_BUF_ADDR')
        size = toolbelt.asm_equ('BTL_SECOND_BUF_SIZE')
        for original, _ in btlp.neg_strings(stock):
            # The status table is consumed by the second text window.
            words = [where for kind, where in refs[original]
                     if kind == 'word' and 0x800CD530 <= where < 0x800CD594]
            text = (rows.get(hex(original - BASE), {}).get('en') or '').strip()
            if not words or not text:
                continue
            with self.subTest(original=hex(original)):
                cpu = self.machine()
                expected = etext.encode(btlp.laid(text), end=btlp.END)
                primary_cpu = self.machine()
                address = primary_cpu.read(words[0])
                self.execute(primary_cpu, address, expected,
                             packed=primary_cpu.read(address, 1) == 0)
                cpu.load(second_buffer - 16, b'\xa5' * (size + 32))
                cpu.write(READ_PTR, BUFFER + 7)
                primary = region(cpu, BUFFER, BUFFER_SIZE)
                cpu.r[REG['s0']] = cpu.read(words[0])
                live = {'a0': 0x800EBB04, 'v0': 0x81, 'v1': 0xFFFFFFFE}
                for name, value in live.items():
                    cpu.r[REG[name]] = value
                # Execute the actual patched writer and its return delay slot.
                cpu.start(0x8007D654)
                cpu.run(0x8007D65C, limit=100000)
                pointer = cpu.read(0x800EBB0C)
                self.assertEqual(region(cpu, pointer, len(expected)), expected)
                if cpu.read(cpu.r[REG['s0']], 1) == 0:
                    self.assertEqual(pointer, second_buffer)
                    self.assertEqual(region(cpu, second_buffer + len(expected), size - len(expected) + 16),
                                     b'\xa5' * (size - len(expected) + 16))
                else:
                    self.assertEqual(pointer, cpu.r[REG['s0']])
                    self.assertEqual(region(cpu, second_buffer, size + 16), b'\xa5' * (size + 16))
                self.assertEqual(region(cpu, second_buffer - 16, 16), b'\xa5' * 16)
                self.assertEqual(cpu.read(READ_PTR), BUFFER + 7)
                self.assertEqual(region(cpu, BUFFER, BUFFER_SIZE), primary)
                self.assertEqual(cpu.r[REG['sp']], STACK)
                for name, value in live.items():
                    self.assertEqual(cpu.r[REG[name]], value, name)

    def test_live_crash_input_returns_through_actual_reader(self):
        cpu = self.machine()
        expected = decode_message(cpu, CRASH_INPUT, self.pairs)
        self.assertGreater(len(expected), 2)
        self.execute(cpu, CRASH_INPUT, expected)

    def test_recursive_low_and_high_pairs_escapes_and_control_codes(self):
        nested = next(code for code, pair in zip(PAIR_CODES, self.pairs)
                      if any(value in PAIR_CODES for value in pair))
        high = next(code for code in PAIR_CODES[0x87:] if PAIR_CODES.index(code) < len(self.pairs))
        for end in (0xF5, 0xEF):
            with self.subTest(end=hex(end)):
                cpu = self.machine()
                data = bytes([nested, high, 0, 0x87, 0, 0x26, 0xFF, 0xF6, 0x88, 0xFF, end])
                cpu.load(ZONE_START, data)
                self.execute(cpu, ZONE_START, decode_message(cpu, ZONE_START, self.pairs))

    def test_unpacked_string_above_zone_keeps_pointer_and_buffer(self):
        cpu = self.machine()
        address = 0x80130000
        data = bytes([0x88, 0x89, 0xFF, 0xF5, 0, 0])
        cpu.load(address, data)
        self.execute(cpu, address, data, packed=False)

    def test_every_original_message_reference_reads_its_own_wording(self):
        # Use the retail reference graph, not the relocated build's addresses:
        # otherwise a forgotten untranslated row disappears from the census.
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import btlp
        import etext
        import toolbelt
        retail = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        references = btlp.evt_refs(retail)
        rows = {row['pos']: row for row in toolbelt.merged_rows('BTLP')}
        seen = gaps = 0
        for start, end in btlp.evt_messages(retail):
            row = rows.get(hex(start - BASE), {})
            wording = btlp.laid(row.get('en', '').strip())
            translated = etext.has_text(wording)
            expected = (etext.encode(wording, end=b'\xff\xf5') if translated
                        else btlp.evt_original_layout(retail[start-BASE:end-BASE]))
            for kind, where in references.get(start, []):
                seen += 1
                gaps += not translated
                with self.subTest(original=hex(start), reference=hex(where),
                                  translated=translated):
                    cpu = self.machine()
                    if kind == 'word':
                        address = cpu.read(where)
                    else:
                        # The patch owns only the addiu's low halfword. The
                        # original LUI high half stays unchanged (signed low).
                        low = cpu.read(where, 2, sign=True)
                        address = (((start + 0x8000) & 0xFFFF0000) + low) & 0xFFFFFFFF
                    self.execute(cpu, address, expected)
        self.assertGreater(seen, 0, 'no retail references exercised')
        # The provenance scanner excludes overwritten registers and control-flow
        # boundaries; only references to a real message START are message pointers.
        self.assertEqual(seen, sum(len(references.get(start, []))
                                   for start, _end in btlp.evt_messages(retail)))
        # Keep the gap count diagnostic rather than requiring untranslated
        # text forever: completing the translation must not break this test.
        self.reference_counts = (seen, gaps)

    def test_direct_story_spill_ranges_decode_at_both_ends(self):
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import btlp
        data = bytes([0x88, 0x89, 0xFF, 0xF5, 0, 0])
        for start, end in btlp.EVT_SPILL:
            for address in (start, end - len(data)):
                with self.subTest(range=(hex(start), hex(end)), address=hex(address)):
                    cpu = self.machine()
                    cpu.load(address, data)
                    self.execute(cpu, address, data[:4])

    def test_story_spill_exclusive_ends_and_negotiation_passthrough(self):
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import btlp
        # At an exclusive story-bank end the bytes are NOT story packed;
        # negotiation strings without a zero marker also remain untouched.
        addresses = [end for _start, end in btlp.EVT_SPILL]
        addresses.extend((btlp.NEG_ZONE[0], btlp.NEG_ZONE[0] - 8))
        data = bytes([0x88, 0x89, 0xFF, 0xF5, 0, 0])
        for address in addresses:
            with self.subTest(address=hex(address)):
                cpu = self.machine()
                cpu.load(address, data)
                self.execute(cpu, address, data, packed=False)

    def test_reserved_instruction_corruption_is_rejected_by_cpu(self):
        cpu = self.machine()
        cpu.write(self.sym['btl_unpack'], 0xFFFFFFFF)
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            self.execute(cpu, CRASH_INPUT, b'')

    def test_zeroed_unpacker_reproduces_nonreturn_instead_of_false_success(self):
        cpu = self.machine()
        entry = self.sym['btl_unpack']
        cpu.load(entry, bytes(ZONE_END - entry))
        cpu.r[REG['a0']] = CRASH_INPUT
        cpu.start(READER)
        with self.assertRaisesRegex((AssertionError, ValueError),
                                    'unsupported|instruction limit|RAM access'):
            cpu.run(RETURN, limit=100000)


if __name__ == '__main__':
    unittest.main()
