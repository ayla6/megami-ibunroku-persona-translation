;; =============================================================
;; S2D's copy of the persona status bottom bar (the mirror of
;; dng/bar.asm, which in turn mirrors adv/cells_row.asm + adv/bar.asm;
;; see the ADV file for the full story).
;;
;; The overworld menu compiles its own copy of the status page, so the
;; ADV/DNG bar patch never reached the save whose status screen lives
;; here: S2D kept retail's fixed-width cells and the master record's
;; ten-glyph name head ("Seimen Kon"). This file gives S2D the same
;; treatment: retail's two cel entries (arcana dx=0/dy=0, name
;; dx=0x58/dy=4), a 16-cell name block, the advance hook on S2D's own
;; SlotsRenderAll, CellsWriteRow rewritten in place so every cell carries
;; its glyph advance, and StatusPersonaNames rewritten to persona_name_copy
;; the full name straight into the cells. S2D has no fusion screen, so
;; there are no fusion write sites.
;;
;; S2D's old blocks and list (0x8009D734/0x8009D78C/0x8009D7E4) become
;; dead bytes. The new pair and the hook live in the image extension,
;; after every generated block and below the 0x800E0000 work-area
;; ceiling, so they load and swap with the overlay like the rest of the
;; small-font kit's data.
;; =============================================================
.psx

;; The extension is assembled before this file (s2d/smallfont.asm), so its
;; end is known here. The bar must never overlap generated content.
.if sf_extension_end_s2d > S2D_BAR_LIST
    .error "s2d/bar.asm: the small-font extension reaches the bar's data slot"
.endif
.if S2D_BAR_HOOK_END > S2D_ITEM_DATA_END
    .error "s2d/bar.asm: the bar's hook reaches the work area"
.endif

;; --- S2D CellsWriteRow, rewritten in place (identical body to ADV/DNG) ---
.org S2D_CELLS_ROW
.area 0xC0

s2d_writer_start:
    andi    v0, a3, 0xFFFF
    beqz    v0, @@ret0              ; the retail count-0 guard (no frame)
    move    t0, a0                  ; (delay) the cell cursor
    addiu   sp, sp, -8              ; the selector call needs the caller's ra
    sw      ra, 0(sp)
    move    t9, a1                  ; the source cursor (a1 carries u/v)
    ori     t4, zero, 0xFF          ; the terminator
    ori     t5, zero, 265           ; the /31 reciprocal
    ori     t3, zero, 0x3C0         ; flag (the CLUT x the renderer reads)
    andi    t2, a2, 0x7F
    addiu   t2, t2, 0x1A0           ; tpage (the CLUT y the renderer reads)
    la      t8, sf_widths_s2d       ; this overlay's advance table

