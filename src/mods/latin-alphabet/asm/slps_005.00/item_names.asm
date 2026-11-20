;; Full item/demon names: ten-byte record heads plus overlay-owned tails.
;; Both wrappers share one bounded head/tail copy. Each tail bank contains
;; [length][glyphs] in id order; its bitmap includes only records with tails.
.align 4
.if ITEM_NAME_FIELD != DEMON_NAME_FIELD
    .error "shared name copy requires equal item/demon head fields"
.endif

;; a0 = destination (21 bytes), a1 = item id (1-based)
;; clobbers v0, v1, a0, a1, a2, at only (callers rely on this: t* live)
item_name_copy:
    sll     v0, a1, 5
    li      v1, ITEM_NAME_BASE
    addu    v0, v0, v1
    la      v1, item_tail_bank
    la      at, item_tail_bits
name_copy_body:
    addiu   sp, sp, -0x10
    sw      t0, 0x0C(sp)
    sw      t1, 0x08(sp)
    sw      t2, 0x04(sp)
    sw      t3, 0x00(sp)
    move    t0, a0                      ; destination cursor
    addiu   t1, a1, -1                  ; zero-based target bitmap index
    move    t2, v1                      ; tail bank cursor
    move    t3, at                      ; bitmap
    move    a2, v0                      ; head cursor
    li      a1, ITEM_NAME_FIELD          ; both families have ten-byte heads
@@head:
    lbu     v0, 0(a2)
    li      at, 0xFF
    beq     v0, at, @@term
    addiu   a2, a2, 1
    sb      v0, 0(t0)
    addiu   t0, t0, 1
    addiu   a1, a1, -1
    bnez    a1, @@head
    nop
    ;; Walk each bitmap bit once; advance the bank only for present tails.
    move    a1, zero
@@walk:
    srl     v1, a1, 3
    addu    v1, t3, v1
    lbu     v0, 0(v1)
    andi    v1, a1, 7
    srlv    v0, v0, v1
    andi    v0, v0, 1
    beq     a1, t1, @@here
    nop
    beqz    v0, @@next
    nop
    lbu     v0, 0(t2)
    addiu   t2, t2, 1
    addu    t2, t2, v0
@@next:
    b       @@walk
    addiu   a1, a1, 1
@@here:
    beqz    v0, @@term
    nop
    lbu     a1, 0(t2)
    addiu   t2, t2, 1
@@copy:
    lbu     v0, 0(t2)
    addiu   t2, t2, 1
    sb      v0, 0(t0)
    addiu   t0, t0, 1
    addiu   a1, a1, -1
    bnez    a1, @@copy
    nop
@@term:
    li      at, 0xFF
    sb      at, 0(t0)
    lw      t0, 0x0C(sp)
    lw      t1, 0x08(sp)
    lw      t2, 0x04(sp)
    lw      t3, 0x00(sp)
    jr      ra
    addiu   sp, sp, 0x10

;; a0 = destination (21 bytes), a1 = demon id (1-based)
;; clobbers v0, v1, a0, a1, a2, at only
demon_name_copy:
    sll     v0, a1, 3
    sll     v1, a1, 6
    subu    v0, v1, v0                  ; id * 0x38
    li      v1, DEMON_NAME_BASE
    addu    v0, v0, v1
    la      v1, demon_tail_bank
    la      at, demon_tail_bits
    b       name_copy_body
    nop

name_scratch:
    .fill 21, 0
