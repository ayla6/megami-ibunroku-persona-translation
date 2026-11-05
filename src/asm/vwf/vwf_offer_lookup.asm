;; The CONTACT producer owns up to DEMON_NAME_MAXLEN glyph bytes in the
;; menu-name scratch. Other effect rows return the retail coordinate and
;; advance, and leave the art mode alone (offer_name_ret).
offer_maybe_name:
    sltiu   t0, t0, DEMON_NAME_MAXLEN
    beqz    t0, offer_name_ret
    nop
;; t3=code, t4=0 position / 1 advance. Use the same complete width table
;; as the battle object-text bridge, including glyphs absent from labels.
offer_lookup:
    lui     t0, hi(BTLP_SF_WIDTH_ADDR)
    addu    t0, t0, t3
    lbu     v0, lo(BTLP_SF_WIDTH_ADDR)(t0)
    nop
    beqz    t4, @@position
    andi    t1, v0, 15
    addiu   t1, t1, -1
    jr      ra
    addu    s4, s4, t1
@@position:
    j       offer_finish_position
    srl     t1, v0, 4
