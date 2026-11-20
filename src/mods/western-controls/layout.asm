;; =============================================================
;; Western controls (--mods=western-controls): the controller page's labels for the swapped buttons.
;;
;; g_pad_layout_actions holds an action per button, four layouts of twenty
;; (two columns of ten; each starts circle, cross, triangle, square), and the
;; layout is the controller type plus two for the second page. Layouts 0 and 2
;; are TYPE 1, whose buttons western_pad.asm swaps: the first four entries of
;; both columns trade places pairwise, so the page names what each physical
;; button does. Each overlay that carries the page has its own copy.
;; Retail bytes in the comments; src/mods/western-controls/test_mod_western.py checks them.
;; =============================================================
;; Run in dungeons (mods/run-in-dungeons/dng.asm) puts its own action on TYPE 1's Circle entry
;; (the cancel button): DNG passes cancel_taken = 1 and leaves that byte to it.
.macro western_layout, table, cancel_taken
.if cancel_taken == 0
.org table + 0                          ; layout 0, 3D column   (retail 07 02 00 03)
    .byte   0x02
.endif
.org table + 1
    .byte   0x07, 0x03, 0x00
.org table + 10                         ; layout 0, 2D column   (retail 01 02 11 03)
    .byte   0x02, 0x01, 0x03, 0x11
.org table + 40                         ; layout 2, first column  (retail 01 02 00 04)
    .byte   0x02, 0x01, 0x04, 0x00
.org table + 50                         ; layout 2, second column (retail 01 02 09 04)
    .byte   0x02, 0x01, 0x04, 0x09
.endmacro

;; Action hints sample the remapped cells; the controller settings page
;; names physical keys. Compensate its cell indices when the cell table was
;; initialized for TYPE 1, preserving its original icon order and labels.
;; Read the table's actual first u, rather than the current pad type: the
;; controller type can change while this page is open or before reopening it.
.macro western_physical_icons, site, workspace_high
.org site
.area 0x40
    lui     a0, workspace_high
    ori     a0, a0, 0xF760
    lui     a1, workspace_high
    lbu     a1, 0x5FEC(a1)
    li      a2, 0x434
    srl     a1, a1, 3
    li      v1, 4
@@physical:
    xor     v0, a2, a1
    sh      v0, 0(a0)
    addiu   v0, v0, 1
    sh      v0, 2(a0)
    addiu   a2, a2, 2
    addiu   v1, v1, -1
    bnez    v1, @@physical
    addiu   a0, a0, 0x50
.endarea
.endmacro

;; All three copies of CellsInit end with jr ra / nop. Tail-call the shared
;; icon remapper after the retail tables are complete. S2D's workspace is
;; 0x20000 above ADV/DNG's; their cell layouts are identical.
.macro western_button_cells_hook, site, workspace_high
.org site
    j       western_button_cells
    lui     a0, workspace_high
.endmacro
