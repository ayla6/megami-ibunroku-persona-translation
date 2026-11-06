;; =============================================================
;; small-font VWF kit constants (shared: the recorders and renderers in
;; the three overlays, plus the resident parts in FONT.BIN and the sorter
;; stubs in SLPS, all read these; defined once because armips symbols are
;; global). See vwf/smallfont.asm (recorder + renderer), vwf/sf_font.asm
;; (the resident sort gate) and vwf/sf_stubs.asm (the sorter entries).
;;
;; The kit renders variable-width small-font rows with the game's own
;; GPU path: the overlay's writer hook RECORDS the row, and the resident
;; sf_sort hooks - hung on the two libgs background sorters - clear the
;; recorded cells immediately before the retail sorter walks that map,
;; then re-emit each recorded row as one sprite packet at its
;; pen offset, with u/v/clut/tpage read from the same cell table the
;; retail renderer uses. Pixels come from the font page in VRAM;
;; nothing composites on the CPU and no glyph bitmaps are stored.
;;
;; THE INVARIANT: cells are cleared only by the call that draws them, in
;; the same frame, for the map it is sorting. Anything else would leave
;; retail text erased on a screen the kit does not serve, so the recorder never touches
;; the map and a sorter call that cannot draw leaves every row alone.
;; =============================================================

;; Every small-font caller uses this layout rule. Screen adapters supply only
;; their current pen and the existing sf_width.bin byte; no local width policy.
.macro sf_glyph_layout, metric, pen, bearing, left, advance
    srl     bearing, metric, 4
    subu    left, pen, bearing
    andi    advance, metric, 0x0F
.endmacro

;; Field Latin cells are left-normalised in their own atlas. The two nibbles
;; hold normal/compact advances; stage 1 changes spaces only, stage 2 selects
;; the compact artwork and its measured advance, always retaining a letter gap.
;; The word space is the normal advance halved per stage (4 -> 2 -> 1 px), so
;; its packed high nibble is not read: stage 2's 1 px space is what makes the
;; compact face fit, and the porter's measurement uses the same shift.
.macro sf_field_metric, metric, code, tier, advance
    bnez    code, @@field_glyph
    nop
    andi    advance, metric, 0x0F       ; the normal word space (4 px)
    srlv    advance, advance, tier      ; 4 -> 2 -> 1 px
    b       @@field_done
    nop
@@field_glyph:
    andi    at, tier, 2
    sll     at, at, 1                   ; tier 2 selects the compact nibble
    srlv    advance, metric, at
    andi    advance, advance, 0x0F
@@field_done:
.endmacro

;; a damaged kit (game scribble, bad registration) degrades to the
;; retail fixed-width row: the recorder blanks nothing, the sorters
;; draw the map as the game wrote it
SF_ENG_MAGIC       equ 0x31574653          ; "SFW1"

;; the registration guard: one word the build places immediately before
;; every entry a registration cell can name (each overlay's renderer, and
;; both FONT.BIN replays). The resident gate (vwf/sf_font.asm, in
;; FONT.BIN) jumps through a registration cell only while the word before
;; the entry still reads this: an EXE loaded straight over the overlays
;; (OPEN.EXE & co, which bypass the game's overlay loader and so never
;; trip any id gate) wipes it, and the sorter call falls through to the
;; retail replay. 16-bit, because the stubs carry it in one instruction.
SF_REG_MAGIC       equ 0x00005245          ; "RE"

