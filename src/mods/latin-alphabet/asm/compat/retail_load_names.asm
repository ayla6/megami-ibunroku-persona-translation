;; Retail title Load Game: replace only OpenFontPutText, in its own footprint.
;; Eight saved-name cells, original atlas UVs, packed original-face metrics.
;; Non-Latin cells retain an 8-pixel advance. The pen resets on every call.
.include "../../../../build/title_name_metrics.asm"
.org 0x800858E8
.area 0x160
 title_name_write:
    sll     t0, a0, 4
    addu    t0, t0, a0
    sll     t0, t0, 1
    addiu   t0, t0, 25
    sll     t1, t0, 3
    addu    t0, t0, t1
    sll     t0, t0, 2
    la      t1, 0x80111484
    addu    t0, t0, t1
    ori     t2, zero, 0x58
    ori     t6, zero, 265
    ori     t7, zero, 8
@@glyph:
    lbu     v0, 0(a1)
    addiu   a1, a1, 1
    ori     t3, zero, 0xFF
    beq     v0, t3, @@done
    nop
    multu   v0, t6
    mflo    t3
    srl     t3, t3, 13
    sll     t4, t3, 5
    subu    t4, t4, t3
    subu    t4, v0, t4
    sll     t4, t4, 3
    sb      t4, 14(t0)
    sll     t4, t3, 1
    addu    t4, t4, t3
    sll     t4, t4, 2
    sb      t4, 15(t0)
    sltiu   t4, v0, TITLE_NAME_LOW
    bnez    t4, @@metric
    move    t5, v0
    addiu   t4, v0, -TITLE_NAME_HIGH
    sltiu   t4, t4, TITLE_NAME_COUNT
    beqz    t4, @@position
    ori     t3, zero, 8
    addiu   t5, v0, TITLE_NAME_LOW - TITLE_NAME_HIGH
@@metric:
    la      t4, title_name_metrics
    addu    t5, t5, t4
    lbu     t3, 0(t5)
    nop
@@position:
    srl     t4, t3, 4
    subu    t4, t2, t4
    sh      t4, 4(t0)
    andi    t3, t3, 15
    addu    t2, t2, t3
    addiu   t0, t0, 36
    addiu   t7, t7, -1
    bnez    t7, @@glyph
    nop
@@done:
    jr      ra
    nop
.align 4
title_name_metrics:
    .incbin "../../../../build/title_name_metrics.bin"
.endarea
