"""The write guard must fail closed on every overwrite class, and pass padding."""
from pathlib import Path
from tempfile import TemporaryDirectory
import struct
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

    def test_runtime_map_rejects_any_overlapping_write(self):
        directory = self.root / 'src' / 'injection_tools'
        directory.mkdir(parents=True)
        manifest = directory / 'runtime-memory-map.tsv'
        manifest.write_text('image\tspace\tstart\tend\towner\tprotection\tevidence\n'
                            'out.bin\tcpu-ram\t0x80000005\t0x80000008\t'
                            'live array\tno-assembly-writes\ttest fixture\n')
        data = bytearray(16)
        data[4:6] = b'\x11\x22'
        self.write_output(data)
        path = self.listing(['@0x80000004 .byte 0x11,0x22'])
        self.assertTrue(any('overlaps live live array' in item for item in self.check(path)))
        data[5] = 0
        self.write_output(data)
        path = self.listing(['@0x80000004 .byte 0x11'])
        self.assertEqual(self.check(path), [])

    def test_invalid_runtime_map_fails_closed(self):
        directory = self.root / 'src' / 'injection_tools'
        directory.mkdir(parents=True)
        (directory / 'runtime-memory-map.tsv').write_text('broken\n')
        self.write_output(bytes(16))
        self.assertTrue(any('invalid runtime memory map' in item
                            for item in self.check(self.listing([]))))

    def test_relative_listing_paths_use_the_given_root(self):
        # armips writes the source's relative paths (../../build/...) into
        # the listing. They belong to the tree that was assembled, not to
        # this repo, so an isolated assembly can be guarded in place.
        data = bytearray(16)
        data[4:6] = b'\x11\x22'
        self.write_output(data)
        path = self.root / 'relative.lst'
        path.write_text(
            'FFFFFFFF .open "../../build/input.bin","../../build/out.bin",'
            '0x80000000; src line 1\n'
            '80000004 .byte 0x11,0x22 ; src line 2\n'
            '80000000 .close ; src line 3\n')
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

    # --- the retail-move audit -------------------------------------------
    # The status screen's misplaced member markers were a half-done move:
    # adv/bar.asm copied g_fm_mark_pos elsewhere, rebased two readers, and
    # left the other marker readers on the original address while the bar
    # data overwrote its tail.

    TABLE = bytes.fromhex(
        '00000000 10009c00 70009c00 1000c000 7000c000 d000c000')

    @staticmethod
    def reader(target):
        """lui/addiu a table base, index it, load the halfword."""
        return struct.pack('<4I', 0x3C018000, 0x24210000 | target,
                           0x00220821, 0x84270000)

    def move_fixture(self):
        retail = bytearray(0x800)
        retail[0x40:0x40 + len(self.TABLE)] = self.TABLE
        retail[0x100:0x110] = self.reader(0x40)
        retail[0x120:0x130] = self.reader(0x40)
        retail[0x300:0x304] = struct.pack('<I', 0x80000040)
        return retail

    def assembled(self, original, built):
        """A listing that names every byte that differs, as armips would."""
        self.input.write_bytes(bytes(original))
        self.output.write_bytes(bytes(built))
        body, i = [], 0
        while i < len(built):
            if i < len(original) and original[i] == built[i]:
                i += 1
                continue
            j = i
            while j < len(built) and (
                    j >= len(original) or original[j] != built[j]):
                j += 1
            body.append(f'@{0x80000000 + i:#x} .byte ' +
                        ','.join(str(byte) for byte in built[i:j]))
            i = j
        return self.listing(body)

    def test_half_done_move_fails(self):
        retail = self.move_fixture()
        built = bytearray(retail)
        built[0x400:0x400 + len(self.TABLE)] = retail[0x40:0x40 + len(self.TABLE)]
        built[0x4C:0x58] = bytes(12)                 # the old home's tail
        built[0x120:0x130] = self.reader(0x400)      # one reader retargeted
        failures = self.check(self.assembled(retail, built))
        self.assertTrue(any('moved 0x80000040..' in item
                            for item in failures), failures)
        self.assertTrue(any('0x80000100' in item for item in failures), failures)
        self.assertTrue(any('0x80000300' in item for item in failures), failures)

    def test_complete_move_passes(self):
        retail = self.move_fixture()
        built = bytearray(retail)
        built[0x400:0x400 + len(self.TABLE)] = retail[0x40:0x40 + len(self.TABLE)]
        built[0x4C:0x58] = bytes(12)
        built[0x100:0x110] = self.reader(0x400)
        built[0x120:0x130] = self.reader(0x400)
        built[0x300:0x304] = struct.pack('<I', 0x80000400)
        self.assertEqual(self.check(self.assembled(retail, built)), [])

    def test_in_place_rewrite_is_not_a_move(self):
        # translations replace retail text/tables where they stand: every
        # reader keeps naming the same address, so nothing is half-moved
        retail = self.move_fixture()
        built = bytearray(retail)
        built[0x4C:0x58] = bytes(12)
        self.assertEqual(self.check(self.assembled(retail, built)), [])

    def test_zero_padding_copy_is_not_a_move(self):
        # a vector of zeros in retail is common padding, not a table: a
        # consistent-looking "move" of it must not be reported even when one
        # of its readers was retargeted and the padding was overwritten
        retail = bytearray(0x800)
        retail[0x140:0x150] = self.reader(0x600)
        retail[0x160:0x170] = self.reader(0x600)
        built = bytearray(retail)
        built[0x500:0x600] = retail[0x600:0x700]     # identical zeros
        built[0x140:0x150] = self.reader(0x500)      # one reader retargeted
        built[0x600:0x608] = b'\x01\x02\x03\x04\x05\x06\x07\x08'
        self.assertEqual(self.check(self.assembled(retail, built)), [])


if __name__ == '__main__':
    unittest.main()
