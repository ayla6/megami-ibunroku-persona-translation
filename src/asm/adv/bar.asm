;; =============================================================
;; The persona status / fusion bottom bar as two VWF sprite rows.
;;
;; Retail draws the bar as TWO ten-cell blocks (arcana + name) laid out by
;; one cel list, with the name block 4 px lower than the arcana - and the
;; name comes from the master record's ten-glyph head, so every English
;; name longer than ten glyphs is cut ("Seimen Kon"). This file:
;;   * rebuilds the bar as retail's TWO cel entries: the arcana block
;;     (10 cells, dx=0, dy=0) and the name block (16 cells expanded from
;;     retail's 10, at the retail name entry's dx=0x58, dy=4): the name is
;;     its own cel-entry line, 88 px right of the arcana and 4 px (half a
;;     character) lower, exactly like retail Japanese;
;;   * keeps the rows in retail's own homes: the arcana block at 0x800B20B4,
;;     the name header at 0x800B210C, whose cells grow from ten to sixteen
;;     over the retail cel list (moved to ADV_BAR_LIST) and over the 1x1
;;     slot-0x20 block at 0x800B2188 (moved to the image tail). The retail
;;     table at 0x800B209C is g_fm_mark_pos - the five member-marker
;;     positions every marker site reads - and is never written;
;;   * hangs sf_cell_adv on the slot renderer's per-cell pen advance, which
;;     applies each cell's stored advance while the entry's pad halfword
;;     marks the row (adv/cells_row.asm stores it);
;;   * retargets the status layout's list pointer and rewrites
;;     StatusPersonaNames and the fusion draw helper's two write pairs:
;;     every name is persona_name_copy(_at)'d straight into the name cells
;;     and written back in place with count 16, so the full name shows and
;;     both texts render at their own widths. Each pair also reloads the
;;     arcana base before its arcana row, because CellsWriteRow clobbers a0
;;     (retail's reload was load-bearing); the label index is kind*10
;;     against ADV_KIND_LABELS-10 to keep the pair in retail's span;
;;   * passes bit 7 of the writer's page argument on both rows, so the
;;     writer maps each retail cell code to the regular VWF Latin cell the
;;     text renderer uses. Without it the bar kept the retail atlas with
;;     VWF advances (the right widths on the wrong face).
;;
;; Every other sprite-cell row in the game (chest results, moon names,
;; entry labels, the persona-data screen) keeps retail pixels: their cel
;; entries carry no mark, so the hook advances them by the block width as
;; before. The same treatment for DNG's copies of these screens is
;; dng/bar.asm.
;; =============================================================
.psx

;; --- sf_cell_adv: the slot renderer's pen advance, per cell ---
;; Runs at the point retail computed pen += w. s4 is the pen, s6 the cell,
;; t9 the cel entry, a3 the block's cell width. Only v1 is clobbered (v0
;; is dead here; the loop reloads everything it needs). A marked entry
;; advances the pen by the cell's +3 byte; anything else advances by w,
;; byte-for-byte retail.
.org ADV_BAR_HOOK
.area ADV_BAR_HOOK_END - ADV_BAR_HOOK

sf_cell_adv:
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

;; --- the bar data: retail's two homes, one grown name row ---
;; The arcana stays at retail's block; the name header stays at retail's
;; header and its cells grow to sixteen over the retail cel list (0x800B2164,
;; moved to the hook/state gap) and over the 1x1 slot-0x20 block at
;; 0x800B2188 (moved to the image tail). The table at 0x800B209C is
;; g_fm_mark_pos and stays untouched. Retail's name entry (dx=0x58, dy=4) is
;; reproduced verbatim.
.org ADV_BAR_LIST
    .word   ADV_BAR_ARCANA_BLOCK    ; entry 1: the 10 arcana cells
    .halfword 0                     ; dx: the arcana starts at the slot's own x
    .halfword 0                     ; dy: the slot's own baseline
    .halfword 0                     ; z
    .halfword SF_BAR_MARK           ; the pad the advance hook reads
    .word   ADV_BAR_NAME_BLOCK      ; entry 2: the 16 name cells
    .halfword 0x58                  ; dx: retail's name entry
    .halfword 4                     ; dy: retail's name entry (the second line)
    .halfword 0                     ; z
    .halfword SF_BAR_MARK           ; the pad the advance hook reads
    .word   0xFFFFFFFF              ; the entry walk's terminator

.org ADV_BAR_ARCANA_BLOCK
    .byte   10, 1                   ; cols, rows
    .halfword 0                     ; attr: the unscaled renderer branch
    .halfword 8, 12                 ; w, h

