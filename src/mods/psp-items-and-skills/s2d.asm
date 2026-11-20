;; =============================================================
;; PSP items and skills (--mods=psp-items-and-skills): S2D.BIN - Clean Salt / Estoma on
;; the overworld (the rule and the dungeon side: mods/psp-items-and-skills/dng.asm; the
;; timer is the same resident byte, so an active Clean Salt carries over
;; between the overworld and the dungeons).
;;
;; Encounter 0x8009686C (once per step): after the grace steps, rand() %
;; 32 < zone threshold triggers a battle; the code then sets "battle
;; pending" 0x800B9C18, clears counters and picks rand() % 30 from the zone
;; record (*0x800B0A84, 30 u16 formation ids). The hook replaces that point
;; (0x800969E4): it draws the rand() itself and looks the formation up
;; first; a formation that is all weaker than the leader returns "no
;; battle" with nothing changed (the next step rolls again), anything else
;; continues the retail code with the same rand() value, so that very
;; formation is fought. Timer: counted down on the overworld moon tick too
;; (0x8008B460, every 16 steps); it ends silently here (the "wore off"
;; message exists only in dungeons). Item: usable from the overworld item
;; menu (no target selection). Emergency Exit is greyed on the overworld
;; (item ids >= 0x68 other than Clean Salt stay "no").
;; =============================================================

.org 0x800969E4                         ; lui at, 0x800C / sw s0, -0x63E8(at) (battle pending), then jal rand
    j       s2d_es_pick
    nop

.org 0x8008B460                         ; moon tick: ori v1, v1, 0x2B30 / lbu v0, 0(v1) (v1 = 0x801F0000)
    j       s2d_es_tick
    nop

.org 0x80069FAC                         ; item menu: ids 0xF / 0x12 skip the target check (s2 = id + 1)
    jal     s2d_es_notarget
    nop
    bnez    v0, 0x8006A0E8
    nop

.org 0x8007F19C                         ; item_use: beqz v0 (id - 1 >= 0x68: no effect) / move s1, a0
    j       s2d_es_item_hi
    move    s1, a0

.org 0x8007F558                         ; item_usable (menu grey-out): beqz v0 (id - 1 >= 0x68: "no") / sw s2, 0x18(sp)
    j       s2d_es_usable_hi
    sw      s2, 0x18(sp)

;; Persona spell Estoma: field-skill effect table 0x80064908 (function
;; 0x8007F7AC, common end 0x8007F950) and usable table 0x80064960
;; (0x8007F9FC, result v1 at 0x8007FAA4); both spell menus skip the target
;; selection like Liftoma (0x8006CEF8, 0x8006D180; the same path serves the
;; unused Mappa).
.org 0x80064908 + (PSP_ES_SKILL - 0x5F) * 4
    .word   s2d_es_effect
.org 0x80064960 + (PSP_ES_SKILL - 0x5F) * 4
    .word   s2d_es_skill_usable

.org 0x8006CEF8                         ; ori v0, 0x6F / beq v1, v0 / ori v0, 0x73 / beq v1, v0 (v1 = skill)
    jal     s2d_es_skill_notarget
    nop
    bnez    v0, 0x8006D030
    nop
.org 0x8006D180
    jal     s2d_es_skill_notarget
    nop
    bnez    v0, 0x8006D2E0
    nop

.ifdef MOD_60_FPS
.if s2dq_end > S2D_PSPITEMS_ADDR
    .error "mod/pspitems: the 60 fps overworld block (s2dq_end) reaches S2D_PSPITEMS_ADDR"
.endif
.endif
.if S2D_PSPITEMS_LIMIT > S2D_ITEM_DATA_END
    .error "mod/pspitems: the overworld block reaches S2D_ITEM_DATA_END"
