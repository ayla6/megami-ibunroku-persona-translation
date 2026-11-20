;; =============================================================
;; BTLP.BIN - battle skill menu header: full Persona name + "Cost" label
;;
;; Name by Persona id (+0x1E in the battle record,
;; s0 = 0x8005CDA8 + slot*0x48) through persona_name_copy into
;; PERSONA_HDR_BUF (16 glyphs at x -52), label "Cost" at +80, value at +112.
;; The label string lives in the bank's fourth slot (BATTLE_LABEL_BUF) but is
;; deliberately outside the owned Persona range: it renders through the retail
;; fixed-width path (8 px steps, fixed atlas cells), like the original label.
;; =============================================================

.org 0x800AC800                         ; name copy (0x800AC800..0x800AC838)
.area 0x800AC83C - 0x800AC800, 0
    lbu     a1, 0x1E(s0)                ; Persona id (not in the delay slot: load delay)
    la      a0, PERSONA_HDR_BUF
    lui     at, hi(SKILL_VWF_SLOTS_ADDR)
    lhu     v0, lo(SKILL_VWF_SLOTS_ADDR)(at)
    li      a2, 0
    andi    v0, v0, 0xFFF8            ; new header invalidates the Persona bits 0..2
    sh      v0, lo(SKILL_VWF_SLOTS_ADDR)(at)
    jal     persona_flag_register
    nop
    jal     persona_name_copy
    nop
.endarea

.org BTLP_HDR_NAME_DESC
    .halfword -52 ; x
.org BTLP_HDR_NAME_DESC + 4
    .word PERSONA_HDR_BUF
    .byte PERSONA_MAXLEN

;; The label string itself is written in the SLPS section (its static bytes
;; live in the Persona dead run, slps_005.00/persona_names.asm); this section
;; only repoints the descriptor.
.org BTLP_HDR_LABEL_DESC
    .halfword 80 ; x
.org BTLP_HDR_LABEL_DESC + 4
    .word BATTLE_LABEL_BUF
.org BTLP_HDR_LABEL_DESC + 8
    .byte 4 ; glyphs
.org BTLP_HDR_VALUE_DESC
    .halfword 112 ; x