;; recorder config block, one per overlay (adv/dng/s2d/smallfont.asm), in
;; the first 0x20 bytes of that overlay's renderer dead run
SF_CFG_MAGIC       equ 0x00                ; SF_ENG_MAGIC
SF_CFG_MAP_BASE    equ 0x04                ; the text map's cell array (per overlay)
SF_CFG_TABLE       equ 0x08                ; the row table (this overlay's sf_table_<ovl>)
SF_CFG_VICTIM      equ 0x0C                ; u16: the next slot a new row reuses
SF_CFG_BUFS        equ 0x10                ; the packet-buffer pair (per overlay)
SF_CFG_WIDTHS      equ 0x14                ; the advance table (this overlay's sf_widths_<ovl>)
SF_CFG_POOL        equ 0x18                ; the affinity pool (this overlay's sf_pool_<ovl>)
SF_CFG_FALLBACK    equ 0x1C                ; the retail loop's resume address (per overlay)
SF_CFG_END         equ 0x20

;; the kit's state: each overlay's own sf_state_<ovl>, in its extension
;; data (loaded and zeroed with the overlay), so a swap can never leave a
;; stale id or cursor behind. The resident registration words hold the
;; live overlay's renderer entry (sf_hook_bg / sf_hook_fastbg).
SF_ST_ID           equ 0x00                ; the overlay slot id at registration
SF_ST_LAST_OT      equ 0x04                ; the ot the current buffer belongs to
SF_ST_CUR_BUF      equ 0x08                ; 0/1 - toggles when the ot changes
SF_ST_BUF_PTR      equ 0x0C                ; absolute write cursor; 0 = start
SF_ST_DIAG_HN      equ 0x10                ; diag: hook entries
SF_ST_DIAG_HA      equ 0x14                ; diag: last call's bg / ot / pri
SF_ST_BUFS         equ 0x20                ; this overlay's packet-buffer pair
SF_ST_END          equ 0x24

;; per-overlay row table, loaded and zeroed with the overlay
SF_ROWS            equ 64                  ; bounded simultaneous rows; tables ride each overlay
SF_NAME_BYTES      equ 24                  ; full terminated name scratch: SKILL_MAXLEN
                                           ; glyphs (23) + FF; covers item/demon (20+FF)
                                           ; and Persona (16+FF) too
SF_ROW_REC         equ 56                  ; bytes per record (8 header + 48 codes)
SF_REC_DST         equ 0x00                ; u32 first map cell (short*); 0 = slot free
SF_REC_COUNT       equ 0x04                ; u16 cells (the walk's length)
SF_REC_OWNED       equ 0x8000              ; bit 15 of the count: the sorter that
                                           ; serves the map cleared these cells
                                           ; and will draw them in the same frame
                                           ; (set by the pre-pass, cleared by the
                                           ; recorder's commit and by every sort)
SF_REC_PAD         equ 0x06                ; u16: the overlay id that wrote the record
                                           ; (low byte) | the row's CLUT bank << 8 |
                                           ; the condensed tier << 10;
                                           ; bit 15: producer says field is centered
;; SF_REC_PAD's high byte (the second byte of the halfword)
SF_REC_BANK_MASK   equ 0x03                ; CLUT bank 0-3
SF_REC_TIER_SHIFT  equ 2                   ; tier 0-2 in bits 2-3
SF_REC_TIER_MASK   equ 0x0C
SF_REC_CENTERED    equ 0x80                ; the producer's centered-field flag
SF_REC_CODES       equ 0x08                ; u8 x (SF_ROW_REC - SF_REC_CODES): cell
                                           ; indices (code+base), 0xFF after the end
SF_REC_CODE_MAX    equ SF_ROW_REC - SF_REC_CODES - 1  ; glyphs that fit beside the 0xFF
SF_TAB             equ 0xD7                ; blank first cell of the next atlas bank
SF_TABLE_SIZE      equ SF_ROWS * SF_ROW_REC

.if SF_REC_CODE_MAX != 47
    .error "smallfont_defs: SF_REC_CODE_MAX must stay 47 (48-byte code area, 0xFF terminator, the affinity head + pool tail cap)"
.endif

.if (SF_ROWS & (SF_ROWS - 1)) != 0
    .error "smallfont_defs: SF_ROWS must be a power of two (the victim index wraps with andi)"
.endif
.if SF_ROW_REC != 56
    .error "smallfont_defs: SF_ROW_REC must stay 56 (the recorder's slot scan and the renderer's chunk walk assume it)"
.endif

;; per-frame GPU packet buffers (per overlay, double-buffered with the
;; game's g_ot[2]; one packet per row: tag + shared draw mode + 4 words per
;; visible glyph)
SF_BUF_SIZE        equ 0x1200              ; complete visible rows only; overflow retains retail text
SF_BUFS            equ 2

.if SF_BUF_SIZE != 0x1200
    .error "smallfont_defs: the renderer computes buffer + index*SF_BUF_SIZE with shifts 12 and 9"
.endif
.if SF_BUFS != 2
    .error "smallfont_defs: the buffer toggle is a single xori (two buffers)"
.endif

;; the affinity row store (SLPS 0x8004C848): 120 records of 25 codes. A
;; record's own 25 cells are the HEAD of its line; the pool carries the
;; remainder of a line longer than that (smallfont_vwf.write_pool), so the
;; record is never a truncation.
SF_AFFINITY_TABLE equ 0x8004C848
SF_RECORDS        equ 120
SF_ROW_BYTES      equ 0x19
SF_POOL_INDEX     equ 240                 ; 120 x u16 text offset, 0xFFFF = none
SF_POOL_LINE_MAX  equ 47                  ; one drawn row: head + pool tail
                                          ; (the recorder's FF-terminated code list)

;; row geometry (persona/common/tilemap.h)
SF_CELL_W         equ 8
SF_CELL_H         equ 12
SF_MAP_W          equ 40

.if SF_CELL_W != 8
    .error "smallfont_defs: the renderer packs col*SF_CELL_W with sll 3 and checks u with andi SF_CELL_W-1"
.endif
.if SF_CELL_H != 12
    .error "smallfont_defs: the renderer packs row*SF_CELL_H as row*4 + row*8 and checks v with divu 12"
.endif

;; the text atlas: cell c sits at u = (c % 31) * 8, v = (c / 31) * 12
;; (cellsinit.c); a cell qualifies as a glyph only when it names this
;; page on this grid - UI word-art and icons live elsewhere and their
;; rows stay retail. The atlas holds SF_BANKS copies of the SAME
;; SF_GLYPHS cells, one per CLUT bank: cell = bank * SF_GLYPHS + glyph
;; (cellsinit.c TEXT_ATLAS[j] = base + j * TEXT_CELLS). The bank only
;; changes the cba; the u/v (and so the advance) are the glyph's own.
SF_GLYPHS         equ 215                 ; TEXT_CELLS: glyphs in one bank
SF_BANKS          equ 4                   ; TEXT_BANKS: CLUT copies of them
SF_CELLS          equ SF_GLYPHS * SF_BANKS ; the atlas cell count (860)
SF_CODES          equ 256                 ; sf_width.bin bytes (indexed by glyph)
SF_TPAGE          equ 0x1E                ; the font page: VRAM halfword x 896, y 256

.if SF_GLYPHS != 215
    .error "smallfont_defs: SF_GLYPHS must stay 215 (cellsinit.c TEXT_CELLS)"
.endif
.if SF_GLYPHS > SF_CODES
    .error "smallfont_defs: the atlas outgrew sf_width.bin (the width table is indexed by glyph)"
.endif

;; the kit's live patches: the writer hook per overlay and the sorter
;; entry jumps. The switch is SF_VWF - src/injection_tools/features.py writes
;; build/features.inc, main.asm includes it before this file, and 0 means the
;; kit contributes NO bytes anywhere (writer hook, sorter stubs, FONT.BIN
;; anchor and the per-overlay blocks are all skipped by that one flag).
;; Never set it here: `build.py --no-sf-kit` is the way to turn the kit off.

;; renderer internals (vwf/sf_font.asm + the overlay renderer)
SF_OT_ENTRY        equ 0x00                ; libgs OT entry: (num<<24) | (addr & 0xFFFFFF)
SF_PACKET_HEAD     equ 8                   ; a row packet's tag + one shared draw mode
SF_SPRITE_BYTES    equ 16                  ; four GP0 words per glyph after the header
SF_SPRT_CODE       equ 0x64                ; textured, opaque; transparency comes from the CLUT's STP

.if SF_PACKET_HEAD + SF_SPRITE_BYTES != 24
    .error "smallfont_defs: the capacity guard checks 24 bytes before a row's first sprite"
.endif
SF_DR_TPAGE        equ 0xE1000200          ; draw-mode word, low bits = the cell's tpage