;; The cells' retail init: u=v=0 (the atlas's blank glyph), texture page
;; 0x1E in the cba low byte, +3 free for the advance, CLUT 0x3C0/0x1A0.
.org ADV_BAR_CELLS
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

.org ADV_BAR_NAME_BLOCK
    .byte   16, 1                   ; cols, rows: retail's 10-name cells + 6
    .halfword 0                     ; attr: the unscaled renderer branch
    .halfword 8, 12                 ; w, h

.org ADV_BAR_NAME_CELLS
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

;; --- the slot-0x20 block retail kept at 0x800B2188, moved to the image tail ---
;; The grown name cells cover 0x800B2188..0x800B2194; this block's 0x10 bytes
;; (a 1x1 header and its one cell) are the only live data there. Its list at
;; 0x800B2198 stays where retail put it and only its block word moves. The
;; block follows the small-font extension, wherever that ends, and both stay
;; inside the image.
.org ADV_MENU_TOP_LIST
    .word   adv_menu_top_def
.org sf_extension_end_adv
adv_menu_top_def:
    .byte   1, 1                    ; cols, rows
    .halfword 0x0100                ; attr: retail's own
    .halfword 0x0060, 0x0090        ; w, h
    .byte   0x00, 0x68, 0x15, 0x00, 0x00, 0x00, 0xE6, 0x01   ; the retail cell
adv_menu_top_def_end:
.if adv_menu_top_def_end > ADV_IMAGE_LIMIT
    .error "adv/bar: the slot-0x20 block runs past the ADV image limit"
.endif

;; --- the status layout points slot 0x1E at the new list ---
;; The list is at 0x800BD224, across the 0x800B/0x800C halfword boundary, so
;; keep retail's lui 0x800B and use ori (zero-extends) for the low half.
.org ADV_BAR_SLOT_INIT + 4
    ori     a0, a0, 0xD224          ; ADV_BAR_LIST

;; --- the slot renderer's pen advance: jal the hook ---
.org ADV_BAR_ADV_SITE
    jal     sf_cell_adv
    nop

