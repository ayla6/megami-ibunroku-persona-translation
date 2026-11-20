;; =============================================================
;; PSP items and skills (--mods=psp-items-and-skills): DNG.BIN.
;;
;; Emergency Exit (item 111) and Traesto (skill 0x71): warp the party back
;; to the dungeon entrance, as on the PSP ("Warps you to the dungeon
;; entrance"). The PS1 has no effect for Traesto.
;;
;; Entrance = where the party stood when the dungeon was entered FROM THE
;; OVERWORLD (previous mode 2): recorded at the first frame of the field
;; input handler after the DNG entry (map file, floor, x, y, facing) in the
;; resident state (mods/psp-items-and-skills/pspitems.inc), since the overlay is reloaded after
;; every battle. Usable only on that map file: dungeons entered otherwise
;; (the Snow Queen route towers, entered from the frozen school) never
;; record an entrance, so the item / spell is greyed out there. Kama Palace
;; (map 0x0F) and Mana Castle (0x12) are reached from an event scene or
;; another map file, never from the overworld, but the PSP allows the item
;; there: for these two the arrival point is recorded when the DNG is
;; entered from an event (previous mode 3) or another dungeon file
;; (previous mode 0) AND the last dungeon map seen was another one
;; (TRV_LAST), so a room inside the dungeon or a battle never moves it.
;; After Continue on a dungeon save the entry records nothing
;; (TRV_LOADED): the saved entrance stays.
;;
;; Warp: the effect only sets "pending"; the next call of the step routine
;; 0x8006A73C returns 2 (warp tile) and the warp lookup 0x8006C90C is
;; replaced for that call by a transfer record to the entrance (0x801F5350:
;; map, x, y, floor, facing; next mode 0 = DNG), which the main loop
;; handles like the stairs (same-file reposition 0x8006826C).
;;
;; Clean Salt (item 110) and Estoma (skill 0x70): no random battles against
;; formations that are all weaker than the party leader, for 16 moon phases
;; (Liftoma's duration). On a hit 0x8007099C picks a formation and writes
;; it to 0x801F5350 (0x80070B40); the hook skips the battle ("no encounter
;; this step", cooldown untouched) when the strongest demon of the
;; formation (build/estoma_levels.asm) is below the leader's level.
;; Fixed-formation cells and event battles are never skipped. The moon
;; tick 0x8006979C counts the timer down; at 0 it raises the "wore off"
;; message (0x800A0D90), and the message hook 0x8006C0D8 shows it with
;; Clean Salt as its item (scriptmsg_item_8009a18c; normally Core Shield,
;; restored for every other message).
;;
;; Hooks: DNG entry 0x80064D50, step 0x8006A73C, field input 0x80067D64,
;; warp lookup call 0x800680A4, field-skill effect table 0x80064ADC and
;; usable table 0x80064B34 (entries 0x70 / 0x71), item use 0x8008F06C and
;; usable 0x8008F428 (ids >= 0x68), no target selection for the items
;; (0x8007A41C, with Skull Pendulum / Core Shield) and the spells
;; (0x8007D1C4, 0x8007D448, with Liftoma).
;; =============================================================

.org 0x80064D50                         ; DNG entry: addiu sp, sp, -0xE8 / sw ra, 0xE4(sp)
    j       dng_tr_entry
    nop

.org 0x8006A73C                         ; step routine: lui v0, 0x800A / lbu v0, 0x368(v0)
    j       dng_tr_step
    nop

.org 0x80067D64                         ; field input handler 0x80067D40 (every frame), after its prologue:
    j       dng_tr_idle                 ; lw v0, 0x1580(a1) / nop
    nop

.org 0x800680A4                         ; step result 2 (warp tile): jal 0x8006C90C
    jal     dng_tr_warp

.org 0x80064ADC + (PSP_TR_SKILL - 0x5F) * 4 ; field-skill effect table (0x8008F67C)
    .word   dng_tr_effect
.org 0x80064B34 + (PSP_TR_SKILL - 0x5F) * 4 ; field-skill usable table (0x8008F8CC)
    .word   dng_tr_usable
.org 0x80064ADC + (PSP_ES_SKILL - 0x5F) * 4
    .word   dng_es_effect
.org 0x80064B34 + (PSP_ES_SKILL - 0x5F) * 4
    .word   dng_es_skill_usable

.org 0x8007A41C                         ; item menu: ids 0xF / 0x12 skip the target selection (s1 = id + 1)
    jal     dng_tr_item_notarget
    nop
    bnez    v0, 0x8007A544
    nop

.org 0x8007D1C4                         ; Persona spell menu: 0x6F / 0x73 skip the target selection (v1 = skill)
    jal     dng_tr_skill_notarget
    nop
    bnez    v0, 0x8007D2FC
    nop
.org 0x8007D448                         ; the same check in the second spell-menu path
    jal     dng_tr_skill_notarget
    nop
    bnez    v0, 0x8007D598
    nop

.org 0x8008F06C                         ; item_use: beqz v0 (id - 1 >= 0x68: no effect) / move s1, a0 (too far for a branch)
    j       dng_tr_item_gate

.org 0x8008F428                         ; item_usable 0x8008F400 (menu grey-out): beqz v0 (id - 1 >= 0x68: "no")
    j       dng_tr_usable_gate          ; (delay slot sw s2, 0x18(sp) kept)

.org 0x80070B40                         ; random formation: lui at, 0x801F / sh v1, 0x5350(at) (v1 = formation id)
    j       dng_es_pick
    lui     at, 0x801F

.org 0x8006979C                         ; moon phase tick, before the Liftoma count: lui v1, 0x801F / ori v1, 0x29A9
    j       dng_es_tick
    nop

.org 0x8006C0D8                         ; "wore off" message: lui v0, 0x801F / lbu v0, 0x29A8(v0)
    j       dng_es_msg
    nop

.org DNG_PSPITEMS_ADDR
.area DNG_PSPITEMS_LIMIT - DNG_PSPITEMS_ADDR
dng_tr_entry:
    addiu   sp, sp, -0xE8
    sw      ra, 0xE4(sp)
    la      at, PSP_STATE
    sb      zero, TRV_PENDING(at)
    sb      zero, TRV_ES_DONE(at)       ; the "wore off" request is cleared with 0x800A0D90 (0x80064DA8)
    lbu     v0, TRV_LOADED(at)          ; first entry after Continue on a dungeon save: the entrance
    nop                                 ; came from the save, record nothing
    bnez    v0, @@go
    sb      zero, TRV_LOADED(at)
    lui     v0, 0x8005
    lw      v0, 0x5C54(v0)              ; previous mode (gp + 0x60)
    ori     v1, zero, 2                 ; overworld: FRESH = 1 (always recorded)
    beq     v0, v1, @@set
    ori     v1, zero, 1
    beqz    v0, @@set                   ; another dungeon file: FRESH = 2 (Kama Palace / Mana Castle only)
    ori     v1, zero, 2
    ori     t0, zero, 3                 ; event scene: FRESH = 2
    bne     v0, t0, @@go
    nop
@@set:
    sb      v1, TRV_FRESH(at)
@@go:
    j       0x80064D58
    nop

dng_tr_step:
    la      at, PSP_STATE
    lbu     v0, TRV_PENDING(at)
    nop
    beqz    v0, @@orig
    nop
    jr      ra                          ; "stepped on a warp tile"
    ori     v0, zero, 2
@@orig:
    lui     v0, 0x800A
    j       0x8006A744
    lbu     v0, 0x368(v0)

;; field input handler: a queued warp is taken at once (as "step result 2", s0 = 2) instead of reading the pad
dng_tr_idle:
    la      at, PSP_STATE
    lhu     t0, 0x15A0(a1)              ; current map
    lbu     t1, TRV_LAST(at)
    addiu   t0, t0, 1
    sb      t0, TRV_LAST(at)
    lbu     v0, TRV_FRESH(at)
    nop
    beqz    v0, @@queued
    ori     t2, zero, 1
    beq     v0, t2, @@record            ; from the overworld
    sb      zero, TRV_FRESH(at)
    beq     t0, t1, @@queued            ; same dungeon as before: back from a room inside it
    ori     t2, zero, TR_MAP_KAMA + 1
    beq     t0, t2, @@record
    ori     t2, zero, TR_MAP_MANA + 1
    bne     t0, t2, @@queued
    nop
@@record:
    move    v0, a1                      ; dungeon state (a1, from the handler prologue; a1 / a3 kept)
    lhu     t0, 0x15A0(v0)
    nop
    sh      t0, TRV_MAP(at)
    lhu     t0, 0x15A2(v0)
    nop
    sb      t0, TRV_FLOOR(at)
    lbu     t0, 0x15A4(v0)
    nop
    sb      t0, TRV_X(at)
    lbu     t0, 0x15A6(v0)
    nop
    sb      t0, TRV_Y(at)
    lbu     t0, 0x15A7(v0)
    la      t1, dng_tr_dir
    andi    t0, t0, 3
    addu    t1, t1, t0
    lbu     t0, 0(t1)
    nop
    sb      t0, TRV_DIR(at)
    ori     t0, zero, 1
    sb      t0, TRV_VALID(at)
@@queued:
    lbu     v0, TRV_PENDING(at)
    nop
    beqz    v0, @@input
    nop
    j       0x800680A4
    ori     s0, zero, 2
@@input:
    lw      v0, 0x1580(a1)
    j       0x80067D6C
    nop

dng_tr_warp:
    la      at, PSP_STATE
    lbu     v0, TRV_PENDING(at)
    nop
    beqz    v0, @@lookup
    nop
    sb      zero, TRV_PENDING(at)
    lui     v1, 0x801F
    lhu     v0, TRV_MAP(at)
    nop
    sh      v0, 0x5350(v1)
    lbu     v0, TRV_X(at)
    nop
    sb      v0, 0x5352(v1)
    lbu     v0, TRV_Y(at)
    nop
    sb      v0, 0x5353(v1)
    lbu     v0, TRV_FLOOR(at)
    nop
    sb      v0, 0x5354(v1)
    lbu     v0, TRV_DIR(at)
    nop
    sb      v0, 0x5355(v1)
    lui     v1, 0x8005
    jr      ra
    sw      zero, 0x5C5C(v1)            ; next mode 0: DNG (same map file: repositioned)
@@lookup:
    j       0x8006C90C
    nop

;; 0x8008F8CC case: v1 = 1 when the entrance of this map file is known (and no warp is pending yet)
dng_tr_usable:
    la      at, PSP_STATE
    lbu     v0, TRV_VALID(at)
    nop
    beqz    v0, @@no
    nop
    lbu     v0, TRV_PENDING(at)
    nop
    bnez    v0, @@no
    nop
    lhu     v0, TRV_MAP(at)
    lui     v1, TR_STATE_PTR >> 16
    lw      v1, TR_STATE_PTR & 0xFFFF(v1)
    nop
    lhu     v1, 0x15A0(v1)
    nop
    bne     v0, v1, @@no
    nop
    j       0x8008F974
    ori     v1, zero, 1
@@no:
    j       0x8008F974
    move    v1, zero

;; 0x8008F67C case: queue the warp (the party may be several members: idempotent)
dng_tr_effect:
    la      at, PSP_STATE
    ori     v0, zero, 1
    j       0x8008F820
    sb      v0, TRV_PENDING(at)

dng_tr_item_gate:                       ; v0 = (id - 1 < 0x68)
    beqz    v0, dng_tr_item_hi
    nop
    j       0x8008F074                  ; table case
    nop
dng_tr_usable_gate:
    beqz    v0, dng_tr_usable_hi
    nop
    j       0x8008F430
    nop

;; item_use, id - 1 (a1) >= 0x68
dng_tr_item_hi:
    ori     v0, zero, PSP_ES_ITEM
    beq     a1, v0, dng_es_use
    ori     v0, zero, PSP_TR_ITEM
    bne     a1, v0, @@out
    ori     a0, zero, 0xFF
    ori     a1, zero, 0xFF
    jal     0x8008F67C
    ori     a2, zero, PSP_TR_SKILL
@@out:
    j       0x8008F3C4
    nop

;; item_usable, id - 1 (a0) >= 0x68 (s0 = 0 = result)
dng_tr_usable_hi:
    ori     v0, zero, PSP_ES_ITEM
    beq     a0, v0, dng_es_usable
    ori     v0, zero, PSP_TR_ITEM
    bne     a0, v0, @@out
    nop
    jal     0x8008F8CC
    ori     a0, zero, PSP_TR_SKILL
    move    s0, v0
@@out:
    j       0x8008F53C
    nop

dng_tr_item_notarget:                   ; s1 = item id + 1 -> v0 = 1: no target selection
    ori     v0, zero, 0xF
    beq     s1, v0, @@yes
    ori     v0, zero, 0x12
    beq     s1, v0, @@yes
    ori     v0, zero, PSP_TR_ITEM + 1
    beq     s1, v0, @@yes
    ori     v0, zero, PSP_ES_ITEM + 1
    beq     s1, v0, @@yes
    nop
    jr      ra
    move    v0, zero
@@yes:
    jr      ra
    ori     v0, zero, 1

dng_tr_skill_notarget:                  ; v1 = skill (kept) -> v0 = 1: no target selection
    ori     v0, zero, 0x6F
    beq     v1, v0, @@yes
    ori     v0, zero, 0x73
    beq     v1, v0, @@yes
    ori     v0, zero, PSP_TR_SKILL
    beq     v1, v0, @@yes
    ori     v0, zero, PSP_ES_SKILL
    beq     v1, v0, @@yes
    nop
    jr      ra
    move    v0, zero
@@yes:
    jr      ra
    ori     v0, zero, 1

dng_es_pick:
    sh      v1, 0x5350(at)
    la      t0, PSP_STATE
    lbu     t1, TRV_ES_TIMER(t0)
    andi    v1, v1, 0xFFFF
    beqz    t1, @@back
    sltiu   t1, v1, ES_FORMATIONS       ; 0xFFFF (empty list slot) is out of range too
    beqz    t1, @@back
    nop
    la      t0, dng_es_levels
    addu    t0, t0, v1
    lbu     t0, 0(t0)                   ; strongest demon of the formation
    lui     t1, ES_PARTY >> 16
    lbu     t1, ES_PARTY & 0xFFFF(t1)   ; leader
    nop
    sll     t2, t1, 1
    addu    t2, t2, t1
    sll     t2, t2, 5                   ; * 0x60
    la      t1, ES_MEMBERS + ES_LEVEL
    addu    t1, t1, t2
    lbu     t1, 0(t1)                   ; leader level
    nop
    sltu    t0, t0, t1
    beqz    t0, @@back
    nop
    j       0x80070D44                  ; return 0: no battle on this step
    move    v0, zero
@@back:
    ori     v0, zero, 0xFFFF            ; 0x80070B48: andi v1 / beq v1, v0 (retry an empty slot) / cooldown
    j       0x80070B48
    nop

dng_es_tick:
    la      t0, PSP_STATE
    lbu     t1, TRV_ES_TIMER(t0)
    nop
    beqz    t1, @@liftoma
    addiu   t1, t1, -1
    sb      t1, TRV_ES_TIMER(t0)
    bnez    t1, @@liftoma
    ori     t1, zero, 1
    sb      t1, TRV_ES_DONE(t0)
    lui     at, 0x800A
    sb      t1, 0x0D90(at)              ; "effect wore off" pending
@@liftoma:
    lui     v1, 0x801F
    j       0x800697A4
    ori     v1, v1, 0x29A9

dng_es_msg:
    la      t0, PSP_STATE
    lbu     t1, TRV_ES_DONE(t0)
.ifdef scriptmsg_item_8009a18c
    la      t2, scriptmsg_item_8009a18c ; translated message's relocated operand
.else
    la      t2, 0x8009A18E           ; retail message 0x100's FF09 item operand
.endif
    beqz    t1, @@other
    ori     t1, zero, ES_CORE_SHIELD
    sb      zero, TRV_ES_DONE(t0)
    ori     t1, zero, PSP_ES_ITEM + 1
    sb      t1, 0(t2)
    j       0x8006C0F0                  ; jal 0x80073E84(0x100)
    ori     a0, zero, 0x100
@@other:
    sb      t1, 0(t2)
    lui     v0, 0x801F
    j       0x8006C0E0
    lbu     v0, 0x29A8(v0)

;; item_use (a1 = id - 1 = Clean Salt): start / refresh the timer (called per member: idempotent)
dng_es_use:
    la      at, PSP_STATE
    ori     v0, zero, ES_PHASES
    sb      v0, TRV_ES_TIMER(at)
    j       0x8008F3C4
    nop

;; Persona spell Estoma: field-skill effect table case (0x8008F67C; idempotent per member)
dng_es_effect:
    la      at, PSP_STATE
    ori     v0, zero, ES_PHASES
    j       0x8008F820
    sb      v0, TRV_ES_TIMER(at)

;; field-skill usable table case (0x8008F8CC): v1 = 1 while no Clean Salt / Estoma is active
dng_es_skill_usable:
    la      at, PSP_STATE
    lbu     v0, TRV_ES_TIMER(at)
    nop
    j       0x8008F974
    sltiu   v1, v0, 1

;; item_usable (a0 = id - 1 = Clean Salt): s0 = 1 while no Clean Salt is active
dng_es_usable:
    la      at, PSP_STATE
    lbu     v0, TRV_ES_TIMER(at)
    nop
    j       0x8008F53C
    sltiu   s0, v0, 1

dng_tr_dir:                             ; facing 0x15A7 -> transfer-record facing (inverse of table 0x80099D1C)
    .byte   3, 0, 2, 1
dng_es_levels:
.include "../../../../build/estoma_levels.asm"
.endarea
