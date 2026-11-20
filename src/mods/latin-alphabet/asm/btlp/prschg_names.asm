;; =============================================================
;; BTLP.BIN - PRS-CHG window: full-length Persona names (NOW / SUB / SUB)
;;
;; Names by Persona id (+0x1E in the battle record) through persona_name_copy
;; into PRSCHG_BUF + 16*k, descriptors draw 16 glyphs.
;; persona_name_copy clobbers v0 v1 a0 a1 a2 a3 at;
;; the function is non-leaf (ra on its stack).
;; =============================================================

.org 0x800ACB08                         ; empty markers of the two SUB slots
    lui     a0, hi(PRSCHG_BUF + 16)
    addiu   a0, a0, lo(PRSCHG_BUF + 16)
.org 0x800ACB28
    lui     at, hi(PRSCHG_BUF + 32)
    sb      v1, lo(PRSCHG_BUF + 32)(at)

.org 0x800ACB3C                         ; NOW: 0x800ACB3C..0x800ACB74 (t2 = current record)
.area 0x800ACB78 - 0x800ACB3C, 0
    la      a0, PRSCHG_BUF
    lui     at, hi(SKILL_VWF_SLOTS_ADDR)
    lhu     v0, lo(SKILL_VWF_SLOTS_ADDR)(at)
    lbu     a1, 0x1E(t2)              ; fills the halfword load delay
    andi    v0, v0, 0xFFF8            ; NOW invalidates the Persona bits 0..2
    sh      v0, lo(SKILL_VWF_SLOTS_ADDR)(at)
    jal     persona_flag_register
    li      a2, 0
    jal     persona_name_copy
    nop
    lui     v1, 0x8006                  ; v1 = 0x8005CDA8 again (used at 0x800ACB88)
    addiu   v1, v1, -0x3258
    la      a0, PRSCHG_BUF + 16         ; a0 -> t0 at 0x800ACB8C: first SUB slot
.endarea

.org 0x800ACBD0                         ; SUB copy body 0x800ACBD0..0x800ACC0C (v1 = Persona slot, t3 = records + 0x1F)
.area 0x800ACC10 - 0x800ACBD0, 0
    sll     v0, v1, 3
    addu    v0, v0, v1
    sll     v0, v0, 3                   ; slot * 0x48
    addu    v0, v0, t3
    lbu     a1, -1(v0)                  ; Persona id (+0x1E)
    move    a0, t0
    la      at, PRSCHG_BUF
    subu    a2, t0, at
    srl     a2, a2, 4                   ; slot 0..2 inside the Persona bank (PERSONA_HDR_STRIDE 16)
    jal     persona_flag_register
    nop
    jal     persona_name_copy
    nop
.endarea
.org 0x800ACC10
    addiu   t0, t0, 16

.org BTLP_PRSCHG_DESC + 4
    .word PRSCHG_BUF
    .byte PERSONA_MAXLEN
.org BTLP_PRSCHG_DESC + 12 + 4
    .word PRSCHG_BUF + 16
    .byte PERSONA_MAXLEN
.org BTLP_PRSCHG_DESC + 24 + 4
    .word PRSCHG_BUF + 32
    .byte PERSONA_MAXLEN