;; -------------------------------------------------------------
;; StatusPersonaNames, rewritten in place (0xC0 bytes): clear+write the
;; arcana at its retail 10 cells, then clear the 16 name cells, grow the
;; full name straight into them and write them back in place. The name
;; comes from the master record by key - never the ten-byte head.
;; -------------------------------------------------------------
.org ADV_STATUS_NAMES
.area 0xC0

    addiu   sp, sp, -0x20
    sw      ra, 0x1C(sp)
    sw      s2, 0x18(sp)
    move    s2, a0                      ; the Persona*
    sw      s0, 0x10(sp)
    lui     s0, 0x800B
    addiu   s0, s0, 0x20BC              ; ADV_BAR_CELLS (retail's arcana cells)

    ;; arcana: the retail clear+write pair
    move    a0, s0
    move    a2, zero                    ; (CellsClear ignores a2)
    ori     a1, zero, 10
    jal     ADV_CELLS_CLEAR
    nop
    move    a0, s0
    ori     a2, zero, 0x80              ; page 0 + bit 7: the VWF Latin face
    lbu     v0, 0x25(s2)                ; kind
    ori     a3, zero, 10
    addiu   v0, v0, -1
    sll     a1, v0, 2
    addu    a1, a1, v0
    sll     a1, a1, 1                   ; (kind-1)*10
    lui     v0, 0x800B
    addiu   v0, v0, 0x24A4              ; ADV_KIND_LABELS
    jal     ADV_CELLS_ROW
    addu    a1, a1, v0                  ; (delay)

    ;; name: clear 16 cells, grow the full name into the frame's free
    ;; outgoing-arg quad (sp+0x00..0x0F: this function's spills live at
    ;; 0x10 and up, and its calls take four registers), then write it
    ;; into the cells from there. The codes cannot be grown into the
    ;; cells themselves: the copy writes them consecutively while the
    ;; cells sit 8 bytes apart, and the writer's own stores would
    ;; trample not-yet-read codes.
    addiu   a0, s0, 0x58                ; ADV_BAR_NAME_CELLS (the block header sits at +0x50)
    ori     a1, zero, 16
    jal     ADV_CELLS_CLEAR
    nop
    move    a0, sp
    lbu     a1, 0x18(s2)                ; the Persona key (0-based record index)
    jal     persona_name_copy           ; that record's 16 glyphs
    nop                                 ; (delay) the key is already the record id
    addiu   a0, s0, 0x58                ; ADV_BAR_NAME_CELLS
    move    a1, sp
    ori     a2, zero, 0x80              ; page 0 + bit 7: the VWF Latin face
    ori     a3, zero, 16
    jal     ADV_CELLS_ROW
    nop

    lw      ra, 0x1C(sp)
    lw      s2, 0x18(sp)
    lw      s0, 0x10(sp)
    addiu   sp, sp, 0x20
    jr      ra
    nop
status_names_end:
.fill ADV_STATUS_NAMES + 0xC0 - status_names_end

.endarea

;; -------------------------------------------------------------
;; The fusion draw helper (0x8009F8E8): the two name+kind write pairs.
;; Each name is grown through persona_name_copy(_at) into the helper's
;; own free frame quad and then written into the name cells with count
;; 16 (the def path takes the record's name field directly; the built
;; path the Persona's own). No insertions: each pair fits the slots the
;; retail writes used.
;; -------------------------------------------------------------

;; the helper's two clears: retail's bases already name the arcana cells and
;; the (grown) name cells; only the name clear's count changes to 16
;; (retail: lui/addiu 0x800B:0x20BC at +0x00/+0x04, lui/addiu 0x800B:0x2114
;; at +0x54/+0x58, count ori 10 at +0x60)
.org ADV_FUSE_CLEAR1 + 0x60
    ori     a1, zero, 16                ; the name clear covers all 16 cells (was 10)

;; the def path: s3 = g_persona_defs entry, its name field at +8
.org ADV_FUSE_SITE_A
.area 0x4C

    move    a0, sp                      ; the frame's free 0x00..0x0F quad: the scratch
    jal     persona_name_copy_at        ; the def's own name field, v1 below
    addiu   v1, s3, 8                   ; (delay) persona_name_copy_at reads v1
    lui     a0, 0x800B
    addiu   a0, a0, 0x2114              ; ADV_BAR_NAME_CELLS
    ori     a2, zero, 0x80              ; page 0 + bit 7: the VWF Latin face
    ori     a3, zero, 16
    jal     ADV_CELLS_ROW
    move    a1, sp                      ; (delay) the scratch
    ;; The arcana, at the retail label table. The row writer clobbers a0
    ;; (its destination is t0; a0 becomes the glyph column), so retail's
    ;; reload of the arcana base is load-bearing and this rewrite must set
    ;; a0 again. The index is kind*10 against ADV_KIND_LABELS-10, which is
    ;; what (kind-1)*10 against the table is - and the shorter form keeps
    ;; the whole pair inside the retail span.
    lbu     v0, 0x14(s3)                ; kind
    ori     a3, zero, 10
    sll     a1, v0, 2
    addu    a1, a1, v0
    sll     a1, a1, 1                   ; kind*10
    lui     v0, 0x800B
    addiu   v0, v0, 0x249A              ; ADV_KIND_LABELS - 10
    addu    a1, a1, v0                  ; (kind-1)*10 + ADV_KIND_LABELS
    jal     ADV_CELLS_ROW               ; a2 = 0x80 survives the row writer
    addiu   a0, v0, -0x3DE              ; (delay) ADV_BAR_CELLS = v0 - 0x3DE

.endarea

;; the built path: s4 = Persona, its name field at +0x19
.org ADV_FUSE_SITE_B
.area 0x4C

    move    a0, sp                      ; the frame's free quad: the scratch
    jal     persona_name_copy_at        ; the built record's name field, v1 below
    addiu   v1, s4, 0x19                ; (delay) persona_name_copy_at reads v1
    lui     a0, 0x800B
    addiu   a0, a0, 0x2114              ; ADV_BAR_NAME_CELLS
    ori     a2, zero, 0x80              ; page 0 + bit 7: the VWF Latin face
    ori     a3, zero, 16
    jal     ADV_CELLS_ROW
    move    a1, sp                      ; (delay) the scratch
    ;; The arcana base must be reloaded after the name write: the row
    ;; writer clobbers a0. kind*10 against ADV_KIND_LABELS-10 keeps the
    ;; pair inside the retail span (see the def path above).
    lbu     v0, 0x25(s4)                ; kind
    ori     a3, zero, 10
    sll     a1, v0, 2
    addu    a1, a1, v0
    sll     a1, a1, 1                   ; kind*10
    lui     v0, 0x800B
    addiu   v0, v0, 0x249A              ; ADV_KIND_LABELS - 10
    addu    a1, a1, v0                  ; (kind-1)*10 + ADV_KIND_LABELS
    jal     ADV_CELLS_ROW               ; a2 = 0x80 survives the row writer
    addiu   a0, v0, -0x3DE              ; (delay) ADV_BAR_CELLS = v0 - 0x3DE

.endarea
