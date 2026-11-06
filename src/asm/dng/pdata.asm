;; =============================================================
;; DNG.BIN - the dungeon menu's Persona Data page (dng/pdata.asm)
;;
;; Two retail fixed-width writers on that page are lifted to the kit:
;;
;;   * DrawSpellName clears ten cells and copies the spell record's
;;     ten-glyph head. It now builds the FULL name with skill_name_copy
;;     into the kit's name scratch and hands that to the same row
;;     writer; the recorder keeps the name whole and its tiered row
;;     still occupies the caller's ten-cell (80 px) footprint. Every
;;     DrawSpellName caller in this overlay gets the same treatment.
;;
;;   * The race + demon-name bar is a sprite-cell row (a two-entry cel
;;     list), not a tilemap row, so it goes through CellsWriteRow like
;;     the status bar. Both list entries carry SF_BAR_MARK, which makes
;;     the slot renderer's advance hook use each cell's stored advance;
;;     the race block keeps retail's six cells (race names are at most
;;     six glyphs) and the demon-name block grows from retail's ten
;;     cells to twenty in the image extension. The full name comes from
;;     demon_name_copy_dng, never the ten-byte record head.
;;
;; The retail name block sits immediately in front of the cel list and
;; cannot grow in place, so only its pointer in the list is repointed;
;; the old ten cells become dead bytes.
;; =============================================================
.psx

.if SF_VWF

;; -------------------------------------------------------------
;; DrawSpellName, rewritten in place (0xC0 bytes avail, 0xB8 used)
;;
;; Retail copied the spell record's ten-glyph head straight into the row.
;; Here the complete skill name is built in the kit's name scratch first
;; and that scratch is the row's source, so the recorder retains the whole
;; terminated name and draws it in the caller's ten-cell (80 px) budget.
;; s3 keeps the caller's fourth argument: the rule branch still tests it,
;; exactly as retail did (the row path zero-extends the third argument as
;; the glyph base).
;; -------------------------------------------------------------
.org DNG_DRAW_SPELL_NAME
.area 0xC0

pdata_spell_name:
    addiu   sp, sp, -0x30
    sw      ra, 0x28(sp)
    sw      s0, 0x18(sp)
    sll     s0, a0, 16                  ; spell id, sign-extended short
    sw      s1, 0x1C(sp)
    sra     s0, s0, 16
    sw      s2, 0x20(sp)
    move    s1, a1                      ; dst
    sw      s3, 0x24(sp)
    move    s2, a2                      ; base
    move    s3, a3                      ; retail's rule flag
    ori     v0, zero, 0x28
    move    a0, s1
    addu    a1, zero, zero
    ori     a2, zero, 10
    ori     a3, zero, 1
    jal     DNG_TILEMAP_FILLRECT
    sw      v0, 0x10(sp)

    beqz    s0, @@rule
    lui     a0, ((sf_name_scratch_dng + 0x8000) >> 16) & 0xFFFF
    addiu   a0, a0, sf_name_scratch_dng & 0xFFFF
    move    a1, s0
    jal     skill_name_copy
    nop
    lui     a0, ((sf_name_scratch_dng + 0x8000) >> 16) & 0xFFFF
    addiu   a0, a0, sf_name_scratch_dng & 0xFFFF
    move    a1, s1
    andi    a2, s2, 0xFFFF
    j       @@call
    ori     a3, zero, 10

@@rule:
    ;; retail's eight-glyph rule under an empty slot (dst + 1 cell)
    sll     v0, s3, 16
    beqz    v0, @@out
    addiu   a1, s1, 2
    lui     a0, ((DNG_SPELL_RULE_GLYPHS + 0x8000) >> 16) & 0xFFFF
    addiu   a0, a0, DNG_SPELL_RULE_GLYPHS & 0xFFFF
    ori     a2, zero, 0xD7
    ori     a3, zero, 8

@@call:
    jal     DNG_SF_HOOK_ADDR
    nop

@@out:
    lw      ra, 0x28(sp)
    lw      s3, 0x24(sp)
    lw      s2, 0x20(sp)
    lw      s1, 0x1C(sp)
    lw      s0, 0x18(sp)
    jr      ra
    addiu   sp, sp, 0x30
pdata_spell_name_end:
.fill DNG_DRAW_SPELL_NAME + 0xC0 - pdata_spell_name_end

.endarea

