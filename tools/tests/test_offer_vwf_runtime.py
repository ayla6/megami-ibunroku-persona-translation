"""Execute assembled offer VWF hooks and compare non-offer retail behavior."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/injection_tools'))
import btlmsg
import btlui
import personality_source
import smallfont_vwf
import name_tails
import items
import etext
import toolbelt

BASE = 0x800643c4
BANK = 0x800c87ec
RETURN = 0x801f0000


class OfferVwf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [ROOT / 'build' / n for n in
                 ('BTLP.BIN', 'SLPS_005.00', 'sf_width.bin', 'btl_sf_width.bin')]
        if not all(p.exists() for p in paths):
            raise unittest.SkipTest('requires assembled overlays')
        cls.battle, cls.resident, cls.widths, cls.battle_widths = \
            [p.read_bytes() for p in paths]
        cls.retail = btlmsg.data()
        cls.names = personality_source.read()
        cls.demon_rows = name_tails.demon_rows()
        if not cls.names or not cls.demon_rows:
            raise AssertionError('source-derived offer names must not be empty')
        cls.codes = [bytes(smallfont_vwf.char_code(c) for c in name) for name in cls.names]

    def machine(self, retail=False):
        c = CPU()
        c.load(BASE, self.retail if retail else self.battle)
        address, size = struct.unpack_from('<II', self.resident, 0x18)
        c.load(address, self.resident[0x800:0x800 + size])
        c.r[REG['sp']] = 0x801e0000
        c.r[REG['ra']] = RETURN
        return c

    def test_every_source_glyph_uses_its_actual_advance_and_bearing(self):
        c = self.machine()
        for i, codes in enumerate(self.codes):
            pointer = c.read(0x800cdd50 + i * 4)
            self.assertEqual(bytes(c.read(pointer + k, 1) for k in range(len(codes) + 1)), codes + b'\xff')
            pen = 0
            for k, code in enumerate(codes):
                packed = self.widths[code]
                c.r[REG['s1']], c.r[REG['s4']] = pointer + k, pen
                c.r[REG['v1']], c.r[REG['a3']] = 123, 456
                c.write(0x801e0028, 0xdeadbeef)
                c.start(0x80078574)
                c.run(0x8007857c, limit=1000)
                self.assertEqual(c.r[REG['v0']], (pen - (packed >> 4)) & 0xffffffff)
                self.assertEqual((c.r[REG['v1']], c.r[REG['a3']]), (123, 456))
                self.assertEqual(c.read(0x801e0028), 0)
                # The actual tail hook must continue/stop on the NEXT byte,
                # preserve the linked-list stores and advance by source metrics.
                c.r[REG['s1']] = pointer + k + 1
                c.r[REG['s4']] = pen
                self.tail(c)
                self.assertEqual(c.r[REG['s4']], pen + (packed & 15))
                self.assertEqual(c.pc, 0x800788d8 if k == len(codes) - 1 else 0x80078564)
                pen += packed & 15

    def tail(self, c):
        c.r[REG['a0']], c.r[REG['a1']] = 0x12345678, 0x80110000
        c.r[REG['a3']], c.r[REG['v1']] = 0xff000000, 0xabcdef01
        c.r[REG['v0']], c.r[REG['at']] = 0x80112233, 0x80100000
        c.start(0x800788b8)
        for _ in range(1000):
            if c.pc in (0x80078564, 0x800788d8):
                break
            c.step()
        else:
            self.fail('offer loop hook failed to reach a retail destination')
        self.assertEqual(c.read(0x800f83a8), 0x80112233)
        self.assertEqual(c.read(0x80110000), 0xbb345678)

    def test_non_offer_rows_match_retail_position_and_tail(self):
        built, retail = self.machine(), self.machine(retail=True)
        for next_byte in (0x23, 0xff):
            for index in range(9):
                snapshots = []
                for c in (built, retail):
                    c.write(0x800ca001, next_byte, 1)
                    c.r[REG['s1']], c.r[REG['s4']] = 0x800ca000, index
                    c.r[REG['v1']], c.r[REG['a3']] = 123, 456
                    c.start(0x80078574)
                    c.run(0x8007857c, limit=1000)
                    pos = (c.r[REG['v0']], c.r[REG['v1']], c.r[REG['a3']])
                    c.r[REG['s1']] = 0x800ca001
                    self.tail(c)
                    snapshots.append((pos, c.r[REG['s4']], c.pc))
                self.assertEqual(snapshots[0], snapshots[1])

    def test_offer_name_uses_all_shared_glyph_metrics(self):
        # The CONTACT gate and the battle art selector share the battle width
        # table: text cells carry their proportional metric, every other cell
        # the retail 8 px cell (bearing 0 / advance 8).
        c = self.machine()
        for code in range(256):
            c.write(0x8002bc84, code, 1)
            c.r[REG['s1']], c.r[REG['s4']] = 0x8002bc84, 24
            c.start(0x80078574)
            c.run(0x8007857c, limit=1000)
            self.assertEqual(c.r[REG['v0']],
                             (24 - (self.battle_widths[code] >> 4)) & 0xffffffff)
            c.r[REG['s1']], c.r[REG['s4']] = 0x8002bc85, 24
            self.tail(c)
            self.assertEqual(c.r[REG['s4']], 24 + (self.battle_widths[code] & 15))

    def test_stock_menu_copies_complete_source_name(self):
        c = self.machine()
        dest = toolbelt.asm_equ('BTLP_STOCK_FULL_ADDR')
        record_base, id_cell, rows = 0x800417a0, 0x801f0000, 0x801f0100
        row = 0x801f0200
        for ident, name in self.demon_rows:
            encoded = items.encode(name)
            head = encoded[:10]
            if len(head) < 10:
                head += b'\xff' + bytes(10 - len(head) - 1)
            c.write(id_cell, ident, 1)
            c.load(record_base + ident * 0x38, head)
            c.load(dest, bytes(22))
            c.r[REG['t0']] = dest
            c.r[REG['t1']] = id_cell
            c.r[REG['t2']] = rows
            c.r[REG['t4']] = record_base
            c.r[REG['t5']] = 0xff
            c.r[REG['a2']] = row
            c.r[REG['a3']] = 11
            c.start(0x80067d30)
            c.run(0x80067dbc, limit=10000)
            actual = bytes(c.read(dest + i, 1) for i in range(len(encoded) + 1))
            self.assertEqual(actual, encoded + b'\xff', (ident, name))
            self.assertEqual(c.r[REG['t0']], dest)
            self.assertEqual((c.r[REG['t1']], c.r[REG['t2']], c.r[REG['a2']]),
                             (id_cell, rows, row))

    def test_direct_record_battle_insert_copies_complete_names(self):
        c = self.machine()
        dest = 0x801f1000
        base = toolbelt.asm_equ('DEMON_NAME_BASE')
        stride = toolbelt.asm_equ('DEMON_NAME_STRIDE')
        for ident, name in self.demon_rows:
            with self.subTest(ident=ident):
                expected = etext.encode(name, end=None) + b'\xff'
                c.load(dest, b'\xa5' * 24)
                c.r[REG['a0']] = dest
                c.r[REG['a1']] = base + ident * stride
                c.r[REG['a2']] = 10
                c.r[REG['ra']] = RETURN
                c.start(0x8007a86c)
                c.run(RETURN, limit=10000)
                actual = bytes(c.read(dest + i, 1) for i in range(len(expected)))
                self.assertEqual(actual, expected)
                self.assertEqual(c.read(dest + 23, 1), 0xa5)

    def test_quad_text_samples_the_proportional_atlas_only_for_gated_rows(self):
        """The position phase records the art mode in at; the eight U/V loads
        remap the gated ranges and nothing else."""
        import btlfont
        mapping, _ = btlfont.art_mapping()
        c = self.machine()
        pointer = c.read(0x800cdd50)                    # first personality label
        code = self.codes[0][0]
        self.assertNotEqual(mapping.get(code, code), code, 'test glyph is not remapped')
        sites = ((0x80078608, 'a0', 'a0', 0x80078610),
                 (0x8007863c, 'v0', 'v0', 0x80078644),
                 (0x80078670, 'a0', 'a0', 0x80078678),
                 (0x800786a8, 'v0', 'v0', 0x800786b0),
                 (0x800786dc, 'a0', 'a0', 0x800786e4),
                 (0x80078710, 'v0', 'v0', 0x80078718),
                 (0x80078748, 'a0', 'a0', 0x80078750),
                 (0x80078780, 'v0', 'v0', 0x80078788))
        rows = ((pointer, True),                        # personality bank
                (toolbelt.asm_equ('BTLP_STOCK_FULL_ADDR'), True),   # stock names
                (toolbelt.asm_equ('BTLP_STOCK_FULL_END') - 1, True),
                (toolbelt.asm_equ('BTLP_STOCK_FULL_END'), False),
                (toolbelt.asm_equ('PERSONA_HDR_BUF'), True),   # offer name scratch
                (toolbelt.asm_equ('PERSONA_HDR_BUF') + 20, False),
                (0x800ca000, False))                    # any other effect row
        for at, result, loaded, stop in sites:
            for row_pointer, gated in rows:
                c.write(row_pointer, code, 1)
                # Position phase: the gate must leave this row's art mode in at.
                c.r[REG['s1']], c.r[REG['s4']] = row_pointer, 0
                c.start(0x80078574)
                c.run(0x8007857c, limit=1000)
                self.assertEqual(c.r[REG['at']], 0 if gated else 0xFFFFFFFF,
                                 (at, row_pointer))
                # Then the retail U/V load site must honour it.
                c.r[REG[loaded]] = 0x5A5A5A5A           # the delay-slot load overwrites this
                c.start(at)
                c.run(stop, limit=200)
                expected = mapping.get(code, code) if gated else code
                self.assertEqual(c.r[REG[result]], expected, (at, row_pointer))


    def test_complete_source_demon_names_reach_offer_row(self):
        c = self.machine()
        offer, scratch = 0x800eb23c, 0x8002bc84
        for ident, name in self.demon_rows:
            encoded = items.encode(name)
            c.load(scratch, bytes(48))
            c.write(offer + 0x30, ident, 1)
            c.r[REG['a0']], c.r[REG['a2']] = 0x800417a0 + ident * 0x38, 0
            c.start(0x80075198)
            c.run(0x80075214, limit=10000)
            actual = bytes(c.read(scratch + i, 1) for i in range(len(encoded) + 1))
            self.assertEqual(actual, encoded + b'\xff', (ident, name))
            self.assertEqual(c.r[REG['v0']], scratch)

    def test_complete_demon_names_reach_analyze_row(self):
        c = self.machine()
        actor, row = 0x801b0000, 0x800f6fb4
        race = 17
        # The race, its ':' and the small-font space analyze_race_gap.asm puts
        # before the name.
        prefix = btlui.sf(btlui.psp_races()[race - 1]) + b'\xcb\x00'
        self.assertEqual(c.read(0x800dea58, 1), 24)
        for ident, name in self.demon_rows:
            encoded = items.encode(name)
            c.load(actor, bytes(0x200))
            c.write(actor + 0x3e, ident, 1)
            c.write(actor + 0xb5, race, 1)
            c.load(actor + 0x3f, (encoded[:10] + b'\xff' * 10)[:10])
            c.load(row, bytes([0xaa] * 25))
            c.r[REG['s0']], c.r[REG['s1']] = actor, 0
            c.start(0x800ad828)
            c.run(0x800ad8ac, limit=10000)
            expected = prefix + encoded + b'\xff'
            self.assertEqual(bytes(c.read(row + i, 1) for i in range(len(expected))), expected,
                             (ident, name))
            self.assertEqual(c.read(row + 24, 1), 0xaa)

    def test_advance_gate_uses_previous_glyph_at_bank_boundaries(self):
        c = self.machine()
        code = self.codes[0][0]
        base = toolbelt.asm_equ('PERSONA_HDR_BUF')
        # The gate covers the personality bank, the stock-name bank, then the
        # name scratch's first DEMON_NAME_MAXLEN bytes. The check inspects the
        # PREVIOUS glyph, so s1 runs one past the written byte.
        for pointer, gated in ((BANK, True), (BANK + 63, True), (BANK + 64, False),
                               (toolbelt.asm_equ('BTLP_STOCK_FULL_ADDR'), True),
                               (toolbelt.asm_equ('BTLP_STOCK_FULL_END') - 1, True),
                               (toolbelt.asm_equ('BTLP_STOCK_FULL_END'), False),
                               (base, True), (base + 19, True),
                               (base + 20, False), (0x800ca000, False)):
            c.write(pointer, code, 1)
            c.r[REG['s1']], c.r[REG['s4']], c.r[REG['ra']] = pointer + 1, 5, RETURN
            c.start(0x800b9f64)
            c.run(RETURN, limit=1000)
            self.assertEqual(c.r[REG['s4']],
                             5 + (self.battle_widths[code] & 15) if gated else 6, pointer)

    def test_production_verifier_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            battle = Path(directory) / 'BTLP.BIN'
            resident = Path(directory) / 'SLPS_005.00'
            battle.write_bytes(self.battle)
            resident.write_bytes(self.resident)
            btlui.verify(str(battle), str(resident))
            corrupt = bytearray(self.battle)
            ptr = struct.unpack_from('<I', corrupt, 0x800cdd50 - BASE)[0]
            corrupt[ptr - BASE] ^= 1
            battle.write_bytes(corrupt)
            with self.assertRaisesRegex(SystemExit, 'personality source mismatch'):
                btlui.verify(str(battle), str(resident))
            corrupt = bytearray(self.battle)
            corrupt[0x800788b8 - BASE] ^= 1
            battle.write_bytes(corrupt)
            with self.assertRaisesRegex(SystemExit, 'offer code mismatch'):
                btlui.verify(str(battle), str(resident))
            battle.write_bytes(self.battle)
            corrupt = bytearray(self.resident)
            resident_base = struct.unpack_from('<I', corrupt, 0x18)[0]
            corrupt[0x800155c8 - resident_base + 0x800] ^= 1     # the window exit
            resident.write_bytes(corrupt)
            with self.assertRaisesRegex(SystemExit, 'offer code mismatch'):
                btlui.verify(str(battle), str(resident))

    def test_offer_builder_leaves_flag_and_geometry_code_retail(self):
        lo, hi = 0x8007524c - BASE, 0x800752f0 - BASE
        self.assertEqual(self.battle[lo:hi], self.retail[lo:hi])


if __name__ == '__main__':
    unittest.main()
