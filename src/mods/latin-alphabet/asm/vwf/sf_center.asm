;; Center an explicitly padded row on its retail fixed-cell midpoint.
;; t5 = record, a2 = metrics, t1 = row x. Return through t6.
;; Only rows marked by an originally centered producer qualify. Tabs are excluded.
sf_center_row:
    lbu     t4, SF_REC_PAD + 1(t5)
    nop
    andi    t4, t4, 0x80
    beqz    t4, @@done
    addiu   a1, t5, SF_REC_CODES
    move    v0, zero                    ; number of cells
    move    v1, zero                    ; proportional pixel width
@@walk:
    lbu     t4, 0(a1)
    addiu   a1, a1, 1
    li      t8, 0xFF
    beq     t4, t8, @@end
    nop
    sltiu   t8, t4, SF_GLYPHS
    beqz    t8, @@done                  ; includes the tab control
    nop
    addu    t8, a2, t4
    lbu     t8, 0(t8)
    addiu   v0, v0, 1
    andi    t8, t8, 0x0F
    b       @@walk
    addu    v1, v1, t8
@@end:
    sll     v0, v0, 3
    subu    v0, v0, v1
    sra     v0, v0, 1
    addu    t1, t1, v0
@@done:
    jr      t6
    nop
sf_center_end:
