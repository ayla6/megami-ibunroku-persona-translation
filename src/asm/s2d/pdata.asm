;; =============================================================
;; S2D.BIN - the Persona Data page's race + demon-name bar
;; (s2d/pdata.asm)
;;
;; The overworld menu compiles its own copy of PersonaDataDraw, so the
;; ADV/DNG pdata fix never reached it: the page keeps drawing the selected
;; demon's race and name as fixed-width sprite-cell rows sourced from
;; ten-byte record fields, and every English name longer than ten glyphs
;; is cut after its head.
;;
;; This is the same port as adv/pdata.asm. The page keeps retail's race
;; block (six cells) and its two-entry cel list. Only the name row changes:
;;
;;   * both cel entries carry SF_BAR_MARK, which makes S2D's slot
;;     renderer advance hook (sf_cell_adv_s2d, s2d/bar.asm) use each
;;     cell's stored advance instead of the block's fixed width;
;;   * the name row points at the status bar's sixteen-cell block
;;     (S2D_BAR_NAME_BLOCK, s2d/bar.asm). Retail's name block sits
;;     immediately before the page's cel list and cannot grow in place,
;;     and the image has no free sixteen-cell run; the page and the
;;     status screen are separate layouts, so the two screens rewrite
;;     the block before their own slot renders it;
;;   * the full name comes from demon_name_copy_s2d, never the ten-byte
;;     record head, and is written into the cells by the same
;;     CellsWriteRow every bar row uses;
;;   * retail's ten-cell name block becomes this page's helper. It is
;;     exactly 88 bytes, and the helper below fits it exactly.
;;
;; The race row stays in PersonaDataDraw's retail tail (s0 is the
;; record offset id*0x38, s5 is the demon id); only its page argument
;; gains bit 7 so the writer maps the six race codes to the regular VWF
;; Latin face and stores their advances.
;; =============================================================
.psx

.if SF_VWF

;; -------------------------------------------------------------
;; The name row helper, in retail's old ten-cell name block.
;; a0 = the demon id (1-based, as the record table indexes it).
;;
;; demon_name_copy_s2d builds the complete FF-terminated name in the
;; overlay's name scratch; the cells are cleared and then written from
;; that scratch with the VWF Latin face. The final writer call is a
;; tail call so the helper fits the 88-byte home exactly.
;; -------------------------------------------------------------
.org S2D_PDATA_BAR
.area S2D_PDATA_BAR_END - S2D_PDATA_BAR

pdata_bar_s2d:
    addiu   sp, sp, -8
    sw      ra, 0(sp)
    move    a1, a0                      ; the demon id
    la      a0, sf_name_scratch_s2d
    jal     demon_name_copy_s2d
    nop
    la      a0, S2D_PDATA_NAME_CELLS
    ori     a1, zero, S2D_PDATA_NAME_COLS
    jal     S2D_CELLS_CLEAR
    nop
    la      a0, S2D_PDATA_NAME_CELLS
    la      a1, sf_name_scratch_s2d
    ori     a2, zero, 0x80              ; page 0 + bit 7: the VWF Latin face
    ori     a3, zero, S2D_PDATA_NAME_COLS
    lw      ra, 0(sp)
    addiu   sp, sp, 8
    j       S2D_CELLS_ROW               ; the row writer returns to our caller
    nop
pdata_bar_s2d_end:
.fill S2D_PDATA_BAR_END - pdata_bar_s2d_end

.endarea

.if pdata_bar_s2d_end > S2D_PDATA_BAR_END
    .error "pdata: the S2D name-row helper overruns retail's old name block"
.endif

;; -------------------------------------------------------------
;; PersonaDataDraw's bar tail: the name row becomes one helper call;
;; the race row keeps retail's code and gains the VWF face.
;; s0 = id * 0x38, s5 = the demon id (retail's own registers).
;; -------------------------------------------------------------
.org S2D_PDATA_TAIL
.area S2D_PDATA_TAIL_END - S2D_PDATA_TAIL

    move    a0, s5
    jal     pdata_bar_s2d
    nop
    .fill   0x30 - 12, 0                ; retail's old name writes; now dead

    ;; race: retail's six cells, written with the VWF Latin face
    la      a0, S2D_PDATA_RACE_CELLS
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
    la      v0, S2D_PDATA_RACE_TABLE
    jal     S2D_CELLS_ROW
    addu    a1, a1, v0                  ; (delay) the race label
pdata_tail_end_s2d:
.fill S2D_PDATA_TAIL_END - pdata_tail_end_s2d

.endarea

;; -------------------------------------------------------------
;; the page's cel list: retail's placement, both entries marked, the
;; name entry repointed at the shared sixteen-cell block.
;; Retail's race entry is dx=0/dy=0; its name entry is dx=0x40/dy=0xC.
;; -------------------------------------------------------------
.org S2D_PDATA_CEL_LIST
    .word   S2D_PDATA_RACE_BLOCK
    .halfword 0                     ; dx
    .halfword 0                     ; dy
    .halfword 0                     ; z
    .halfword SF_BAR_MARK           ; the pad the advance hook reads
    .word   S2D_PDATA_NAME_BLOCK
    .halfword 0x40                  ; dx: retail's name entry
    .halfword 0x0C                  ; dy: retail's name entry
    .halfword 0                     ; z
    .halfword SF_BAR_MARK           ; the pad the advance hook reads
    .word   0xFFFFFFFF

.endif                              ; SF_VWF
