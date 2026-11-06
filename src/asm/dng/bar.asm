;; =============================================================
;; DNG's copy of the persona status bottom bar (the mirror of
;; adv/cells_row.asm + adv/bar.asm; see the ADV file for the full story).
;;
;; DNG has ONE write site (the dungeon menu's Persona page; its
;; persona-data screen reads dynamic records and stays retail), so this
;; file carries no fusion patches and no persona_name_copy_at user. The
;; hint table stays at 0x8009AB90 - SEVENTEEN reader sites name it - and
;; the bar's list and rows move out to the image tail instead; the old
;; span's blocks and cel list become dead bytes. The list, both blocks and
;; the hook live past the current image end, below the 0x800C0000 work area,
;; the same grow-by-sectors rule every DNG extension tool already uses.
;; =============================================================
.psx

;; --- DNG CellsWriteRow, rewritten in place (identical body to ADV's) ---
.org DNG_CELLS_ROW
.area 0xC0

dng_writer_start:
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
    la      t8, sf_widths_dng       ; this overlay's advance table

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
    jal     sf_variant_uv_v1_dng    ; retail code -> the regular Latin cell
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
dng_writer_end:
.fill DNG_CELLS_ROW + 0xC0 - dng_writer_end

.endarea

;; --- sf_cell_adv_dng: the slot renderer's pen advance, per cell ---
;; Same shape as the ADV hook (the renderer is compiled into both overlays
;; with identical registers: s4 pen, s6 cell, t9 entry, a3 width).
.org DNG_BAR_HOOK
.area DNG_BAR_HOOK_END - DNG_BAR_HOOK

sf_cell_adv_dng:
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

;; --- the bar data at the image tail: retail's two rows ---
;; The list keeps retail's name entry dx=0x58, dy=4; the name block grows
;; from retail's 10 cells to 16. The 28-byte two-entry list does not fit
;; beside the blocks (0x800B54D0..0x800B54E8 is the DNG name scratch, then
;; only 0x18 bytes to 0x800B5500), so it follows the hook at 0x800B5610.
.org DNG_BAR_LIST
    .word   DNG_BAR_ARCANA_BLOCK
    .halfword 0                     ; dx: the arcana starts at the slot's own x
    .halfword 0                     ; dy: the slot's own baseline
    .halfword 0                     ; z
    .halfword SF_BAR_MARK           ; the pad the advance hook reads
    .word   DNG_BAR_NAME_BLOCK
    .halfword 0x58                  ; dx: retail's name entry
    .halfword 4                     ; dy: retail's name entry (the second line)
    .halfword 0                     ; z
    .halfword SF_BAR_MARK           ; the pad the advance hook reads
    .word   0xFFFFFFFF

.org DNG_BAR_ARCANA_BLOCK
    .byte   10, 1
    .halfword 0
    .halfword 8, 12

.org DNG_BAR_CELLS
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

.org DNG_BAR_NAME_BLOCK
    .byte   16, 1
    .halfword 0
    .halfword 8, 12

.org DNG_BAR_NAME_CELLS
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

;; --- the slot layout points slot 0x1E at the new list ---
.org DNG_BAR_SLOT_INIT
    lui     a0, 0x800B
    addiu   a0, a0, 0x5610              ; DNG_BAR_LIST (was lui 0x800A / addiu -0x53AC)

;; --- the slot renderer's pen advance: jal the hook ---
.org DNG_BAR_ADV_SITE
    jal     sf_cell_adv_dng
    nop

;; -------------------------------------------------------------
;; DNG StatusPersonaNames, rewritten in place (0xC0 bytes): the same
;; shape as ADV's - arcana clear+write at 10 cells, name clear+grow+write
;; at 16, the full name grown straight into the name cells.
;; -------------------------------------------------------------
.org DNG_STATUS_NAMES
.area 0xC0

    addiu   sp, sp, -0x20
    sw      ra, 0x1C(sp)
    sw      s2, 0x18(sp)
    move    s2, a0                      ; the Persona*
    sw      s0, 0x10(sp)
    lui     s0, 0x800B
    addiu   s0, s0, 0x5508              ; DNG_BAR_CELLS

    ;; arcana: the retail clear+write pair
    move    a0, s0
    move    a2, zero                    ; (CellsClear ignores a2)
    ori     a1, zero, 10
    jal     DNG_CELLS_CLEAR
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
    addiu   v0, v0, 0xAF94              ; DNG_KIND_LABELS
    jal     DNG_CELLS_ROW
    addu    a1, a1, v0                  ; (delay)

    ;; name: clear 16 cells, grow the full name into the frame's free
    ;; outgoing-arg quad, then write it into the cells from there (the
    ;; codes cannot be grown into the cells themselves: the copy writes
    ;; them consecutively while the cells sit 8 bytes apart, and the
    ;; writer's own stores would trample not-yet-read codes)
    addiu   a0, s0, 0x58                ; DNG_BAR_NAME_CELLS (the block header sits at +0x50)
    ori     a1, zero, 16
    jal     DNG_CELLS_CLEAR
    nop
    move    a0, sp
    lbu     a1, 0x18(s2)                ; the Persona key (0-based record index)
    jal     persona_name_copy           ; that record's 16 glyphs
    nop                                 ; (delay) the key is already the record id
    addiu   a0, s0, 0x58                ; DNG_BAR_NAME_CELLS
    move    a1, sp
    ori     a2, zero, 0x80              ; page 0 + bit 7: the VWF Latin face
    ori     a3, zero, 16
    jal     DNG_CELLS_ROW
    nop

    lw      ra, 0x1C(sp)
    lw      s2, 0x18(sp)
    lw      s0, 0x10(sp)
    addiu   sp, sp, 0x20
    jr      ra
    nop
dng_status_names_end:
.fill DNG_STATUS_NAMES + 0xC0 - dng_status_names_end

.endarea
