;; =============================================================
;; BTLP.BIN - enemy-kind list (board 23): full arcana tag and VWF names
;;
;; R1 on the command picker puts the list of enemy kinds up.  Retail copies
;; six bytes of the arcana label into a 6-cell row and ten bytes of the
;; demon-name head into a 10-cell row, so a six-letter arcana loses its colon
;; and any name past ten glyphs is cut ("SpiritQuicksilve").
;;
;; The label table already holds seven-glyph slots ("Spirit:"); the tag row
;; is drawn in place, owned, and stops at the slot's FF.  Its widest rendered
;; form is 36 px, so the retail name x (-24) stays clear of it.  The three
;; name rows become 16-cell buffers (ten head + up to five bank tail + FF,
;; asserted in btlp.py) and are owned, so the row renders proportionally and
;; the longest name (82 px) still ends before the count column at x = 64.
;;
;; The loop walks one descriptor group per kind: s2 is the tag descriptor
;; itself, so the name descriptor (+0x24) and count descriptor (+0x48) are
;; reached by displacement and no row index table is needed.
;;
;; The count row, the member boards and every other battle row are untouched.
;; =============================================================

.if BTLP_BOARD23_NAMES_END - BTLP_BOARD23_NAMES_ADDR != 2 * BTLP_BOARD23_NAME_STRIDE
    .error "board 23 name bank must hold two 16-cell rows"
.endif
.if BTLP_BOARD23_NAME_END_2 - BTLP_BOARD23_NAME_ROW_2 != BTLP_BOARD23_NAME_STRIDE
    .error "board 23 third name row must be 16 cells"
.endif

;; --- the three descriptor rows ---------------------------------------------
;; tag: seven cells from the shared label slot (a slot's FF ends a shorter one)
.org 0x800DFC44
    .byte 7
.org 0x800DFC50
    .byte 7
.org 0x800DFC5C
    .byte 7
;; name: 16-cell rows in the retail name pool and arcana pool
.org 0x800DFC64
    .word BTLP_BOARD23_NAMES_ADDR
.org 0x800DFC68
    .byte BTLP_BOARD23_NAME_STRIDE
.org 0x800DFC70
    .word BTLP_BOARD23_NAMES_ADDR + BTLP_BOARD23_NAME_STRIDE
.org 0x800DFC74
    .byte BTLP_BOARD23_NAME_STRIDE
.org 0x800DFC7C
    .word BTLP_BOARD23_NAME_ROW_2
.org 0x800DFC80
    .byte BTLP_BOARD23_NAME_STRIDE

;; --- s2 becomes the group's tag descriptor, not a pool index ----------------
.org 0x800AB154
    lui     s2, 0x800e
.org 0x800AB158
    addiu   s2, s2, 0xfc3c              ; 0x800DFC3C: first tag descriptor

;; --- the used-kind rows -----------------------------------------------------
;; Retail 0x800AB198..0x800AB214 copies six label bytes into the arcana pool.
;; Point the tag row straight at the shared label slot instead.  v0 = arcana*8.
.org 0x800AB198
.area 0x800AB218 - 0x800AB198
    lui     at, 0x800e
    addiu   at, at, 0x2060
    addu    at, at, v0
    sw      at, 4(s2)                   ; the tag row's text pointer
    lw      a0, 0x4c(s2)                ; the count row for the call below
    .fill 0x800AB218 - ., 0
.endarea

;; Retail 0x800AB218..0x800AB2F0 copies the ten-byte demon head into a
;; ten-byte row.  Copy it into the 16-cell row the descriptor names, then
;; append the bank tail (offer_name.asm) and terminate.
.org 0x800AB218
.area 0x800AB2F4 - 0x800AB218
    lw      t3, 0x28(s2)                ; the row's 16-cell buffer
    lbu     v1, 0(s1)                   ; kind key
    nop                                 ; load delay: v1
    sll     v0, v1, 3
    subu    v0, v0, v1
    sll     v0, v0, 3                   ; key * DEMON_NAME_STRIDE
    la      a2, DEMON_NAME_BASE
    addu    a2, a2, v0                  ; demon record name head
    lwl     v0, 3(a2)
    lwr     v0, 0(a2)
    nop                                 ; load delay: unaligned half
    swl     v0, 3(t3)
    swr     v0, 0(t3)
    lwl     v0, 7(a2)
    lwr     v0, 4(a2)
    nop                                 ; load delay: unaligned half
    swl     v0, 7(t3)
    swr     v0, 4(t3)
    lbu     v0, 8(a2)
    nop                                 ; load delay: v0
    sb      v0, 8(t3)
    lbu     v0, 9(a2)
    nop                                 ; load delay: v0
    sb      v0, 9(t3)
    lbu     v1, 0(s1)                   ; the bank is keyed by the same id
    ori     v0, zero, 0xff              ; offer_tail's scan/terminator byte
    li      a1, DEMON_NAME_FIELD
    jal     offer_tail
    nop
    addu    t1, t3, a1
    sb      v0, 0(t1)                   ; offer_tail leaves 0xFF in v0
    .fill 0x800AB2F4 - ., 0
.endarea

;; --- a row no kind took -----------------------------------------------------
;; Point its tag at the lone-FF slot and empty its name and count rows.
.org 0x800AB314
.area 0x800AB348 - 0x800AB314
    lui     at, 0x800e
    addiu   at, at, 0x2060              ; slot 0 is a lone FF
    sw      at, 4(s2)
    lw      at, 0x28(s2)
    lw      t3, 0x4c(s2)
    sb      s4, 0(at)                   ; blank the name
    sb      s4, 0(t3)                   ; blank the count value, not its count
    .fill 0x800AB348 - ., 0
.endarea

;; --- one descriptor group's stride -----------------------------------------
.org 0x800AB310
    nop                                 ; retail advanced the old name-row index
.org 0x800AB348
    addiu   s2, s2, 12
