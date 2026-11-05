"""Relocation pointers must be real LUI-derived addresses, not stale values."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import btlp


def words(*values):
    return struct.pack(f'<{len(values)}I', *values)


class RelocationProvenance(unittest.TestCase):
    zone = (0x800d0008, 0x800d0009)
    base = btlp.B

    def scan(self, *ins):
        return btlp._zone_refs(words(*ins), self.zone, tables=[]).get(self.zone[0], [])

    def test_true_address_pair_and_unrelated_load(self):
        # lui v0,800d; lbu v1,0(v0); addiu a0,v0,8
        self.assertEqual(self.scan(0x3c02800d, 0x90430000, 0x24440008),
                         [('addiu', self.base + 8)])

    def test_load_overwrites_lui_register_before_arithmetic(self):
        # The exact false-positive shape from BtlHighlightDraw: the lbu reads
        # x into v0, so the following addiu is coordinate arithmetic.
        self.assertEqual(self.scan(0x3c02800d, 0x9042ddd9, 0xa4a40012,
                                   0x24420008), [])

    def test_r3000_immediate_load_delay_reads_previous_lui_value(self):
        # The instruction immediately after LBU sees the old v0; the one
        # after that sees the loaded byte and must not be relocated.
        self.assertEqual(self.scan(0x3c02800d, 0x90420000, 0x24440008,
                                   0x24450008), [('addiu', self.base + 8)])

    def test_same_register_consecutive_load_cancels_pending_write(self):
        self.assertEqual(self.scan(0x3c02800d, 0x90420000, 0x90420001,
                                   0x24440008), [('addiu', self.base + 12)])

    def test_alu_overwrite_and_second_addiu_invalidate_provenance(self):
        self.assertEqual(self.scan(0x3c02800d, 0x24020001, 0x24420008), [])
        self.assertEqual(self.scan(0x3c02800d, 0x24420008, 0x24420008),
                         [('addiu', self.base + 4)])

    def test_branch_delay_slot_is_checked_but_not_the_next_block(self):
        # beq zero,zero,+1: its delay slot executes with the original LUI.
        self.assertEqual(self.scan(0x3c02800d, 0x10000001, 0x24440008,
                                   0x24450008), [('addiu', self.base + 8)])

    def test_address_lui_in_branch_delay_slot_fails_closed(self):
        # Branch target consumes the LUI in the delay slot; linear fallthrough
        # cannot prove every successor, so relocation must stop, not omit it.
        with self.assertRaises(SystemExit):
            self.scan(0x10000001, 0x3c02800d, 0x24440008)

    def test_direct_branch_into_reference_sequence_fails_closed(self):
        # A jump into ADDIU could bypass the apparent preceding LUI.
        with self.assertRaises(SystemExit):
            self.scan(0x10000002, 0, 0x3c02800d, 0x24440008)

    def test_coprocessor_branch_into_reference_sequence_fails_closed(self):
        # BC2T target points to the ADDIU, bypassing its nearby LUI.
        with self.assertRaises(SystemExit):
            self.scan(0x49010002, 0, 0x3c02800d, 0x24440008)

    def test_unknown_instruction_discards_pending_provenance(self):
        self.assertEqual(self.scan(0x3c02800d, 0xffffffff, 0x24440008), [])

    def test_retail_highlight_is_not_a_relocation_reference(self):
        stock = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        refs = btlp.evt_refs(stock)
        found = {(kind, where) for entries in refs.values() for kind, where in entries}
        self.assertNotIn(('addiu', 0x800769b8), found)
        self.assertNotIn(('addiu', 0x800769e4), found)
        for at in (0x800769b8, 0x800769e4):
            self.assertEqual(struct.unpack_from('<I', stock, at - self.base)[0], 0x24420008)

    def test_verifier_rejects_changed_highlight_code(self):
        stock = (ROOT / 'data/psx/BTLP.BIN').read_bytes()
        btlp.verify_highlight_ownership(stock, stock)
        bad = bytearray(stock)
        bad[0x800769b8 - self.base] ^= 1
        with self.assertRaises(SystemExit):
            btlp.verify_highlight_ownership(stock, bad)

    def test_built_highlight_is_retail_identical(self):
        built = ROOT / 'build/BTLP.BIN'
        if not built.exists():
            self.skipTest('requires assembled overlay')
        btlp.verify_highlight_ownership((ROOT / 'data/psx/BTLP.BIN').read_bytes(),
                                        built.read_bytes())


if __name__ == '__main__':
    unittest.main()
