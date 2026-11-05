;; Title load list: the same bottom-aligned retail ADV panel and row fields.
;; Slots 10/11 retain the LOAD badge. 12/13 are the two texture halves of
;; ONE panel; 14 is the cursor, 16..253 text. Confirm/message slots stay retail.
.include "qol/saves.inc"
.definelabel SP_CURSOR, 14
.definelabel SP_CELL, 16
.definelabel QOL_C_NAME, 8
.definelabel QOL_C_ALL, 17
.definelabel QOL_C_CLOCK0, 12
.if SP_CELL + QOL_ROWS * QOL_C_ALL > 262
    .error "save text reaches confirmation sprites"
.endif

.org 0x80083094
    nop
    nop
.org 0x8008306C
    j       qol_o_setup
    nop
.org 0x800836E8
    j       qol_o_step
    nop
.org 0x80083774
    j       0x800837D0
    nop
.org 0x80083B60
    j       qol_o_cursor
    nop
.org 0x800840CC
    nop                         ; no card-choice cursor update
.org 0x80084140
    j       qol_o_rebuild
    nop
.org 0x80084CE4
    j       qol_o_screen
    nop

;; OpenMessageOpen (0x800861D0) draws each message on the 4bpp page 0x1D
;; (VRAM word x=832, y=256): upload rect (0x340 + j*4, 0x100 + i*16) and
;; sprite v = i*16. That is the top-left of the panel's two 8bpp halves
;; (832/912, y 256..447), so every title message - "Loading data" while a
;; card is read included - erased the panel strips underneath it. Move the
;; scratch to y=448, the first row below the panel, still clear of ADVCMD0's
;; frame at x=896. The sprite v follows (page y base 256 + 0xC0).
.org 0x800862D8
    addiu   v0, v1, 0x1C0
.org 0x800863F4
    addiu   a0, v1, 0xC0
.org SUBS_OBLOB_END
    .align 4
qol_o_list:
    .fill QOL_LIST_ROW * QOL_ROWS, 0
qol_o_kind:
    .fill QOL_ROWS, 0
qol_o_card:
    .byte 0, 0
    .align 4
qol_o_frame:
    .word 0
;; Each text sprite: relative x/y, width, u/v. Labels are atlas strips.
qol_o_cells:
    .byte 0,0,8,144,72, 8,0,8,144,72, 16,0,8,144,72, 24,0,8,144,72
    .byte 32,0,8,144,72, 40,0,8,144,72, 48,0,8,144,72, 56,0,8,144,72
    .byte QOL_X_LV,12,16,QOL_U_LV,QOL_V_LV
    .byte QOL_X_LEVEL,12,8,144,72, QOL_X_LEVEL+8,12,8,144,72
    .byte QOL_X_TIME,12,32,QOL_U_TIME,QOL_V_TIME
    .byte QOL_X_CLOCK,12,8,144,72, QOL_X_CLOCK+8,12,8,144,72
    .byte QOL_X_CLOCK+16,12,8,136,72
    .byte QOL_X_CLOCK+24,12,8,144,72, QOL_X_CLOCK+32,12,8,144,72
    .align 4
    .include "../../build/qol_save_uploads.asm"
qol_o_rect_clut:
    .halfword 288,480,32,1
qol_o_rect_grey:
    .halfword 320,480,16,1

qol_o_setup:
    la      t0, qol_o_frame
    sw      fp, 0(t0)
    ;; The entry hook replaces this retail call as well as card selection.
    ;; Initialize the badge before preserving its slots in qol_o_screen.
    lw      a0, 0x48(fp)
    jal     0x800849C0          ; OpenLoadMenuSprites
    nop
    lw      a0, 0x48(fp)
    jal     qol_o_build
    nop
    j       0x800830B8
    nop

qol_o_upload:
    addiu   sp, sp, -0x20
    sw      ra, 0x1C(sp)
    sw      s0, 0x18(sp)
    sw      s1, 0x14(sp)
    la      s0, qol_save_uploads
    ori     s1, zero, 32
qol_o_upload_strip:
    move    a0, s0
    lw      a1, 8(s0)
    jal     0x8008AA5C
    nop
    addiu   s0, s0, 12
    addiu   s1, s1, -1
    bnez    s1, qol_o_upload_strip
    nop
    la      a0, qol_o_rect_clut
    la      a1, qol_save_panel_clut
    jal     0x8008AA5C
    nop
    la      a0, qol_o_rect_grey
    la      a1, qol_save_grey_clut
    jal     0x8008AA5C
    nop
    jal     0x8008A834          ; DrawSync(0)
    move    a0, zero
    lw      ra, 0x1C(sp)
    lw      s0, 0x18(sp)
    lw      s1, 0x14(sp)
    nop
    jr      ra
    addiu   sp, sp, 0x20

