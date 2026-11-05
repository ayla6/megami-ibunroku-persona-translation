;; =============================================================
;; NAME.BIN - the caret moves in a ring of the row's real cells
;;
;; The key grid is twelve columns wide in the code (screen.c): col 0 is
;; the left button column, cols 1-10 the keys, col 11 the right button
;; column; g_name_col/g_name_row hold the caret. The left column has
;; one cell: the field switch at (0,5) (name/abc_only.asm).
;; Each row is a ring of the cells that exist, and a
;; step past either end wraps to the other end (slps_005.00/name_ring.asm):
;;   row 5:    Given | Z . ' - z ! ? / : | Enter
;;   rows 0-3: A ... | ... a ... | arrows/Delete/Clear
;;   row 4:    P Q R S T p q r s t   (the button columns have no row 4)
;; So the far-right buttons wrap onto the row's first letter, the letters
;; wrap onto the buttons above the Z row and onto Given at it, and the
;; caret never jumps rows or rests on a cell that is not there (the
;; vertical handlers' own row-4 skips stay as they are).
;;
;; The four horizontal handlers of NameEntryInput - LEFT and RIGHT, in
;; the keyboard mode and the kanji-list mode - drop their wrap/snap
;; fix-ups and jump to name_col_ring right after storing the new
;; g_name_col. The replaced tails are unreachable from anywhere else
;; (checked: only their own branches point into them).
;; =============================================================

;; --- keyboard mode (screen.c case 0) ---
.org NAME_ADDR + 0x630                   ; 0x800649F4: sll v0,v0,16 (LEFT, after sh g_name_col)
    j       name_col_ring
    nop
.org NAME_ADDR + 0x6A0                   ; 0x80064A64: sll v0,v0,16 (RIGHT, after sh g_name_col)
    j       name_col_ring
    nop

;; --- kanji-list mode (screen.c case 1) ---
.org NAME_ADDR + 0x1280                  ; 0x80065644: sll v0,v0,16 (LEFT, after sh g_name_col)
    j       name_col_ring
    nop
.org NAME_ADDR + 0x12EC                  ; 0x800656B0: sll v0,v0,16 (RIGHT, after sh g_name_col)
    j       name_col_ring
    nop
