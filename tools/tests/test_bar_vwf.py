"""The persona status/fusion bottom bar as retail's two VWF sprite rows (ADV + DNG + S2D).

Retail drew two ten-cell blocks (arcana + name) with the name entry at
dx=0x58/dy=4 and sourced from the master record's ten-glyph head, so longer
English names were cut ("Seimen Kon"). ADV and DNG carry the fusion/status
bar; S2D compiles its own copy for the overworld status page, so it needs the
same treatment. The patch keeps retail's two cel
entries (arcana at dx=0/dy=0, name at dx=0x58/dy=4) and expands the name block
from ten cells to sixteen; retargets the status layout's list; rewrites
each overlay's CellsWriteRow in place so every cell also stores its glyph's
pen advance in the cell's +3 byte (the cba high byte the slot renderer never
reads), hangs a small advance hook on the slot renderer's per-cell pen step
(only for cel entries whose unread pad halfword is SF_BAR_MARK), and grows
the full Persona name straight into the name cells before writing them back
in place.

Run after assembly:
    python -m unittest discover -s tools/tests -p test_bar_vwf.py -v
"""
from pathlib import Path
import struct
import sys
import unittest

from mips_cpu import CPU, REG

ROOT = Path(__file__).resolve().parents[2]

OVERLAY_BASE = 0x800643C4
EXE_BASE = 0x80010000
STACK = 0x801FF000
RETURN = 0x801FF800
BUF = 0x80180000

MARK = 0x5342

# ADV
ADV_WRITER = 0x8008F730
ADV_CELLS_CLEAR = 0x8008F5B4
ADV_WRITER_SPAN = (0x8008F730, 0x8008F7F0)
ADV_ADVANCE_SITE = 0x80065C64
ADV_HOOK = 0x800BD1F4
ADV_HOOK_END = 0x800BD224
ADV_LIST = 0x800BD224                         # between the hook and sf_state_adv
ADV_ARCANA_BLOCK = 0x800B20B4
ADV_CELLS = 0x800B20BC
ADV_NAME_BLOCK = 0x800B210C
ADV_NAME_CELLS = 0x800B2114
ADV_MENU_TOP_DEF = 0x800BFBA4                # the 1x1 slot-0x20 block, moved to the tail
ADV_MENU_TOP_LIST = 0x800B2198               # slot 0x20's list, retail home
ADV_MARK_POS = 0x800B209C                    # g_fm_mark_pos, retail home
ADV_SLOT_INIT = 0x8006FB08
ADV_STATUS = 0x80070144
ADV_WIDTHS = 0x800BD264                      # sf_widths_adv
ADV_KIND_LABELS = 0x800B24A4                 # g_kind_labels

# ADV's Velvet Room card page (adv/pdata.asm)
ADV_PDATA_RACE_BLOCK = 0x800BA080
ADV_PDATA_RACE_CELLS = 0x800BA088
ADV_PDATA_LIST = 0x800BA110
ADV_PDATA_NAME_BLOCK = ADV_NAME_BLOCK        # shared with the status bar
ADV_PDATA_NAME_CELLS = ADV_NAME_CELLS
ADV_PDATA_BAR = 0x800BA0B8                   # retail's old ten-cell name block
ADV_PDATA_TAIL = 0x80099014
ADV_PDATA_TAIL_END = 0x80099084
ADV_DEMON_BASE = 0x800417A0
ADV_RACE_TABLE = 0x800B23C0

# DNG
DNG_WRITER = 0x8009392C
DNG_ADVANCE_SITE = 0x80075B54
DNG_HOOK = 0x800B55E0
DNG_LIST = 0x800B5610                         # after the hook, past the name scratch
DNG_ARCANA_BLOCK = 0x800B5500
DNG_NAME_BLOCK = 0x800B5558
DNG_NAME_CELLS = 0x800B5560
DNG_SLOT_INIT = 0x8007EE34
DNG_STATUS = 0x8007F464
DNG_WIDTHS = 0x800B3024                      # sf_widths_dng

# DNG's dungeon-menu Persona Data page (dng/pdata.asm)
DNG_PDATA_RACE_BLOCK = 0x8009D300
DNG_PDATA_RACE_CELLS = 0x8009D308
DNG_PDATA_LIST = 0x8009D390
DNG_PDATA_NAME_BLOCK = 0x800B562C
DNG_PDATA_NAME_CELLS = 0x800B5634
DNG_PDATA_BAR = 0x800B56E0
DNG_PDATA_TAIL = 0x800998F8
DNG_PDATA_TAIL_END = 0x80099968
DNG_DRAW_SPELL_NAME = 0x8008A8A4
DNG_SKILL_NAME_COPY = 0x80011FBC
DNG_DEMON_BASE = 0x800417A0
DNG_RACE_TABLE = 0x8009AEB0

# S2D (the overworld menu's own status page)
S2D_WRITER = 0x80083A64
S2D_WRITER_SPAN = (0x80083A64, 0x80083B24)
S2D_ADVANCE_SITE = 0x80065744
S2D_HOOK = 0x800BE900
S2D_HOOK_END = 0x800BE930
S2D_LIST = 0x800BE800
S2D_ARCANA_BLOCK = 0x800BE820
S2D_NAME_BLOCK = 0x800BE878
S2D_NAME_CELLS = 0x800BE880
S2D_SLOT_INIT = 0x8006EC2C
S2D_STATUS = 0x8006F26C
S2D_WIDTHS = 0x800BC224                      # sf_widths_s2d

# S2D's Persona Data page (s2d/pdata.asm)
S2D_PDATA_RACE_BLOCK = 0x8009FE90
S2D_PDATA_RACE_CELLS = 0x8009FE98
S2D_PDATA_LIST = 0x8009FF20
S2D_PDATA_NAME_BLOCK = S2D_NAME_BLOCK        # shared with the status bar
S2D_PDATA_NAME_CELLS = S2D_NAME_CELLS
S2D_PDATA_BAR = 0x8009FEC8                   # retail's old ten-cell name block
S2D_PDATA_TAIL = 0x800899F4
S2D_PDATA_TAIL_END = 0x80089A64
S2D_DEMON_BASE = 0x800417A0
S2D_RACE_TABLE = 0x8009DA40

ADV_FUSE_SITE_A = 0x8009FB40
ADV_FUSE_SITE_B = 0x8009FE38
ADV_FUSE_A = ADV_FUSE_SITE_A
ADV_FUSE_B = ADV_FUSE_SITE_B

# retail instructions around the patched fusion sites that must survive
ADV_FUSE_ALIVE = ((0x8009F93C, 0xAFB40028),   # sw s4,0x28(sp)
                  (0x8009F948, 0xAFB20020))   # sw s2,0x20(sp)

# a few of DNG's seventeen hint readers (they must keep naming 0x8009AB90)
DNG_HINT_PAIRS = (0x80079A88, 0x8007A254, 0x8007C300, 0x800813F8)


def jal(target):
    return 0x0C000000 | ((target >> 2) & 0x03FFFFFF)