qol_o_rebuild:
    addiu   sp, sp, -0x18
    sw      ra, 0x14(sp)
    jal     qol_o_build
    nop
    lw      ra, 0x14(sp)
    nop
    jr      ra
    addiu   sp, sp, 0x18

;; Scan both physical cards using the driver's normal cadence. A nested
;; error prompt may own fp; writes target the saved OpenLoadMenu frame.
qol_o_build:
    addiu   sp, sp, -0x30
    sw      ra, 0x2C(sp)
    sw      s0, 0x28(sp)
    sw      s1, 0x24(sp)
    sw      s2, 0x20(sp)
    sw      s3, 0x1C(sp)
    move    s0, a0
    la      t0, qol_o_kind
    ori     t1, zero, QOL_ROWS
qol_o_clear:
    sb      zero, 0(t0)
    addiu   t0, t0, 1
    addiu   t1, t1, -1
    bnez    t1, qol_o_clear
    nop
    move    s1, zero
qol_o_scan_card:
    jal     QOL_O_VSYNC
    ori     a0, zero, 30
    jal     QOL_O_CARDLOAD
    move    a0, s1
    la      t0, qol_o_card
    addu    t0, t0, s1
    sb      zero, 0(t0)
    bnez    v0, qol_o_scan_next_card
    nop
    ori     t1, zero, 1
    sb      t1, 0(t0)
    jal     QOL_O_VSYNC
    move    a0, zero
    la      a2, qol_o_list
    ori     t0, zero, QOL_LIST_ROW * QOL_ROWS_PER_CARD
    multu   s1, t0
    nop
    nop
    mflo    t0
    addu    a2, a2, t0
    move    a0, s1
    jal     QOL_O_CARDSCAN
    move    a1, s0
    move    s2, v0
    move    s3, zero
qol_o_scan_slot:
    bltz    s2, qol_o_scan_next_card
    nop
    srlv    t0, s2, s3
    andi    t1, t0, 1
    beqz    t1, qol_o_scan_next_slot
    andi    t0, t0, 0x100
    bnez    t0, qol_o_scan_next_slot
    nop
    ori     t0, zero, QOL_ROWS_PER_CARD
    multu   s1, t0
    nop
    nop
    mflo    t0
    addu    t0, t0, s3
    la      t1, qol_o_kind
    addu    t1, t1, t0
    ori     t0, zero, 1
    sb      t0, 0(t1)
qol_o_scan_next_slot:
    addiu   s3, s3, 1
    sltiu   t0, s3, QOL_ROWS_PER_CARD
    bnez    t0, qol_o_scan_slot
    nop
qol_o_scan_next_card:
    addiu   s1, s1, 1
    sltiu   t0, s1, 2
    bnez    t0, qol_o_scan_card
    nop
    move    s1, zero
    ori     s2, zero, QOL_ROWS
    move    s3, zero
qol_o_newest:
    la      t0, qol_o_kind
    addu    t0, t0, s1
    lbu     t0, 0(t0)
    nop
    beqz    t0, qol_o_newest_next
    nop
    ori     t0, zero, QOL_LIST_ROW
    multu   s1, t0
    nop
    nop
    mflo    t0
    la      t1, qol_o_list
    addu    t0, t0, t1
    lbu     t1, 8(t0)
    nop
    addiu   t1, t1, -1
    sltiu   t1, t1, 99
    bnez    t1, qol_o_summary_valid
    nop
    la      t0, qol_o_kind
    addu    t0, t0, s1
    sb      zero, 0(t0)            ; not displayable or eligible for newest selection
    b       qol_o_newest_next
    nop
qol_o_summary_valid:
    lhu     t1, QOL_SUM_SERIAL(t0)
    ori     t2, zero, 0xFFFF
    bne     t1, t2, qol_o_serial_valid
    nop
    move    t1, zero               ; unset serial follows the same rule as legacy zero
qol_o_serial_valid:
    ori     t2, zero, QOL_ROWS
    beq     s2, t2, qol_o_choose
    nop
    sltu    t2, s3, t1
    beqz    t2, qol_o_newest_next
    nop
