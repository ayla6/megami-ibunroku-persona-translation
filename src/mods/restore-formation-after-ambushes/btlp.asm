;; =============================================================
;; Restore formation after ambushes (--mods=restore-formation-after-ambushes): after an ambush the party stands where it stood
;; before the fight (BTLP.BIN).
;;
;; When the enemies get the jump on the party (the field's surprise roll
;; failed: g_btl_battle_kind 2 at 0x800F70D0), the battle entry turns the
;; party round - the battle's formation grid (0x8004E1BC) has its front half
;; swapped end for end with its back half (decomp src/btlp/entry.c). When the
;; fight ends, BtlStoreParty (inlined at 0x8008768C) copies that grid into
;; the save block's live formation row (0x801F264C), the one the field
;; stands the party in. Retail never swaps it back, so every ambush leaves
;; the party reversed on the field.
;;
;; Here the grid is copied aside just before that swap, and written over the
;; live row when the battle entry returns to the field, after that store:
;; the formation from BEFORE the
;; ambush, whatever the player moved during the fight. The copy and its
;; flag live in BTLP's own image (the entry's unreachable debug dump), so a
;; fresh load of the overlay - every battle - starts with the flag clear; a
;; battle that never returns (a game over) leaves nothing behind.
;;
;; The flag is the copy's length: 25 after an ambush, 0 otherwise, so the
;; exit is one memmove (SLPS 0x8004137C) that copies nothing when there
;; was no ambush.
;; =============================================================
.definelabel AMB_FORMATION, 0x8004E1BC        ; the battle's formation grid (25 cells)
.definelabel AMB_LIVE_ROW, 0x801F264C         ; the save block's live formation row (g_formation_preset row 8)
.definelabel AMB_MEMMOVE, 0x8004137C          ; SLPS memmove(dst, src, n)
.definelabel AMB_CELLS, 25

;; the ambush branch of the battle entry: save the grid, then the retail
;; swap (moved to amb_mirror), then the retail BtlFormationCloseUp call
.org 0x80080D14
.area 0x80080D48 - 0x80080D14
    lui     a0, hi(amb_saved)
    addiu   a0, a0, lo(amb_saved)
    ori     a2, zero, AMB_CELLS
    sb      a2, AMB_CELLS(a0)                 ; the flag: the length the exit copies back
    lui     a1, hi(AMB_FORMATION)
    jal     AMB_MEMMOVE                       ; memmove(amb_saved, grid, 25)
    addiu   a1, a1, lo(AMB_FORMATION)
    lui     a0, hi(AMB_FORMATION)
    jal     amb_mirror
    addiu   a0, a0, lo(AMB_FORMATION)
    .fill 0x80080D48 - ., 0                   ; the rest of the retail swap: nops
.endarea

;; the battle entry's return to the field
.org 0x80080F04
    j       amb_restore
    nop

;; the battle entry's "SND INIT" dump (0x800802C4 beqz skips it while
;; g_btl_debug is clear, and no code sets it): its body, the branch's delay
;; slot at 0x800802C8 left as it is
.org 0x800802CC
.area 0x800803E8 - 0x800802CC
;; a0 = the grid: its front half swapped end for end with its back half, as
;; the retail entry does (the middle cell stays)
amb_mirror:
    addiu   a1, a0, 0x18
@@swap:
    lbu     v0, 0(a1)
    lbu     v1, 0(a0)
    sb      v0, 0(a0)
    addiu   a0, a0, 1
    sb      v1, 0(a1)
    sltu    v0, a0, a1
    bnez    v0, @@swap
    addiu   a1, a1, -1
    jr      ra
    nop
;; the battle entry's return, with the saved grid written over the live row
;; first (ra is already the caller's)
amb_restore:
    lui     a1, hi(amb_saved)
    lbu     a2, lo(amb_saved) + AMB_CELLS(a1)  ; 25 after an ambush, else 0
    addiu   a1, a1, lo(amb_saved)
    lui     a0, hi(AMB_LIVE_ROW)
    sb      zero, AMB_CELLS(a1)
    j       AMB_MEMMOVE                       ; memmove(live row, amb_saved, n), returns to the caller
    addiu   a0, a0, lo(AMB_LIVE_ROW)
amb_saved:
    .fill AMB_CELLS + 1, 0                    ; the grid before the ambush, then the flag
.endarea
