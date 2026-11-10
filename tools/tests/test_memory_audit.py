"""Allocation reports preserve exact intervals and label uncertainty."""
from pathlib import Path
import csv
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import memory_audit
import write_guard


def write(start, size, path='patch.asm', zero=False, line=1):
    return write_guard.Write('BTLP.BIN', start, size, zero, path, line, '.byte 0', line)


def store_sequence(base):
    """lui/addiu base, addu index, sw: one exact indexed store at `base`."""
    return struct.pack('<4I',
                       (0x0F << 26) | (8 << 16) | (base >> 16),
                       (0x09 << 26) | (8 << 21) | (8 << 16) | (base & 0xFFFF),
                       (8 << 21) | (4 << 16) | (8 << 11) | 0x21,
                       (0x2B << 26) | (8 << 21) | (2 << 16))


class MemoryAudit(unittest.TestCase):
    def test_merges_only_same_origin_and_kind_without_bridging_gaps(self):
        section = write_guard.Section('BTLP.BIN', 'retail', 0x80000000, '', 1, False)
        section.writes = [write(100, 4), write(104, 2), write(110, 2),
                          write(102, 1, 'other.asm'), write(100, 8, zero=True)]
        spans = memory_audit.allocations(section)
        self.assertEqual([(x['start'], x['end'], x['path'], x['padding']) for x in spans],
                         [(100, 106, 'patch.asm', False), (100, 108, 'patch.asm', True),
                          (102, 103, 'other.asm', False), (110, 112, 'patch.asm', False)])

    def test_retail_zeros_do_not_imply_safety(self):
        self.assertEqual(memory_audit.retail_content(0x1000, 0x1004, 0x1000, bytes(8)), 'all-zero')
        self.assertEqual(memory_audit.retail_content(0x1004, 0x1009, 0x1000, bytes(8)), 'outside-retail-image')

    def test_nearby_bases_are_leads_not_assumed_array_extents(self):
        spans = [{'start': 0x1200, 'end': 0x1210, 'path': 'x', 'padding': False}]
        refs = [(1, 0x1204, 'lw', 2), (2, 0x11f0, 'sw', 3), (3, 0x1000, 'sw', 3)]
        hits = memory_audit.indexed_hits(spans, refs, 0x20)
        self.assertEqual([(h[0], h[4]) for h in hits],
                         [(2, 'base-before-write'), (1, 'base-inside-write')])
        with self.assertRaises(ValueError):
            memory_audit.indexed_hits(spans, refs, -1)


class MultiImageAudit(unittest.TestCase):
    def test_each_image_gets_its_own_reports_and_a_summary_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = 0x800643C4
            retail = store_sequence(base)
            source = root / 'retail.bin'
            source.write_bytes(retail)
            output = root / 'build' / 'SYN.BIN'
            output.parent.mkdir()
            section = write_guard.Section(str(output), str(source), base,
                                          'src/main.asm', 1, False)
            section.writes = [write(base, 0x10)]

            summary = memory_audit.audit_section(section, root / 'audit')

            self.assertEqual(summary['image'], 'SYN.BIN')
            self.assertEqual((summary['ranges'], summary['references']), (1, 1))
            self.assertEqual((summary['exact'], summary['near_stores'],
                              summary['near_loads']), (1, 0, 0))
            report = root / 'audit' / 'SYN.BIN'
            with (report / 'allocations.tsv').open(encoding='utf-8', newline='') as f:
                rows = list(csv.DictReader(f, delimiter='\t'))
            self.assertEqual(rows[0]['start'], hex(base))
            with (report / 'indexed-leads.tsv').open(encoding='utf-8', newline='') as f:
                leads = list(csv.DictReader(f, delimiter='\t'))
            self.assertEqual(leads[0]['relation'], 'base-inside-write')
            self.assertEqual(leads[0]['access'], 'sw')

    def test_all_skips_images_without_assembled_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'retail.bin'
            source.write_bytes(bytes(16))
            listing = root / 'listing.lst'
            listing.write_text(
                f'FFFFFFFF .open "{source}","{root / "build" / "SYN.BIN"}",'
                f'0x800643C4; /src/main.asm line 1\n'
                f'800643C4 .word 0x12345678; /src/x.asm line 2\n'
                f'FFFFFFFF .close; /src/main.asm line 3\n'
                f'FFFFFFFF .open "{source}","{root / "build" / "EMPTY.BIN"}",'
                f'0x800643C4; /src/main.asm line 4\n'
                f'FFFFFFFF .close; /src/main.asm line 5\n',
                encoding='utf-8')

            summaries = memory_audit.audit_images(listing, None, root / 'audit')

            self.assertEqual([row['image'] for row in summaries], ['SYN.BIN'])
            with (root / 'audit' / 'summary.tsv').open(encoding='utf-8', newline='') as f:
                rows = list(csv.DictReader(f, delimiter='\t'))
            self.assertEqual([row['image'] for row in rows], ['SYN.BIN'])

    def test_an_image_without_retail_input_is_reported_not_scanned(self):
        section = write_guard.Section('build/FRESH.BIN', None, 0x80010000,
                                      'src/main.asm', 1, True)
        section.writes = [write(0x80010000, 4)]
        summary = memory_audit.audit_section(section, Path('/nonexistent'))
        self.assertEqual(summary['ranges'], 0)
        self.assertEqual(summary['note'], 'no retail input to scan')


if __name__ == '__main__':
    unittest.main()