qol_o_choose:
    move    s3, t1
    move    s2, s1
qol_o_newest_next:
    addiu   s1, s1, 1
    sltiu   t0, s1, QOL_ROWS
    bnez    t0, qol_o_newest
    nop
    sltiu   t0, s2, QOL_ROWS
    bnez    t0, qol_o_selected
    nop
    move    s2, zero
qol_o_selected:
    ori     t0, zero, QOL_ROWS_PER_CARD
    divu    s2, t0
    nop
    nop
    mflo    t0
    mfhi    t1
    la      t2, qol_o_frame
    lw      t2, 0(t2)
    nop
    sw      t0, 0x1C(t2)
    sw      t1, 0x24(t2)
    sw      zero, 0x14(gp)
    sw      zero, 0x18(gp)
    jal     qol_o_screen
    nop
    la      t2, qol_o_frame
    lw      t2, 0(t2)
    la      t0, qol_o_card
    lbu     t1, 0(t0)
    lbu     t3, 1(t0)
    ori     t1, t1, 0x80
    ori     t3, t3, 0x80
    sw      t1, 0x38(t2)
    sw      t3, 0x3C(t2)
    la      t0, QOL_O_MENU_STATE
    ori     t1, zero, 1
    sb      t1, 0(t0)
    addiu   t0, zero, -1
    sw      t0, 4(gp)
    sw      zero, 0xC(gp)
    lw      ra, 0x2C(sp)
    lw      s0, 0x28(sp)
    lw      s1, 0x24(sp)
    lw      s2, 0x20(sp)
    lw      s3, 0x1C(sp)
    nop
    jr      ra
    addiu   sp, sp, 0x30

qol_o_step:
    lw      v1, 0xC(gp)
    nop
    andi    t0, v1, 0x8000
    bnez    t0, qol_o_step_left
    nop
    andi    t0, v1, 0x2000
    beqz    t0, qol_o_step_retail
    ori     t1, zero, 1
    b       qol_o_step_column
    nop
qol_o_step_left:
    move    t1, zero
qol_o_step_column:
    sw      t1, 0x1C(fp)
    jal     QOL_O_SEQ
    move    a0, zero
    j       0x80083B1C
    nop
qol_o_step_retail:
    j       0x800836F0
    nop

qol_o_spr:
    sll     t0, s4, 3
    addu    t0, t0, s4
    sll     t0, t0, 2
    la      s5, QOL_O_GSPRITES
    addu    s5, s5, t0
    jr      ra
    nop

qol_o_putcursor:
    la      t2, qol_o_frame
    lw      t2, 0(t2)
    nop
    lw      t0, 0x1C(t2)
    lw      t1, 0x24(t2)
    sll     t2, t0, 7
    sll     t0, t0, 5
    addu    t0, t0, t2
    addiu   t0, t0, QOL_CURSOR_X
    sll     t2, t1, 4
    sll     t1, t1, 3
    addu    t1, t1, t2
    addiu   t1, t1, QOL_ROW_Y
    la      t2, QOL_O_GSPRITES + SP_CURSOR * 36
    sh      t0, 4(t2)
    jr      ra
    sh      t1, 6(t2)
qol_o_cursor:
    jal     qol_o_putcursor
    nop
    j       0x80084078
    nop

;; Two numeric sprites. Level and hours retain the retail blank tens;
;; minutes retain their leading zero. a1=first sprite, a3=pad flag.
qol_o_num:
    addiu   sp, sp, -0x20
    sw      ra, 0x1C(sp)
    sw      s4, 0x18(sp)
    sw      s5, 0x14(sp)
    ori     t0, zero, 10
    divu    a0, t0
    nop
    nop
    mflo    t1
    mfhi    t2
    move    s4, a1
    jal     qol_o_spr
    nop
    or      t3, t1, a3
    sll     t1, t1, 3
    addiu   t1, t1, 0x30
    ori     t0, zero, 0x48
    bnez    t3, qol_o_num_tens
    nop
    move    t1, zero
    move    t0, zero
qol_o_num_tens:
    sb      t1, 14(s5)
    sb      t0, 15(s5)
    addiu   s4, s4, 1
    jal     qol_o_spr
    nop
    sll     t2, t2, 3
    addiu   t2, t2, 0x30
    ori     t0, zero, 0x48
    sb      t2, 14(s5)
    sb      t0, 15(s5)
    lw      ra, 0x1C(sp)
    lw      s4, 0x18(sp)
    lw      s5, 0x14(sp)
    nop
    jr      ra
    addiu   sp, sp, 0x20

