;; t1 = row origin, t2 = pen; return next 40-pixel stop in t2 via t6.
;; Clobbers t4, t8 and HI/LO. Shared by reservation and emission.
.org SF_TAB_HELPER_ADDR
sf_tab_advance:
    subu    t4, t2, t1
    li      t8, 40
    divu    t4, t8
    nop
    nop
    mflo    t4
    addiu   t4, t4, 1
    multu   t4, t8
    nop
    nop
    mflo    t2
    jr      t6
    addu    t2, t2, t1
;; Renderer adapter; t3 remains the glyph cursor and t8 the atlas bank.
sf_tab_emit:
    sw      t8, 0x48(sp)
    move    t2, t1
    lw      t1, 0x54(sp)
    li      t4, SF_TAB_HELPER_ADDR
    jalr    t4, t6
    nop
    move    t1, t2
    lw      t8, 0x48(sp)
    jr      ra
    nop
.if . > SF_TAB_HELPER_END
    .error "smallfont tab helper overruns its resident run"
.endif
