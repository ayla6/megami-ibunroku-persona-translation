;; =============================================================
;; Variable-width small-font rows - the 8x12 menu font
;; (the overlay-side kit; tools/smallfont_vwf.py emits one copy per
;;  overlay - build/smallfont_<ovl>.asm - with the labels suffixed
;;  and its .orgs in the overlay's bounded code partitions: the recorder
;;  at HELP_ADDR, the renderer (+ thunks) at ROW_ADDR + 0x24, with
;;  the config in the run's first 0x20 bytes and the kit's data in
;;  the overlay's extension. The never-wiped resident anchor (the
;;  sort gate + retail replays) is vwf/sf_font.asm, in FONT.BIN;
;;  the sorter stubs are vwf/sf_stubs.asm.)
;;
;; The retail TileMapWriteRow loop writes `code + base` into `count`
;; cells of the map row at dst. The RECORDER (part 1) takes the same
;; arguments and:
;;   * validates the row is small-font text - every cell it names
;;     must be one of the atlas's own glyphs (SF_BANKS copies of the
;;     same SF_GLYPHS 8x12 cells, one per CLUT bank); anything else
;;     leaves through the verbatim writer;
;;   * retains complete terminated names independently of the caller's
;;     fixed-cell count; drawing is bounded by the actual map row;
;;   * resolves affinity records through the pool (the record's 25 cells
;;     are the head of its line; a pool tail continues a longer line);
;;   * records glyph indices and preserves the retail map write. The sorter
;;     serving that map clears only rows it claims immediately before sorting;
;;     paths without that sorter retain the current fixed-width text;
;;   * registers the shared state with the resident stubs under the
;;     overlay slot's own id word, and tags the record with that id.
;; The RENDERER (part 2, entered from the stubs) runs after the real
;; sorter and chains one textured sprite per glyph onto the layer's
;; own OT entry - u/v/clut/tpage copied from the map's cell table,
;; pixels straight from the font page in VRAM. A row whose blanks
;; someone rewrote, or that another overlay wrote, is dropped; a
;; damaged kit (bad magic / stale id) writes the row the way the game
;; does.
;; =============================================================

