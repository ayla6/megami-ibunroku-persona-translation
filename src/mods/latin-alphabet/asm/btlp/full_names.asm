;; Resolve complete source names before encoding the insertion, never repair
;; an already-written insert. The stack scratch is private to this call.
.org BTL_FULL_NAME_CODE
.area 364
btl_name_copy:
    addiu   sp, sp, -0x38
    sw      ra, 0x34(sp)
    sw      a0, 0x30(sp)
    sw      a1, 0x2C(sp)
    sw      a2, 0x28(sp)
    li      t0, ITEM_NAME_BASE + 32
    subu    t1, a1, t0
    sltiu   t2, t1, 382 * 32
    beqz    t2, @@offer
    andi    t2, t1, 31
    bnez    t2, @@original
    srl     a1, t1, 5
    addiu   a1, a1, 1
    jal     item_name_copy_btlp
    addiu   a0, sp, 0x10
    b       @@resolved
    nop
@@offer:
    lw      a1, 0x2C(sp)
    li      t0, BTLP_OFFER_NAME_BASE ; BtlOffer.name, stride 0x48
    subu    t1, a1, t0
    sltiu   t2, t1, 3 * 0x48
    beqz    t2, @@actor
    li      t2, 0x48
    b       @@stride
    nop
@@actor:
    li      t0, BTLP_ENEMY_NAME_BASE
    subu    t1, a1, t0
    sltiu   t2, t1, 9 * 0xEC
    beqz    t2, @@record
    li      t2, 0xEC
@@stride:
    divu    t1, t2
    nop
    nop
    mfhi    t1
    bnez    t1, @@original
    nop
    lbu     v1, -1(a1)                  ; offer/actor's source record id
    b       @@head_setup
    nop
@@record:
    li      t0, DEMON_NAME_BASE + DEMON_NAME_STRIDE
    subu    t1, a1, t0
    sltiu   t2, t1, DEMON_NAME_COUNT * DEMON_NAME_STRIDE
    beqz    t2, @@original
    li      t2, DEMON_NAME_STRIDE
    divu    t1, t2
    nop
    nop
    mfhi    t0
    bnez    t0, @@original
    mflo    v1
    addiu   v1, v1, 1                   ; record id indexes OFFER_NAME_BANK
@@head_setup:
    move    t0, a1
    addiu   t3, sp, 0x10
    move    a1, zero
@@head:
    lbu     t2, 0(t0)
    li      v0, 0xFF
    beq     t2, v0, @@short
    addiu   t0, t0, 1
    addu    t1, t3, a1
    sb      t2, 0(t1)
    addiu   a1, a1, 1
    sltiu   t1, a1, 10
    bnez    t1, @@head
    nop
    la      t0, OFFER_NAME_BANK
    jal     offer_tail
    nop
    addu    t0, t3, a1
    sb      v0, 0(t0)
    b       @@resolved
    nop
@@short:
    addu    t0, t3, a1
    sb      v0, 0(t0)
@@resolved:
    addiu   a1, sp, 0x10
    li      a2, 20
    b       @@encode
    nop
@@original:
    lw      a1, 0x2C(sp)
    lw      a2, 0x28(sp)
@@encode:
    lw      a0, 0x30(sp)
    jal     btl_name_encode
    nop
    lw      ra, 0x34(sp)
    nop
    jr      ra
    addiu   sp, sp, 0x38
.endarea

;; The victory-board producer owns the complete name write. Its descriptor
;; reads the shared, mutually exclusive Persona-header scratch, which has
;; room for the full item name. No later pass rewrites the row.
.org 0x800AADD8
.area 0x800AAE68 - 0x800AADD8
    lui     a3, 0x800F
    lhu     a3, 0x7EB8(a3)             ; dropped item id
    la      a0, PERSONA_HDR_BUF
    beqz    a3, @@result_empty
    move    a1, a3
    jal     item_name_copy_btlp
    nop
    ;; Register the source-derived English item as a VWF-owned row.
    srl     t0, a3, 3
    la      t1, btl_result_item_english
    addu    t1, t1, t0
    lbu     t0, 0(t1)
    andi    t1, a3, 7
    srlv    t0, t0, t1
    andi    t0, t0, 1
    b       @@result_ownership
    nop
@@result_empty:
    li      t0, 0xFF
    sb      t0, 0(a0)
    move    t0, zero
@@result_ownership:
    lui     at, hi(SKILL_VWF_SLOTS_ADDR)
    lhu     t1, lo(SKILL_VWF_SLOTS_ADDR)(at)
    nop
    andi    t1, t1, 0xFFF8
    or      t1, t1, t0
    sh      t1, lo(SKILL_VWF_SLOTS_ADDR)(at)
    j       0x800AAE68
    nop
.endarea

.org 0x800DF7AC
    .word PERSONA_HDR_BUF
    .byte 20

;; Item and spell lists share these descriptors. Both producers write their
;; own row once into the same expanded bank; the spell producer terminates its
;; ten-cell retail row and retains the retail renderer when ownership is clear.
.if BTLP_ITEM_FULL_ADDR < VWF_DLG_RING_LIMIT || BTLP_ITEM_FULL_END > 0x80058018
    .error "battle list names overlap dialogue or CD scratch"
.endif
.org 0x800ACF20
    lui     s5, hi(BTLP_ITEM_FULL_ADDR)
    addiu   s5, s5, lo(BTLP_ITEM_FULL_ADDR)
.org 0x800AD014
.area 0x800AD09C - 0x800AD014
    lhu     a1, 0(s1)
    move    a0, s5
    andi    a1, a1, 0x1FF
    beqz    a1, @@empty
    nop
    jal     item_name_copy_btlp
    nop
    b       @@done
    nop
@@empty:
    li      v0, 0xFF
    sb      v0, 0(s5)
@@done:
    j       0x800AD09C
    nop
;; The second producer writes exactly ten cells, which may have no terminator.
btl_list_spell_terminate:
    sb      t6, 10(t4)
    lui     at, 0x800D
    addiu   at, at, 0x2AD0
    j       0x800AD4A4
    nop
.endarea
.org 0x800AD0F8
    addiu   s5, s5, BTLP_ITEM_FULL_STRIDE
.org 0x800AD49C
    j       btl_list_spell_terminate
    nop
.org 0x800AD4F4
    addiu   t4, t4, BTLP_ITEM_FULL_STRIDE