@@row:
    lbu     v1, 0(t9)               ; the glyph code
    addiu   t9, t9, 1
    beq     v1, t4, @@ret           ; 0xFF ends the row (retail)
    addiu   a3, a3, -1              ; (delay)
    multu   v1, t5
    mflo    v0
    srl     v0, v0, 13              ; v0 = code / 31
    sll     t6, v0, 5
    subu    t6, t6, v0              ; q * 31
    subu    a0, v1, t6              ; code % 31
    sll     a0, a0, 3               ; u (a0/a1 are the selector's own in/out pair)
    sll     a1, v0, 1
    addu    a1, a1, v0
    sll     a1, a1, 2               ; v = q * 12
    addu    t1, t8, v1              ; the glyph's advance entry
    andi    t6, a2, 0x80            ; bit 7 of the page: the VWF Latin face
    beqz    t6, @@uv                ; retail face: keep the atlas u/v
    move    v0, v1                  ; (delay) the selector's code
    jal     sf_variant_uv_v1_s2d    ; retail code -> the regular Latin cell
    nop
@@uv:
    sb      a0, 0(t0)
    sb      a1, 1(t0)
    lbu     v0, 0(t1)
    sh      t3, 4(t0)               ; (lbu load delay: the flag doesn't read v0)
    andi    v0, v0, 0xF             ; the glyph's pen advance
    sb      v0, 3(t0)               ; +3: the bar's advance hook reads it
    sh      t2, 6(t0)
    addiu   t0, t0, 8
    bnez    a3, @@row
    nop                             ; (delay)

@@ret:
    lw      ra, 0(sp)
    addiu   sp, sp, 8
@@ret0:
    jr      ra
    nop
s2d_writer_end:
.fill S2D_CELLS_ROW + 0xC0 - s2d_writer_end

.endarea

;; --- sf_cell_adv_s2d: the slot renderer's pen advance, per cell ---
;; Same shape as the ADV/DNG hooks (S2D's renderer is compiled with the
;; same registers: s4 pen, s6 cell, t9 entry, a3 width).
.org S2D_BAR_HOOK
.area S2D_BAR_HOOK_END - S2D_BAR_HOOK

sf_cell_adv_s2d:
    lhu     v1, 10(t9)              ; the entry's pad halfword
    lbu     v0, 0(s6)               ; (delay) the cell's u (the clear check)
    xori    v1, v1, SF_BAR_MARK     ; one of ours?
    addiu   v0, v0, 0xFF01          ; u - 0xFF: zero only for a cleared cell
    bnez    v1, @@retail
    lbu     v1, 3(s6)               ; (delay) the cell's stored advance
    beqz    v0, @@retail            ; cleared cell (u = 0xFF): retail pitch
    nop
    jr      ra
    addu    s4, s4, v1              ; (delay) pen += advance
@@retail:
    jr      ra
    addu    s4, s4, a3              ; (delay) pen += w

.endarea

;; --- the bar data in the image extension: retail's two rows ---
;; The list keeps retail's name entry dx=0x58, dy=4; the name block grows
;; from retail's 10 cells to 16, exactly like ADV/DNG.
.org S2D_BAR_LIST
    .word   S2D_BAR_ARCANA_BLOCK
    .halfword 0                     ; dx: the arcana starts at the slot's own x
    .halfword 0                     ; dy: the slot's own baseline
    .halfword 0                     ; z
    .halfword SF_BAR_MARK           ; the pad the advance hook reads
    .word   S2D_BAR_NAME_BLOCK
    .halfword 0x58                  ; dx: retail's name entry
    .halfword 4                     ; dy: retail's name entry (the second line)
    .halfword 0                     ; z
    .halfword SF_BAR_MARK           ; the pad the advance hook reads
    .word   0xFFFFFFFF

.org S2D_BAR_ARCANA_BLOCK
    .byte   10, 1
    .halfword 0
    .halfword 8, 12

.org S2D_BAR_CELLS
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

.org S2D_BAR_NAME_BLOCK
    .byte   16, 1
    .halfword 0
    .halfword 8, 12

.org S2D_BAR_NAME_CELLS
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

;; --- the status preview points slot 0x1E at the new list ---
.org S2D_BAR_SLOT_INIT
    lui     a0, 0x800C
    addiu   a0, a0, -0x1800             ; 0x800C0000 - 0x1800 = S2D_BAR_LIST (was 0x8009D7E4)

;; --- the slot renderer's pen advance: jal the hook ---
.org S2D_BAR_ADV_SITE
    jal     sf_cell_adv_s2d
    nop

;; -------------------------------------------------------------
;; S2D StatusPersonaNames, rewritten in place (0xC0 bytes): the same
;; shape as ADV/DNG - arcana clear+write at 10 cells, name clear+grow+write
;; at 16, the full name grown straight into the name cells.
;; -------------------------------------------------------------
.org S2D_STATUS_NAMES
.area 0xC0

    addiu   sp, sp, -0x20
    sw      ra, 0x1C(sp)
    sw      s2, 0x18(sp)
    move    s2, a0                      ; the Persona*
    sw      s0, 0x10(sp)
    lui     s0, 0x800C
    addiu   s0, s0, -0x17D8             ; 0x800C0000 - 0x17D8 = S2D_BAR_CELLS

    ;; arcana: the retail clear+write pair
    move    a0, s0
    move    a2, zero                    ; (CellsClear ignores a2)
    ori     a1, zero, 10
    jal     S2D_CELLS_CLEAR
    nop
    move    a0, s0
    ori     a2, zero, 0x80              ; page 0 + bit 7: the VWF Latin face
    lbu     v0, 0x25(s2)                ; kind
    ori     a3, zero, 10
    addiu   v0, v0, -1
    sll     a1, v0, 2
    addu    a1, a1, v0
    sll     a1, a1, 1                   ; (kind-1)*10
    lui     v0, 0x800A
    addiu   v0, v0, -0x24DC             ; 0x800A0000 - 0x24DC = S2D_KIND_LABELS
    jal     S2D_CELLS_ROW
    addu    a1, a1, v0                  ; (delay)

    ;; name: clear 16 cells, grow the full name into the frame's free
    ;; outgoing-arg quad, then write it into the cells from there (the
    ;; codes cannot be grown into the cells themselves: the copy writes
    ;; them consecutively while the cells sit 8 bytes apart, and the
    ;; writer's own stores would trample not-yet-read codes)
    addiu   a0, s0, 0x58                ; S2D_BAR_NAME_CELLS (the block header sits at +0x50)
    ori     a1, zero, 16
    jal     S2D_CELLS_CLEAR
    nop
    move    a0, sp
    lbu     a1, 0x18(s2)                ; the Persona key (0-based record index)
    jal     persona_name_copy           ; that record's 16 glyphs
    nop                                 ; (delay) the key is already the record id
    addiu   a0, s0, 0x58                ; S2D_BAR_NAME_CELLS
    move    a1, sp
    ori     a2, zero, 0x80              ; page 0 + bit 7: the VWF Latin face
    ori     a3, zero, 16
    jal     S2D_CELLS_ROW
    nop

    lw      ra, 0x1C(sp)
    lw      s2, 0x18(sp)
    lw      s0, 0x10(sp)
    addiu   sp, sp, 0x20
    jr      ra
    nop
s2d_status_names_end:
.fill S2D_STATUS_NAMES + 0xC0 - s2d_status_names_end

.endarea
