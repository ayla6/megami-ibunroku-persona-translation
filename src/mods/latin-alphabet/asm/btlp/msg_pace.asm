;; Both battle windows emit at most two glyphs per typing step. Only the
;; plain-glyph call sites enter this wrapper; their control interpreters still
;; run once. Stop before FF, a full page, or an emitter that defers a glyph.
.org BTLP_MESSAGE_PACE_ADDR
.area BTLP_MESSAGE_PACE_END - BTLP_MESSAGE_PACE_ADDR
btl_message_pace:
    addiu   sp, sp, -0x20
    sw      ra, 0x1C(sp)
    sw      s0, 0x18(sp)
    sw      s1, 0x14(sp)
    move    s0, a0
    move    s1, a1
    jal     btlp_vwf_emit
    nop
    beq     v0, s1, @@done
    nop
    move    s1, v0
    lbu     t0, 0(v0)
    lw      t1, 0x1C(s0)
    ori     t2, zero, 0xFF
    beq     t0, t2, @@done
    sltiu   t1, t1, 45
    beqz    t1, @@done
    nop
    move    a0, s0
    jal     btlp_vwf_emit
    move    a1, s1
@@done:
    lw      ra, 0x1C(sp)
    lw      s0, 0x18(sp)
    lw      s1, 0x14(sp)
    jr      ra
    addiu   sp, sp, 0x20
.endarea