.endif
.org S2D_PSPITEMS_ADDR
.area S2D_PSPITEMS_LIMIT - S2D_PSPITEMS_ADDR
s2d_es_pick:
    jal     0x800413F8                  ; rand()
    nop
    move    t3, v0
    la      t0, PSP_STATE
    lbu     t1, TRV_ES_TIMER(t0)
    ori     t2, zero, 30
    beqz    t1, @@battle
    nop
    divu    t3, t2
    lui     t5, S2D_ZONE_PTR >> 16
    lw      t5, S2D_ZONE_PTR & 0xFFFF(t5)
    mfhi    t4
    sll     t4, t4, 1
    addu    t5, t5, t4
    lhu     t5, 0(t5)                   ; the formation the retail code will pick with this rand()
    nop
    sltiu   t1, t5, ES_FORMATIONS
    beqz    t1, @@battle
    nop
    la      t0, s2d_es_levels
    addu    t0, t0, t5
    lbu     t0, 0(t0)
    lui     t1, ES_PARTY >> 16
    lbu     t1, ES_PARTY & 0xFFFF(t1)
    nop
    sll     t2, t1, 1
    addu    t2, t2, t1
    sll     t2, t2, 5                   ; * 0x60
    la      t1, ES_MEMBERS + ES_LEVEL
    addu    t1, t1, t2
    lbu     t1, 0(t1)
    nop
    sltu    t0, t0, t1
    beqz    t0, @@battle
    nop
    j       0x80096A80                  ; return 0: no battle on this step
    nop
@@battle:
    lui     at, S2D_PENDING >> 16
    sw      s0, S2D_PENDING & 0xFFFF(at)    ; (s0 = 1)
    j       0x800969F4                  ; continue after the retail rand() call
    move    v0, t3

s2d_es_tick:
    la      t0, PSP_STATE
    lbu     t1, TRV_ES_TIMER(t0)
    nop
    beqz    t1, @@moon
    addiu   t1, t1, -1
    sb      t1, TRV_ES_TIMER(t0)
@@moon:
    ori     v1, v1, 0x2B30
    lbu     v0, 0(v1)
    j       0x8008B468
    nop

s2d_es_notarget:                        ; s2 = item id + 1 -> v0 = 1: no target selection
    ori     v0, zero, 0xF
    beq     s2, v0, @@yes
    ori     v0, zero, 0x12
    beq     s2, v0, @@yes
    ori     v0, zero, PSP_ES_ITEM + 1
    beq     s2, v0, @@yes
    nop
    jr      ra
    move    v0, zero
@@yes:
    jr      ra
    ori     v0, zero, 1

s2d_es_item_hi:                         ; a1 = id - 1, v0 = (a1 < 0x68)
    beqz    v0, @@hi
    nop
    j       0x8007F1A4                  ; table case (v0 is overwritten there)
    nop
@@hi:
    ori     v0, zero, PSP_ES_ITEM
    bne     a1, v0, @@out
    nop
    la      at, PSP_STATE
    ori     v0, zero, ES_PHASES
    sb      v0, TRV_ES_TIMER(at)
@@out:
    j       0x8007F4F4
    nop

s2d_es_usable_hi:                       ; a0 = id - 1, s0 = 0 = result, v0 = (a0 < 0x68)
    beqz    v0, @@hi
    nop
    j       0x8007F560                  ; table case (v0 is overwritten there)
    nop
@@hi:
    ori     v0, zero, PSP_ES_ITEM
    bne     a0, v0, @@out
    nop
    la      at, PSP_STATE
    lbu     v0, TRV_ES_TIMER(at)
    nop
    sltiu   s0, v0, 1
@@out:
    j       0x8007F66C
    nop

s2d_es_effect:
    la      at, PSP_STATE
    ori     v0, zero, ES_PHASES
    j       0x8007F950
    sb      v0, TRV_ES_TIMER(at)

s2d_es_skill_usable:                    ; v1 = 1 while no Clean Salt / Estoma is active
    la      at, PSP_STATE
    lbu     v0, TRV_ES_TIMER(at)
    nop
    j       0x8007FAA4
    sltiu   v1, v0, 1

s2d_es_skill_notarget:                  ; v1 = skill (kept) -> v0 = 1: no target selection
    ori     v0, zero, 0x6F
    beq     v1, v0, @@yes
    ori     v0, zero, 0x73
    beq     v1, v0, @@yes
    ori     v0, zero, PSP_ES_SKILL
    beq     v1, v0, @@yes
    nop
    jr      ra
    move    v0, zero
@@yes:
    jr      ra
    ori     v0, zero, 1

s2d_es_levels:
.include "../../../../build/estoma_levels.asm"
.endarea
