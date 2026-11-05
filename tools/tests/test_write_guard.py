"""The write guard must fail closed on every overwrite class, and pass padding."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src' / 'injection_tools'))
import write_guard


class WriteGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'src' / 'asm' / 'common').mkdir(parents=True)
        (self.root / 'build').mkdir()
        self.addresses = self.root / 'src' / 'asm' / 'common' / 'addresses.inc'
        self.addresses.write_text('')
        self.input = self.root / 'build' / 'input.bin'
        self.input.write_bytes(bytes(16))
        self.output = self.root / 'build' / 'out.bin'
        self.source = self.root / 'src' / 'test.asm'

    def tearDown(self):
        self.tmp.cleanup()

    def listing(self, body, output=None, source=None):
        output = output or self.output
        source = source or self.source
        lines = [f'FFFFFFFF .open "{self.input}","{output}",0x80000000; {source} line 1']
        for number, statement in enumerate(body, 2):
            address = 0x80000000
            if statement.startswith('@'):
                address = int(statement[1:].split()[0], 0)
                statement = statement.split(None, 1)[1]
            lines.append(f'{address:08X} {statement} ; {source} line {number}')
        lines.append(f'80000000 .close ; {source} line {len(body) + 2}')
        path = self.root / 'listing.lst'
        path.write_text('\n'.join(lines) + '\n')
        return path

    def check(self, path):
        problems, failures, _stats = write_guard.check_listing(path, self.root)
        return problems + failures

    def write_output(self, data, pad_to=16):
        self.output.write_bytes(bytes(data).ljust(pad_to, b'\0'))

    def test_valid_listing_passes(self):
        data = bytearray(16)
        data[4:6] = b'\x11\x22'
        self.write_output(data)
        path = self.listing(['@0x80000004 .byte 0x11,0x22'])
        self.assertEqual(self.check(path), [])

    def test_duplicate_output_fails(self):
        data = bytearray(16)
        data[4:6] = b'\x11\x22'
        self.write_output(data)
        path = self.listing(['@0x80000004 .byte 0x11,0x22',
                             '.close',
                             f'.open "{self.input}","{self.output}",0x80000000',
                             '@0x80000004 .byte 0x11,0x22'])
        self.assertTrue(any('opened again' in item for item in self.check(path)))

    def test_output_outside_build_fails(self):
        outside = self.root / 'dist' / 'out.bin'
        outside.parent.mkdir()
        outside.write_bytes(bytes(16))
        path = self.listing([], output=outside)
        self.assertTrue(any('outside' in item for item in self.check(path)))

    def test_growth_past_retail_size_fails_without_limit(self):
        data = bytearray(20)
        data[16:20] = b'\x01\x02\x03\x04'
        self.write_output(data, pad_to=20)
        path = self.listing(['@0x80000010 .word 0x04030201'])
        self.assertTrue(any('past retail file size' in item for item in self.check(path)))

    def test_declared_limit_allows_growth(self):
        self.addresses.write_text(
            'X_OUTPUT equ "../../build/out.bin"\n'
            'X_IMAGE_LIMIT equ 0x80000020\n')
        data = bytearray(20)
        data[16:20] = b'\x01\x02\x03\x04'
        self.write_output(data, pad_to=20)
        path = self.listing(['@0x80000010 .word 0x04030201'])
        self.assertEqual(self.check(path), [])

    def test_declared_limit_is_enforced(self):
        self.addresses.write_text(
            'X_OUTPUT equ "../../build/out.bin"\n'
            'X_IMAGE_LIMIT equ 0x80000010\n')
        data = bytearray(20)
        data[16:20] = b'\x01\x02\x03\x04'
        self.write_output(data, pad_to=20)
        path = self.listing(['@0x80000010 .word 0x04030201'])
        self.assertTrue(any('past' in item and 'IMAGE_LIMIT' in item
                            for item in self.check(path)))

    def test_later_write_over_nonzero_write_fails(self):
        self.write_output(b'\x03\x04' + bytes(14))
        path = self.listing(['@0x80000000 .byte 0x01,0x02',
                             '@0x80000000 .byte 0x03,0x04'])
        self.assertTrue(any('bytes are lost' in item for item in self.check(path)))

    def test_padding_then_content_passes(self):
        self.write_output(b'\x11\x22' + bytes(14))
        path = self.listing(['@0x80000000 .fill 16,0',
                             '@0x80000000 .byte 0x11,0x22'])
        self.assertEqual(self.check(path), [])

    def test_shared_suffix_passes(self):
        self.write_output(b'\x01\x02\x03\x04' + bytes(12))
        path = self.listing(['@0x80000000 .byte 0x01,0x02,0x03,0x04',
                             '@0x80000002 .byte 0x03,0x04,0x05,0x06'])
        # the second statement starts inside the first but repeats its bytes
        self.assertEqual(self.check(path), [])

    def test_unaccounted_changed_byte_fails(self):
        data = bytearray(16)
        data[4] = 0x11
        self.write_output(data)
        path = self.listing(['@0x80000008 .byte 0x22'])
        self.assertTrue(any('outside the write log' in item for item in self.check(path)))

    def test_unaccounted_change_in_empty_section_fails(self):
        self.write_output(b'\x01' + bytes(15))
        self.assertTrue(any('outside the write log' in item
                            for item in self.check(self.listing([]))))

    def test_zero_filled_growth_past_retail_fails(self):
        self.write_output(bytes(32), pad_to=32)
        self.assertTrue(any('past retail file size' in item
                            for item in self.check(self.listing(['.byte 0']))))

    def test_write_below_base_fails(self):
        data = bytearray(16)
        self.write_output(data)
        path = self.listing(['@0x7FFFFFFC .word 0'])
        self.assertTrue(any('below' in item for item in self.check(path)))

    def test_exe_header_size_is_checked(self):
        exe = bytearray(0x800 + 16)
        exe[:8] = b'PS-X EXE'
        exe[0x1C:0x20] = (16).to_bytes(4, 'little')
        self.input.write_bytes(exe)
        data = bytearray(exe[:0x804])
        data[4] = 0x11
        data[0x800] = 0x22
        data[0x1C:0x20] = (20).to_bytes(4, 'little')
        self.output.write_bytes(data)
        path = self.listing(['@0x80000000 .byte 0x22'])
        failures = self.check(path)
        self.assertTrue(any('t_size' in item for item in failures))


if __name__ == '__main__':
    unittest.main()
