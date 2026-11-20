;; ANALYZE affinity helper continuation, in an unreferenced resident function.
;; The adjacent remainder is reserved for battle message spill by btlp.py.
.org 0x800182B4
.area 0x44
btl_trait_tail_continue:
    addiu   t1, t3, 120                 ; load-delay filler; text after index
    beq     t0, at, btl_trait_terminate
    addu    t1, t1, t0
@@copy:
    lbu     t3, 0(t1)
    addiu   t1, t1, 1
    sb      t3, 0(t2)
    bne     t3, at, @@copy
    addiu   t2, t2, 1
btl_trait_resume:
    jal     0x800AE43C
    ori     a2, zero, 3
    j       0x800ADA9C
    nop
btl_trait_terminate:
    ori     t3, zero, 0xFF
    j       btl_trait_resume
    sb      t3, 0(t2)
.endarea
