;; =============================================================
;; NAMEDT.BIN - the empty tab column fills with the light panel
;; (name/abc_only.asm)
;;
;; The keyboard panel is BACKGROUND art, not a sprite: g_bg_keys is
;; built from entry 5 (cells) + entry 6 (a 19x8 cell map) over the
;; shared tile atlas in entry 12, and every map row draws the panel's
;; zones - column 0 = the panel's gold frame, columns 1-2 = the tab
;; column's recess, column 3 = a divider tile (the same gold frame
;; again), columns 4-14 = the key field, column 15 = the button
;; column's divider, 16-17 = the button column, 18 = the frame.
;; (Rendered from the files and matched against the screen: the
;; recessed panel left behind by the hidden tabs is this map, so it
;; cannot be removed by hiding sprites - and it needs no art editing
;; either.)
;;
;; With the tabs gone (name/abc_only.asm) the recess is empty. It is
;; not filled with the key field's dark checkered tiles (that reads as
;; more keyboard), but with the light panel texture the button plates
;; are cut from (atlas 80..128,24 - sprite 42's plate: "the keyboard
;; background without the dark overlay"). The divider tile goes away
;; with it, so the light area runs from the frame to the key field;
;; rows 0 and 7 keep the panel's top/bottom frame segments. The button
;; column keeps its divider: the field switch still sits at the bottom
;; of the light area.
;;
;; Map index: u16s at entry 6 + 8 (19 columns x 8 rows). One cell per
;; row is free to re-point: cell 5r+3 (the divider, only column 3 used
;; it), so columns 1-3 of the middle rows take it. Cell u,v live in
;; entry 5 (8 bytes per cell, u/v at +0/+1).
;; =============================================================

;; --- the frame's inner 4 px take the fill texture too ---
;; The panel's left frame tile (atlas u 160..176) is 12 px of gold band plus
;; 4 px of the old recess edge (the dark texture, x 172..175). With the
;; recess gone that edge reads as a dark line beside the light fill, so it
;; takes the fill texture as well: columns 92..95 of the same plate, in
;; phase with the fill tile's rows 24..39. Only the six middle edge cells
;; (atlas rows 32..127) need it - the corner cells' inner columns are the
;; panel's top/bottom gold band and stay.
;; Atlas pixels live at entry 12 + 20 (256 bytes a row).

.macro tab_edge_fill, y0
.org NAMEDT_ADDR + 0x3350 + (y0 + 0) * 256 + 172
    .byte 0x13, 0x0D, 0x13, 0x1D
.org NAMEDT_ADDR + 0x3350 + (y0 + 1) * 256 + 172
    .byte 0x15, 0x13, 0x15, 0x1A
.org NAMEDT_ADDR + 0x3350 + (y0 + 2) * 256 + 172
    .byte 0x19, 0x0F, 0x1A, 0x1B
.org NAMEDT_ADDR + 0x3350 + (y0 + 3) * 256 + 172
    .byte 0x12, 0x12, 0x15, 0x1E
.org NAMEDT_ADDR + 0x3350 + (y0 + 4) * 256 + 172
    .byte 0x0E, 0x12, 0x1A, 0x22
.org NAMEDT_ADDR + 0x3350 + (y0 + 5) * 256 + 172
    .byte 0x12, 0x1A, 0x20, 0x1F
.org NAMEDT_ADDR + 0x3350 + (y0 + 6) * 256 + 172
    .byte 0x12, 0x1E, 0x22, 0x19
.org NAMEDT_ADDR + 0x3350 + (y0 + 7) * 256 + 172
    .byte 0x15, 0x1E, 0x19, 0x0C
.org NAMEDT_ADDR + 0x3350 + (y0 + 8) * 256 + 172
    .byte 0x15, 0x1A, 0x14, 0x0A
.org NAMEDT_ADDR + 0x3350 + (y0 + 9) * 256 + 172
    .byte 0x14, 0x15, 0x12, 0x12
.org NAMEDT_ADDR + 0x3350 + (y0 + 10) * 256 + 172
    .byte 0x19, 0x12, 0x12, 0x15
.org NAMEDT_ADDR + 0x3350 + (y0 + 11) * 256 + 172
    .byte 0x15, 0x0C, 0x12, 0x1A
.org NAMEDT_ADDR + 0x3350 + (y0 + 12) * 256 + 172
    .byte 0x19, 0x0C, 0x0F, 0x19
.org NAMEDT_ADDR + 0x3350 + (y0 + 13) * 256 + 172
    .byte 0x19, 0x0E, 0x12, 0x19
.org NAMEDT_ADDR + 0x3350 + (y0 + 14) * 256 + 172
    .byte 0x19, 0x12, 0x12, 0x12
.org NAMEDT_ADDR + 0x3350 + (y0 + 15) * 256 + 172
    .byte 0x1B, 0x15, 0x0F, 0x13
.endmacro

tab_edge_fill 32                          ; cell 5  (map row 1)
tab_edge_fill 48                          ; cell 10 (map row 2)
tab_edge_fill 64                          ; cell 15 (map row 3)
tab_edge_fill 80                          ; cell 20 (map row 4)
tab_edge_fill 96                          ; cell 25 (map row 5)
tab_edge_fill 112                         ; cell 30 (map row 6)

;; --- the divider cell of rows 1-6 becomes a light panel tile ---
.org NAMEDT_ADDR + 0xA48 + 8 + 8 * (5 * 1 + 3)     ; cell 8
    .byte 96, 24
.org NAMEDT_ADDR + 0xA48 + 8 + 8 * (5 * 2 + 3)     ; cell 13
    .byte 96, 24
.org NAMEDT_ADDR + 0xA48 + 8 + 8 * (5 * 3 + 3)     ; cell 18
    .byte 96, 24
.org NAMEDT_ADDR + 0xA48 + 8 + 8 * (5 * 4 + 3)     ; cell 23
    .byte 96, 24
.org NAMEDT_ADDR + 0xA48 + 8 + 8 * (5 * 5 + 3)     ; cell 28
    .byte 96, 24
.org NAMEDT_ADDR + 0xA48 + 8 + 8 * (5 * 6 + 3)     ; cell 33
    .byte 96, 24

;; --- map: the tab column takes that cell (columns 1-3, rows 1-6) ---
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (1 * 19 + 1)
    .halfword 5 * 1 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (1 * 19 + 2)
    .halfword 5 * 1 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (1 * 19 + 3)
    .halfword 5 * 1 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (2 * 19 + 1)
    .halfword 5 * 2 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (2 * 19 + 2)
    .halfword 5 * 2 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (2 * 19 + 3)
    .halfword 5 * 2 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (3 * 19 + 1)
    .halfword 5 * 3 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (3 * 19 + 2)
    .halfword 5 * 3 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (3 * 19 + 3)
    .halfword 5 * 3 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (4 * 19 + 1)
    .halfword 5 * 4 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (4 * 19 + 2)
    .halfword 5 * 4 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (4 * 19 + 3)
    .halfword 5 * 4 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (5 * 19 + 1)
    .halfword 5 * 5 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (5 * 19 + 2)
    .halfword 5 * 5 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (5 * 19 + 3)
    .halfword 5 * 5 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (6 * 19 + 1)
    .halfword 5 * 6 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (6 * 19 + 2)
    .halfword 5 * 6 + 3
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (6 * 19 + 3)
    .halfword 5 * 6 + 3

;; --- map: rows 0 and 7 keep the panel's top/bottom frame across the
;;     column (the frame segment cell, as columns 1-2 use) ---
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (0 * 19 + 3)
    .halfword 5 * 0 + 1
.org NAMEDT_ADDR + 0xB90 + 8 + 2 * (7 * 19 + 3)
    .halfword 5 * 7 + 1
