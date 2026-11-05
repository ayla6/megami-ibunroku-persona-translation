;; =============================================================
;; NAME.BIN / NAMEDT.BIN - the name entry is ABC-only: the
;; character-set selector is gone and the left button column
;; holds one button
;;
;; The keyboard has four pages (hira, kata, ABC, dakuten hiragana;
;; name/latin_start.asm opens the screen on ABC). The pages are
;; switched by NameSetPage (page.c) from two pad paths - tapping a
;; tab (col 0, rows 0-3 of screen.c's Circle handler, twice: the
;; keyboard mode and the kanji-list mode) and SELECT page cycling
;; (twice as well) - and the tabs themselves are sprites 7-10
;; (labels: NAMEDT.BIN atlas cells 0/48/96/144,0 = Hira / Kata /
;; ABC / Kanji) with frames 29-32 (entry.h SPR_PAGE_TAB /
;; SPR_PAGE_TAB2; sprite defs at NAME.BIN 0x3F28 = RAM 0x800682EC,
;; 20 bytes each, attr at +0x12 -> g_sprite_attr, 0x80 = hidden).
;;
;; Three changes, one rule: the entry is ABC-only, so the selector
;; has nothing to select and the typed name is always Latin (this
;; is what lets text flow reserve 'R' runs for name inserts, see
;; vwf_wrap.py):
;;   1. the four tab labels and their four frames are defined
;;      hidden (attr |= 0x80): the selector is not drawn;
;;   2. NameSetPage's "g_name_page = page" store is dropped: the
;;      page can never change, so tapping a (hidden) tab cell or
;;      pressing SELECT cannot reach the other character sets -
;;      every pad path funnels through that one store;
;;   3. the caret tail clamps the row: the left column holds one
;;      button (the field switch at row 5), so the caret cannot sit
;;      on the hidden tab cells (slps_005.00/name_tab.asm);
;;   4. the empty tab column closes up (NAMEDT.BIN): the recess the
;;      tabs sat in is part of the keyboard BACKGROUND (its tile map
;;      draws frame + divider tiles round it), not a sprite, so the
;;      divider tile is dropped from the map and the column merges
;;      into the keyboard panel.
;; =============================================================

;; --- 1. tab labels (7-10) and tab frames (29-32) are defined hidden ---
;; sprite def attr: 0x60 = GsSortSprite + semi-transparent (labels),
;; 0x40 = GsSortSprite (frames); 0x80 keeps them out of NameDrawFrame
;; (frame.c). Nothing shows them again (NameListClose's sprite 10
;; un-hide sits in the kanji-list mode that rule 2 makes unreachable).
.org NAME_ADDR + 0x3F28 + 20 * 7 + 0x12      ; sprite 7 attr (Hira)
    .byte 0xE0
.org NAME_ADDR + 0x3F28 + 20 * 8 + 0x12      ; sprite 8 attr (Kata)
    .byte 0xE0
.org NAME_ADDR + 0x3F28 + 20 * 9 + 0x12      ; sprite 9 attr (ABC)
    .byte 0xE0
.org NAME_ADDR + 0x3F28 + 20 * 10 + 0x12     ; sprite 10 attr (Kanji)
    .byte 0xE0
.org NAME_ADDR + 0x3F28 + 20 * 29 + 0x12     ; sprite 29 attr (frame)
    .byte 0xC0
.org NAME_ADDR + 0x3F28 + 20 * 30 + 0x12     ; sprite 30 attr (frame)
    .byte 0xC0
.org NAME_ADDR + 0x3F28 + 20 * 31 + 0x12     ; sprite 31 attr (frame)
    .byte 0xC0
.org NAME_ADDR + 0x3F28 + 20 * 32 + 0x12     ; sprite 32 attr (frame)
    .byte 0xC0

;; --- 2. the keyboard page can never change ---
;; NameSetPage (page.c, NAME @ 0x80067158) writes the page first thing:
;;   0x80067158: lui  a1, 0x8007        a1 = g_name_page (old, for the tab scales)
;;   0x8006715c: lbu  a1, -0x7d64(a1)
;;   0x80067160: lui  at, 0x8007
;;   0x80067164: sb   a0, -0x7d64(at)   g_name_page = page   <- dropped
;;   0x80067168: lui  a0, 0x8007        a0 reloaded from g_name_page (still ABC)
;;   0x8006716c: lbu  a0, -0x7d64(a0)
;; With the store dropped, g_name_page keeps the ABC page the init stub
;; writes (slps_005.00/name_tab.asm) and every caller - tab taps, SELECT
;; cycling, the field-switch page guard - merely redraws ABC.
.org NAME_ADDR + 0x2DA0                       ; 0x80067164: sb a0, -0x7d64(at)
    nop

;; --- 3. the caret tail: see slps_005.00/name_tab.asm ---
;; 0x80066230: lui  v0, 0x8007
;; 0x80066234: lh   v0, -0x7d2a(v0)    v0 = g_name_row (caret_y = row*16+0x78)
;; replaced by a call to name_caret_row_clamp (col 0 -> row 5), which
;; replays those two instructions and returns to 0x80066238.
.org NAME_ADDR + 0x1E6C                       ; 0x80066230: lui v0, 0x8007
    j       name_caret_row_clamp
    nop

;; --- 4. the empty tab column closes up: see namedt/tab_column.asm ---
;; The recess the tabs sat in is part of the keyboard BACKGROUND (the
;; g_bg_keys tile map draws frame + divider tiles round it), not a
;; sprite; that file drops the divider tile from the map so the column
;; merges into the keyboard panel. (Patches NAMEDT.BIN, so it lives in
;; that file's assembly context.)