;; -------------------------------------------------------------
;; PART 1 - the recorder (build copy: .org HELP_ADDR).
;; sf_record(src [a0], dst [a1], base [a2], count [a3]; t0 = config)
;; s0-s3 kept; t/v/a scratch. The fallback is the retail loop itself:
;; the hook replaced only its first three words, so the recorder
;; restores its frame and jumps to SF_CFG_FALLBACK (the loop's body).
;; -------------------------------------------------------------
sf_record:
    addiu   sp, sp, -0x30
    sw      ra, 0x2C(sp)
    sw      s0, 0x28(sp)
    sw      s1, 0x24(sp)
    sw      s2, 0x20(sp)
    sw      s3, 0x1C(sp)
    move    s0, a0                      ; src
    move    s1, a1                      ; dst
    move    s2, a2                      ; base
    andi    t1, a3, 0xC000              ; producer's centered/fixed-cell flags
    sw      t1, 0x10(sp)
    andi    s3, a3, 0x3FFF              ; count, without metadata bits
    sw      zero, 0x18(sp)              ; optional complete Persona source
    sw      zero, 0x0C(sp)              ; affinity pool tail the walk continues with

    beqz    s3, @@out                   ; nothing to write (also guards the
    nop                                 ; retail loop's missing count check)
    ;; ---- the kit must be this build's ----
    lw      t1, SF_CFG_MAGIC(t0)
    li      t2, SF_ENG_MAGIC
    bne     t1, t2, @@verbatim
    nop
    ;; ---- an item record's 10-byte head resolves to the FULL name ----
    ;; Not every writer goes through DrawItemName: EquipDrawCompare draws
    ;; g_item_defs[id].name straight to the map, which is only the head.
    ;; Any source that is exactly an item record's name field gets the same
    ;; treatment as DrawItemName's hook: the whole name is built in the
    ;; scratch (head + tail bank) and the walk reads that.
    li      t3, ITEM_NAME_BASE + ITEM_NAME_STRIDE   ; id 1's name field
    subu    t4, s0, t3
    sltiu   t5, t4, (ITEM_RECORDS - 1) * ITEM_NAME_STRIDE
    beqz    t5, @@not_item
    andi    t5, t4, ITEM_NAME_STRIDE - 1
    bnez    t5, @@not_item
    srl     a1, t4, 5                   ; (delay) id - 1
    addiu   a1, a1, 1                   ; the 1-based id
    la      a0, sf_name_scratch
    jal     item_name_copy              ; clobbers v0/v1/a0-a2/at only: t0 (config) survives
    nop
    lw      ra, 0x2C(sp)                ; @@out returns through ra
    la      s0, sf_name_scratch
@@not_item:
    ;; ---- a demon record's 10-byte head resolves to the FULL name ----
    ;; Fusion/card rows copy the record's ten cells straight to the map, so
    ;; a name over ten glyphs would draw only its head. Any source that is
    ;; exactly a demon record's name field gets the full name in the
    ;; scratch, the same shape as DrawItemName's hook.
    li      t3, DEMON_NAME_BASE + DEMON_NAME_STRIDE   ; id 1's name field
    subu    t4, s0, t3
    sltiu   t5, t4, DEMON_RECORDS * DEMON_NAME_STRIDE
    beqz    t5, @@not_demon
    li      t5, DEMON_NAME_STRIDE
    divu    t4, t5
    nop
    nop
    mfhi    t5
    bnez    t5, @@not_demon
    nop
    mflo    a1
    addiu   a1, a1, 1                   ; the 1-based id
    la      a0, sf_name_scratch
    jal     demon_name_copy             ; clobbers v0/v1/a0-a2/at only
    nop
    lw      ra, 0x2C(sp)                ; @@out returns through ra
    la      s0, sf_name_scratch
@@not_demon:
    ;; Master Persona name fields are ten-byte heads, followed by tails in
    ;; the master record or overflow bank. Resolve only exact field addresses;
    ;; the original source still owns the retail write and its extent.
    li      t3, PERSONA_RECORDS_ADDR + PERSONA_NAME + 0x2C
    subu    t4, s0, t3
    sltiu   t5, t4, 100 * 0x2C
    beqz    t5, @@not_persona
    li      t5, 0x2C
    divu    t4, t5
    nop
    nop
    mfhi    t5
    bnez    t5, @@not_persona
    nop
    mflo    a1
    addiu   a1, a1, 1
    la      a0, sf_name_scratch
    jal     persona_name_copy
    nop
    lw      ra, 0x2C(sp)
    la      t3, sf_name_scratch
    li      t4, 0xFF
    sb      t4, PERSONA_MAXLEN(t3)
    sw      t3, 0x18(sp)
@@not_persona:
.if ITEM_NAME_STRIDE != 32
    .error "smallfont: the item id is the record offset >> 5"
.endif
    ;; ---- the walk's cap: a full name is one FF-terminated string;
    ;; an affinity head + pool tail has SF_POOL_LINE_MAX ----
    li      t8, SF_NAME_BYTES
    la      t3, sf_name_scratch         ; this overlay's full-name scratch
    ;; a full-name row's budget is the caller's own retail footprint (8 px
    ;; per cell); a centered field keeps its natural advances, because its
    ;; origin is derived from them
    lw      t4, 0x10(sp)
    sll     t1, s3, 3
    bne     s0, t3, @@bare_row
    nop
    beqz    t4, @@row_budget
    nop
@@bare_row:
    move    t1, zero
@@row_budget:
    sw      t1, 0x08(sp)
    beq     s0, t3, @@have_cap
    nop
    move    t8, s3
@@have_cap:
    sltiu   t3, t8, SF_REC_CODE_MAX + 1 ; the code area holds SF_REC_CODE_MAX glyphs
    bnez    t3, @@cap_ok                ; plus the 0xFF end marker
    nop                                 ; (not the delay slot: a clamp there
    li      t8, SF_REC_CODE_MAX         ;  would overwrite the cap every time)
@@cap_ok:

    ;; ---- an affinity record's own cells are the head of its line; a pool
    ;; tail continues it (the record cannot hold a longer line) ----
    li      t3, SF_AFFINITY_TABLE
    sltu    t4, s0, t3
    bnez    t4, @@walk0
    nop
    addiu   t4, t3, SF_RECORDS * SF_ROW_BYTES
    sltu    t4, s0, t4
    beqz    t4, @@walk0
    nop
    subu    t4, s0, t3
    li      t5, SF_ROW_BYTES
    divu    t4, t5
    lw      t3, SF_CFG_POOL(t0)         ; the pool base
    nop
    nop
    mflo    t4                          ; the record index
    sll     t5, t4, 1
    addu    t5, t3, t5
    lhu     t4, 0(t5)                   ; the tail's offset
    li      t5, 0xFFFF
    beq     t4, t5, @@walk0
    nop
    addiu   t3, t3, SF_POOL_INDEX
    addu    t4, t3, t4
    sw      t4, 0x0C(sp)                ; the walk continues here after the head
    li      t8, SF_POOL_LINE_MAX        ; head + tail, ended by the tail's own FF
@@walk0:
    ;; Retire records only for cells this write actually touches. Pool/name
    ;; source resolution is complete here; an early FF leaves later cells alone.
    move    t6, s0
    move    t4, s3
    li      t2, 0xFF
@@write_extent:
    lbu     t1, 0(t6)
    addiu   t6, t6, 1
    beq     t1, t2, @@write_terminated
    nop
    addiu   t4, t4, -1
    bnez    t4, @@write_extent
    nop
    b       @@write_measured
    nop
@@write_terminated:
    addiu   t6, t6, -1
@@write_measured:
    subu    t6, t6, s0
    sw      t6, 0x14(sp)                ; actual retail cells, including early FF
    beqz    t6, @@out                   ; empty source performs no map write
    sll     t6, t6, 1
    addu    t6, s1, t6                  ; exclusive end of the actual logical write
    lw      t5, SF_CFG_TABLE(t0)
    li      t4, SF_ROWS
@@invalidate:
    lw      t1, SF_REC_DST(t5)
    lhu     t2, SF_REC_COUNT(t5)
    beqz    t1, @@invalidate_next
    andi    t2, t2, SF_REC_OWNED - 1
    sll     t2, t2, 1
    addu    t2, t1, t2
    sltu    t3, s1, t2
    beqz    t3, @@invalidate_next
    sltu    t3, t1, t6
    beqz    t3, @@invalidate_next
    nop
    sw      zero, SF_REC_DST(t5)
@@invalidate_next:
    addiu   t4, t4, -1
    bnez    t4, @@invalidate
    addiu   t5, t5, SF_ROW_REC

    ;; ---- reuse a retired/free slot before evicting another live row ----
    lw      t3, SF_CFG_TABLE(t0)
    nop
    move    t5, t3
    li      t4, SF_ROWS
@@scan:
    lw      t6, SF_REC_DST(t5)
    nop
    beq     t6, s1, @@slot
    nop
    beqz    t6, @@slot
    nop
    addiu   t4, t4, -1
    bnez    t4, @@scan
    addiu   t5, t5, SF_ROW_REC
    lhu     t4, SF_CFG_VICTIM(t0)
    nop
    addiu   t4, t4, 1
    andi    t4, t4, SF_ROWS - 1         ; wrap (SF_ROWS is a power of two)
    sh      t4, SF_CFG_VICTIM(t0)
    sll     t5, t4, 6                   ; slot * 64
    sll     t6, t4, 3                   ; slot * 8
    subu    t5, t5, t6                  ; * SF_ROW_REC (56)
    addu    t5, t3, t5                  ; the victim slot
@@slot:
    sw      zero, SF_REC_DST(t5)        ; uncommitted until the row fits

    ;; ---- validate + measure the row into the slot ----
    move    t6, s0
    lw      t3, 0x18(sp)
    nop
    beqz    t3, @@walk_source_ready
    nop
    move    t6, t3
    li      t8, PERSONA_MAXLEN
@@walk_source_ready:
    move    t7, zero                    ; glyphs consumed; first glyph uses bank setup
    lw      a2, SF_CFG_MAP_BASE(t0)
    addiu   a3, t5, SF_REC_CODES
    li      v1, 0xFF                    ; the list terminator (retail's own)
@@walk:
    beq     t7, t8, @@committed
    nop
    ;; the record's own cells end the head: a pooled line continues in the
    ;; pool tail (0x0C(sp) = 0 when this row has none, so every other row
    ;; costs one not-taken load+branch per glyph). t4 is the row's bank and
    ;; must survive to @@committed; t1/t3 are the walk's scratch.
    lw      t3, 0x0C(sp)
    nop
    beqz    t3, @@walk_read
    nop
    li      t1, SF_ROW_BYTES
    bne     t7, t1, @@walk_read
    nop
    move    t6, t3
    sw      zero, 0x0C(sp)
@@walk_read:
    lbu     v0, 0(t6)
    addiu   t6, t6, 1                   ; (load delay) the source cursor
    beq     v0, v1, @@committed         ; the raw code, before the base lands
    addu    v0, v0, s2                  ; (delay) the cell index
    bnez    s2, @@ordinary_cell
    li      t1, SF_TAB
    bne     v0, t1, @@ordinary_cell
    nop
    beqz    t7, @@verbatim
    nop
    b       @@bank_ok
    nop
@@ordinary_cell:
    sltiu   t1, v0, SF_CELLS            ; the atlas (SF_BANKS x SF_GLYPHS); past
    beqz    t1, @@verbatim              ;   it live the label/icon strips, word
    sll     t1, v0, 3                   ;   art this writer must leave alone
    addu    t1, t1, a2
    lhu     t2, 6(t1)
    li      t3, SF_TPAGE
    bne     t2, t3, @@verbatim
    lbu     t2, 0(t1)                   ; (delay) the cell's u
    lbu     v1, 1(t1)                   ; cell v; t9 retains the row's bank base
    andi    t2, t2, SF_CELL_W - 1
    bnez    t2, @@verbatim
    li      t3, SF_CELL_H               ; (delay)
    divu    v1, t3
    nop                                 ; division result latency
    li      t3, SF_GLYPHS               ; (delay) a bank's cell count
    mfhi    v1                          ; v % 12: a row start only
    bnez    v1, @@verbatim
    li      v1, 0xFF                    ; (delay) restore the source terminator
    ;; The banks alias the same cells under another CLUT: cell = bank *
    ;; SF_GLYPHS + glyph (cellsinit.c lays the atlas out that way). The
    ;; width table is the glyph's (shared art); the record keeps the
    ;; glyph in its code byte and the row's bank for cba lookup. Only the
    ;; row's first glyph divides; every later one must land in the same
    ;; bank, because a run that crosses one mixes CLUTs in a row.
    bnez    t7, @@same_bank
    nop
    divu    v0, t3
    nop
    nop
    mflo    t4                          ; the row's bank
    mfhi    v0                          ; the glyph
    multu   t4, t3
    nop                                 ; the multiplier's result latency
    b       @@bank_ok
    mflo    t9                          ; the bank's first cell
@@same_bank:
    subu    v0, v0, t9                  ; the glyph within the row's bank
    sltiu   t3, v0, SF_GLYPHS
    beqz    t3, @@verbatim
    nop
@@bank_ok:
    sb      v0, 0(a3)                   ; preserve wording; map geometry bounds drawing
    addiu   a3, a3, 1
    b       @@walk
    addiu   t7, t7, 1                   ; (delay) count this glyph

@@committed:
    beqz    t7, @@out
    sb      v1, 0(a3)                   ; (delay slot) terminate the code list (the renderer
                                        ; reads it until 0xFF; a reused slot
                                        ; still holds the old row's codes)
    ;; The cells this row covers are the glyphs the walk consumed - the retail
    ;; loop puts one glyph in each cell and stops at 0xFF or at the caller's
    ;; count. Not the text's pixel extent: a wide glyph spans more than one
    ;; cell and a narrow one less, and a row blanked only to its pixel width
    ;; leaves the retail glyphs past it on screen. The cells are NOT cleared
    ;; here: the only thing allowed to clear a cell is the sorter that is about
    ;; to draw it (the renderer's pre-pass below), so a screen drawn by any
    ;; other path keeps the game's own row instead of a blank. Every recorded
    ;; glyph advances >= 1 px (sf_width.bin), so a run that got here has n >= 1.
    sltu    t2, s3, t7                  ; walked past the caller's own run?
    beqz    t2, @@commit
    move    t2, t7                      ; (delay slot: one cell per glyph,
    move    t2, s3                      ;  then clamped to the caller's run)
@@commit:
    lw      t3, 0x18(sp)
    nop
    beqz    t3, @@commit_count_ready
    nop
    lw      t2, 0x14(sp)                ; the original Persona head's write extent
    nop
@@commit_count_ready:
    sw      s1, SF_REC_DST(t5)
    sh      t2, SF_REC_COUNT(t5)
    ;; fill this overlay's state (the extension block - fresh zero at every
    ;; overlay load, so a stale cursor can never survive a swap) and
    ;; register its renderers by rewriting the FONT.BIN registration cells
    ;; (never wiped; their build-time content names the retail replays, so
    ;; the kit is inert until the first registration)
    la      t6, sf_state
    li      t1, OVERLAY_SLOT_ADDR
    lw      t1, 0(t1)
    nop
    sw      t1, SF_ST_ID(t6)
    andi    t1, t1, 0xFF                ; SF_REC_PAD = id | bank << 8: the low
    sll     t2, t4, 8                   ;   byte is the overlay that wrote the
    lw      t3, 0x10(sp)                ; producer-owned centering metadata
    or      t1, t1, t2                  ;   row (the pre-pass compares one
    or      t1, t1, t3
    sh      t1, SF_REC_PAD(t5)          ;   byte); the high byte is its bank
    lw      t1, SF_CFG_BUFS(t0)
    nop
    sw      t1, SF_ST_BUFS(t6)

    ;; ---- the condensed tier of a full-name row ----
    ;; The codes just recorded are the whole wording. A name row's budget is
    ;; its caller's retail footprint (8 * s3, at 0x08(sp)); every other row
    ;; has 0 there and keeps tier 0. Choose the least aggressive tier whose
    ;; advances fit, using the same table the emitter reads:
    ;;   tier 1  every word space loses 2 px
    ;;   tier 2  compact artwork and its measured advances (still 1-px gaps)
    lw      t2, 0x08(sp)
    nop
    beqz    t2, @@tier_ready
    nop
    lw      t3, SF_CFG_WIDTHS(t0)
    addiu   t6, t5, SF_REC_CODES
    move    a0, zero                    ; natural width
    move    a1, zero                    ; compact-face width
    move    t7, zero                    ; number of word spaces
@@tier_sum:
    lbu     t1, 0(t6)
    addiu   t6, t6, 1
    li      t4, 0xFF
    beq     t1, t4, @@tier_pick
    nop
    addu    t4, t3, t1
    lbu     t4, 0(t4)
    nop
    andi    at, t4, 0x0F                ; normal font advance
    addu    a0, a0, at
    srl     t4, t4, 4                   ; independently measured compact font
    addu    a1, a1, t4
    sltiu   at, t1, 1                   ; code 0 is the word space
    b       @@tier_sum
    addu    t7, t7, at
@@tier_pick:
    subu    a0, a0, t2                  ; excess over caller's footprint
    blez    a0, @@tier_ready
    sll     t4, t7, 1
    subu    a0, a0, t4                  ; tier 1: spaces are 2 px narrower
    blez    a0, @@tier_store
    li      t4, 1
    sltu    t1, t2, a1                  ; compact font still over budget?
    bnez    t1, @@tier_ready             ; nothing fits: keep the natural row
    nop
    li      t4, 2
@@tier_store:
    lhu     t1, SF_REC_PAD(t5)
    nop
    sll     t4, t4, SF_REC_TIER_SHIFT + 8
    or      t1, t1, t4
    sh      t1, SF_REC_PAD(t5)
@@tier_ready:
    li      t2, SF_FONT_CELL_BG
    la      t1, sf_hook_bg
    sw      t1, 0(t2)
    la      t1, sf_hook_fastbg
    sw      t1, 4(t2)
    b       @@verbatim                  ; keep the map current until its sorter claims it
    nop

@@verbatim:
    move    a0, s0
    move    a1, s1
    move    a2, s2
    move    a3, s3
    lw      t1, SF_CFG_FALLBACK(t0)
    li      t0, 0xFF                    ; the hook's four words displaced the
                                        ; retail 'ori t0, zero, 0xFF': put the
                                        ; terminator back before the loop body
    b       @@restore
    nop

@@out:
    move    t1, ra
@@restore:
    lw      ra, 0x2C(sp)
    lw      s0, 0x28(sp)
    lw      s1, 0x24(sp)
    lw      s2, 0x20(sp)
    lw      s3, 0x1C(sp)
    addiu   sp, sp, 0x30
    jr      t1
    nop
;; Count visible glyphs in the current and next horizontal copies. A retained
;; name may extend past the physical map edge; viewport clipping owns its tail.
;; If an earlier copy or both counted copies are visible, leave it to retail.
;; Inputs: t1 = first pen, t5 = record, a2 = widths. t0/t3/t5/t7/a0/a3
;; and all saved registers survive. Output: v0 = selected copy (0/1, -1 for
;; malformed record), v1 = its packet bytes. Scratch: 0x08(sp), 0x2C(sp).
sf_row_reserve:
    la      t8, sf_center_row
    jalr    t8, t6
    nop
    lbu     t8, SF_REC_PAD + 1(t5)      ; the row's condensed tier (0-2)
    addiu   a1, t5, SF_REC_CODES
    srl     t8, t8, SF_REC_TIER_SHIFT
    andi    t8, t8, 0x03
    sw      t8, 0x2C(sp)
    move    t2, t1
    move    v0, zero
    move    v1, zero
    sw      zero, 0x08(sp)
@@row_count:
    lbu     t4, 0(a1)
    addiu   a1, a1, 1
    li      t6, 0xFF
    beq     t4, t6, @@row_count_done
    nop
    sltiu   t6, v0, SF_REC_CODE_MAX
    beqz    t6, @@row_bad
    addiu   v0, v0, 1
    li      t6, SF_TAB
    bne     t4, t6, @@row_metric
    nop
    li      t8, SF_TAB_HELPER_ADDR
    jalr    t8, t6
    nop
    b       @@row_count
    nop
@@row_metric:
    addu    t4, a2, t4
    lbu     t4, 0(t4)
    nop
    li      t8, 0x11
    beq     t4, t8, @@row_blank         ; packed bearing 0 + advance 1
    nop
    lbu     t8, -1(a1)                  ; the cell's code (0 = word space)
    lw      t6, 0x2C(sp)
    nop
    sf_field_metric t4, t8, t6, t4
    move    t6, t2                      ; both Latin atlases are left-normalised
    beqz    t8, @@row_count
    addu    t2, t2, t4                  ; spaces still advance the pen
    ;; A tail crossing the ring edge can make the preceding copy visible.
    ;; Do not suppress a row this single-copy renderer cannot represent.
    lw      t8, 0x58(sp)
    lw      t4, 0x18(sp)
    nop
    subu    t8, t8, t4
    subu    t4, t6, t8
    lw      t8, 0x38(sp)
    nop
    slt     t8, t4, t8
    beqz    t8, @@row_first
    addiu   t4, t4, SF_CELL_W
    lw      t8, 0x30(sp)
    nop
    slt     t8, t8, t4
    bnez    t8, @@row_hidden
    nop
@@row_first:
    addiu   t4, t6, SF_CELL_W
    lw      t8, 0x38(sp)
    nop
    slt     t8, t6, t8
    beqz    t8, @@row_other
    nop
    lw      t8, 0x30(sp)
    nop
    slt     t8, t8, t4
    beqz    t8, @@row_other
    nop
    addiu   v1, v1, 24
@@row_other:
    lw      t8, 0x58(sp)               ; right edge - base = ring width
    lw      t4, 0x18(sp)
    nop
    subu    t8, t8, t4
    addu    t6, t6, t8                 ; next copy's glyph left
    lw      t8, 0x38(sp)
    nop
    slt     t8, t6, t8
    beqz    t8, @@row_count
    addiu   t4, t6, SF_CELL_W
    lw      t8, 0x30(sp)
    nop
    slt     t8, t8, t4
    beqz    t8, @@row_count
    nop
    lw      t8, 0x08(sp)
    nop
    addiu   t8, t8, 24
    sw      t8, 0x08(sp)
    b       @@row_count
    nop
@@row_blank:
    b       @@row_count
    addiu   t2, t2, 1
@@row_count_done:
    beqz    v0, @@row_bad
    nop
    lw      t8, 0x08(sp)
    nop
    beqz    v1, @@row_second
    nop
    bnez    t8, @@row_hidden           ; two copies: retail owns the row
    move    v0, zero
    jr      ra
    nop
@@row_second:
    move    v1, t8
    li      v0, 1
    jr      ra
    nop
@@row_bad:
    li      v0, -1
    jr      ra
    nop
@@row_hidden:
    move    v0, zero
    move    v1, zero
    jr      ra
    nop
sf_record_end:

;; -------------------------------------------------------------
;; PART 2 - the renderer (build copy: .org ROW_ADDR + 0x24, after the
;; registration guard, with the clones). Entered from the resident
;; stubs; a0/a1/a2 = GsBG*, GsOT*, pri. The state is the kit's one
;; own state block (sf_state_<ovl>, in the extension data below); the config is this
;; overlay's own (sf_cfg_<ovl>, naming the resident tables).
;; Frame map: +00 walk ptr +04 first chunk +08 old entry value
;;   +0C entry addr +10 map index +14 kit-live flag +18 row x base
;;   +1C row y base +20 advance table +24 map cell count +28 thunk / row y<<16
;;   +2C recorded condensed tier (reservation and emission)
;;   +30..+3C viewport bounds +40..+4C clipped glyph geometry
;;   +50 map height +54 normalized y scroll +5C..+6C s3/s2/s1/s0/ra
;; -------------------------------------------------------------
sf_hook_bg:
    la      t9, sf_state
    li      t0, GSORT_BG_ADDR
    la      t1, sf_call_bg
    la      t2, sf_cfg
    b       sf_hook
    nop
    .word   SF_REG_MAGIC                    ; the gate checks entry-4, so each
                                            ;   registered entry owns its guard
sf_hook_fastbg:
    la      t9, sf_state
    li      t0, GSORT_FASTBG_ADDR
    la      t1, sf_call_fastbg
    la      t2, sf_cfg
sf_hook:
    addiu   sp, sp, -0x70
    sw      ra, 0x6C(sp)
    sw      s0, 0x68(sp)
    sw      s1, 0x64(sp)
    sw      s2, 0x60(sp)
    sw      s3, 0x5C(sp)
    move    s0, a0                      ; bg
    move    s1, a1                      ; ot
    move    s2, a2                      ; pri

    ;; ---- diag: off unless the build asked for it (features.py) ----
.if SF_DIAG
    lw      t3, SF_ST_DIAG_HN(t9)
    nop
    addiu   t3, t3, 1
    sw      t3, SF_ST_DIAG_HN(t9)
    sw      s0, SF_ST_DIAG_HA(t9)
    sw      s1, SF_ST_DIAG_HA + 4(t9)
    sw      s2, SF_ST_DIAG_HA + 8(t9)
.endif

    ;; ---- the kit must be this overlay's ----
    lw      t4, SF_ST_ID(t9)
    li      t5, OVERLAY_SLOT_ADDR
    lw      t5, 0(t5)
    sw      t1, 0x28(sp)
    xor     t3, t4, t5
    sltiu   t3, t3, 1
@@sort:
    sw      t3, 0x14(sp)

    ;; ---- geometry of the layer this call sorts ------------------------
    ;; Both passes need it - the pre-pass bounds a record to this map, the
    ;; emit pass places its glyphs - and the sorter call between them owns
    ;; every register, so it is computed once here and the pieces the emit
    ;; pass needs again are in frame slots: map index +10, cell count +24,
    ;; x base +18, y base +1C, advances +20, OT entry +0C.
    beqz    t3, @@sorted                ; not this overlay's sort
    nop
    lw      a2, 0x14(s0)                ; bg->map
    nop
    lbu     t3, 0(a2)                   ; GsMAP cellw / cellh
    lbu     t4, 1(a2)
    li      t5, SF_CELL_W
    bne     t3, t5, @@other_geometry
    li      t5, SF_CELL_H
    beq     t4, t5, @@text_geometry
    nop
@@other_geometry:
    b       @@sorted
    sw      zero, 0x14(sp)              ; e.g. 16x16 dungeon map: retail owns it
@@text_geometry:
    lw      t7, 12(a2)                  ; map->index: the cell array (u16*)
    lhu     t8, 2(a2)                   ; ncellw
    lhu     t3, 4(a2)                   ; ncellh
    nop
    multu   t8, t3
    nop
    nop
    nop
    mflo    t3
    sw      t3, 0x24(sp)                ; ncellw * ncellh: the map's cell count
    sw      t7, 0x10(sp)
    lh      t3, 4(s0)                   ; bg->x
    lh      t4, 12(s0)                  ; signed bg->scrollx
    sll     t5, t8, 3                   ; ncellw * 8
    beqz    t5, @@other_geometry        ; invalid map: retail owns it
    nop
    div     t4, t5
    nop
    nop
    mfhi    t4
    bgez    t4, @@have_xscroll
    nop
    addu    t4, t4, t5
@@have_xscroll:
    sw      t4, 0x4C(sp)
    subu    t3, t3, t4                  ; x - normalized scrollx
    li      t6, GS_DRAW_OFS_X_ADDR
    lh      t6, 0(t6)
    lh      t4, 0x18(s0)                ; libgs origin within the background
    addu    t3, t3, t6
    subu    t3, t3, t4
    sw      t3, 0x18(sp)
    sll     t5, t8, 3                   ; ncellw * 8: physical map row width
    addu    t5, t3, t5
    sw      t5, 0x58(sp)                ; physical row right edge
    ;; Retail GsSortBg reduces signed scroll modulo map height. Retain the
    ;; normalized remainder and map period for both pre-pass and emit.
    lhu     t5, 4(a2)                   ; map->ncellh
    nop
    sll     t6, t5, 2
    sll     t5, t5, 3
    addu    t5, t5, t6                  ; height = ncellh * 12 pixels
    bnez    t5, @@have_map_height
    sw      t5, 0x50(sp)
    sw      zero, 0x14(sp)              ; invalid map: use retail only
    b       @@sorted
    nop
@@have_map_height:
    lh      t4, 14(s0)                  ; signed bg->scrolly
    nop
    div     t4, t5
    nop
    nop
    mfhi    t4
    bgez    t4, @@have_yscroll
    nop
    addu    t4, t4, t5
@@have_yscroll:
    sw      t4, 0x54(sp)
    lh      t3, 6(s0)                   ; bg->y
    nop
    subu    t3, t3, t4                  ; y - normalized scrolly
    li      t6, GS_DRAW_OFS_Y_ADDR
    lh      t6, 0(t6)
    lh      t4, 0x1A(s0)
    addu    t3, t3, t6
    subu    t3, t3, t4
    sw      t3, 0x1C(sp)
    ;; Visible viewport is independent of the full tilemap and its scroll.
    lh      t4, 8(s0)
    lh      t5, 10(s0)
    blez    t4, @@no_view
    nop
    blez    t5, @@no_view
    nop
    lw      t6, 0x58(sp)
    lw      t3, 0x18(sp)
    nop
    subu    t6, t6, t3                  ; map's horizontal period
    slt     t6, t6, t4                  ; wider view can show 3+ copies
    bnez    t6, @@no_view               ; leave every row to the retail sorter
    nop
    lw      t6, 0x4C(sp)                ; same normalized scroll as x base
    lw      t3, 0x18(sp)
    nop
    addu    t3, t3, t6
    sw      t3, 0x30(sp)                ; viewport left
    addu    t4, t3, t4
    sw      t4, 0x38(sp)                ; viewport right (exclusive)
    lw      t6, 0x54(sp)                ; same normalized scroll as y base
    lw      t3, 0x1C(sp)
    nop
    addu    t3, t3, t6
    sw      t3, 0x34(sp)                ; viewport top
    addu    t5, t3, t5
    sw      t5, 0x3C(sp)                ; viewport bottom (exclusive)
    lw      t4, SF_CFG_WIDTHS(t2)       ; this overlay's own advance table
    andi    s2, s2, 0xFFFF              ; the sorter reads pri as a u16
    sw      t4, 0x20(sp)
    lw      t4, 8(s1)                   ; ot->offset: GsSortBg's entry index is
    nop                                 ; pri + ot->offset (0x80032a14), not pri
    addu    t3, s2, t4
    sll     t3, t3, 2
    lw      t4, 4(s1)                   ; ot->org: the stable table base -
    nop                                 ; point is zeroed between frames, and
    addu    t3, t4, t3                  ; org + that index is where the sorter
    sw      t3, 0x0C(sp)                ; itself chains this layer's packets

    ;; ---- select and bound this frame's packet storage ----
    lw      t1, SF_ST_LAST_OT(t9)
    nop
    beq     t1, s1, @@same_ot
    nop
    sw      s1, SF_ST_LAST_OT(t9)
    lw      t1, SF_ST_CUR_BUF(t9)
    nop
    xori    t1, t1, 1
    sw      t1, SF_ST_CUR_BUF(t9)
    sw      zero, SF_ST_BUF_PTR(t9)
@@same_ot:
    lw      t0, SF_ST_BUFS(t9)          ; this overlay's buffer pair
    lw      t1, SF_ST_CUR_BUF(t9)
    nop
    sll     t2, t1, 9
    sll     t1, t1, 12
    addu    t1, t1, t2                  ; * SF_BUF_SIZE (0x1200)
    addu    t1, t0, t1                  ; this frame's buffer base
    lw      t2, SF_ST_BUF_PTR(t9)
    nop
    bnez    t2, @@cursor_ok             ; a cursor from an earlier layer today
    move    s3, t2                      ; (the delay slot: 0 when fresh)
    move    s3, t1
@@cursor_ok:
    addiu   t0, t1, SF_BUF_SIZE         ; t0 = the buffer end; t9 stays the state

    sw      t0, 0x04(sp)                ; retain buffer end across the retail sorter
    subu    t6, t0, s3
    sw      t6, 0x00(sp)                ; bytes available for complete row reservations
    la      t2, sf_cfg                  ; buffer selection uses temporary registers

    ;; ---- temporarily suppress only complete rows this call can draw ----
    ;; The recorder never clears a cell; the sorter that serves the map is
    ;; the only thing allowed to, and it does it here, immediately before
    ;; the retail body walks the map. So the map is blank exactly on the
    ;; frames and screens this renderer serves, and a screen drawn by any
    ;; other path (sprite panels, a writer with no background sort) keeps
    ;; the game's own row - visible text, never an empty plate.
    ;; A record whose cells no longer hold the row that was recorded
    ;; (someone else rewrote it) is not ours: leave it alone as well.
    lw      t3, 0x24(sp)
    nop
    sll     t3, t3, 1                   ; the map's byte span
    lw      t5, SF_CFG_TABLE(t2)        ; this overlay's record table
    nop
    li      a3, SF_ROWS
@@blank_rec:
    lhu     t2, SF_REC_COUNT(t5)        ; bit 15 = "cleared by this pass yet"
    lw      a0, SF_REC_DST(t5)          ; (the delay slot: dst is read next)
    andi    t2, t2, SF_REC_OWNED - 1    ; no: a record is nobody's until the
    sh      t2, SF_REC_COUNT(t5)        ; clearing below claims it
    beqz    a0, @@blank_next
    nop
    beqz    t2, @@blank_next            ; a free slot has no row to clear
    nop
    lbu     t4, SF_REC_PAD(t5)          ; low byte: the overlay that wrote it
    lbu     t2, SF_ST_ID(t9)
    nop
    bne     t4, t2, @@blank_next
    lbu     t1, SF_REC_PAD + 1(t5)      ; (delay slot) the row's bank
    li      t4, 0x40                   ; producer-owned fixed-cell text
    and     t4, t1, t4
    bnez    t4, @@blank_next
    nop
    li      t4, SF_GLYPHS
    andi    t1, t1, SF_REC_BANK_MASK    ; exclude the tier and centering bits
    multu   t1, t4                      ; bank * SF_GLYPHS: the row's first
    subu    t4, a0, t7                  ; (delay) the record's cell offset
    sltu    t2, a0, t7                  ; (delay) before the map's cells?
    mflo    t1                          ;   cell in the atlas
    bnez    t2, @@blank_next
    sltu    t2, t4, t3                  ; (delay) past the map?
    beqz    t2, @@blank_next
    lhu     t2, SF_REC_COUNT(t5)        ; (delay) the compose's length
    move    v0, a0                      ; count load delay
    sll     t6, t2, 1
    addu    t6, t6, t4                  ; end offset = start + count * 2
    sltu    t6, t3, t6
    bnez    t6, @@blank_next            ; reject a row extending beyond this map
    addiu   a1, t5, SF_REC_CODES
@@blank_chk:
    lhu     t6, 0(v0)                   ; logical map cell
    lbu     t4, 0(a1)                   ; recorded glyph
    addiu   a1, a1, 1
    subu    t6, t6, t1                  ; compare exact logical map contents
    beq     t4, t6, @@blank_ok
    nop
@@blank_invalid:
    sw      zero, SF_REC_DST(t5)        ; a rewrite or page clear retires this row
    b       @@blank_next
    nop
@@blank_ok:
    addiu   t2, t2, -1
    bnez    t2, @@blank_chk
    addiu   v0, v0, 2
    ;; Determine the row's actual screen position before reserving packets.
    subu    t4, a0, t7
    srl     t4, t4, 1
    lw      t6, 0x14(s0)
    nop
    lhu     t6, 2(t6)
    nop
    divu    t4, t6
    nop
    nop
    mflo    t4
    mfhi    t6
    sll     t8, t4, 2
    sll     t4, t4, 3
    addu    t4, t8, t4
    lw      t8, 0x1C(sp)
    nop
    addu    t4, t4, t8
    ;; Select the first copy whose bottom reaches the viewport. Fully hidden
    ;; preceding rows may reappear at the end of the ring.
    addiu   v0, t4, SF_CELL_H
    lw      t8, 0x34(sp)
    nop
    slt     t8, t8, v0
    bnez    t8, @@blank_y_ready
    nop
    lw      t8, 0x50(sp)
    nop
    addu    t4, t4, t8
@@blank_y_ready:
    ;; If a second vertical copy is visible, do not suppress the retail row:
    ;; the current bounded VWF packet path only emits one copy.
    lw      t8, 0x50(sp)
    lw      v0, 0x3C(sp)
    addu    t8, t4, t8
    slt     t8, t8, v0
    bnez    t8, @@blank_next
    nop
    lw      t8, 0x3C(sp)
    nop
    slt     t8, t4, t8
    beqz    t8, @@blank_next
    addiu   t4, t4, 12
    lw      t8, 0x34(sp)
    nop
    slt     t8, t8, t4
    beqz    t8, @@blank_next
    nop
    sll     t6, t6, 3
    lw      t1, 0x18(sp)
    lw      a2, 0x20(sp)
    addu    t1, t1, t6                  ; row pen; a2 is the advance table
    jal     sf_row_reserve              ; count both possible ring copies
    nop
    bltz    v0, @@blank_invalid
    nop
    beqz    v1, @@blank_next             ; hidden rows leave capacity and the map untouched
    move    t2, v1
    lw      t6, 0x00(sp)
    nop
    sltu    v0, t6, t2
    bnez    v0, @@blank_next            ; leave the complete retail row visible
    subu    t6, t6, t2
    sw      t6, 0x00(sp)
    lhu     t2, SF_REC_COUNT(t5)
    li      t6, 0xFFFF                  ; retail GsSortBg's empty-cell marker
@@blank_do:
.if SF_NOCLEAR
    ;; DIAGNOSTIC (features.py: SF_NOCLEAR; off in every real build). The
    ;; The suppression store becomes a nop; retail and VWF text both draw.
    nop
.else
    sh      t6, 0(a0)
.endif
    addiu   t2, t2, -1
    bnez    t2, @@blank_do
    addiu   a0, a0, 2
    ;; cleared, and drawn by this very pass: claim it for the emit below
    lw      t2, SF_REC_COUNT(t5)
    ori     t4, zero, SF_REC_OWNED      ; NOT lui: the bit lives at 15, and lui
    or      t2, t2, t4                  ; would set bit 31 - which the sh below
    sh      t2, SF_REC_COUNT(t5)        ; then throws away, claiming nothing
@@blank_next:
    addiu   a3, a3, -1
    bnez    a3, @@blank_rec
    addiu   t5, t5, SF_ROW_REC
@@sorted:
    ;; The pre-pass and the geometry spend a0-a2 as scratch, but the thunk
    ;; replays the sorter's prologue and then runs its body with the very
    ;; arguments this hook was handed. Give them back: the sorter reads a0
    ;; as the GsBG (its prologue moves it to t7 and the body dereferences
    ;; it) and a1 as the GsOT it chains the packets into.
    lw      t1, 0x28(sp)                ; reload the thunk after pre-pass scratch use
    move    a0, s0                      ; load delay
    move    a1, s1
    la      ra, @@ret
    jr      t1                          ; the thunk: prologue, then the sorter
    move    a2, s2
@@ret:
    la      t9, sf_state                ; the sorter owns t9: reload it
    lw      t0, 0x14(sp)
    nop
    beqz    t0, @@out
    nop

    lw      t0, 0x04(sp)                ; buffer end; s3 is callee-saved
    nop

    ;; ---- what the pre-pass kept for us ----
    lw      a2, 0x14(s0)                ; bg->map
    nop
    lw      a2, 8(a2)                   ; map->base: the glyph cell table
    nop

    la      t5, sf_cfg
    lw      t5, SF_CFG_TABLE(t5)        ; this overlay's own record table
    li      a3, SF_ROWS
@@rec:
    lw      t7, 0x14(s0)                ; bg->map; width is scratch after each row
    lh      t2, SF_REC_COUNT(t5)
    lhu     t8, 2(t7)                   ; map->ncellw for this record
    bgez    t2, @@rec_next              ; emit only rows claimed by this map's pre-pass
    lw      t7, 0x10(sp)                ; (delay) map->index
    lw      a0, SF_REC_DST(t5)
    nop
    subu    t1, a0, t7                  ; the record's cell offset (in the
    srl     t1, t1, 1                   ; map: the pre-pass checked the bounds)
    divu    t1, t8
    lbu     t3, SF_REC_PAD + 1(t5)      ; (delay) the row's CLUT bank
    sll     t6, t8, 3                   ; (delay) ncellw * 8: the map row's width
    andi    t3, t3, SF_REC_BANK_MASK    ; exclude the tier and centering bits
    mfhi    t4                          ; col
    mflo    t2                          ; row
    sll     t2, t2, 2                   ; row * 4
    addu    t8, t2, t2                  ; row * 8 (t8's ncellw is spent)
    addu    t2, t8, t2                  ; row * 12
    lw      t8, 0x1C(sp)
    nop
    addu    t2, t8, t2                  ; the row's y
    addiu   v0, t2, SF_CELL_H
    lw      t8, 0x34(sp)
    nop
    slt     v0, t8, v0
    bnez    v0, @@emit_y_ready
    nop
    lw      t8, 0x50(sp)
    nop
    addu    t2, t2, t8
@@emit_y_ready:
    sw      t2, 0x4C(sp)
    sll     t2, t2, 16                  ; y to the high half
    sw      t2, 0x28(sp)                ; the row's y<<16 for every chunk
    li      t8, SF_GLYPHS               ; a bank's cell count
    multu   t3, t8                      ; the row's first cell = bank * SF_GLYPHS
    sll     t1, t4, 3                   ; (delay) col * 8
    lw      t8, 0x18(sp)                ; (delay) the layer's x base
    mflo    t3
    addu    t1, t8, t1                  ; the row's first-copy x
    lw      s2, 0x38(sp)                ; clip to viewport, not the map edge
    sw      a2, 0x40(sp)                ; atlas; the reservation helper needs widths
    lw      a2, 0x20(sp)
    nop
    jal     sf_row_reserve
    nop
    lw      a2, 0x40(sp)
    beqz    v0, @@emit_x_ready
    nop
    lw      t8, 0x58(sp)                ; shift both pen and boundary by map width
    lw      t6, 0x18(sp)
    nop
    subu    t8, t8, t6
    addu    t1, t1, t8
@@emit_x_ready:                          ; s2 is the viewport's right edge
                                        ; retained names may cross the map edge
    sw      t1, 0x54(sp)                ; this copy's tab origin
    sll     t8, t3, 3                   ; glyph loop's bank offset in bytes

    ;; The retail sorter has consumed the temporary empty cells. Restore the
    ;; logical map before returning to the game, so clears and rewrites are
    ;; distinguishable from this renderer's suppression on the next frame.
    lhu     t6, SF_REC_COUNT(t5)
    addiu   v0, t5, SF_REC_CODES
    andi    t6, t6, SF_REC_OWNED - 1
@@restore_cells:
    lbu     v1, 0(v0)
    addiu   v0, v0, 1
    addu    v1, v1, t3
    sh      v1, 0(a0)
    addiu   t6, t6, -1
    bnez    t6, @@restore_cells
    addiu   a0, a0, 2

    ;; ---- emit: one 6-word chunk per glyph ----
    sw      t5, 0x00(sp)                ; the record pointer (emit clobbers t5)
    li      t2, 0
    sw      t2, 0x04(sp)                ; this row's first chunk tag (0 = none)
    lw      t3, 0x0C(sp)
    nop
    lw      t2, 0(t3)                   ; the OT entry's value before us
    nop
    sw      t2, 0x08(sp)
    addiu   t3, t5, SF_REC_CODES        ; the record's codes
@@glyph:
    lbu     v0, 0(t3)
    addiu   t3, t3, 1
    li      t4, 0xFF
    beq     v0, t4, @@row_end
    nop
    li      t4, SF_TAB
    bne     v0, t4, @@glyph_normal
    nop
    jal     sf_tab_emit
    nop
    b       @@glyph
    nop
@@glyph_normal:
    lw      t5, 0x20(sp)
    sll     v1, v0, 3                   ; (delay) the cell's byte offset
    addu    t5, t5, v0
    lbu     t4, 0(t5)                   ; packed bearing << 4 | advance
    li      t5, 0x11
    beq     t4, t5, @@blank_advance     ; both fonts' advance-1 blank marker
    nop
    lw      t6, 0x2C(sp)                ; the row's condensed tier
    move    t2, t1
    sf_field_metric t4, v0, t6, t4
    beqz    v0, @@have_first            ; word space: advance without a packet
    nop
    slt     t6, t2, s2                  ; signed screen coordinates, including scroll
    beqz    t6, @@row_end               ; no: the row ends here
    nop
    addiu   t6, s3, 24
    sltu    t6, t0, t6
    bnez    t6, @@row_end               ; the buffer is full: stop the row
    nop
    addu    v1, v1, a2
    addu    v1, v1, t8                  ; the cell in this row's bank
    lbu     a0, 0(v1)                   ; u
    lbu     a1, 1(v1)                   ; v
    lhu     t5, 2(v1)                   ; cba
    lhu     v1, 6(v1)                   ; tpage
    jal     sf_variant_uv
    lw      t7, 0x2C(sp)                ; (delay) the row's tier for the selector
    jal     sf_clip_glyph
    nop
    beqz    v0, @@have_first
    nop
    li      t6, 0x00FFFFFF
    addiu   t2, s3, 24
    and     t6, t2, t6                  ; next = the chunk after this one
    lui     t2, 0x0500
    or      t6, t6, t2                  ; tag: 5 words then that next chunk
    sw      t6, 0(s3)
    lui     t6, 0xE100
    ori     t6, t6, 0x0200
    or      t6, t6, v1                  ; draw mode, this page
    sw      t6, 4(s3)
    ;; the SPRT word: code<<24 | b<<16 | g<<8 | r. The code must be in
    ;; the high byte (the GPU command); the low 24 bits are the layer's
    ;; own text colour, so the row fades with the background. t5 (the
    ;; cell's CLUT), t4 (the advance), t7 (the bearing), a0/a1 (u/v) and
    ;; t1 (pen) must survive; v1's tpage is spent on the word above.
    lbu     t6, 0x12(s0)                ; bg->b
    lbu     t2, 0x11(s0)                ; bg->g
    lbu     v1, 0x10(s0)                ; bg->r
    sll     t6, t6, 16
    sll     t2, t2, 8
    or      t6, t6, t2
    or      t6, t6, v1
    lui     t2, SF_SPRT_CODE << 8       ; the textured-sprite command byte
    or      t6, t6, t2
    sw      t6, 8(s3)
    lw      t6, 0x40(sp)                ; clipped x|y<<16
    nop
    sw      t6, 12(s3)
    lw      t2, 0x44(sp)                ; clipped texture delta: dx|dy<<8
    sll     t6, t5, 16
    sll     v0, a1, 8
    or      v0, v0, a0
    addu    v0, v0, t2
    or      t6, t6, v0
    sw      t6, 16(s3)
    lw      t6, 0x48(sp)                ; clipped w|h<<16
    nop
    sw      t6, 20(s3)
    addiu   s3, s3, 24
    lw      t6, 0x04(sp)
    nop
    bnez    t6, @@have_first
    nop
    addiu   t6, s3, -24
    sw      t6, 0x04(sp)                ; the row's first chunk tag
@@have_first:
    addu    t1, t1, t4                  ; x += advance, including blank glyphs
    b       @@glyph
    nop
@@blank_advance:
    b       @@have_first
    li      t4, 1
@@row_end:
    lw      t2, 0x04(sp)
    nop
    beqz    t2, @@no_row                ; nothing was emitted
    nop
    ;; the last chunk points back at the entry's old head, and the
    ;; entry names this row's first chunk: prepend. The chunk's own
    ;; length (5 words) must survive the link - the entry's value has
    ;; length 0 (it is the root tag), so copy only its address.
    lw      t3, 0x08(sp)
    li      t5, 0x00FFFFFF
    and     t3, t3, t5
    lui     t4, SF_CHUNK_SPRITE << 8    ; the chunk's length: 5 words
    or      t3, t3, t4
    addiu   t4, s3, -24
    sw      t3, 0(t4)                   ; the last chunk -> the old head
    lw      t3, 0x0C(sp)
    and     t4, t2, t5
    sw      t4, 0(t3)                   ; the entry -> this row's first chunk
@@no_row:
    lw      t5, 0x00(sp)
    nop
@@rec_next:
    addiu   a3, a3, -1
    bnez    a3, @@rec
    addiu   t5, t5, SF_ROW_REC
    sw      s3, SF_ST_BUF_PTR(t9)       ; the frame's cursor, for the next layer
@@out:
    lw      ra, 0x6C(sp)
    lw      s0, 0x68(sp)
    lw      s1, 0x64(sp)
    lw      s2, 0x60(sp)
    lw      s3, 0x5C(sp)
    jr      ra
    addiu   sp, sp, 0x70
@@no_view:
    b       @@sorted
    sw      zero, 0x14(sp)

;; Clip an 8x12 glyph to the viewport. Only v0/t6/t7 are scratch;
;; t2 is the glyph's signed x, +4C(sp) its signed y. Results at +40/+44/+48
;; are packet XY, texture offset, and WH. v0=0 means no visible pixels.
sf_clip_glyph:
    lw      t6, 0x30(sp)
    move    t7, t2
    slt     v0, t7, t6
    beqz    v0, @@left_ok
    nop
    move    t7, t6
@@left_ok:
    sw      t7, 0x40(sp)
    lw      t7, 0x38(sp)
    addiu   t6, t2, 8
    slt     v0, t7, t6
    beqz    v0, @@right_ok
    lw      v0, 0x40(sp)
    move    t6, t7
@@right_ok:
    nop                                 ; branch-target load delay
    subu    t6, t6, v0
    blez    t6, @@empty
    sw      t6, 0x48(sp)
    subu    t6, v0, t2
    sw      t6, 0x44(sp)
    lw      t6, 0x4C(sp)
    lw      t7, 0x34(sp)
    nop
    slt     v0, t6, t7
    beqz    v0, @@top_ok
    lw      v0, 0x40(sp)
    move    t6, t7
@@top_ok:
    sll     t6, t6, 16
    andi    t7, v0, 0xFFFF
    or      t6, t6, t7
    sw      t6, 0x40(sp)
    lw      t6, 0x4C(sp)
    lw      t7, 0x3C(sp)
    addiu   t6, t6, 12
    slt     v0, t7, t6
    beqz    v0, @@bottom_ok
    nop
    move    t6, t7
@@bottom_ok:
    lw      t7, 0x40(sp)
    nop
    sra     t7, t7, 16
    subu    t6, t6, t7
    blez    t6, @@empty
    nop
    lw      v0, 0x48(sp)
    sll     t6, t6, 16
    or      t6, t6, v0
    sw      t6, 0x48(sp)
    lw      t6, 0x4C(sp)
    lw      v0, 0x44(sp)
    subu    t6, t7, t6
    sll     t6, t6, 8
    or      t6, t6, v0
    sw      t6, 0x44(sp)
    jr      ra
    li      v0, 1
@@empty:
    jr      ra
    move    v0, zero
sf_hook_end:

;; -------------------------------------------------------------
;; the call-throughs: replay the sorter's displaced prologue below
;; our frame and enter its body at +0x18 (ra carries @@ret through
;; both). t0 = the real sorter's entry (set by the clone above).
;; -------------------------------------------------------------
sf_call_bg:
    addiu   sp, sp, -0xA8
    move    t7, a0
    sw      ra, 0xA4(sp)
    sw      s8, 0xA0(sp)
    sw      s7, 0x9C(sp)
    sw      s6, 0x98(sp)
    li      t2, GSORT_BG_ADDR + 0x18
    jr      t2
    nop
sf_call_fastbg:
    addiu   sp, sp, -0xE8                   ; GsSortFastBg's displaced prologue: the stub
    sw      s5, 0xD4(sp)                    ; took its first five words, this is the
    move    s5, a0                          ; fifth (the stub's, not ours, is the
    sw      ra, 0xE4(sp)                    ; one at +0x14 - the delay slot below)
    sw      fp, 0xE0(sp)
    li      t2, GSORT_FASTBG_ADDR + 0x18                    ; both sorters' bodies resume at +0x18
    jr      t2
    sw      s7, 0xDC(sp)
sf_thunks_end:
