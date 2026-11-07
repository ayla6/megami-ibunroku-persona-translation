;; =============================================================
;; ADV.BIN - the Velvet Room card list's race + demon-name bar
;; (adv/pdata.asm)
;;
;; This is the ADV copy of the same bottom bar dng/pdata.asm fixes for
;; the dungeon menu's Persona Data page: retail draws the selected
;; demon's race and name as two fixed-width sprite-cell rows sourced
;; from ten-byte record fields, so every English name longer than ten
;; glyphs is cut after its head.
;;
;; The page keeps retail's race block (six cells) and its two-entry cel
;; list. Only the name row changes:
;;
;;   * both cel entries carry SF_BAR_MARK, which makes the slot
;;     renderer's advance hook (sf_cell_adv, adv/bar.asm) use each
;;     cell's stored advance instead of the block's fixed width;
;;   * the name row points at the status bar's sixteen-cell block
;;     (ADV_BAR_NAME_BLOCK, adv/bar.asm). Retail's name block sits
;;     immediately before the page's cel list and cannot grow in place,
;;     and the image has no free 16-cell run; the card page and the
;;     status page are separate layouts, so the two screens rewrite the
;;     block before their own slot renders it;
;;   * the full name comes from demon_name_copy_adv, never the ten-byte
;;     record head, and is written into the cells by the same
;;     CellsWriteRow every bar row uses;
;;   * retail's ten-cell name block becomes this page's helper. It is
;;     exactly 88 bytes, and the helper below fits it exactly.
;;
;; The race row stays in PersonaDataDraw's retail tail (it already
;; builds id*0x38 in s0 and keeps the id in s5); only its page argument
;; gains bit 7 so the writer maps the six race codes to the regular VWF
;; Latin face and stores their advances.
;; =============================================================
.psx

.if SF_VWF

;; -------------------------------------------------------------
;; The name row helper, in retail's old ten-cell name block.
;; a0 = the demon id (1-based, as the record table indexes it).
;;
;; demon_name_copy_adv builds the complete FF-terminated name in the
;; overlay's name scratch; the cells are cleared and then written from
;; that scratch with the VWF Latin face. The final writer call is a
;; tail call so the helper fits the 88-byte home exactly.
;; -------------------------------------------------------------
.org ADV_PDATA_BAR
.area ADV_PDATA_BAR_END - ADV_PDATA_BAR

pdata_bar_adv:
    addiu   sp, sp, -8
    sw      ra, 0(sp)
    move    a1, a0                      ; the demon id
    lui     a0, 0x800C
    addiu   a0, a0, -0x474              ; sf_name_scratch_adv (0x800BFB8C)
    jal     demon_name_copy_adv
    nop
    lui     a0, 0x800B
    addiu   a0, a0, 0x2114              ; ADV_PDATA_NAME_CELLS
    ori     a1, zero, ADV_PDATA_NAME_COLS
    jal     ADV_CELLS_CLEAR
    nop
    lui     a0, 0x800B
    addiu   a0, a0, 0x2114              ; ADV_PDATA_NAME_CELLS
    lui     a1, 0x800C
    addiu   a1, a1, -0x474              ; sf_name_scratch_adv
    ori     a2, zero, 0x80              ; page 0 + bit 7: the VWF Latin face
    ori     a3, zero, ADV_PDATA_NAME_COLS
    lw      ra, 0(sp)
    addiu   sp, sp, 8
    j       ADV_CELLS_ROW               ; the row writer returns to our caller
    nop
pdata_bar_adv_end:
.fill ADV_PDATA_BAR_END - pdata_bar_adv_end

.endarea

.if pdata_bar_adv_end > ADV_PDATA_BAR_END
    .error "pdata: the ADV name-row helper overruns retail's old name block"
.endif

;; -------------------------------------------------------------
;; PersonaDataDraw's bar tail: the name row becomes one helper call;
;; the race row keeps retail's code and gains the VWF face.
;; s0 = id * 0x38, s5 = the demon id (retail's own registers).
;; -------------------------------------------------------------
.org ADV_PDATA_TAIL
.area ADV_PDATA_TAIL_END - ADV_PDATA_TAIL

    move    a0, s5
    jal     pdata_bar_adv
    nop
    .fill   0x30 - 12, 0                ; retail's old name writes; now dead

    ;; race: retail's six cells, written with the VWF Latin face
    lui     a0, 0x800C
    addiu   a0, a0, -0x5F78             ; ADV_PDATA_RACE_CELLS (0x800BA088)
    ori     a2, zero, 0x80              ; page 0 + bit 7: the VWF Latin face
    lui     at, 0x8004
    addiu   at, at, 0x17AB              ; the record's race byte
    addu    at, at, s0
    lbu     v0, 0(at)
    ori     a3, zero, 6
    addiu   v0, v0, -1                  ; race is 1-based
    sll     a1, v0, 1
    addu    a1, a1, v0
    sll     a1, a1, 1                   ; (race - 1) * 6
    lui     v0, 0x800B
    addiu   v0, v0, 0x23C0              ; ADV_PDATA_RACE_TABLE
    jal     ADV_CELLS_ROW
    addu    a1, a1, v0                  ; (delay) the race label
pdata_tail_end_adv:
.fill ADV_PDATA_TAIL_END - pdata_tail_end_adv

.endarea

;; -------------------------------------------------------------
;; the page's cel list: retail's placement, both entries marked, the
;; name entry repointed at the shared sixteen-cell block.
;; Retail's race entry is dx=0/dy=0; its name entry is dx=0x40/dy=0xC.
;; -------------------------------------------------------------
.org ADV_PDATA_CEL_LIST
    .word   ADV_PDATA_RACE_BLOCK
    .halfword 0                     ; dx
    .halfword 0                     ; dy
    .halfword 0                     ; z
    .halfword SF_BAR_MARK           ; the pad the advance hook reads
    .word   ADV_PDATA_NAME_BLOCK
    .halfword 0x40                  ; dx: retail's name entry
    .halfword 0x0C                  ; dy: retail's name entry
    .halfword 0                     ; z
    .halfword SF_BAR_MARK           ; the pad the advance hook reads
    .word   0xFFFFFFFF

.endif                              ; SF_VWF
