;; ANALYZE board header (BTLP 0x800AD874, btlp/offer_name.asm): a race prefix
;; ending in ':' gets a space before the name ("Jaki: Gremlin"). Resident
;; space in a dead SLPS function, entered only from BTLP while it is loaded.
.org ANALYZE_RACE_GAP_ADDR
.area ANALYZE_RACE_GAP_END - ANALYZE_RACE_GAP_ADDR
;; a2 = the cell after the copied prefix; the name copy writes from a2.
analyze_race_gap:
    lbu     v0, -1(a2)
    li      v1, 0xCB                    ; ':'
    bne     v0, v1, @@name
    nop
    sb      zero, 0(a2)                 ; small-font space
    addiu   a2, a2, 1
@@name:
    lwl     v0, 0x42(s0)                ; the two displaced instructions
    j       0x800ad87c
    lwr     v0, 0x3f(s0)
.endarea
