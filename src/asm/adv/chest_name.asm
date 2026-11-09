;; ADV field item pickup: the original ten-cell sprite block is repurposed
;; as code. Its replacement block is battle's mutually exclusive unpack
;; scratch; the dialogue compositor starts after that scratch.
.if SF_VWF
.definelabel ADV_CHEST_NAME_BLOCK, BTLEVT_BUF_ADDR
.definelabel ADV_CHEST_NAME_CELLS, ADV_CHEST_NAME_BLOCK + 8
.definelabel ADV_CHEST_NAME_COUNT, ITEM_NAME_MAXLEN
.if ADV_CHEST_NAME_BLOCK + 8 + ADV_CHEST_NAME_COUNT * 8 > VWF_DLG_RING_ADDR
    .error "chest name cells reach the dialogue compositor"
.endif

;; The original cel list keeps its quantity and multiplication-sign rows.
.org 0x800B5A1C
    .word ADV_CHEST_NAME_BLOCK
.org 0x800B5A26
    .halfword SF_BAR_MARK

;; s3 is the cell base. Jump before the original clear; the delay slot saves
;; ra exactly as retail did, and the helper returns to the next instruction.
.org 0x80081C14
    la      s3, ADV_CHEST_NAME_CELLS
    j       chest_name_init
.org 0x80081C3C
    ori     a1, zero, ADV_CHEST_NAME_COUNT

;; The caller's outgoing-argument area has 24 bytes before its saved s0.
;; Build the full FF-terminated item there and write it once to the cells.
.org 0x80081C84
.area 0x28
    move    a0, sp
    lui     a1, 0x800F
    lhu     a1, 0x7EB8(a1)
    jal     item_name_copy_adv
    nop
    move    a0, s3
    move    a1, sp
    ori     a2, zero, 0x80
    jal     ADV_CELLS_ROW
    ori     a3, zero, ADV_CHEST_NAME_COUNT
.endarea

;; t0 remains the cell cursor returned by CellsWriteRow until SlotInitTagged.
;; Use its glyph count times the retail cell width as a conservative bound,
;; so even the widest possible VWF cells remain inside the 320px screen.
.org 0x80081D28
    jal     chest_clamp_entry
    sw      v0, 0x10(sp)

;; Retail's 88-byte name block is no longer referenced after the list rewrite.
.org 0x800B599C
.area 0x58
chest_name_init:
    addiu   t0, s3, -8
    ori     t1, zero, 0x0100 + ADV_CHEST_NAME_COUNT ; columns, one row, attr 0
    sw      t1, 0(t0)
    lui     t1, 0x000C
    ori     t1, t1, 8                   ; 8x12 cell dimensions
    sw      t1, 4(t0)
    move    t0, s3
    ori     t1, zero, 0x1E              ; retail texture page
    ori     t2, zero, ADV_CHEST_NAME_COUNT
@@init:
    sh      t1, 2(t0)                   ; page and cleared advance byte
    addiu   t2, t2, -1
    bnez    t2, @@init
    addiu   t0, t0, 8
    j       0x80081C24
    move    a0, s3

chest_clamp_lower:
    slti    t2, a3, -32                 ; cel-list x=32 must stay visible
    beqz    t2, @@open
    nop
    addiu   a3, zero, -32
@@open:
    j       0x80065EB0                  ; original SlotInitTagged, preserves ra
    nop
.endarea
.endif
