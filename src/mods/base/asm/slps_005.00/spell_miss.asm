;; Spell resolution calls here only when it skips a target.  Preserve the
;; retail tint and show the existing miss mark for an actual failed hit.
.org 0x80029100
.area 0x214
spell_miss_tint:
    addiu sp, sp, -32
    sw ra, 28(sp)
    sw s0, 24(sp)
    sw s1, 20(sp)
    sw a0, 16(sp)
    ;; s0 is the hit result, s1 the target actor.  Unavailable targets,
    ;; targets protected by special rules and Persona interception are not misses.
    bnez s0, @@tint
    nop
    lbu v0, 0xd3(s1)
    nop
    bnez v0, @@tint
    nop
    lbu v0, 0xde(s1)
    nop
    bnez v0, @@tint
    nop
    lui v0, 0x800d
    lw v1, 0x0ae4(v0)
    nop
    beqz v1, @@spawn
    nop
    lw v1, 0x0ae8(v0)
    nop
    beq v1, s1, @@tint
    nop
@@spawn:
    lw a0, 0x60(s1)
    jal 0x800859f0
    addiu a0, a0, 8
    move s0, v0
    ori v0, zero, 0xff
    sb v0, 0xd2(s0)
    lw v0, 0x10(s0)
    lui v1, 0xffe8
    addu v0, v0, v1
    sw v0, 0x10(s0)
    lui v0, 0x800d
    lw a1, -0xff4(v0)
    nop
@@find:
    beqz a1, @@mark
    nop
    lhu v0, 0xb2(a1)
    nop
    ori v1, zero, 0x0d
    bne v0, v1, @@next
    nop
    lbu v0, 0xd2(a1)
    lw v1, 0x60(s1)
    nop
    lbu v1, 0xd2(v1)
    nop
    bne v0, v1, @@next
    nop
    jal 0x80081900
    move a0, s0
    b @@mark
    nop
@@next:
    lw a1, 0x48(a1)
    b @@find
    nop
@@mark:
    lw v0, 0x60(s1)
    nop
    lbu v0, 0xd2(v0)
    nop
    sb v0, 0xd2(s0)
@@tint:
    ;; not in the delay slot: the tint's first instruction reads a0
    lw a0, 16(sp)
    jal 0x800c83bc
    nop
    lw s1, 20(sp)
    lw s0, 24(sp)
    lw ra, 28(sp)
    addiu sp, sp, 32
    jr ra
    nop
.endarea
