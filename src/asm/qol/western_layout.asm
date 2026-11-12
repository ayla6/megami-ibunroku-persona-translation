;; =============================================================
;; QoL (--qol=western): the controller page's labels for the swapped buttons.
;;
;; g_pad_layout_actions holds an action per button, four layouts of twenty
;; (two columns of ten; each starts circle, cross, triangle, square), and the
;; layout is the controller type plus two for the second page. Layouts 0 and 2
;; are TYPE 1, whose buttons western_pad.asm swaps: the first four entries of
;; both columns trade places pairwise, so the page names what each physical
;; button does. Each overlay that carries the page has its own copy.
;; Retail bytes in the comments; tools/tests/test_qol_western.py checks them.
;; =============================================================
;; The run QoL (qol/run_dng.asm) puts its own action on TYPE 1's Circle entry
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
