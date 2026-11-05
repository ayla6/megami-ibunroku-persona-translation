;; =============================================================
;; NAME.BIN - name entry opens on the Latin (ABC) keyboard page,
;; caret on its first key
;;
;; The keyboard has four pages (g_keyboard[4][6][10] at NAME.BIN
;; 0x4310: hiragana, katakana, ABC, dakuten hiragana); page 2 is the
;; ABC grid this project replaces with A-Z | a-z (name_grid.py).
;; g_name_page is at 0x8007829C; the init stub sets it to page 2.
;;
;; Three changes: two inside init (references/persona-decomp
;; src/name/ui/init.c), one in the data the screen opens from:
;;   1. the "load g_name_page" before the keyboard draw is replaced by
;;      a stub call that sets the page to 2 (and the caret to its first
;;      key) and passes 2 as the draw argument;
;;   2. the hardcoded tab-highlight scales move from the page-0 tab
;;      sprites (7 and 29) to the page-2 ones (9 and 31). Sprite 11's
;;      scale is the static "Given" button enlargement and stays.
;;      Sprite record: scalex at 0x8007A828 + i*0x24, scaley at +2;
;;   3. the caret sprites open on that first key too: their defaults in
;;      g_name_sprite_defs are placed there (see below).
;; =============================================================

;; --- 1. draw page 2 and record it ---
.org NAME_ADDR + 0x31AC                 ; 0x80067570: lui a0,0x8007
    jal name_tab_init_stub
.org NAME_ADDR + 0x31B0                 ; 0x80067574: lbu a0,-0x7d64(a0)
    nop

;; --- 2. tab highlight: page-0 sprites -> page-2 sprites ---
;; sh immediates are the low half of the target address:
;;   sprite[i].scalex = 0x8007A828 + i*0x24 (scaley at +2)
;;   sprite[9]  = 0x8007A96C/.A96E   sprite[31] = 0x8007AC84/.AC86
.org NAME_ADDR + 0x3338                 ; 0x800676FC: sh 0x1200 -> sprite[7].scaley
    .dh 0xa96e                        ; -> sprite[9].scaley
.org NAME_ADDR + 0x3340                 ; 0x80067704: sh 0x1200 -> sprite[29].scalex
    .dh 0xac84                        ; -> sprite[31].scalex
.org NAME_ADDR + 0x3348                 ; 0x8006770C: sh 0x1200 -> sprite[29].scaley
    .dh 0xac86                        ; -> sprite[31].scaley
.org NAME_ADDR + 0x3364                 ; 0x80067728: sh 0x1400 -> sprite[7].scalex
    .dh 0xa96c                        ; -> sprite[9].scalex

;; --- 3. the caret opens on the first key ---
;; The sprite table's defaults (g_name_sprite_defs, NAME.BIN 0x3F28,
;; 20 bytes each: x, y at +0/+4, attr at +0x12) ARE the state the screen
;; opens in: retail defines the side caret (sprite 27) at (0x10, 0x78) -
;; exactly what NameCaretPlace writes for col 0/row 0, the first tab
;; cell - and the text caret (sprite 28) at (0xA0, 0x28), field 0's
;; first cell. init copies the defs into the sprites before the fade-in,
;; while NameCaretPlace only re-places the carets from NameEntryInput's
;; tail (screen.c) - i.e. once the 0x81-frame fade-in is over and input
;; starts. So the defaults are what shows while the screen "loads":
;;   1. the key caret (sprite 26) is defined on the 'A' key, visible:
;;      (0x50, 0x80) is NameCaretPlace's own placement for col 1/row 0
;;      (g_caret_x = (col-1)*16 + 0x48, +8; g_caret_y = row*16 + 0x78,
;;      +8), and 0x60 is the retail attr with 0x80 (hidden) dropped;
;;   2. the side caret is defined hidden (attr 0x20 -> 0xA0). Nothing
;;      shows it back on its own: NameCaretPlace does whenever the caret
;;      is on a button column (col 0 or 11), which is the state the
;;      confirm dialog (confirm.c) opens from - it only moves the side
;;      caret over the Yes/No boxes.
;; The caret state itself (g_name_col/g_name_row = 1/0) is set by the
;; init stub (slps_005.00/name_tab.asm), so state and sprites agree from
;; the first drawn frame.
.org NAME_ADDR + 0x3F28 + 20 * 26               ; sprite 26 def (key caret)
    .word 0x50                                  ; x = 0x48 + 8 (the 'A' key)
    .word 0x80                                  ; y = 0x78 + 8 (row 0)
.org NAME_ADDR + 0x3F28 + 20 * 26 + 0x12        ; sprite 26 def attr
    .byte 0x60 ; visible
.org NAME_ADDR + 0x3F28 + 20 * 27 + 0x12        ; sprite 27 def attr (side caret)
    .byte 0xA0 ; hidden

;; --- 4. Triangle runs the field switch instead of teleporting ---
;; Retail (screen.c, both input paths): Triangle from the key area just
;; moves the caret to the Given button (col 0, row 5), where Circle
;; performs the switch. The handler exists twice - keyboard mode and
;; kanji-list mode - each with its own switch block. Jump from each
;; teleport into its own mode's switch block (the "row == 5" guard sits
;; upstream and is not needed by the block itself):
;;   NamePlaySe(4); field = (field + 1) % 3; field-underline attrs;
;;   if (field == Nick && page == dakuten) -> page 0 (+ list close).
;; Keyboard mode (screen.c case 0):
.org NAME_ADDR + 0xF6C                  ; 0x80065330: jal NamePlaySe(1)
    j 0x80064f68                        ; -> the keyboard Circle-at-Given switch
    nop
;; Kanji-list mode (screen.c case 1):
.org NAME_ADDR + 0x1D04                 ; 0x800660C8: jal NamePlaySe(1)
    j 0x80065a30                        ; -> the list Circle-at-Given switch
    nop
