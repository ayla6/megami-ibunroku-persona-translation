;; CONTACT: append the source-derived tail to the already copied ten-byte
;; head in the shared menu-name scratch. a0 is the selected offer, a1 is
;; the head length, and the caller has established at for its
;; terminator store. Scratch is shared with the mutually exclusive Persona
;; header menu, not with the live offer or its other rows.
.org 0x800751c0
    lui     at, hi(PERSONA_HDR_BUF)
    addiu   at, at, lo(PERSONA_HDR_BUF)
.org 0x800751f8
    jal     offer_full_name
    lui     at, hi(PERSONA_HDR_BUF)
.org 0x80075200
    addiu   at, at, lo(PERSONA_HDR_BUF)
.org 0x8007520c
    lui     v0, hi(PERSONA_HDR_BUF)
    addiu   v0, v0, lo(PERSONA_HDR_BUF)

.org OFFER_NAME_CODE
.area 108
offer_full_name:
    lbu     v1, 0x30(a0)
    ori     v0, zero, 0xff
    la      t0, OFFER_NAME_BANK
    la      t3, PERSONA_HDR_BUF
offer_tail:
@@entry:
    lbu     t2, 0(t0)
    addiu   t0, t0, 1
    beqz    t2, @@done
    nop
    beq     t2, v1, @@copy
    nop
@@skip:
    lbu     t2, 0(t0)
    addiu   t0, t0, 1
    bne     t2, v0, @@skip
    nop
    b       @@entry
    nop
@@copy:
    lbu     t2, 0(t0)
    addiu   t0, t0, 1
    beq     t2, v0, @@done
    addu    t1, t3, a1
    sb      t2, 0(t1)
    b       @@copy
    addiu   a1, a1, 1
@@done:
    jr      ra
    nop
.endarea

;; ANALYZE builds the race prefix before copying the ten-byte actor name.
;; A prefix ending in ':' gets a space before the name ("Jaki: Gremlin").
;; Append the same tail after that head, then terminate the combined row.
.org 0x800ad874
    j       analyze_race_gap
    nop
.org 0x800ad8a4
    jal     analyze_full_name
    nop
.org 0x800dea58
    .byte   24

.org ANALYZE_NAME_CODE
.area ANALYZE_NAME_CODE_SIZE
analyze_full_name:
    move    t4, ra
    lbu     v1, 0x3e(s0)
    ori     v0, zero, 0xff
    li      a1, 10
    move    t3, a2
    la      t0, OFFER_NAME_BANK
    jal     offer_tail
    nop
    addu    t0, a2, a1
    sb      v0, 0(t0)
    lui     a0, 0x8010
    jr      t4
    lb      v1, 0x49(s0)
.endarea
