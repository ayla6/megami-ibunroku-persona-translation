    ;; The name in the original font, as the field kit draws it: the
    ;; retail cell at pen - its left bearing, then the pen moves by the
    ;; glyph's advance (mod_o_orig: bearing << 4 | advance per code).
    addu    t0, s7, s6
    lbu     t0, 0(t0)
    la      t3, mod_o_orig
    addu    t3, t3, t0
    lbu     t3, 0(t3)
    nop
    srl     t0, t3, 4               ; the left bearing
    andi    t3, t3, 0x0F            ; the advance
    subu    t0, s2, t0
    addu    t0, t0, s0
    sh      t0, 4(s5)
    addu    s2, s2, t3