;; -------------------------------------------------------------
;; PersonaDataDraw's bar tail: hand the demon id to the VWF bar
;; (s5 is the id; the tail keeps its epilogue at DNG_PDATA_TAIL_END)
;; -------------------------------------------------------------
.org DNG_PDATA_TAIL
.area DNG_PDATA_TAIL_END - DNG_PDATA_TAIL

    sll     a0, s5, 16
    sra     a0, a0, 16
    jal     pdata_bar
    nop
pdata_tail_end:
.fill DNG_PDATA_TAIL_END - pdata_tail_end

.endarea

;; -------------------------------------------------------------
;; pdata_bar: race and demon name as two VWF sprite rows
;; a0 = the demon id (1-based, as the record table indexes it)
;; -------------------------------------------------------------
.org DNG_PDATA_BAR
pdata_bar:
    addiu   sp, sp, -0x18
    sw      ra, 0x14(sp)
    sw      s0, 0x10(sp)
    move    s0, a0

    ;; ---- race: retail's six cells, now with advances ----
    la      a0, DNG_PDATA_RACE_CELLS
    ori     a1, zero, 6
    jal     DNG_CELLS_CLEAR
    nop
    sll     t0, s0, 3
    sll     t1, s0, 6
    subu    t0, t1, t0                  ; id * 0x38
    li      at, DEMON_NAME_BASE + 0xB    ; the record's race byte
    addu    at, at, t0
    lbu     v0, 0(at)
    nop                                 ; load delay
    addiu   v0, v0, -1                  ; race is 1-based
    sll     t0, v0, 1
    addu    t0, t0, v0
    sll     t0, t0, 1                   ; (race - 1) * 6
    la      a0, DNG_PDATA_RACE_CELLS
    li      a1, DNG_PDATA_RACE_TABLE
    addu    a1, a1, t0
    ori     a2, zero, 0x80              ; page 0 + bit 7: the VWF Latin face
    ori     a3, zero, 6
    jal     DNG_CELLS_ROW
    nop

    ;; ---- name: the full demon name in the 20-cell block ----
    la      a0, sf_name_scratch_dng
    move    a1, s0
    jal     demon_name_copy_dng
    nop
    la      a0, DNG_PDATA_NAME_CELLS
    ori     a1, zero, DNG_PDATA_NAME_COLS
    jal     DNG_CELLS_CLEAR
    nop
    la      a0, DNG_PDATA_NAME_CELLS
    la      a1, sf_name_scratch_dng
    ori     a2, zero, 0x80
    ori     a3, zero, DNG_PDATA_NAME_COLS
    jal     DNG_CELLS_ROW
    nop

    lw      ra, 0x14(sp)
    lw      s0, 0x10(sp)
    jr      ra
    addiu   sp, sp, 0x18
pdata_bar_end:

.if pdata_bar_end > DNG_PDATA_BAR_END
    .error "pdata: the bar helper overruns DNG_PDATA_BAR_END"
.endif
.if DNG_PDATA_BAR_END > DNG_PDATA_EXT_LIMIT
    .error "pdata: the bar helper reaches the sector-safe extension ceiling"
.endif

;; -------------------------------------------------------------
;; the page's cel list: both entries marked, the name row repointed
;; (retail's dx=0x40, dy=0xC placement is kept)
;; -------------------------------------------------------------
.org DNG_PDATA_CEL_LIST
    .word   DNG_PDATA_RACE_BLOCK
    .halfword 0                     ; dx
    .halfword 0                     ; dy
    .halfword 0                     ; z
    .halfword SF_BAR_MARK           ; the pad the advance hook reads
    .word   DNG_PDATA_NAME_BLOCK
    .halfword 0x40                  ; dx: retail's name entry
    .halfword 0x0C                  ; dy: retail's name entry
    .halfword 0                     ; z
    .halfword SF_BAR_MARK           ; the pad the advance hook reads
    .word   0xFFFFFFFF

;; -------------------------------------------------------------
;; the twenty-cell demon-name block in the image extension
;; -------------------------------------------------------------
.org DNG_PDATA_NAME_BLOCK
    .byte   DNG_PDATA_NAME_COLS, 1
    .halfword 0
    .halfword 8, 12

.org DNG_PDATA_NAME_CELLS
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01
    .byte   0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0xFF, 0x01

.if DNG_PDATA_NAME_CELLS + DNG_PDATA_NAME_COLS * 8 > DNG_PDATA_BAR
    .error "pdata: the name block reaches the bar helper"
.endif
.if DNG_BAR_LIST + 0x1C != DNG_PDATA_NAME_BLOCK
    .error "pdata: the name block must follow the status bar's cel list"
.endif

.endif                              ; SF_VWF