class BarVWF(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = [ROOT / 'build' / name for name in
                 ('ADV.BIN', 'DNG.BIN', 'S2D.BIN', 'SLPS_005.00')]
        if not all(path.exists() for path in paths):
            raise unittest.SkipTest('requires the assembled overlays')
        cls.adv = paths[0].read_bytes()
        cls.dng = paths[1].read_bytes()
        cls.s2d = paths[2].read_bytes()
        cls.exe = paths[3].read_bytes()
        cls.retail_adv = (ROOT / 'data/psx/ADV.BIN').read_bytes()
        cls.retail_dng = (ROOT / 'data/psx/DNG.BIN').read_bytes()
        cls.retail_s2d = (ROOT / 'data/psx/S2D.BIN').read_bytes()
        cls.widths = bytes(cls.adv[ADV_WIDTHS - OVERLAY_BASE:ADV_WIDTHS - OVERLAY_BASE + 256])
        cls.dng_widths = bytes(cls.dng[DNG_WIDTHS - OVERLAY_BASE:DNG_WIDTHS - OVERLAY_BASE + 256])
        cls.s2d_widths = bytes(cls.s2d[S2D_WIDTHS - OVERLAY_BASE:S2D_WIDTHS - OVERLAY_BASE + 256])
        cls.sym = {}
        for line in (ROOT / 'build' / 'persona.sym').read_text().splitlines():
            fields = line.split()
            if len(fields) == 2:
                cls.sym[fields[1]] = int(fields[0], 16)

    def word(self, data, address):
        return struct.unpack_from('<I', data, address - OVERLAY_BASE)[0]

    def half(self, data, address):
        return struct.unpack_from('<H', data, address - OVERLAY_BASE)[0]

    # -------------------------------------------------------------
    # byte-level: the patches landed and their neighbours survived
    # -------------------------------------------------------------

    def test_adv_writer_rewritten_and_bounded(self):
        start, end = ADV_WRITER_SPAN
        body = self.adv[start - OVERLAY_BASE:end - OVERLAY_BASE]
        self.assertEqual(self.word(self.adv, start), 0x30E2FFFF)      # andi v0,a3,0xFFFF
        self.assertEqual(struct.unpack_from('<I', body, 4)[0] >> 26, 4)   # beqz
        self.assertEqual(struct.unpack_from('<I', body, 0x2C)[0], 0x3C18800C)  # la t8, sf_widths_adv
        self.assertEqual(struct.unpack_from('<I', body, 0x30)[0], 0x2718D264)
        self.assertIn(0xA1020003, struct.unpack(f'<{len(body) // 4}I', body))  # sb v0,3(t0)
        self.assertEqual(body[0xB8:], bytes(len(body) - 0xB8))        # the stale tail zeroed
        # the next retail function intact
        self.assertEqual(self.word(self.adv, end), self.word(self.retail_adv, end))

    def test_adv_hook_and_site(self):
        self.assertEqual(self.word(self.adv, ADV_ADVANCE_SITE), jal(ADV_HOOK))
        self.assertEqual(self.word(self.adv, ADV_ADVANCE_SITE + 4), 0)
        self.assertEqual(self.word(self.adv, ADV_HOOK), 0x9723000A)   # lhu v1,10(t9)
        self.assertEqual(self.word(self.adv, ADV_HOOK + 4), 0x92C20000)   # lbu v0,(s6)
        self.assertEqual(self.word(self.adv, ADV_HOOK + 12), 0x2442FF01)  # addiu v0,v0,-255

    def bar_rows(self, data, list_addr):
        """The two retail-shaped cel entries: arcana line then name line."""
        return (
            self.word(data, list_addr),
            self.half(data, list_addr + 4), self.half(data, list_addr + 6),
            self.half(data, list_addr + 10),
            self.word(data, list_addr + 12),
            self.half(data, list_addr + 16), self.half(data, list_addr + 18),
            self.half(data, list_addr + 22),
            self.word(data, list_addr + 24),
        )

    def test_adv_data_span(self):
        # retail's two entries: arcana at dx=0/dy=0, name at dx=0x58/dy=4
        self.assertEqual(self.bar_rows(self.adv, ADV_LIST),
                         (ADV_ARCANA_BLOCK, 0, 0, MARK,
                          ADV_NAME_BLOCK, 0x58, 4, MARK, 0xFFFFFFFF))
        self.assertEqual(self.adv[ADV_ARCANA_BLOCK - OVERLAY_BASE:ADV_ARCANA_BLOCK - OVERLAY_BASE + 2],
                         bytes([10, 1]))
        self.assertEqual(self.adv[ADV_NAME_BLOCK - OVERLAY_BASE:ADV_NAME_BLOCK - OVERLAY_BASE + 2],
                         bytes([16, 1]))
        self.assertEqual(ADV_NAME_BLOCK, ADV_CELLS + 10 * 8)
        self.assertEqual(ADV_NAME_CELLS, ADV_NAME_BLOCK + 8)
        self.assertEqual(ADV_NAME_CELLS + 16 * 8, 0x800B2194)
        for cells in (ADV_CELLS, ADV_NAME_CELLS):
            self.assertEqual(self.adv[cells - OVERLAY_BASE:cells - OVERLAY_BASE + 8],
                             bytes.fromhex('00001E000000FF01'))
        # g_fm_mark_pos (the five member-marker positions) keeps its retail
        # home and bytes; the two readers retail put there keep naming it,
        # so every status-screen marker site reads the intact table
        self.assertEqual(self.adv[ADV_MARK_POS - OVERLAY_BASE:0x800B20B4 - OVERLAY_BASE],
                         self.retail_adv[ADV_MARK_POS - OVERLAY_BASE:0x800B20B4 - OVERLAY_BASE])
        for site in (0x80073118, 0x800734B8):
            self.assertEqual(self.word(self.adv, site), 0x3C01800B)      # lui at,0x800B
            self.assertEqual(self.word(self.adv, site + 4), 0x2421209C)  # addiu at,at,0x209C
            self.assertEqual(self.word(self.adv, site + 0x10), 0x3C01800B)
            self.assertEqual(self.word(self.adv, site + 0x14), 0x2421209E)
        # the grown name cells cover the 1x1 slot-0x20 block retail kept at
        # 0x800B2188: its 0x10 bytes move to the image tail and its list word
        # is repointed; the list itself stays at 0x800B2198
        self.assertEqual(self.word(self.adv, ADV_MENU_TOP_LIST), ADV_MENU_TOP_DEF)
        self.assertEqual(self.adv[ADV_MENU_TOP_DEF - OVERLAY_BASE:ADV_MENU_TOP_DEF - OVERLAY_BASE + 0x10],
                         self.retail_adv[0x800B2188 - OVERLAY_BASE:0x800B2188 - OVERLAY_BASE + 0x10])
        # the slot layout points slot 0x1E at the list (lui 0x800B + ori 0xD224)
        self.assertEqual(self.word(self.adv, ADV_SLOT_INIT - 4), 0x3C04800B)
        self.assertEqual(self.word(self.adv, ADV_SLOT_INIT), 0x3484D224)

    def test_adv_status_and_fusion_sites(self):
        # the status function grows the full name through persona_name_copy,
        # handing it the retail Persona key unchanged (retail reads the name
        # at 0x8004B0D4 + key*0x2C; a +1 would show the next record)
        self.assertEqual(self.word(self.adv, 0x800701B8), 0x92450018)  # lbu a1,0x18(s2)
        self.assertEqual(self.word(self.adv, 0x800701BC), jal(0x80031878))
        self.assertEqual(self.word(self.adv, 0x800701C0), 0)            # nop
        span = struct.unpack(f'<{(0xC0) // 4}I',
                             self.adv[ADV_STATUS - OVERLAY_BASE:ADV_STATUS + 0xC0 - OVERLAY_BASE])
        self.assertNotIn(0x24A50001, span)                              # no addiu a1,a1,1
        # the fusion clears keep retail's bases, count 16
        self.assertEqual(self.word(self.adv, 0x8009F904), 0x248420BC)   # retail ADV_BAR_CELLS
        self.assertEqual(self.word(self.adv, 0x8009F958), 0x24842114)   # ADV_BAR_NAME_CELLS
        self.assertEqual(self.word(self.adv, 0x8009F960), 0x34050010)   # ori a1,16
        # the status clears/writes the name cells past the block header (+0x58)
        self.assertEqual(span.count(0x26040058), 2)                     # addiu a0,s0,0x58
        self.assertNotIn(0x26040050, span)
        # the surrounding retail stack stores survived
        for address, word in ADV_FUSE_ALIVE:
            self.assertEqual(self.word(self.adv, address), word)
        # both fusion sites grow the name through persona_name_copy_at,
        # whose direct entry reads the source pointer from v1 (only the
        # key-based persona_name_copy computes v1 from a1 first)
        self.assertEqual(self.word(self.adv, ADV_FUSE_A + 4), jal(0x80031898))
        self.assertEqual(self.word(self.adv, ADV_FUSE_A + 8), 0x26630008)  # addiu v1,s3,8
        self.assertEqual(self.word(self.adv, ADV_FUSE_B + 4), jal(0x80031898))
        self.assertEqual(self.word(self.adv, ADV_FUSE_B + 8), 0x26830019)  # addiu v1,s4,0x19
        # the copy grows into the frame's free outgoing quad
        self.assertEqual(self.word(self.adv, ADV_FUSE_A), 0x03A02021)      # move a0,sp
        self.assertEqual(self.half(self.adv, ADV_FUSE_A + 0x24), 0x14)     # lbu v0,0x14(s3) kind
        # the arcana row is written with a fresh base: CellsWriteRow keeps its
        # destination in t0 and turns a0 into the glyph column, so retail's
        # reload of the arcana base is load-bearing. The index is kind*10
        # against ADV_KIND_LABELS-10, and the delay slot rebases onto
        # ADV_BAR_CELLS (0x800B249A - 0x3DE == 0x800B20BC).
        for site, kind_load in ((ADV_FUSE_A, 0x92620014),   # lbu v0,0x14(s3)
                                (ADV_FUSE_B, 0x92820025)):  # lbu v0,0x25(s4)
            self.assertEqual(self.word(self.adv, site + 0x24), kind_load)
            self.assertEqual(self.word(self.adv, site + 0x28), 0x3407000A)  # ori a3,10
            self.assertEqual(self.word(self.adv, site + 0x38), 0x3C02800B)  # lui v0,0x800B
            self.assertEqual(self.word(self.adv, site + 0x3C), 0x2442249A)  # addiu v0,ADV_KIND_LABELS-10
            self.assertEqual(self.word(self.adv, site + 0x44), jal(ADV_WRITER))
            self.assertEqual(self.word(self.adv, site + 0x48), 0x2444FC22)  # addiu a0,v0,-0x3DE
        self.assertEqual((ADV_KIND_LABELS - 10 - 0x3DE) & 0xFFFFFFFF, ADV_CELLS)

    def test_adv_pdata_page(self):
        """The Velvet Room card page: race and full demon name in VWF cells.

        Retail's ten-cell name block sits immediately before the page's cel
        list, so the name entry points at the status bar's sixteen-cell block;
        the race block and the list keep retail's placement. The old name
        block becomes the name-row helper, and PersonaDataDraw's tail keeps
        retail's race write (now with the VWF face) after that call.
        """
        # the tail: one helper call, then retail's race write
        self.assertEqual(self.word(self.adv, ADV_PDATA_TAIL), 0x02A02021)  # move a0,s5
        self.assertEqual(self.word(self.adv, ADV_PDATA_TAIL + 4), jal(ADV_PDATA_BAR))
        self.assertEqual(self.word(self.adv, ADV_PDATA_TAIL + 8), 0)       # nop
        # Former dead instructions now hold the pickup clamp. The ordinary
        # Persona-data path jumps over it to the unchanged race-row writer.
        self.assertEqual(self.word(self.adv, ADV_PDATA_TAIL + 12),
                         0x08000000 | (((ADV_PDATA_TAIL + 0x30) >> 2) & 0x03ffffff))
        self.assertEqual(self.word(self.adv, ADV_PDATA_TAIL + 0x30), 0x3C04800C)  # lui a0,0x800C
        self.assertEqual(self.word(self.adv, ADV_PDATA_TAIL + 0x34), 0x2484A088)  # addiu a0,-0x5F78
        self.assertEqual(self.word(self.adv, ADV_PDATA_TAIL + 0x38), 0x34060080)  # ori a2,0x80
        self.assertEqual(self.word(self.adv, ADV_PDATA_TAIL + 0x68), jal(ADV_WRITER))
        self.assertEqual(self.word(self.adv, ADV_PDATA_TAIL + 0x6C), 0x00A22821)  # addu a1,a1,v0
        # the epilogue and the next function survived
        self.assertEqual(self.word(self.adv, ADV_PDATA_TAIL_END),
                         self.word(self.retail_adv, ADV_PDATA_TAIL_END))

        # the cel list: retail's race entry, the shared name block, both marks
        self.assertEqual(self.bar_rows(self.adv, ADV_PDATA_LIST),
                         (ADV_PDATA_RACE_BLOCK, 0, 0, MARK,
                          ADV_PDATA_NAME_BLOCK, 0x40, 0x0C, MARK, 0xFFFFFFFF))
        self.assertEqual(self.adv[ADV_PDATA_RACE_BLOCK - OVERLAY_BASE:
                                  ADV_PDATA_RACE_BLOCK - OVERLAY_BASE + 2],
                         bytes([6, 1]))
        self.assertEqual(ADV_PDATA_NAME_BLOCK, ADV_NAME_BLOCK)
        self.assertEqual(ADV_PDATA_NAME_CELLS, ADV_NAME_CELLS)

        # the helper fills retail's old name block exactly
        self.assertEqual(self.word(self.adv, ADV_PDATA_BAR), 0x27BDFFF8)  # addiu sp,-8
        self.assertEqual(self.word(self.adv, ADV_PDATA_BAR + 4), 0xAFBF0000)  # sw ra,(sp)
        self.assertEqual(self.word(self.adv, ADV_PDATA_BAR + 0x14), jal(0x800BDA88))
        self.assertEqual(self.word(self.adv, ADV_PDATA_BAR + 0x1C), 0x3C04800B)  # lui a0,0x800B
        self.assertEqual(self.word(self.adv, ADV_PDATA_BAR + 0x20), 0x24842114)  # ADV_BAR_NAME_CELLS
        self.assertEqual(self.word(self.adv, ADV_PDATA_BAR + 0x28), jal(ADV_CELLS_CLEAR))
        self.assertEqual(self.word(self.adv, ADV_PDATA_BAR + 0x40), 0x34060080)  # ori a2,0x80
        self.assertEqual(self.word(self.adv, ADV_PDATA_BAR + 0x44), 0x34070010)  # ori a3,16
        self.assertEqual(self.word(self.adv, ADV_PDATA_BAR + 0x50),
                         0x08000000 | ((ADV_WRITER >> 2) & 0x03FFFFFF))  # j ADV_CELLS_ROW
        self.assertEqual(self.word(self.adv, ADV_PDATA_BAR + 0x54), 0)  # nop (delay)
        self.assertEqual(ADV_PDATA_BAR + 0x58, ADV_PDATA_LIST)

    def a2_selects_vwf(self, data, site, writer):
        """The a2 in force at a row call is page 0 + bit 7.

        Walk back to the nearest instruction that writes a2. A call in
        between is allowed only when it is the row writer itself, whose
        documented contract is that it never writes a2 (so the fusion
        helper can set the face once and chain its arcana row).
        """
        for back in range(4, 128, 4):
            word = self.word(data, site - back)
            op, rt, rd, fn = word >> 26, word >> 16 & 31, word >> 11 & 31, word & 63
            if op in (9, 10, 11, 12, 13, 15) and rt == 6:
                return word == 0x34060080        # ori a2,zero,0x80
            if op in (32, 33, 35, 36, 37) and rt == 6:
                return False
            if op == 0 and rd == 6 and fn not in (8, 9, 24, 25, 26, 27):
                return False
            if op == 3:
                target = 0x80000000 | ((word & 0x3FFFFFF) << 2)
                if target != writer:
                    return False
        return False

    def test_every_bar_row_selects_the_vwf_face(self):
        for data, writer, spans in (
                (self.adv, ADV_WRITER,
                 ((ADV_STATUS, 0xC0), (ADV_FUSE_SITE_A, 0x4C),
                  (ADV_FUSE_SITE_B, 0x4C))),
                (self.dng, DNG_WRITER, ((DNG_STATUS, 0xC0),)),
                (self.s2d, S2D_WRITER, ((S2D_STATUS, 0xC0),))):
            for start, size in spans:
                calls = [a for a in range(start, start + size, 4)
                         if self.word(data, a) == jal(writer)]
                self.assertEqual(len(calls), 2, f'{start:#x}')
                for call in calls:
                    self.assertTrue(self.a2_selects_vwf(data, call, writer),
                                    f'row call at {call:#x} does not select the VWF face')

    def test_dng_patches(self):
        self.assertEqual(self.word(self.dng, DNG_ADVANCE_SITE), jal(DNG_HOOK))
        self.assertEqual(self.word(self.dng, DNG_ADVANCE_SITE + 4), 0)
        self.assertEqual(self.bar_rows(self.dng, DNG_LIST),
                         (DNG_ARCANA_BLOCK, 0, 0, MARK,
                          DNG_NAME_BLOCK, 0x58, 4, MARK, 0xFFFFFFFF))
        self.assertEqual(self.dng[DNG_ARCANA_BLOCK - OVERLAY_BASE:DNG_ARCANA_BLOCK - OVERLAY_BASE + 2],
                         bytes([10, 1]))
        self.assertEqual(self.dng[DNG_NAME_BLOCK - OVERLAY_BASE:DNG_NAME_BLOCK - OVERLAY_BASE + 2],
                         bytes([16, 1]))
        self.assertEqual(DNG_NAME_BLOCK, DNG_ARCANA_BLOCK + 8 + 10 * 8)
        self.assertEqual(DNG_NAME_CELLS, DNG_NAME_BLOCK + 8)
        self.assertEqual(DNG_NAME_CELLS + 16 * 8, DNG_HOOK)
        # slot init: lui 0x800B / addiu 0x5610
        self.assertEqual(self.word(self.dng, DNG_SLOT_INIT), 0x3C04800B)
        self.assertEqual(self.half(self.dng, DNG_SLOT_INIT + 4), 0x5610)
        # the status rewrite grows the full name, key passed unchanged
        self.assertEqual(self.word(self.dng, 0x8007F4D8), 0x92450018)  # lbu a1,0x18(s2)
        self.assertEqual(self.word(self.dng, 0x8007F4DC), jal(0x80031878))
        self.assertEqual(self.word(self.dng, 0x8007F4E0), 0)            # nop
        span = struct.unpack(f'<{(0xC0) // 4}I',
                             self.dng[DNG_STATUS - OVERLAY_BASE:DNG_STATUS + 0xC0 - OVERLAY_BASE])
        self.assertNotIn(0x24A50001, span)                              # no addiu a1,a1,1
        self.assertEqual(span.count(0x26040058), 2)                     # name past the header
        self.assertNotIn(0x26040050, span)
        # the writer body carries the +3 store and this overlay's table
        body = self.dng[DNG_WRITER - OVERLAY_BASE:DNG_WRITER - OVERLAY_BASE + 0xC0]
        self.assertIn(0xA1020003, struct.unpack(f'<{len(body) // 4}I', body))
        self.assertEqual(struct.unpack_from('<I', body, 0x2C)[0], 0x3C18800B)  # la t8, sf_widths_dng
        self.assertEqual(struct.unpack_from('<I', body, 0x30)[0], 0x27183024)
        self.assertEqual(body[0xB8:], bytes(len(body) - 0xB8))        # the stale tail zeroed
        # the seventeen hint readers still name 0x8009AB90
        for site in DNG_HINT_PAIRS:
            hi = self.word(self.dng, site) & 0xFFFF
            imm = struct.unpack_from('<h', self.dng, site + 4 - OVERLAY_BASE)[0]
            self.assertEqual(((hi << 16) + imm) & 0xFFFFFFFF, 0x8009AB90)

    def test_dng_pdata_page(self):
        """The Persona Data page: full skill names and a VWF race/name bar.

        DrawSpellName now builds the full name through skill_name_copy into
        the kit's scratch and hands the scratch to the same recorder, whose
        tiered row keeps the caller's ten-cell (80 px) footprint. The bar's
        tail hands the demon id to dng_pdata_bar; both cel entries carry the
        advance mark and the name block grows to twenty cells in the extension.
        """
        # DrawSpellName: copy the full skill name, then the unchanged row call
        self.assertEqual(self.word(self.dng, DNG_DRAW_SPELL_NAME + 0x58),
                         jal(DNG_SKILL_NAME_COPY))
        self.assertEqual(self.word(self.dng, DNG_DRAW_SPELL_NAME + 0x94),
                         jal(0x8007782C))                 # the DNG recorder hook
        self.assertEqual(self.half(self.dng, DNG_DRAW_SPELL_NAME + 0x74), 10)
        self.assertEqual(self.word(self.dng, DNG_DRAW_SPELL_NAME + 0x60), 0x3C04800B)  # lui a0,0x800B
        self.assertEqual(self.half(self.dng, DNG_DRAW_SPELL_NAME + 0x64), 0x54D0)      # sf_name_scratch_dng
        # the next retail function is untouched
        self.assertEqual(self.word(self.dng, DNG_DRAW_SPELL_NAME + 0xC0),
                         self.word(self.retail_dng, DNG_DRAW_SPELL_NAME + 0xC0))

        # PersonaDataDraw's old fixed-width tail is a jump to the VWF helper
        self.assertEqual(self.word(self.dng, DNG_PDATA_TAIL), 0x00152400)  # sll a0,s5,16
        self.assertEqual(self.word(self.dng, DNG_PDATA_TAIL + 4), 0x00042403)  # sra a0,a0,16
        self.assertEqual(self.word(self.dng, DNG_PDATA_TAIL + 8), jal(DNG_PDATA_BAR))
        self.assertEqual(self.word(self.dng, DNG_PDATA_TAIL + 12), 0)
        self.assertEqual(self.dng[DNG_PDATA_TAIL + 16 - OVERLAY_BASE:
                                  DNG_PDATA_TAIL_END - OVERLAY_BASE], bytes(DNG_PDATA_TAIL_END - DNG_PDATA_TAIL - 16))
        self.assertEqual(self.word(self.dng, DNG_PDATA_TAIL_END),
                         self.word(self.retail_dng, DNG_PDATA_TAIL_END))

        # the cel list keeps retail's race entry and name dx/dy, adds the mark
        self.assertEqual(self.bar_rows(self.dng, DNG_PDATA_LIST),
                         (DNG_PDATA_RACE_BLOCK, 0, 0, MARK,
                          DNG_PDATA_NAME_BLOCK, 0x40, 0x0C, MARK, 0xFFFFFFFF))
        self.assertEqual(self.dng[DNG_PDATA_RACE_BLOCK - OVERLAY_BASE:
                                  DNG_PDATA_RACE_BLOCK - OVERLAY_BASE + 2],
                         bytes([6, 1]))
        self.assertEqual(self.dng[DNG_PDATA_NAME_BLOCK - OVERLAY_BASE:
                                  DNG_PDATA_NAME_BLOCK - OVERLAY_BASE + 2],
                         bytes([20, 1]))
        self.assertEqual(DNG_PDATA_NAME_CELLS, DNG_PDATA_NAME_BLOCK + 8)
        self.assertLessEqual(DNG_PDATA_NAME_CELLS + 20 * 8, DNG_PDATA_BAR)
        for i in range(20):
            self.assertEqual(self.dng[DNG_PDATA_NAME_CELLS - OVERLAY_BASE + i * 8:
                                      DNG_PDATA_NAME_CELLS - OVERLAY_BASE + i * 8 + 8],
                             bytes.fromhex('00001E000000FF01'))

    def test_dng_pdata_bar_runtime(self):
        """Run the real helper: race and full demon name into their cells."""
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import smallfont_variants                         # noqa: E402
        editable = smallfont_variants.editable_codes()
        regular, _compact = smallfont_variants.cell_codes()

        def uv(code):
            if code in editable:
                return smallfont_variants.cell_uv(regular[editable.index(code)])
            return ((code % 31) * 8, (code // 31) * 12)

        ident = 1                                        # Jahi: no tail
        record = DNG_DEMON_BASE + ident * 0x38
        name = bytes([0xAF, 0x23, 0x34])                 # J a h i
        race = 1                                         # Night
        cpu = self.machine(self.dng)
        cpu.load(record, name + b'\xff' + bytes(6))
        cpu.write(record + 0xB, race, 1)
        cpu.r[REG['a0']] = ident
        cpu.start(DNG_PDATA_BAR)
        cpu.run(RETURN, limit=20000)

        race_codes = self.dng[DNG_RACE_TABLE - OVERLAY_BASE +
                              (race - 1) * 6:DNG_RACE_TABLE - OVERLAY_BASE +
                              (race - 1) * 6 + 6]
        for i, code in enumerate(race_codes):
            base = DNG_PDATA_RACE_CELLS + i * 8
            u, v = uv(code)
            self.assertEqual(cpu.read(base, 1), u)
            self.assertEqual(cpu.read(base + 1, 1), v)
            self.assertEqual(cpu.read(base + 3, 1), self.dng_widths[code] & 0xF)
        for i, code in enumerate(name):
            base = DNG_PDATA_NAME_CELLS + i * 8
            u, v = uv(code)
            self.assertEqual(cpu.read(base, 1), u)
            self.assertEqual(cpu.read(base + 1, 1), v)
            self.assertEqual(cpu.read(base + 3, 1), self.dng_widths[code] & 0xF)
        # the FF ended the row; the rest of the twenty cells stay cleared
        for i in range(len(name), 20):
            self.assertEqual(cpu.read(DNG_PDATA_NAME_CELLS + i * 8, 1), 0xFF)

    def test_adv_pdata_tail_runtime(self):
        """The real card-page tail: the shared name block gets the full
        demon name and the race row gets its six VWF cells."""
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import demons                                   # noqa: E402
        import skills                                   # noqa: E402
        import smallfont_variants                       # noqa: E402
        editable = smallfont_variants.editable_codes()
        regular, _compact = smallfont_variants.cell_codes()

        def uv(code):
            if code in editable:
                return smallfont_variants.cell_uv(regular[editable.index(code)])
            return ((code % 31) * 8, (code // 31) * 12)

        ident = 90                                      # Yomotsu Shikome: 15 glyphs
        codes = list(skills.encode_glyphs(ident, demons.record_en()[ident]))
        self.assertGreater(len(codes), 10)              # the head alone would cut it

        cpu = self.machine(self.adv)
        frame = STACK - 0x80
        cpu.write(frame + 0x30, RETURN, 4)              # the tail's epilogue
        cpu.r[REG['sp']] = frame
        cpu.r[REG['s5']] = ident
        cpu.r[REG['s0']] = ident * 0x38
        cpu.start(ADV_PDATA_TAIL)
        cpu.run(RETURN, limit=200000)

        for i, code in enumerate(codes):
            base = ADV_PDATA_NAME_CELLS + i * 8
            u, v = uv(code)
            self.assertEqual(cpu.read(base, 1), u)
            self.assertEqual(cpu.read(base + 1, 1), v)
            self.assertEqual(cpu.read(base + 3, 1), self.widths[code] & 0xF)
        # the FF ended the row; the remaining cells stayed cleared
        self.assertEqual(cpu.read(ADV_PDATA_NAME_CELLS + len(codes) * 8, 1), 0xFF)

        race = cpu.read(ADV_DEMON_BASE + ident * 0x38 + 0xB, 1)
        race_codes = self.adv[ADV_RACE_TABLE - OVERLAY_BASE + (race - 1) * 6:
                              ADV_RACE_TABLE - OVERLAY_BASE + (race - 1) * 6 + 6]
        for i, code in enumerate(race_codes):
            base = ADV_PDATA_RACE_CELLS + i * 8
            u, v = uv(code)
            self.assertEqual(cpu.read(base, 1), u)
            self.assertEqual(cpu.read(base + 1, 1), v)
            self.assertEqual(cpu.read(base + 3, 1), self.widths[code] & 0xF)

    def test_s2d_patches(self):
        self.assertEqual(self.word(self.s2d, S2D_ADVANCE_SITE), jal(S2D_HOOK))
        self.assertEqual(self.word(self.s2d, S2D_ADVANCE_SITE + 4), 0)
        self.assertEqual(self.bar_rows(self.s2d, S2D_LIST),
                         (S2D_ARCANA_BLOCK, 0, 0, MARK,
                          S2D_NAME_BLOCK, 0x58, 4, MARK, 0xFFFFFFFF))
        self.assertEqual(self.s2d[S2D_ARCANA_BLOCK - OVERLAY_BASE:S2D_ARCANA_BLOCK - OVERLAY_BASE + 2],
                         bytes([10, 1]))
        self.assertEqual(self.s2d[S2D_NAME_BLOCK - OVERLAY_BASE:S2D_NAME_BLOCK - OVERLAY_BASE + 2],
                         bytes([16, 1]))
        self.assertEqual(S2D_NAME_BLOCK, S2D_ARCANA_BLOCK + 8 + 10 * 8)
        self.assertEqual(S2D_NAME_CELLS, S2D_NAME_BLOCK + 8)
        self.assertEqual(S2D_NAME_CELLS + 16 * 8, S2D_HOOK)
        self.assertEqual(S2D_HOOK_END - S2D_HOOK, 0x30)
        for cells in (S2D_ARCANA_BLOCK + 8, S2D_NAME_CELLS):
            self.assertEqual(self.s2d[cells - OVERLAY_BASE:cells - OVERLAY_BASE + 8],
                             bytes.fromhex('00001E000000FF01'))
        # the status preview points slot 0x1E at the list (lui 0x800C / addiu -0x1800)
        self.assertEqual(self.word(self.s2d, S2D_SLOT_INIT), 0x3C04800C)
        self.assertEqual(self.half(self.s2d, S2D_SLOT_INIT + 4), 0xE800)
        # the status rewrite grows the full name, key passed unchanged
        self.assertEqual(self.word(self.s2d, 0x8006F2E0), 0x92450018)  # lbu a1,0x18(s2)
        self.assertEqual(self.word(self.s2d, 0x8006F2E4), jal(0x80031878))
        self.assertEqual(self.word(self.s2d, 0x8006F2E8), 0)            # nop
        span = struct.unpack(f'<{(0xC0) // 4}I',
                             self.s2d[S2D_STATUS - OVERLAY_BASE:S2D_STATUS + 0xC0 - OVERLAY_BASE])
        self.assertNotIn(0x24A50001, span)                              # no addiu a1,a1,1
        self.assertEqual(span.count(0x26040058), 2)                     # name past the header
        self.assertNotIn(0x26040050, span)
        # the writer body carries the +3 store and this overlay's table
        body = self.s2d[S2D_WRITER - OVERLAY_BASE:S2D_WRITER - OVERLAY_BASE + 0xC0]
        self.assertIn(0xA1020003, struct.unpack(f'<{len(body) // 4}I', body))
        self.assertEqual(struct.unpack_from('<I', body, 0x2C)[0], 0x3C18800C)  # la t8, sf_widths_s2d
        self.assertEqual(struct.unpack_from('<I', body, 0x30)[0], 0x2718C224)
        self.assertEqual(body[0xB8:], bytes(len(body) - 0xB8))        # the stale tail zeroed

    def test_s2d_pdata_page(self):
        """The Persona Data page: race and full demon name in VWF cells.

        Same port as the ADV card page: retail's ten-cell name block becomes
        the name-row helper, the list's name entry points at the shared
        sixteen-cell status block, and PersonaDataDraw's tail keeps retail's
        race write (now with the VWF face) after the helper call.
        """
        # the tail: one helper call, then retail's race write
        self.assertEqual(self.word(self.s2d, S2D_PDATA_TAIL), 0x02A02021)  # move a0,s5
        self.assertEqual(self.word(self.s2d, S2D_PDATA_TAIL + 4), jal(S2D_PDATA_BAR))
        self.assertEqual(self.word(self.s2d, S2D_PDATA_TAIL + 8), 0)       # nop
        for off in range(12, 0x30, 4):
            self.assertEqual(self.word(self.s2d, S2D_PDATA_TAIL + off), 0)
        self.assertEqual(self.word(self.s2d, S2D_PDATA_TAIL + 0x30), 0x3C04800A)  # lui a0,0x800A
        self.assertEqual(self.word(self.s2d, S2D_PDATA_TAIL + 0x34), 0x2484FE98)  # race cells
        self.assertEqual(self.word(self.s2d, S2D_PDATA_TAIL + 0x38), 0x34060080)  # ori a2,0x80
        self.assertEqual(self.word(self.s2d, S2D_PDATA_TAIL + 0x68), jal(S2D_WRITER))
        self.assertEqual(self.word(self.s2d, S2D_PDATA_TAIL + 0x6C), 0x00A22821)  # addu a1,a1,v0
        # the epilogue and the next function survived
        self.assertEqual(self.word(self.s2d, S2D_PDATA_TAIL_END),
                         self.word(self.retail_s2d, S2D_PDATA_TAIL_END))

        # the cel list: retail's race entry, the shared name block, both marks
        self.assertEqual(self.bar_rows(self.s2d, S2D_PDATA_LIST),
                         (S2D_PDATA_RACE_BLOCK, 0, 0, MARK,
                          S2D_PDATA_NAME_BLOCK, 0x40, 0x0C, MARK, 0xFFFFFFFF))
        self.assertEqual(self.s2d[S2D_PDATA_RACE_BLOCK - OVERLAY_BASE:
                                  S2D_PDATA_RACE_BLOCK - OVERLAY_BASE + 2],
                         bytes([6, 1]))
        self.assertEqual(S2D_PDATA_NAME_BLOCK, S2D_NAME_BLOCK)
        self.assertEqual(S2D_PDATA_NAME_CELLS, S2D_NAME_CELLS)

        # the helper fills retail's old name block exactly
        self.assertEqual(self.word(self.s2d, S2D_PDATA_BAR), 0x27BDFFF8)  # addiu sp,-8
        self.assertEqual(self.word(self.s2d, S2D_PDATA_BAR + 4), 0xAFBF0000)  # sw ra,(sp)
        self.assertEqual(self.word(self.s2d, S2D_PDATA_BAR + 0x14), jal(0x800BD7E4))
        self.assertEqual(self.word(self.s2d, S2D_PDATA_BAR + 0x1C), 0x3C04800C)  # lui a0,0x800C
        self.assertEqual(self.word(self.s2d, S2D_PDATA_BAR + 0x20), 0x2484E880)  # S2D_BAR_NAME_CELLS
        self.assertEqual(self.word(self.s2d, S2D_PDATA_BAR + 0x28), jal(0x800838E8))
        self.assertEqual(self.word(self.s2d, S2D_PDATA_BAR + 0x40), 0x34060080)  # ori a2,0x80
        self.assertEqual(self.word(self.s2d, S2D_PDATA_BAR + 0x44), 0x34070010)  # ori a3,16
        self.assertEqual(self.word(self.s2d, S2D_PDATA_BAR + 0x50),
                         0x08000000 | ((S2D_WRITER >> 2) & 0x03FFFFFF))  # j S2D_CELLS_ROW
        self.assertEqual(self.word(self.s2d, S2D_PDATA_BAR + 0x54), 0)  # nop (delay)
        self.assertEqual(S2D_PDATA_BAR + 0x58, S2D_PDATA_LIST)

    def test_s2d_pdata_tail_runtime(self):
        """The real Persona Data tail: the shared name block gets the full
        demon name and the race row gets its six VWF cells."""
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import demons                                   # noqa: E402
        import skills                                   # noqa: E402
        import smallfont_variants                       # noqa: E402
        editable = smallfont_variants.editable_codes()
        regular, _compact = smallfont_variants.cell_codes()

        def uv(code):
            if code in editable:
                return smallfont_variants.cell_uv(regular[editable.index(code)])
            return ((code % 31) * 8, (code // 31) * 12)

        ident = 90                                      # Yomotsu Shikome: 15 glyphs
        codes = list(skills.encode_glyphs(ident, demons.record_en()[ident]))
        self.assertGreater(len(codes), 10)              # the head alone would cut it

        cpu = self.machine(self.s2d)
        frame = STACK - 0x80
        cpu.write(frame + 0x30, RETURN, 4)              # the tail's epilogue
        cpu.r[REG['sp']] = frame
        cpu.r[REG['s5']] = ident
        cpu.r[REG['s0']] = ident * 0x38
        cpu.start(S2D_PDATA_TAIL)
        cpu.run(RETURN, limit=200000)

        for i, code in enumerate(codes):
            base = S2D_PDATA_NAME_CELLS + i * 8
            u, v = uv(code)
            self.assertEqual(cpu.read(base, 1), u)
            self.assertEqual(cpu.read(base + 1, 1), v)
            self.assertEqual(cpu.read(base + 3, 1), self.s2d_widths[code] & 0xF)
        # the FF ended the row; the remaining cells stayed cleared
        self.assertEqual(cpu.read(S2D_PDATA_NAME_CELLS + len(codes) * 8, 1), 0xFF)

        race = cpu.read(S2D_DEMON_BASE + ident * 0x38 + 0xB, 1)
        race_codes = self.s2d[S2D_RACE_TABLE - OVERLAY_BASE + (race - 1) * 6:
                              S2D_RACE_TABLE - OVERLAY_BASE + (race - 1) * 6 + 6]
        for i, code in enumerate(race_codes):
            base = S2D_PDATA_RACE_CELLS + i * 8
            u, v = uv(code)
            self.assertEqual(cpu.read(base, 1), u)
            self.assertEqual(cpu.read(base + 1, 1), v)
            self.assertEqual(cpu.read(base + 3, 1), self.s2d_widths[code] & 0xF)

    # -------------------------------------------------------------
    # runtime: the writer and the advance hook on the R3000
    # -------------------------------------------------------------

    def machine(self, overlay):
        cpu = CPU()
        cpu.load(OVERLAY_BASE, overlay)
        size = struct.unpack_from('<I', self.exe, 0x1C)[0]
        cpu.load(EXE_BASE, self.exe[0x800:0x800 + size])
        cpu.r[REG['sp']] = STACK
        cpu.r[REG['ra']] = RETURN
        return cpu

    def test_adv_writer_cells(self):
        cpu = self.machine(self.adv)
        codes = [0x89, 0x91, 0x00, 0xFF]            # two glyphs, a blank, terminator
        cpu.load(BUF, bytes(0x100))
        cpu.load(BUF + 0x100, bytes(codes))
        cpu.r[REG['a0']] = BUF
        cpu.r[REG['a1']] = BUF + 0x100
        cpu.r[REG['a2']] = 0
        cpu.r[REG['a3']] = 3                        # the count, not the FF
        cpu.start(ADV_WRITER)
        cpu.run(RETURN, limit=20000)
        for i, code in enumerate(codes[:3]):
            base = BUF + i * 8
            self.assertEqual(cpu.read(base, 1), (code % 31) * 8)
            self.assertEqual(cpu.read(base + 1, 1), (code // 31) * 12)
            self.assertEqual(cpu.read(base + 3, 1), self.widths[code] & 0xF)
            self.assertEqual(cpu.read(base + 4, 2), 0x03C0)
            self.assertEqual(cpu.read(base + 6, 2), 0x01A0)
        # the fourth cell keeps its bytes: the FF ended the row

    def test_adv_writer_vwf_face(self):
        """Bit 7 of the page routes each glyph through the overlay's Latin
        selector; the advance stays this overlay's table and the page's low
        7 bits still set the tpage."""
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import smallfont_variants                         # noqa: E402
        editable = smallfont_variants.editable_codes()
        regular, _compact = smallfont_variants.cell_codes()

        def uv(code):
            if code in editable:
                return smallfont_variants.cell_uv(regular[editable.index(code)])
            return ((code % 31) * 8, (code // 31) * 12)

        glyphs = [0xB4, 0x32, 0x00]                       # O, g, the blank pad
        cpu = self.machine(self.adv)
        cpu.load(BUF, bytes(0x100))
        cpu.load(BUF + 0x100, bytes(glyphs + [0xFF]))
        cpu.r[REG['a0']] = BUF
        cpu.r[REG['a1']] = BUF + 0x100
        cpu.r[REG['a2']] = 0x80
        cpu.r[REG['a3']] = 3
        cpu.start(ADV_WRITER)
        cpu.run(RETURN, limit=20000)
        for i, code in enumerate(glyphs):
            base = BUF + i * 8
            u, v = uv(code)
            self.assertEqual(cpu.read(base, 1), u)
            self.assertEqual(cpu.read(base + 1, 1), v)
            self.assertEqual(cpu.read(base + 3, 1), self.widths[code] & 0xF)
            self.assertEqual(cpu.read(base + 6, 2), 0x01A0)

    def test_renderer_and_selector_share_t7(self):
        start = self.sym['sf_variant_uv_adv']
        end = self.sym['sf_variant_uv_end_adv']
        words = [self.word(self.adv, a) for a in range(start, end, 4)]
        self.assertIn(0x000F0842, words)                  # srl at,t7,1
        self.assertNotIn(0x8FA1002C, words)               # no lw at,0x2C(sp)
        call = jal(start)
        hits = [a for a in range(self.sym['sf_hook_bg_adv'],
                                 self.sym['sf_thunks_end_adv'], 4)
                if self.word(self.adv, a) == call]
        self.assertTrue(hits)
        for site in hits:
            # the delay slot supplies the tier the selector reads
            self.assertEqual(self.word(self.adv, site + 4), 0x8FAF002C)

    def test_adv_writer_count_zero(self):
        cpu = self.machine(self.adv)
        cpu.load(BUF, b'\xAA' * 8)
        cpu.r[REG['a0']] = BUF
        cpu.r[REG['a1']] = BUF
        cpu.r[REG['a2']] = 0
        cpu.r[REG['a3']] = 0
        cpu.start(ADV_WRITER)
        cpu.run(RETURN, limit=1000)
        self.assertEqual(cpu.read(BUF, 1), 0xAA)

    def test_adv_advance_hook(self):
        entry = BUF
        cell = BUF + 0x40
        cases = [
            (MARK, 0x00, 7, 107),     # marked, drawn: pen += the stored advance
            (0x0000, 0x00, 7, 108),   # unmarked: retail width
            (MARK, 0xFF, 7, 108),     # marked, cleared: retail width
        ]
        for mark, u, advance, want in cases:
            cpu = self.machine(self.adv)
            cpu.load(entry, struct.pack('<IHHHH', BUF + 0x80, 0, 0, 0, mark))
            cpu.load(cell, bytes([u, 0xFF, 0x1E, advance, 0xC0, 0x03, 0xA0, 0x01]))
            cpu.r[REG['t9']] = entry
            cpu.r[REG['s6']] = cell
            cpu.r[REG['s4']] = 100
            cpu.r[REG['a3']] = 8
            cpu.start(ADV_HOOK)
            cpu.run(RETURN, limit=100)
            self.assertEqual(cpu.r[REG['s4']], want, f'mark={mark:#x} u={u:#x}')

    def test_adv_full_name_via_scratch(self):
        """persona_name_copy into the frame scratch, then the writer into
        the cells: the bar's exact two-call flow."""
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import personas                                    # noqa: E402
        import smallfont_variants                           # noqa: E402
        editable = smallfont_variants.editable_codes()
        regular, _compact = smallfont_variants.cell_codes()

        def uv(code):
            if code in editable:
                return smallfont_variants.cell_uv(regular[editable.index(code)])
            return ((code % 31) * 8, (code // 31) * 12)

        rows = sorted(personas.record_en().items())
        self.assertTrue(rows)
        for ident, _text in rows[:4]:
            cpu = self.machine(self.adv)
            cells = BUF + 0x40
            scratch = BUF + 0x200
            cpu.load(cells, bytes(0x80))
            cpu.r[REG['a0']] = scratch
            cpu.r[REG['a1']] = ident
            cpu.start(0x80031878)                          # persona_name_copy
            cpu.run(RETURN, limit=5000)
            copied = bytes(cpu.read(scratch + i, 1) for i in range(16))
            self.assertTrue(any(copied))
            # the writer copies the scratch into the cells
            cpu.r[REG['a0']] = cells
            cpu.r[REG['a1']] = scratch
            cpu.r[REG['a2']] = 0x80                         # the bar's VWF face
            cpu.r[REG['a3']] = 16
            cpu.start(ADV_WRITER)
            cpu.run(RETURN, limit=20000)
            for i, code in enumerate(copied):
                base = cells + i * 8
                u, v = uv(code)
                self.assertEqual(cpu.read(base, 1), u)
                self.assertEqual(cpu.read(base + 1, 1), v)
                self.assertEqual(cpu.read(base + 3, 1), self.widths[code] & 0xF)

    def writer_row(self, cells, codes, count):
        """Run CellsWriteRow on its own cleared row: the expected bytes."""
        cpu = self.machine(self.adv)
        dst, src = 0x80190000, 0x80190100
        cpu.load(dst, bytes(cells))
        cpu.load(src, bytes(codes))
        cpu.r[REG['a0']] = dst
        cpu.r[REG['a1']] = src
        cpu.r[REG['a2']] = 0x80                     # the bar's VWF face
        cpu.r[REG['a3']] = count
        cpu.start(ADV_WRITER)
        cpu.run(RETURN, limit=20000)
        return bytes(cpu.read(dst + i, 1) for i in range(len(cells)))

    def test_adv_fusion_sites_write_arcana_and_name(self):
        """Each fusion write pair fills both rows.

        CellsWriteRow keeps its destination in t0 and reuses a0 for the
        glyph column, so the arcana row is only drawn when the site reloads
        its base after the name row. Run the real site over a cleared pair
        of rows and compare every byte with a direct writer run.
        """
        clear = bytes.fromhex('ffff1e000000ff01')
        cases = (
            # site, record register, name offset, kind offset, name codes, kind
            (ADV_FUSE_A, 's3', 8, 0x14,
             [0xA6, 0x39, 0x36, 0x3A, 0x40], 13),        # Ankou / DEATH
            (ADV_FUSE_B, 's4', 0x19, 0x25,
             [0xB2, 0xA6, 0xAC, 0xAE, 0xA8, 0xAE, 0xA6, 0xB3], 1),  # MAGICIAN
        )
        for site, reg, name_off, kind_off, codes, kind in cases:
            cpu = self.machine(self.adv)
            record = BUF
            cpu.load(record, bytes(0x40))
            cpu.load(record + name_off, bytes(codes + [0xFF]))
            cpu.load(record + kind_off, bytes([kind]))
            cpu.load(ADV_CELLS, clear * 10)
            cpu.load(ADV_NAME_CELLS, clear * 16)
            cpu.r[REG[reg]] = record
            # the site falls through into the next retail write; stop it
            # there (ra cannot be used: the site's last jal writes it)
            cpu.r[REG['s5']] = RETURN
            cpu.load(site + 0x4C, struct.pack('<II', 0x02A00008, 0))  # jr s5
            cpu.start(site)
            cpu.run(RETURN, limit=20000)

            copied = bytes(cpu.read(STACK + i, 1) for i in range(16))
            self.assertEqual(copied[:len(codes)], bytes(codes))
            self.assertEqual(copied[len(codes):], bytes(16 - len(codes)))

            arcana = bytes(cpu.read(ADV_CELLS + i, 1) for i in range(80))
            name = bytes(cpu.read(ADV_NAME_CELLS + i, 1) for i in range(128))
            label = self.adv[ADV_KIND_LABELS + (kind - 1) * 10 - OVERLAY_BASE:
                             ADV_KIND_LABELS + (kind - 1) * 10 - OVERLAY_BASE + 10]
            self.assertEqual(arcana, self.writer_row(clear * 10, label, 10),
                             f'{site:#x}: arcana row')
            self.assertNotEqual(arcana[:2], b'\xff\xff',
                                f'{site:#x}: the arcana row was never drawn')
            self.assertEqual(name, self.writer_row(clear * 16,
                                                   copied + b'\xff', 16),
                             f'{site:#x}: name row')

    def test_persona_name_copy_uses_the_retail_record_key(self):
        """The bar hands persona_name_copy the same key retail indexes with.

        Retail reads a Persona name at 0x8004B0CC + 8 + key*0x2C. Ogun is
        key 51 and Otohime key 52, so copying key 51 must not read 52 (the
        old status bar passed key+1 and showed the next Persona).
        """
        for key, neighbour in ((51, 52), (52, 51)):
            cpu = self.machine(self.adv)

            def field(k):
                return 0x8004B0CC + 8 + k * 0x2C

            cpu.load(field(key), bytes([0x20 + key, 0x21 + key, 0xFF]))
            cpu.load(field(neighbour), bytes([0x60 + neighbour, 0x61 + neighbour, 0xFF]))
            scratch = BUF
            cpu.r[REG['a0']] = scratch
            cpu.r[REG['a1']] = key
            cpu.start(0x80031878)                          # persona_name_copy
            cpu.run(RETURN, limit=5000)
            copied = bytes(cpu.read(scratch + i, 1) for i in range(16))
            self.assertEqual(copied[:2], bytes([0x20 + key, 0x21 + key]))
            self.assertEqual(copied[2:], bytes(14))

    def test_dng_advance_hook(self):
        entry = BUF
        cell = BUF + 0x40
        cpu = self.machine(self.dng)
        cpu.load(entry, struct.pack('<IHHHH', BUF + 0x80, 0, 0, 0, MARK))
        cpu.load(cell, bytes([0x12, 0xFF, 0x1E, 6, 0xC0, 0x03, 0xA0, 0x01]))
        cpu.r[REG['t9']] = entry
        cpu.r[REG['s6']] = cell
        cpu.r[REG['s4']] = 40
        cpu.r[REG['a3']] = 8
        cpu.start(DNG_HOOK)
        cpu.run(RETURN, limit=100)
        self.assertEqual(cpu.r[REG['s4']], 46)

    def test_dng_writer_cells(self):
        cpu = self.machine(self.dng)
        codes = [0x89, 0x00, 0xFF]
        cpu.load(BUF, bytes(0x100))
        cpu.load(BUF + 0x100, bytes(codes))
        cpu.r[REG['a0']] = BUF
        cpu.r[REG['a1']] = BUF + 0x100
        cpu.r[REG['a2']] = 0
        cpu.r[REG['a3']] = 2
        cpu.start(DNG_WRITER)
        cpu.run(RETURN, limit=20000)
        for i, code in enumerate(codes[:2]):
            base = BUF + i * 8
            self.assertEqual(cpu.read(base, 1), (code % 31) * 8)
            self.assertEqual(cpu.read(base + 3, 1), self.dng_widths[code] & 0xF)

    def test_dng_writer_vwf_face(self):
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import smallfont_variants                         # noqa: E402
        editable = smallfont_variants.editable_codes()
        regular, _compact = smallfont_variants.cell_codes()
        glyphs = [0xAD, 0x39]                             # H, n
        cpu = self.machine(self.dng)
        cpu.load(BUF, bytes(0x100))
        cpu.load(BUF + 0x100, bytes(glyphs + [0xFF]))
        cpu.r[REG['a0']] = BUF
        cpu.r[REG['a1']] = BUF + 0x100
        cpu.r[REG['a2']] = 0x80
        cpu.r[REG['a3']] = 2
        cpu.start(DNG_WRITER)
        cpu.run(RETURN, limit=20000)
        for i, code in enumerate(glyphs):
            base = BUF + i * 8
            u, v = smallfont_variants.cell_uv(regular[editable.index(code)])
            self.assertEqual(cpu.read(base, 1), u)
            self.assertEqual(cpu.read(base + 1, 1), v)
            self.assertEqual(cpu.read(base + 3, 1), self.dng_widths[code] & 0xF)
            self.assertEqual(cpu.read(base + 6, 2), 0x01A0)

    def test_s2d_advance_hook(self):
        entry = BUF
        cell = BUF + 0x40
        cpu = self.machine(self.s2d)
        cpu.load(entry, struct.pack('<IHHHH', BUF + 0x80, 0, 0, 0, MARK))
        cpu.load(cell, bytes([0x12, 0xFF, 0x1E, 6, 0xC0, 0x03, 0xA0, 0x01]))
        cpu.r[REG['t9']] = entry
        cpu.r[REG['s6']] = cell
        cpu.r[REG['s4']] = 40
        cpu.r[REG['a3']] = 8
        cpu.start(S2D_HOOK)
        cpu.run(RETURN, limit=100)
        self.assertEqual(cpu.r[REG['s4']], 46)

    def test_s2d_writer_cells(self):
        cpu = self.machine(self.s2d)
        codes = [0x89, 0x00, 0xFF]
        cpu.load(BUF, bytes(0x100))
        cpu.load(BUF + 0x100, bytes(codes))
        cpu.r[REG['a0']] = BUF
        cpu.r[REG['a1']] = BUF + 0x100
        cpu.r[REG['a2']] = 0
        cpu.r[REG['a3']] = 2
        cpu.start(S2D_WRITER)
        cpu.run(RETURN, limit=20000)
        for i, code in enumerate(codes[:2]):
            base = BUF + i * 8
            self.assertEqual(cpu.read(base, 1), (code % 31) * 8)
            self.assertEqual(cpu.read(base + 3, 1), self.s2d_widths[code] & 0xF)

    def test_s2d_writer_vwf_face(self):
        sys.path.insert(0, str(ROOT / 'src/injection_tools'))
        import smallfont_variants                         # noqa: E402
        editable = smallfont_variants.editable_codes()
        regular, _compact = smallfont_variants.cell_codes()
        glyphs = [0xAD, 0x39]                             # H, n
        cpu = self.machine(self.s2d)
        cpu.load(BUF, bytes(0x100))
        cpu.load(BUF + 0x100, bytes(glyphs + [0xFF]))
        cpu.r[REG['a0']] = BUF
        cpu.r[REG['a1']] = BUF + 0x100
        cpu.r[REG['a2']] = 0x80
        cpu.r[REG['a3']] = 2
        cpu.start(S2D_WRITER)
        cpu.run(RETURN, limit=20000)
        for i, code in enumerate(glyphs):
            base = BUF + i * 8
            u, v = smallfont_variants.cell_uv(regular[editable.index(code)])
            self.assertEqual(cpu.read(base, 1), u)
            self.assertEqual(cpu.read(base + 1, 1), v)
            self.assertEqual(cpu.read(base + 3, 1), self.s2d_widths[code] & 0xF)
            self.assertEqual(cpu.read(base + 6, 2), 0x01A0)


if __name__ == '__main__':
    unittest.main()
