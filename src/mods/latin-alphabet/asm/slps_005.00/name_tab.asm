;; =============================================================
;; SLPS_005.00 - stubs for the name entry (name/latin_start.asm,
;; name/abc_only.asm)
;;
;; Both stubs live in one dead SLPS function (tools/deadfuncs.py,
;; unclaimed): 0x80024744..0x8002479C, 88 bytes, 32 + 44 used.
;;
;; State (decomp references/persona-decomp src/name/ui, entry.h):
;;   g_name_mode  0x8007829A (0 keyboard, 1 kanji list)
;;   g_name_field 0x8007829B (Family/Given/Nick)
;;   g_name_page  0x8007829C (keyboard page; 2 = ABC)
;;   g_name_col   0x800782D4 (short; col 0 = tab/button column)
;;   g_name_row   0x800782D6 (short)
;; =============================================================

;; --- name_tab_init_stub (name/latin_start.asm) ---
;; Runs from NAME.BIN's init in place of "lui a0,0x8007 / lbu
;; a0,-0x7d64(a0)" (the load of g_name_page before the keyboard draw).
;; Opens the keyboard on the ABC page with the caret on its first key,
;; then returns so init's own "jal NameDrawKeyboardPage" draws it.
;; Col 0 row 0 is the Hira tab cell, so col must start at 1 to sit on
;; the 'A' key; the row is written too so the caret state is the first
;; key in full (1/0), not just by column. The caret sprites carry the
;; same default (name/latin_start.asm).
.org NAME_TAB_STUB_ADDR
name_tab_init_stub:
    lui   $at, 0x8007
    ori   $v0, $zero, 2                  ; keyboard page 2 = ABC (g_keyboard[2] = A-Z/a-z)
    sb    $v0, -0x7d64($at)              ; g_name_page = 2
    ori   $a0, $zero, 2                  ; argument for init's NameDrawKeyboardPage call
    ori   $v0, $zero, 1
    sh    $v0, -0x7d2c($at)              ; g_name_col = 1 -> caret on the first key ('A')
    jr    $ra
    sh    $zero, -0x7d2a($at)            ; (delay slot) g_name_row = 0

;; --- name_caret_row_clamp (name/abc_only.asm) ---
;; Runs from the caret tail of NameEntryInput (screen.c) in place of
;; "lui v0,0x8007 / lh v0,-0x7d2a(v0)" (the g_name_row load behind
;; g_caret_y = g_name_row * 16 + 0x78), then replays those two
;; instructions and returns to 0x80066238. The left button column's
;; tab cells are hidden (name/abc_only.asm), so the column holds one
;; button: the row is clamped to 5 (the field switch) whenever the
;; caret is on col 0 - every pad path in screen.c ends this frame, so
;; no input can rest on or reach the hidden tab cells. Clobbers v0 and
;; at (the tail reloads both before use).
.org NAME_TAB_STUB_ADDR + 0x20
name_caret_row_clamp:
    lui   $at, 0x8007
    lh    $v0, -0x7d2c($at)              ; g_name_col
    nop
    bnez  $v0, @@row                     ; only the left button column
    nop
    ori   $v0, $zero, 5
    sh    $v0, -0x7d2a($at)              ; g_name_row = 5 (the field switch)
@@row:
    lui   $v0, 0x8007                    ; (moved from the caret tail)
    lh    $v0, -0x7d2a($v0)              ; v0 = g_name_row
    j     0x80066238                     ; caret tail: caret_y = row * 16 + 0x78
    nop
