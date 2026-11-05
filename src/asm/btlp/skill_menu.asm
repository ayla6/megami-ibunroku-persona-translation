;; =============================================================
;; BTLP.BIN - battle skill menu with full-length skill names
;;
;; The copies call skill_name_copy (slps_005.00/skill_names.asm) into
;; SKILL_MENU_BUF + slot*SKILL_MENU_STRIDE; the descriptors allow SKILL_MAXLEN
;; glyphs and the copy ends each name with FF, so the renderer draws only the
;; real glyphs.
;; Each copy body may clobber v0 v1 a0 a1 a2 at;
;; the enclosing functions are non-leaf (ra saved on the stack).
;; =============================================================

;; --- descriptors: pointer + glyph count ---
.macro skill_desc, base
    .org base + 4
    .word SKILL_MENU_BUF
    .byte SKILL_MAXLEN
    .org base + 12 + 4
    .word SKILL_MENU_BUF + SKILL_MENU_STRIDE
    .byte SKILL_MAXLEN
    .org base + 24 + 4
    .word SKILL_MENU_BUF + SKILL_MENU_STRIDE * 2
    .byte SKILL_MAXLEN
    .org base + 36 + 4
    .word SKILL_MENU_BUF + SKILL_MENU_STRIDE * 3
    .byte SKILL_MAXLEN
    .org base + 48 + 4
    .word SKILL_MENU_BUF + SKILL_MENU_STRIDE * 4
    .byte SKILL_MAXLEN
    .org base + 60 + 4
    .word SKILL_MENU_BUF + SKILL_MENU_STRIDE * 5
    .byte SKILL_MAXLEN
    .org base + 72 + 4
    .word SKILL_MENU_BUF + SKILL_MENU_STRIDE * 6
    .byte SKILL_MAXLEN
.endmacro

skill_desc BTLP_SKILL_DESC_A
skill_desc BTLP_SKILL_DESC_B

;; --- loop 1 (0x800AC8F8, menu build; t2 = FF offset, t3 = slot+1 after the increment) ---
.org 0x800AC908
    lui     at, hi(SKILL_MENU_BUF)      ; FF marker of the slot
    addiu   at, at, lo(SKILL_MENU_BUF)
.org 0x800AC924
    addiu   t2, t2, SKILL_MENU_STRIDE
.org 0x800AC978                         ; copy body 0x800AC978..0x800ACA40
.area 0x800ACA44 - 0x800AC978, 0
    move    a1, v1                      ; skill id
    jal     skill_menu_copy
    addiu   a2, t3, -1                  ; zero-based slot (delay slot)
    b       0x800ACA44
    nop

;; a1 = skill id, a2 = slot; the destination SKILL_MENU_BUF + slot*STRIDE is
;; computed here. Keep all t*/a3 live exactly as the original skill_name_copy
;; ABI did. The bitmap is generated from canonical English records;
;; Japanese/untranslated IDs clear the slot bit. Ownership is per range:
;; skill slot i owns bit SKILL_BIT_OFFSET+i and the Persona bank bits 0..2.
;; The static "Cost" header label is not owned (fixed-width).
skill_menu_copy:
    addiu   sp, sp, -16
    sw      ra, 12(sp)
    sw      t0, 8(sp)
    sw      t1, 4(sp)
    sll     v0, a2, 1
    addu    v0, v0, a2                  ; slot * 3
    sll     a0, v0, 3                   ; slot * SKILL_MENU_STRIDE (24)
    lui     at, hi(SKILL_MENU_BUF)
    addiu   at, at, lo(SKILL_MENU_BUF)
    addu    a0, a0, at
    sltiu   v0, a1, SKILL_COUNT + 1
    bnez    v0, @@valid_id
    li      v1, 1                       ; (overwritten on the valid path)
    b       @@set_slot
    move    v1, zero
@@valid_id:
    lui     t0, hi(SKILL_VWF_FLAGS_ADDR)
    srl     v0, a1, 3
    addu    t0, t0, v0
    lbu     v1, lo(SKILL_VWF_FLAGS_ADDR)(t0)
    andi    v0, a1, 7
    srlv    v1, v1, v0
    andi    v1, v1, 1
@@set_slot:
    addiu   a2, a2, SKILL_BIT_OFFSET    ; ownership bit: skill slot i at SKILL_BIT_OFFSET+i
    li      t1, 1
    sllv    t1, t1, a2                  ; mask = 1 << bit
    sllv    v1, v1, a2                  ; flag << bit
    lui     t0, hi(SKILL_VWF_SLOTS_ADDR)
    lhu     v0, lo(SKILL_VWF_SLOTS_ADDR)(t0)
    nor     at, t1, zero                ; (at is scratch: the base lives in t0)
    and     v0, v0, at
    or      v0, v0, v1
    sh      v0, lo(SKILL_VWF_SLOTS_ADDR)(t0)
    jal     skill_name_copy
    lw      t1, 4(sp)                   ; delay slot: t1 survives the call (its contract)
    lw      t0, 8(sp)
    lw      ra, 12(sp)
    addiu   sp, sp, 16                  ; the load-delay slot between lw ra and jr ra
    jr      ra
    nop

;; Canonical Persona-ID ownership; IDs with no written English stay clear.
persona_vwf_flags:
    .incbin "../../build/persona_vwf_flags.bin"
.endarea

;; --- loop 2 (0x800A5634; t1 = FF offset, a3 = slot) ---
.org 0x800A5634
    lui     at, hi(SKILL_MENU_BUF)
    addiu   at, at, lo(SKILL_MENU_BUF)
.org 0x800A5650
    addiu   t1, t1, SKILL_MENU_STRIDE
.org 0x800A5654                         ; copy body 0x800A5654..0x800A5690 (0x800A5694 addiu t0 kept)
.area 0x800A5694 - 0x800A5654, 0
    move    a1, v1
    jal     skill_menu_copy
    move    a2, a3
    b       0x800A5694
    nop
persona_flag_continue:
    andi    v1, v1, 1
    sllv    v1, v1, a2
    li      v0, 1
    sllv    v0, v0, a2
    j       persona_flag_store
    lui     at, hi(SKILL_VWF_SLOTS_ADDR)
.endarea

;; --- loop 3 (0x800ACC40; same shape as loop 2) ---
.org 0x800ACC40
    lui     at, hi(SKILL_MENU_BUF)
    addiu   at, at, lo(SKILL_MENU_BUF)
.org 0x800ACC5C
    addiu   t1, t1, SKILL_MENU_STRIDE
.org 0x800ACC60
.area 0x800ACCA0 - 0x800ACC60, 0
    move    a1, v1
    jal     skill_menu_copy
    move    a2, a3
    b       0x800ACCA0
    nop
persona_flag_store:
    lhu     a2, lo(SKILL_VWF_SLOTS_ADDR)(at)
    nor     v0, v0, zero
    and     v0, v0, a2
    or      v0, v0, v1
    jr      ra
    sh      v0, lo(SKILL_VWF_SLOTS_ADDR)(at)
.endarea

;; --- empty-slot test (cursor movement): slot*11 -> slot*SKILL_MENU_STRIDE ---
.org 0x800A5328
    sll     v0, v1, 1
    addu    v0, v0, v1                  ; slot * 3
    sll     v0, v0, 3                   ; slot * SKILL_MENU_STRIDE (24)
    nop
    lui     at, hi(SKILL_MENU_BUF)
    addiu   at, at, lo(SKILL_MENU_BUF)