qol_o_screen:
    addiu   sp, sp, -0x50
    sw      ra, 0x4C(sp)
    sw      s0, 0x48(sp)
    sw      s1, 0x44(sp)
    sw      s2, 0x40(sp)
    sw      s3, 0x3C(sp)
    sw      s4, 0x38(sp)
    sw      s5, 0x34(sp)
    sw      s6, 0x30(sp)
    sw      s7, 0x2C(sp)
    ;; Card/status glyph uploads share the old panel scratch. Restore the
    ;; panel after scanning, including every rebuild following an error.
    jal     qol_o_upload
    nop
    la      t0, QOL_O_GSPRITES + 10 * 36
    ori     t1, zero, 8
    sh      t1, 4(t0)
    ori     t1, zero, 16
    sh      t1, 6(t0)
    sh      t1, 40(t0)         ; sphere x=16
    ori     t1, zero, 8
    sh      t1, 42(t0)         ; sphere y=8
    ;; Preserve LOAD's sphere and lettering, unlike the old blanket clear.
    la      t0, QOL_O_GFLAGS + 12 * 4
    ori     t1, zero, 269 - 12
qol_o_clear_sprites:
    sw      zero, 0(t0)
    addiu   t0, t0, 4
    addiu   t1, t1, -1
    bnez    t1, qol_o_clear_sprites
    nop
    move    s0, zero
qol_o_panel:
    sll     t0, s0, 5          ; second half begins 32 texels into page 14
    sw      t0, 16(sp)
    sw      zero, 20(sp)
    ori     t0, zero, 288
    sw      t0, 24(sp)
    ori     t0, zero, 480
    sw      t0, 28(sp)
    addiu   s4, s0, 12
    move    a0, s4
    ori     a1, zero, QOL_COL_W
    ori     a2, zero, QOL_PANEL_H
    addiu   a3, s0, 0x9D       ; 8bpp, VRAM x=832/912, y=256
    jal     QOL_O_SPRITEINIT
    nop
    jal     qol_o_spr
    nop
    ori     t0, zero, QOL_COL_W
    multu   s0, t0
    nop
    nop
    mflo    t0
    sh      t0, 4(s5)
    ori     t0, zero, QOL_PANEL_Y
    sh      t0, 6(s5)
    ;; GsSortFastSprite takes texture depth from attribute bits 24..25,
    ;; NOT from tpage bits 7..8 (it masks tpage down to 0x1f).
    lui     t0, 0x0100
    sw      t0, 0(s5)
    sll     t0, s4, 2
    la      t1, QOL_O_GFLAGS
    addu    t1, t1, t0
    ori     t0, zero, 0x86      ; behind list and retail confirmation backing
    sw      t0, 0(t1)
    addiu   s0, s0, 1
    sltiu   t0, s0, 2
    bnez    t0, qol_o_panel
    nop
    ;; Retail red cursor, below text but above the common panel.
    sw      zero, 16(sp)
    ori     t0, zero, 0xD8
    sw      t0, 20(sp)
    ori     t0, zero, 256
    sw      t0, 24(sp)
    ori     t0, zero, 480
    sw      t0, 28(sp)
    ori     a0, zero, SP_CURSOR
    ori     a1, zero, QOL_ROW_W
    ori     a2, zero, 24
    jal     QOL_O_SPRITEINIT
    ori     a3, zero, 0x18
    la      t0, QOL_O_GSPRITES + SP_CURSOR * 36
    lui     t1, 0x4000
    sw      t1, 0(t0)
    la      t0, QOL_O_GFLAGS + SP_CURSOR * 4
    ori     t1, zero, 0x85
    sw      t1, 0(t0)
    jal     qol_o_putcursor
    nop
    move    s3, zero
qol_o_row:
    ori     t0, zero, QOL_ROWS_PER_CARD
    divu    s3, t0
    nop
    nop
    mflo    t0
    mfhi    t1
    sll     t2, t0, 7
    sll     t0, t0, 5
    addu    s0, t0, t2
    addiu   s0, s0, QOL_TEXT_X
    sll     t2, t1, 4
    sll     t1, t1, 3
    addu    s1, t1, t2
    addiu   s1, s1, QOL_ROW_Y
    la      s2, qol_o_cells
    move    s6, zero
    la      t0, qol_o_kind
    addu    t0, t0, s3
    lbu     s7, 0(t0)
    ori     t0, zero, QOL_C_ALL
    multu   s3, t0
    nop
    nop
    mflo    s4
    addiu   s4, s4, SP_CELL
