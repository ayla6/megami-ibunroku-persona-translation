;; =============================================================
;; SLPS_005.00 - stub for the name entry's caret ring (name/ring.asm)
;;
;; One dead SLPS function (tools/deadfuncs.py, unclaimed; taken from
;; tools/choices.py FREE): NAME_RING_STUB_ADDR..NAME_RING_STUB_END,
;; 148 bytes, 100 used. See name_tab.asm for the other name stubs.
;; =============================================================

;; --- name_col_ring (name/ring.asm) ---
;; Runs from the four horizontal-movement handlers of NameEntryInput
;; (screen.c: the keyboard mode and the kanji-list mode, twice) in place
;; of their wrap/snap fix-ups, after the new g_name_col has been stored.
;; Each row is a ring of the cells that exist:
;;   rows 0-3: cols 1-11 (the keys, then the arrows/Delete/Clear),
;;   row 4:    cols 1-10 (the button columns have no row 4),
;;   row 5:    cols 0-11 (the left column's one cell - the field switch
;;                       at (0,5) - is in that row).
;; A step past either end wraps to the other end, so the caret lands on a
;; cell that exists and never jumps rows. Clobbers at, v0, v1, t0-t2.
.org NAME_RING_STUB_ADDR
.area NAME_RING_STUB_END - NAME_RING_STUB_ADDR
name_col_ring:
    lui   $at, 0x8007
    lh    $v0, -0x7d2c($at)              ; g_name_col (after the step)
    lh    $v1, -0x7d2a($at)              ; g_name_row
    ori   $t1, $zero, 1                  ; ring start = the first key ...
    ori   $t2, $zero, 11                 ; ring end = the right button column
    ori   $t0, $zero, 5
    bne   $v1, $t0, @@notrow5
    nop
    ori   $t1, $zero, 0                  ; ... except on row 5, which starts at the field switch
@@notrow5:
    ori   $t0, $zero, 4
    bne   $v1, $t0, @@cmp
    nop
    ori   $t2, $zero, 10                 ; row 4 ends at the last key: no button cells
@@cmp:
    slt   $t0, $v0, $t1
    bne   $t0, $zero, @@wrap_end         ; before the start -> the ring's end
    nop
    slt   $t0, $t2, $v0
    beq   $t0, $zero, @@store            ; inside the ring: keep the step
    nop
    addu  $v0, $t1, $zero                ; past the end -> the ring's start
    j     @@store
    nop
@@wrap_end:
    addu  $v0, $t2, $zero
@@store:
    sh    $v0, -0x7d2c($at)              ; g_name_col = v0
    j     0x80066180                      ; the input tail (caret placement)
    nop
.endarea
