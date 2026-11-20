;; =============================================================
;; PSP items and skills (--mods=psp-items-and-skills): SLPS_005.00 - the records, and
;; the dungeon entrance / Clean Salt timer in memory-card saves.
;;
;; Estoma: skill record 0x70 (Trafuri, unused) takes the PSP Estoma data
;; bytes (= Traesto's 66 00 11 FF 0A 00 FF: field-only, like Liftoma /
;; Traesto). Effect: mods/psp-items-and-skills/dng.asm and mods/psp-items-and-skills/s2d.asm.
;;
;; Items: record = flags word (name - 4), name, +0xA battle skill, +0x15
;; type (0 = teaches the skill at +0x16 in a fusion, like the spell
;; stones: ADV 0x800A0710 writes it into the result's 7th skill slot),
;; +0x16 field skill, +0x18 sell price. Both new items: flags 0x6040 like
;; Core Shield (used up, no target selection), no battle use, sell for
;; 5000 (buy 10000, PSP). Emergency Exit's field skill is Traesto, Clean
;; Salt's Estoma, so a fusion with them teaches that skill.
;;
;; Personas: the PSP adds Estoma / Traesto in one EMPTY slot of seven
;; Personas; no skill is replaced and the 7th (fusion item) slot stays.
;;
;; Saves: the save function 0x80013E2C writes a 128-byte location sector
;; (0x8005E380: +0x0D dungeon flag, +0x0E.. map / floor / position, +0x7F
;; XOR checksum); +0x18..+0x7E were always 0. It now also stores
;; TR_SAVE_MAGIC at +0x18 and the first TRV_SAVED bytes of the state at
;; +0x1C, before the checksum; Continue restores them
;; (mods/psp-items-and-skills/open.asm). The checksum loop 0x80014348..0x800143C3
;; (-O0 code, 31 words) is rewritten compactly to make room.
;; =============================================================

.org PSP_SKILLS + PSP_ES_SKILL * 0x14 + 0x0A
    .byte 0x66, 0x00, 0x11, 0xFF, 0x0A, 0x00, 0xFF

.org PSP_ITEM_NAMES + PSP_ES_ITEM * 0x20 - 4      ; Clean Salt
    .byte 0xFF, 0x01, 0x40, 0x60
.org PSP_ITEM_NAMES + PSP_ES_ITEM * 0x20 + 0x16
    .byte PSP_ES_SKILL
.org PSP_ITEM_NAMES + PSP_ES_ITEM * 0x20 + 0x18
    .word 5000
.org PSP_ITEM_NAMES + PSP_TR_ITEM * 0x20 - 4      ; Emergency Exit
    .byte 0xFF, 0x01, 0x40, 0x60
.org PSP_ITEM_NAMES + PSP_TR_ITEM * 0x20 + 0x16
    .byte PSP_TR_SKILL
.org PSP_ITEM_NAMES + PSP_TR_ITEM * 0x20 + 0x18
    .word 5000

psp_persona_skill 6, 4, PSP_ES_SKILL    ; Cu Chulainn
psp_persona_skill 14, 3, PSP_ES_SKILL   ; Urdr
psp_persona_skill 40, 2, PSP_ES_SKILL   ; Shouki
psp_persona_skill 53, 3, PSP_ES_SKILL   ; Byakko
psp_persona_skill 52, 2, PSP_TR_SKILL   ; Otohime
psp_persona_skill 54, 4, PSP_TR_SKILL   ; Aonbarr
psp_persona_skill 97, 3, PSP_TR_SKILL   ; Quetzalcoatl

.org 0x80014348
.area 0x800143C4 - 0x80014348, 0
    lui     t1, 0x8006
    addiu   t1, t1, -0x1C80             ; location sector 0x8005E380
    la      t0, PSP_STATE
    ori     v0, zero, TR_SAVE_MAGIC
    sb      v0, 0x18(t1)
    lw      v0, 0(t0)                   ; valid, fresh, pending, floor
    lw      v1, 4(t0)                   ; map, x, y
    sw      v0, 0x1C(t1)
    lw      v0, 8(t0)                   ; facing, Clean Salt timer, "wore off", last map
    sw      v1, 0x20(t1)
    sw      v0, 0x24(t1)
    lbu     v1, 0x68(fp)                ; checksum (starts at 0)
    move    v0, t1
    addiu   t2, t1, 0x7F
@@sum:
    lbu     t3, 0(v0)
    addiu   v0, v0, 1
    bne     v0, t2, @@sum
    xor     v1, v1, t3
    sb      v1, 0x68(fp)
    sb      v1, 0(v0)                   ; + 0x7F
.endarea
