;; Offer-only gate: three VWF ranges. The CONTACT personality bank and the
;; negotiation stock-name bank use the battle small-font width table; the
;; CONTACT producer's ten-glyph head in PERSONA_HDR_BUF continues past its
;; own length check in offer_maybe_name. Every other glyph row returns to
;; retail (offer_name_ret) with its art mode left alone.
;; t4=0 for position, t4=1 after text has advanced. All t registers are
;; caller-scratch and the surrounding retail glyph loop does not use them.
offer_gate:
    subu    t2, s1, t4                 ; advance mode points past the glyph
    lui     t0, hi(BTLP_PERSONALITY_BANK)
    addiu   t0, t0, lo(BTLP_PERSONALITY_BANK)
    subu    t1, t2, t0
    sltiu   t1, t1, BTLP_PERSONALITY_BANK_END - BTLP_PERSONALITY_BANK
    bnez    t1, @@lookup
    lbu     t3, 0(t2)                  ; glyph code for the width table
    lui     t0, hi(BTLP_STOCK_FULL_ADDR)
    addiu   t0, t0, lo(BTLP_STOCK_FULL_ADDR)
    subu    t1, t2, t0
    sltiu   t1, t1, BTLP_STOCK_FULL_SIZE
    bnez    t1, @@lookup
    lbu     t3, 0(t2)
    lui     t0, hi(PERSONA_HDR_BUF)
    addiu   t0, t0, lo(PERSONA_HDR_BUF)
    j       offer_maybe_name
    subu    t0, t2, t0
@@lookup:
    j       offer_lookup
    nop
