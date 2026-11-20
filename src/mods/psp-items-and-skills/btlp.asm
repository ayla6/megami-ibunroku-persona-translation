;; =============================================================
;; PSP items and skills (--mods=psp-items-and-skills): BTLP.BIN - field-only Persona
;; skills cannot be cast in battle.
;;
;; The battle skill list greys a skill whose record byte +0x0A has bit
;; 0x80 clear (0x800AC938): Estoma (0x70,
;; mods/psp-items-and-skills/slps.asm), Traesto (0x71) and Liftoma (0x73) - and Mappa
;; (0x6F), which no Persona learns. The confirm
;; only refused Liftoma, by id (buzzer, back to the list); the others were
;; cast with no battle effect. It now refuses every greyed skill, by that
;; same record bit, through the retail buzzer block 0x800A3618.
;;
;; In place: the copy loop in front (the listed skill ids -> 0x800F6E04)
;; loaded each byte twice and waited out both loads with a nop; loaded
;; once, it frees the words the record test needs.
;; =============================================================

.org 0x800A35CC
.area 0x800A3618 - 0x800A35CC
@@copy:                             ; v1 = source, a1 = its end, a0 = 0x800F6E04
    lbu     a2, 0(v1)
    addiu   v1, v1, 1
    beqz    a2, @@next              ; 0 = no skill in that slot
    slt     v0, v1, a1
    sb      a2, 0(a0)
    addiu   a0, a0, 1
@@next:
    bnez    v0, @@copy
    lui     at, 0x800F
    addu    at, at, s0
    lbu     a2, 0x6E04(at)          ; the selected skill
    lui     at, 0x8004
    sll     v1, a2, 2
    addu    v1, v1, a2
    sll     v1, v1, 2               ; id * 0x14
    addu    at, at, v1
    lbu     v1, 0x7D4E(at)          ; skill record + 0x0A (0x80047D44 + id * 0x14)
    ori     v0, zero, 0xA2          ; for the next test (0x800A362C)
    andi    v1, v1, 0x80
    bnez    v1, 0x800A362C          ; usable in battle: continue (delay: ori a0, zero, 1)
.endarea                            ; greyed: 0x800A3618 buzzes and stays in the list