qol_o_cell:
    lbu     t0, 3(s2)
    lbu     t1, 4(s2)
    sw      t0, 16(sp)
    sw      t1, 20(sp)
    sltiu   t0, s6, QOL_C_NAME
    and     t0, t0, s7
    beqz    t0, qol_o_cell_init
    nop
    sw      zero, 16(sp)
    sw      zero, 20(sp)
qol_o_cell_init:
    ori     t0, zero, 256
    sw      t0, 24(sp)
    ori     t0, zero, 480
    sw      t0, 28(sp)
    move    a0, s4
    lbu     a1, 2(s2)
    ori     a2, zero, 12
    jal     QOL_O_SPRITEINIT
    ori     a3, zero, 0x18
    jal     qol_o_spr
    nop
    lbu     t0, 0(s2)
    lbu     t1, 1(s2)
    addu    t0, t0, s0
    addu    t1, t1, s1
    sh      t0, 4(s5)
    sh      t1, 6(s5)
    sw      zero, 0(s5)
    bnez    s7, qol_o_cell_color_done
    nop
    ori     t0, zero, 8            ; Lv label, TIME label, colon stay colored
    beq     s6, t0, qol_o_cell_color_done
    ori     t0, zero, 11
    beq     s6, t0, qol_o_cell_color_done
    ori     t0, zero, 14
    beq     s6, t0, qol_o_cell_color_done
    ori     t0, zero, 320
    sh      t0, 16(s5)             ; dash placeholders use ADV's grey ink
qol_o_cell_color_done:
    sll     t0, s4, 2
    la      t1, QOL_O_GFLAGS
    addu    t1, t1, t0
    ori     t0, zero, 0x84
    sw      t0, 0(t1)
    addiu   s4, s4, 1
    addiu   s2, s2, 5
    addiu   s6, s6, 1
    sltiu   t0, s6, QOL_C_ALL
    bnez    t0, qol_o_cell
    nop
    beqz    s7, qol_o_next_row
    nop
    ori     t0, zero, QOL_LIST_ROW
    multu   s3, t0
    nop
    nop
    mflo    t0
    la      s7, qol_o_list
    addu    s7, s7, t0
    addiu   s4, s4, -QOL_C_ALL
    move    s6, zero
qol_o_name:
    addu    t0, s7, s6
    lbu     t1, 0(t0)
    ori     t0, zero, 0xFF
    beq     t1, t0, qol_o_numbers
    ori     t0, zero, 31
    divu    t1, t0
    nop
    nop
    mfhi    t1
    mflo    t2
    sll     t1, t1, 3
    sll     t0, t2, 3
    sll     t2, t2, 2
    addu    t2, t2, t0
    jal     qol_o_spr
    nop
    sb      t1, 14(s5)
    sb      t2, 15(s5)
    addiu   s4, s4, 1
    addiu   s6, s6, 1
    sltiu   t0, s6, QOL_C_NAME
    bnez    t0, qol_o_name
    nop
qol_o_numbers:
    ori     t0, zero, QOL_C_ALL
    multu   s3, t0
    nop
    nop
    mflo    s2
    addiu   s2, s2, SP_CELL
    lbu     a0, 8(s7)
    addiu   a1, s2, 9
    jal     qol_o_num
    move    a3, zero
    lbu     a0, 9(s7)
    addiu   a1, s2, QOL_C_CLOCK0
    jal     qol_o_num
    move    a3, zero
    lbu     a0, 10(s7)
    addiu   a1, s2, QOL_C_CLOCK0 + 3
    jal     qol_o_num
    ori     a3, zero, 1
qol_o_next_row:
    addiu   s3, s3, 1
    sltiu   t0, s3, QOL_ROWS
    bnez    t0, qol_o_row
    nop
    lw      ra, 0x4C(sp)
    lw      s0, 0x48(sp)
    lw      s1, 0x44(sp)
    lw      s2, 0x40(sp)
    lw      s3, 0x3C(sp)
    lw      s4, 0x38(sp)
    lw      s5, 0x34(sp)
    lw      s6, 0x30(sp)
    lw      s7, 0x2C(sp)
    nop
    jr      ra
    addiu   sp, sp, 0x50
qol_o_end:
.if qol_o_end > 0x80180000
    .error "save-list code/state overlaps OPEN.BIN"
.endif
