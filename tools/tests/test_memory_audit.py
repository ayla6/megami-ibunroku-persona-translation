"""Allocation reports preserve exact intervals and label uncertainty."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import memory_audit
import write_guard


def write(start, size, path='patch.asm', zero=False, line=1):
    return write_guard.Write('BTLP.BIN', start, size, zero, path, line, '.byte 0', line)


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


if __name__ == '__main__':
    unittest.main()
