;; Offer-only gate: private personality bank and the retail offer-name buffer.
;; Other glyph rows go to offer_name_ret, which is also the mode-aware exit
;; (see below).
;; t4=0 for position, t4=1 after text has advanced. All t registers are
;; caller-scratch and the surrounding retail glyph loop does not use them.
offer_gate:
    lui     t0, 0x800d
    addiu   t0, t0, -0x7814
    subu    t2, s1, t4                 ; advance mode points at the previous glyph
    subu    t0, t2, t0
    sltiu   t0, t0, 64
    beqz    t0, @@ret
    lbu     t3, 0(t2)
    j       offer_lookup
    nop
@@ret:
    lui     t0, hi(PERSONA_HDR_BUF)
    addiu   t0, t0, lo(PERSONA_HDR_BUF)
    j       offer_maybe_name
    subu    t0, t2, t0
