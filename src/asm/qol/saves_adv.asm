;; =============================================================
;; Optional save UI (--qol=saves): ADV.BIN.
;;
;; * fourteen slots in two columns of seven - rows 0-6 live on memory
;;   card 1, rows 7-13 on card 2 (a formatted card holds seven of this
;;   game's saves at two blocks each, so the second column is where
;;   the extra room comes from on emulators with two cards);
;; * no memory card selection screen; each column selects its own card;
;; * shared two-line fields with OPEN: name / Lv, level, TIME, hh:mm.
;;
;; Placement: code occupies SaveSlotsDraw, SaveScanSlots, SavePortStep
;; and SavePortOpen; the patch bypasses their game bodies. Summary tables
;; borrow battle-only scratch while ADV is active; code stays in retired
;; ADV functions. Neither CD RAM nor the live packet area is touched.
;;
;; Row layout: 16 cells / 128 px. Name on line 1; line 2 uses the
;; shared offsets in saves.inc (Lv, level, TIME, hh:mm). Serial
;; numbers are metadata for newest-save selection, not visible text.
;; =============================================================
.include "qol/saves.inc"

;; Same badge center in both menus: sphere (16,8), label (8,16).
.org 0x8009A6C8
    ori     a3, zero, 32
.org 0x8009A6E8
    ori     a3, zero, 8

.definelabel QOL_MENUSTEP, 0x80067DF4              ; MenuStepCursor(list)

;; =============================================================
;; patches in the original code
;; =============================================================

;; FacilityOpen initializes Agastya BEFORE its shared fade-in. Prepare the
;; whole list there, not on the first dispatcher tick after the fade.
.org 0x8009A370
    jal     qol_prepare_menu

;; Initial card warnings/format choices may now run while the facility is
;; black. Make those interactive prompts visible before waiting for input.
.org 0x8009AB20
    jal     qol_initial_message
.org 0x8009ACAC
    jal     qol_initial_message
.org 0x8009ACC4
    jal     qol_initial_format

;; Agastya is a save facility, not a SAVE / GAME END selector. Keep
;; the badge initialization, then enter the normal card-check/scan path
;; in this same dispatcher tick, without consuming an Accept button.
.org 0x8009A720
    j       0x8009A820             ; SaveScreenOpen's normal epilogue
    nop
.org 0x8009A5D8
    j       0x8009A5E0             ; newly initialized step 1 runs immediately
    nop
.org 0x8009A860
    j       0x8009AAD0             ; after SaveTopStep's callee-save prologue
    nop

;; There is no parent selector to return to. Cancel from the list and
;; failed initial card/format checks close the facility (STEP_DONE=FF).
.org 0x8009B4FC
    j       0x8009B54C
    ori     v0, zero, 0xFF
.org 0x8009AB28
    j       0x8009AD20             ; both cards absent: show the error once
    ori     v0, zero, 0xFF
.org 0x8009ACB4
    j       0x8009AD20             ; card error/removal or declined formatting
    ori     v0, zero, 0xFF

;; Retired SAVE / GAME END sprite setup supplies bounded adapter space.
.org QOL_ADV_RETIRED_SELECTOR_START
    .area QOL_ADV_RETIRED_SELECTOR_END - QOL_ADV_RETIRED_SELECTOR_START
qol_prepare_menu:
    addiu   sp, sp, -0x18
    sw      ra, 0x14(sp)
    jal     0x8009A580             ; initialize + scan + list before the fade
    nop
    ;; Slot blackout and BG-layer brightness are independent. The blocking
    ;; fade terminates from BG layer 0, NOT from the slot fade level. Reset
    ;; both after preparation or a bright inherited BG ends it in one frame.
    ;; An initial warning/format prompt has already faded up: do not black
    ;; out an interactive screen a second time after it returns.
    la      t0, 0x800DC00C
    lbu     t0, 0(t0)
    nop
    bnez    t0, qol_prepare_done
    nop
    move    a0, zero
    jal     0x8008BDBC             ; FadeSpritesStep(0, 0): six BG RGB triplets
    move    a1, zero
    jal     qol_card_ready         ; blackout + hidden frames after all card activity
    nop
qol_prepare_done:
    lw      ra, 0x14(sp)
    nop                             ; return to the unchanged retail fade setup
    jr      ra
    addiu   sp, sp, 0x18

qol_initial_message:
    la      t0, 0x8009C1A8         ; SaveMessage(n, keep)
    b       qol_initial_visible
    nop
qol_initial_format:
    la      t0, 0x8009B9D4         ; SaveOfferFormat(keep)
qol_initial_visible:
    addiu   sp, sp, -0x28
    sw      ra, 0x24(sp)
    sw      t0, 0x20(sp)
    sw      a0, 0x1C(sp)
    sw      a1, 0x18(sp)
    la      t0, 0x800DC00C
    lbu     t0, 0(t0)
    nop
    bnez    t0, qol_initial_fade
    nop
    move    a0, zero
    jal     0x8008BDBC
    move    a1, zero
    jal     qol_card_ready
    nop
qol_initial_fade:
    ori     a0, zero, 4              ; same step as the retail facility fade
    jal     0x8008BCAC             ; FadeUpBlocking, only on initial prompts
    ori     a1, zero, 0x80
    lw      t9, 0x20(sp)
    lw      a0, 0x1C(sp)
    lw      a1, 0x18(sp)
    lw      ra, 0x24(sp)
    addiu   sp, sp, 0x28
    jr      t9
    nop
;; qol_step_cursor's frame is live. A card came or went: let the poll's
;; own _card_info finish (the title's rebuild waits the same 30 frames),
;; bring both ports up, then rescan and redraw the list.
qol_poll_change:
    beqz    v0, qol_poll_ret
    nop
    jal     QOL_VSYNC
    ori     a0, zero, 30
    jal     QOL_CARD_LOAD
    move    a0, zero
    jal     QOL_CARD_LOAD
    ori     a0, zero, 1
    j       qol_poll_rescan
    nop
    .endarea

;; SaveTopStep picks the first card that answered and goes straight to
;; the slot list, which merges both cards.
.org 0x8009AB58
    j       qol_skip_port
    nop

;; the slot cursor spans both columns
.org 0x8009AB40
    ori     a3, zero, 13            ; MenuListInit(&g_menu->unk2C0, 0, 0, 13, 0x1E)

;; SaveSlotStep: our cursor step (Up/Down in the column, Left/Right
;; across it) and the cursor sprite's place on the two-column grid
.org 0x8009B080
    jal     qol_step_cursor
.org 0x8009B0B4
    jal     qol_cursor_pos

;; the row's kind comes from our 14-entry table (the game's holds 7)
.org 0x8009B124
    la at, qol_kinds
.org 0x8009B160
    la at, qol_kinds
.org 0x8009B19C
    la at, qol_kinds
.org 0x8009B480
    la at, qol_kinds
.org 0x8009B608
    la at, qol_kinds

;; Keep the retail argument loads and their load delay. Resident adapters
;; split the combined row into the physical card and its local slot.
.org 0x8009B658
    jal     qol_delete_row
.org 0x8009B748
    jal     qol_save_row
.org 0x8009BDB4
    jal     qol_slots_ready
.org 0x8009BD34
    j       0x8009BDB4             ; no SLOT label or backing plate
    nop
.org 0x8009BCE8
    la      a0, qol_cursor_def

;; Unreachable card-choice branch space; keep the retail slot initializer,
;; but place the cursor on the combined grid before the very first frame.
.org QOL_ADV_RETIRED_TOP_START
    .area QOL_ADV_RETIRED_TOP_END - QOL_ADV_RETIRED_TOP_START
qol_slots_ready:
    addiu   sp, sp, -0x18
    sw      ra, 0x14(sp)
    jal     0x800ABB94          ; FacilitySlotsClear
    nop
    jal     qol_cursor_pos
    nop
    lw      ra, 0x14(sp)
    nop
    jr      ra
    addiu   sp, sp, 0x18
qol_stamp:
    addiu   sp, sp, -0x10
    sw      t0, 0(sp)
    sw      t1, 4(sp)
    la      t0, qol_serial
    lw      t1, 0(t0)
    ori     t0, zero, QOL_SERIAL_MAX
    beq     t1, t0, qol_stamp_number
    nop
    addiu   t1, t1, 1
qol_stamp_number:
    la      t0, qol_serial
    sw      t1, 0(t0)
    la      t0, QOL_SAVE_SUM
    sh      t1, 0(t0)
    lw      t0, 0(sp)
    lw      t1, 4(sp)
    addiu   sp, sp, 0x10
    lbu     v0, 0x12(fp)
    ori     v1, zero, 2
    j       0x80014284
    nop
qol_poll_ret:
    lw      ra, 0x14(sp)
    nop
    jr      ra
    addiu   sp, sp, 0x18
    .endarea

;; SaveSlotsOpen: a 40-cell window, and both layers get the width the
;; two columns need (a GsBG's x, y, w, h are halfwords at +4..+10)
.org 0x8009BCD0
    ori     a1, zero, 40 ; TileMapDrawWindow(g_tilemap0, 40, 0x10, MAP_W)
.org 0x8009BC8C
    j       qol_layers              ; after MenuSetLayers(0x21)
    nop

;; =============================================================
;; the new code, in the functions the patch makes unreachable
;; =============================================================

;; --- SavePortStep: what the patch jumps to -----------
.org QOL_ADV_RETIRED_PORTSTEP_START
    .area QOL_ADV_RETIRED_PORTSTEP_END - QOL_ADV_RETIRED_PORTSTEP_START

;; SaveTopStep continues at 0x8009ABF4 (the scan) with the port list
;; replaced: the cursors our grid needs, and the channel the card
;; calls use - the first card that answered.
qol_skip_port:
    addiu   sp, sp, -0x20
    sw      ra, 0x1C(sp)
    la      a0, qol_row_list        ; the row cursor: 0..6, Up/Down, wraps
    move    a1, zero
    move    a2, zero
    ori     a3, zero, 6
    ori     t0, zero, 0x16          ; wrap | Down is next | click
    sw      t0, 0x10(sp)
    jal     QOL_MENULISTINIT
    nop
    la      a0, qol_col_list        ; the column cursor: 0..1, Left/Right
    move    a1, zero
    move    a2, zero
    ori     a3, zero, 1
    ori     t0, zero, 0x1A          ; wrap | Right is next | click
    sw      t0, 0x10(sp)
    jal     QOL_MENULISTINIT
    nop
    la t0, QOL_STATE_A    ; the first card that answered
    lh      t1, 0(t0)
    ori     t0, zero, 2             ; CARD_NONE
    beq     t1, t0, qol_skip_other
    nop
    move    t1, zero
    j       qol_skip_chan
    nop
qol_skip_other:
    ori     t1, zero, 1
qol_skip_chan:
    la t0, QOL_MENU       ; g_menu->unk2D0: lo = hi = cur = chan
    lw      t0, 0(t0)
    nop
    sw      t1, 0x2D0(t0)
    sw      t1, 0x2D4(t0)
    sw      t1, 0x2D8(t0)
    ori     t2, zero, QOL_ROWS_PER_CARD
    multu   t1, t2
    nop
    nop
    mflo    t2
    sw      t2, 0x2C0(t0)
    la      t0, qol_col_list
    sw      t1, 0(t0)
    lw      ra, 0x1C(sp)
    addiu   sp, sp, 0x20
    j       0x8009ABF4              ; SaveTopStep's scan
    nop

;; One MenuStepCursor per axis: the row moves Up/Down inside its
;; column, the column flips with Left/Right.  The game's own repeat
;; and click live in the two lists.
qol_step_cursor:
    addiu   sp, sp, -0x18
    sw      ra, 0x14(sp)
    la      a0, qol_row_list
    jal     QOL_MENUSTEP
    nop
    la      a0, qol_col_list
    jal     QOL_MENUSTEP
    nop
    la      t0, qol_col_list
    lw      t1, 0(t0)               ; column
    la      t0, qol_row_list
    lw      t2, 0(t0)               ; row
    ori     t3, zero, QOL_ROWS_PER_CARD
    multu   t1, t3
    nop
    nop
    mflo    t3
    addu    t3, t3, t2              ; the row index the game sees
    la t0, QOL_MENU
    lw      t0, 0(t0)
    nop
    sw      t3, 0x2C0(t0)           ; g_menu->unk2C0.cur
    sw      t1, 0x2D0(t0)           ; unk2D0.cur = lo = hi = the card
    sw      t1, 0x2D4(t0)
    sw      t1, 0x2D8(t0)
    ;; Retail only re-checked the card on confirm, after its card-choice
    ;; screen; without that screen the list would keep its first scan.
    ;; Poll both ports every frame like the title's load list does.
    ori     a0, zero, 0x81
    jal     QOL_CARD_POLL
    ori     a1, zero, 0x81
    j       qol_poll_change
    nop

qol_save_row:
    ori     t0, zero, QOL_ROWS_PER_CARD
    divu    a1, t0
    nop
    nop
    mfhi    a1
    mflo    a0
    j       QOL_CARD_SAVE
    nop
qol_delete_row:
    ori     t0, zero, QOL_ROWS_PER_CARD
    divu    a1, t0
    nop
    nop
    mfhi    a1
    mflo    a0
    j       QOL_CARD_DELETE
    nop
    .endarea

;; --- SaveScanSlots entry; spare space for layer/cursor helpers --
.org QOL_ADV_RETIRED_SCAN_START
    j       qol_adv_scan           ; every retail rescan enters here
    nop
    .area QOL_ADV_RETIRED_SCAN_END - QOL_ADV_RETIRED_SCAN_START - 8
;; SlotSetPos(4, 0x42, x, y) with the grid's x and y
qol_cursor_pos:
    la      t0, qol_col_list
    lw      t1, 0(t0)               ; column
    la      t0, qol_row_list
    lw      t2, 0(t0)               ; row
    ori     a0, zero, 4
    ori     a1, zero, 0x42
    sll     t3, t1, 7
    sll     t4, t1, 5
    addu    t3, t3, t4              ; column * 160
    addiu   a2, t3, QOL_CURSOR_X
    sll     t3, t2, 4
    sll     t4, t2, 3
    addu    t3, t3, t4              ; row * 24
    addiu   a3, t3, QOL_ROW_Y
    j       QOL_SLOTSETPOS
    nop
;; qol_layers: MenuSetLayers(0x21) put up the one-column layer sizes; both layers
;; take the width of the two columns.  The two instructions this hook
;; replaces load g_tilemap0 into a0.
qol_layers:
    la t0, QOL_BGLAYERS
    ori     t1, zero, 0
    sh      t1, 4(t0)      ; layer 0 .x
    ori     t1, zero, 320
    sh      t1, 8(t0)      ; layer 0 .w
    ori     t1, zero, QOL_PANEL_Y
    sh      t1, 6(t0)      ; layer 0 .y
    ori     t1, zero, QOL_PANEL_H
    sh      t1, 10(t0)     ; layer 0 .h; visible bottom border is y=232
    ori     t1, zero, QOL_TEXT_X
    sh      t1, 0x28(t0)     ; layer 1 .x
    ori     t1, zero, 308
    sh      t1, 0x2C(t0)     ; layer 1 .w
    ori     t1, zero, QOL_ROW_Y
    sh      t1, 0x2A(t0)     ; layer 1 .y (GsBG stride is 36)
    ori     t1, zero, QOL_ROWS_PER_CARD * 24
    sh      t1, 0x2E(t0)     ; layer 1 .h
    lui     a0, 0x800e
    ori     a0, a0, 0xe180          ; the displaced g_tilemap0 load
    j       0x8009BC94
    nop

;; MenuListInit(list, cur, lo, hi, repeat): cur/lo/hi/repeat.  The row
;; list runs 0..6 down a column and the column list 0..1 across.
qol_row_list:
    .word   0, 0, 6, 0x1E
qol_col_list:
    .word   0, 0, 1, 0x1E

;; Finish card preparation before the visible ramp. DuckStation continues
;; its automatic card fast-forward for 30 frames after the last access.
;; Render those frames black; on hardware this is a fixed half-second phase.
qol_card_ready:
    addiu   sp, sp, -0x18
    sw      ra, 0x14(sp)
    jal     0x80066034             ; FadeBlackout: sprite RGB + slot fade level
    nop
    lw      ra, 0x14(sp)
    ori     a0, zero, QOL_CARD_READY_FRAMES
    j       0x8008BC04             ; RenderFrames: no menu dispatch or card reads
    addiu   sp, sp, 0x18
qol_poll_rescan:
    jal     qol_adv_scan
    nop
    lw      ra, 0x14(sp)
    j       qol_adv_draw           ; SaveSlotsDraw returns to SaveSlotStep
    addiu   sp, sp, 0x18
    .endarea

;; --- SaveSlotsDraw: the fourteen rows ----------------
.org QOL_ADV_RETIRED_DRAW_START
    .area QOL_ADV_RETIRED_DRAW_END - QOL_ADV_RETIRED_DRAW_START
qol_adv_draw:
    addiu   sp, sp, -0x40
    sw      ra, 0x3C(sp)
    sw      s0, 0x38(sp)            ; row index 0..13
    sw      s1, 0x34(sp)            ; line 1 of the row (short * into g_tilemap1)
    sw      s2, 0x30(sp)            ; line 2 of the row
    sw      s3, 0x2C(sp)            ; the row's summary
    sw      s4, 0x28(sp)            ; the row's kind
    move    s0, zero
qol_draw_row:
    slti    t0, s0, QOL_ROWS_PER_CARD
    beqz    t0, qol_draw_right
    ori     t1, zero, 0             ; (delay) column 0
    move    t2, s0
    j       qol_draw_cells
    nop
qol_draw_right:
    ori     t1, zero, 1
    addiu   t2, s0, -QOL_ROWS_PER_CARD
qol_draw_cells:
    sll     t0, t2, 7               ; row * 160 + column * 40, into the text layer
    sll     t3, t2, 5
    addu    t0, t0, t3
    sll     t3, t1, 5
    sll     t4, t1, 3
    addu    t3, t3, t4
    addu    t0, t0, t3
    la      t3, QOL_TM1
    addu    s1, t3, t0
    addiu   s2, s1, 80
    ;; A redraw must erase old names and numbers, including FF tails.
    move    a0, s1
    move    a1, zero
    jal     qol_fill
    ori     a2, zero, QOL_TEXT_W / 8
    move    a0, s2
    move    a1, zero
    jal     qol_fill
    ori     a2, zero, QOL_TEXT_W / 8
    la      a0, QOL_STRRUN
    addiu   a1, s2, QOL_X_TIME / 4
    ori     a2, zero, QOL_CELL_TIME
    jal     qol_row
    ori     a3, zero, 4
    ;; The clear helpers clobber t0: derive the frame offset anew.
    la      t3, QOL_TM1
    subu    t0, s1, t3
    la      t3, QOL_TM0             ; the frame sits one row lower, one cell right
    addu    a0, t3, t0
    addiu   a0, a0, 82
    ori     a1, zero, 18
    ori     a2, zero, 2
    jal     QOL_DRAWBOX
    ori     a3, zero, 40            ; (delay) stride
    la      t0, qol_kinds
    sll     t1, s0, 1
    addu    t0, t0, t1
    lh      s4, 0(t0)
    ori     t1, zero, QOL_SAVE_EMPTY
    beq     s4, t1, qol_draw_empty
    nop
    la      t0, qol_valid
    addu    t0, t0, s0
    lbu     t0, 0(t0)
    nop
    beqz    t0, qol_draw_empty
    nop
    la      s3, qol_list
    ori     t0, zero, QOL_LIST_KIND
    multu   s4, t0
    nop
    nop
    mflo    t1
    addu    s3, s3, t1
    ori     t0, zero, QOL_LIST_ROW
    multu   s0, t0
    nop
    nop
    mflo    t1
    addu    s3, s3, t1
    ;; line 1: the name -- the same row the title's load list draws
    move    a0, s1                  ; name in cells 0-7
    ori     a1, zero, 0
    jal     qol_fill
    ori     a2, zero, 8             ; (delay)
    move    a0, s3
    move    a1, s1
    move    a2, zero
    jal     qol_row
    ori     a3, zero, 8             ; (delay)
    ;; line 2: dedicated Lv artwork, level, TIME artwork, hh:mm
    la      a0, QOL_STRRUN
    move    a1, s2
    ori     a2, zero, QOL_CELL_LV
    jal     qol_row
    ori     a3, zero, 2             ; (delay) cells 0-1
    lbu     a0, 0x8(s3)             ; the level
    move    a1, zero                ; suppress a leading level zero
    jal     qol_num
    addiu   a2, s2, QOL_X_LEVEL / 4 + 2
    lbu     a0, 0x9(s3)             ; hours
    move    a1, zero                ; suppress a leading hour zero
    jal     qol_num
    addiu   a2, s2, QOL_X_CLOCK / 4 + 2
    addiu   a0, s2, QOL_X_CLOCK / 4 + 4
    ori     a1, zero, QOL_CELL_COLON
    jal     qol_fill
    ori     a2, zero, 1             ; (delay) first colon
    lbu     a0, 0xA(s3)             ; minutes
    ori     a1, zero, 1             ; minutes retain their leading zero
    jal     qol_num
    addiu   a2, s2, QOL_X_CLOCK / 4 + 8
    j       qol_draw_labels
    nop
qol_draw_empty:
    move    a0, s1                  ; the name
    ori     a1, zero, QOL_CELL_DASH
    jal     qol_fill
    ori     a2, zero, 8
    la      a0, QOL_STRRUN          ; "Lv" keeps its label
    move    a1, s2
    ori     a2, zero, QOL_CELL_LV
    jal     qol_row
    ori     a3, zero, 2
    addiu   a0, s2, QOL_X_LEVEL / 4
    ori     a1, zero, QOL_CELL_DASH
    jal     qol_fill
    ori     a2, zero, 2
    addiu   a0, s2, QOL_X_CLOCK / 4
    ori     a1, zero, QOL_CELL_DASH
    jal     qol_fill
    ori     a2, zero, 2
    addiu   a0, s2, QOL_X_CLOCK / 4 + 4
    ori     a1, zero, QOL_CELL_COLON
    jal     qol_fill
    ori     a2, zero, 1
    addiu   a0, s2, QOL_X_CLOCK / 4 + 6
    ori     a1, zero, QOL_CELL_DASH
    jal     qol_fill
    ori     a2, zero, 2
    j       qol_draw_labels
    nop

;; qol_fill(dst=a0, value=a1, w=a2): a run of one row of cells
qol_fill:
    addiu   sp, sp, -0x20
    sw      ra, 0x1C(sp)
    ori     t0, zero, 40
    sw      t0, 0x10(sp)            ; the layer is 40 cells wide
    jal     QOL_FILLRECT
    ori     a3, zero, 1             ; (delay) one row
    lw      ra, 0x1C(sp)
    nop
    jr      ra
    addiu   sp, sp, 0x20

;; qol_row(src=a0, dst=a1, base=a2, count=a3): the row's cells, written
;; straight into the tilemap.  TileMapWriteRow is the VWF's dispatcher in
;; this build and TileMapWriteRowRev mirrors the row, so neither is used.
qol_row:
    addiu   sp, sp, -0x10
    sw      ra, 0xC(sp)
    move    t0, zero
qol_row_loop:
    addu    t1, a0, t0
    lbu     t2, 0(t1)
    ori     t4, zero, 0xFF
    beq     t2, t4, qol_row_done    ; TileMapWriteRow stops at FF
    nop
    addu    t2, t2, a2
    sll     t3, t0, 1
    addu    t1, a1, t3
    sh      t2, 0(t1)
    addiu   t0, t0, 1
    sltu    t1, t0, a3
    bnez    t1, qol_row_loop
    nop
qol_row_done:
    lw      ra, 0xC(sp)
    nop
    jr      ra
    addiu   sp, sp, 0x10

;; qol_num(value=a0, pad=a1, last_cell=a2): two cells, last a pointer.
qol_num:
    ;; Match retail: only minutes pad their leading zero.
    ori     t0, zero, 10
    divu    a0, t0
    nop
    nop
    mflo    t1
    mfhi    t2
    or      t3, t1, a1
    addiu   t1, t1, QOL_CELL_DIGIT
    bnez    t3, qol_num_tens
    nop
    move    t1, zero
qol_num_tens:
    addiu   t2, t2, QOL_CELL_DIGIT
    sh      t1, -2(a2)
    jr      ra
    sh      t2, 0(a2)

;; qol_draw_labels: the row is drawn; on to the next one
qol_draw_labels:
    addiu   s0, s0, 1
    slti    t0, s0, QOL_ROWS
    bnez    t0, qol_draw_row
    nop
    lw      ra, 0x3C(sp)
    lw      s0, 0x38(sp)
    lw      s1, 0x34(sp)
    lw      s2, 0x30(sp)
    lw      s3, 0x2C(sp)
    lw      s4, 0x28(sp)
    nop
    jr      ra
    addiu   sp, sp, 0x40
    .include "../../build/qol_save_cursor.asm"
    .endarea

;; --- SaveScanSlots: both cards, both kinds -----------
.org QOL_ADV_RETIRED_PORTOPEN_START
    .area QOL_ADV_RETIRED_PORTOPEN_END - QOL_ADV_RETIRED_PORTOPEN_START
qol_adv_scan:
    addiu   sp, sp, -0x38
    sw      ra, 0x34(sp)
    sw      s0, 0x30(sp)            ; chan
    sw      s1, 0x2C(sp)            ; kind
    sw      s2, 0x28(sp)            ; the scan's found bits
    sw      s3, 0x24(sp)            ; slot on the card
    la      v0, qol_kinds       ; every row starts empty ...
    ori     t0, zero, QOL_SAVE_EMPTY
    ori     t1, zero, QOL_ROWS
qol_scan_clear:
    sh      t0, 0(v0)
    la      t2, qol_valid + QOL_ROWS
    subu    t2, t2, t1
    sb      zero, 0(t2)
    addiu   v0, v0, 2
    addiu   t1, t1, -1
    bnez    t1, qol_scan_clear
    nop
    la      t0, qol_serial          ; ... and no save number is known yet
    sw      zero, 0(t0)
    move    s0, zero
qol_scan_chan:
    move    s1, zero
qol_scan_kind:
    ;; the vanilla SaveScanSlots syncs before every scan and never
    ;; calls CardLoad - touching the card outside that cadence makes
    ;; the BIOS call trap with a reserved instruction
    move    a0, zero
    jal     QOL_VSYNC
    nop
    la      a2, qol_list            ; CardScanSaves(chan, kind, &list[kind][chan*7])
    ori     t0, zero, QOL_LIST_KIND
    multu   s1, t0
    nop
    nop
    mflo    t1
    addu    a2, a2, t1
    ori     t0, zero, QOL_LIST_ROW * QOL_ROWS_PER_CARD
    multu   s0, t0
    nop
    nop
    mflo    t1
    addu    a2, a2, t1
    move    a0, s0
    move    a1, s1
    jal     QOL_CARD_SCAN
    nop
    move    s2, v0
    move    s3, zero
qol_scan_slot:
    bltz    s2, qol_scan_next       ; a card that failed to scan keeps empty rows
    move    v0, zero                ; (delay) nothing is present
    srlv    v0, s2, s3
    andi    v0, v0, 1               ; present = (found >> slot) & 1
    beqz    v0, qol_scan_next
    nop
    ori     t0, zero, QOL_ROWS_PER_CARD
    multu   s0, t0
    nop
    nop
    mflo    t1
    addu    t1, t1, s3              ; row = chan*7 + slot
    la      t2, qol_kinds
    sll     t3, t1, 1
    addu    t2, t2, t3
    lh      t3, 0(t2)
    ori     t4, zero, QOL_SAVE_EMPTY
    xor     t7, t3, t4
    bnez    t7, qol_scan_metadata   ; kind 0 wins display, both kinds supply orders
    nop
    sh      s1, 0(t2)
qol_scan_metadata:
    ;; A bad summary still occupies its file slot, but contributes neither
    ;; stale display bytes nor an arbitrary serial to newest-save ordering.
    addiu   t2, s3, 8
    srlv    t2, s2, t2
    andi    t2, t2, 1
    bnez    t2, qol_scan_next
    nop
    la      t2, qol_list            ; keep the highest save number
    ori     t0, zero, QOL_LIST_KIND
    multu   s1, t0
    nop
    nop
    mflo    t3
    addu    t2, t2, t3
    ori     t0, zero, QOL_LIST_ROW
    multu   t1, t0
    nop
    nop
    mflo    t3
    addu    t2, t2, t3
    ;; An erased header can pass retail's XOR checksum (127 FF bytes
    ;; XOR to FF). It must not supply either display fields or an order.
    lbu     t3, 8(t2)
    nop
    addiu   t3, t3, -1
    sltiu   t3, t3, 99             ; retail levels are 1..99
    beqz    t3, qol_scan_next
    nop
    la      t3, qol_valid
    bnez    t7, qol_scan_serial
    addu    t3, t3, t1
    ori     t4, zero, 1
    sb      t4, 0(t3)
qol_scan_serial:
    lhu     t3, QOL_SUM_SERIAL(t2)
    ori     t4, zero, 0xFFFF
    beq     t3, t4, qol_scan_next   ; legacy/erased serial is not the newest save
    nop
    la      t4, qol_serial
    lw      t5, 0(t4)
    nop
    sltu    t6, t5, t3
    beqz    t6, qol_scan_next
    nop
    sw      t3, 0(t4)
qol_scan_next:
    addiu   s3, s3, 1
    slti    v0, s3, QOL_ROWS_PER_CARD
    bnez    v0, qol_scan_slot
    nop
    addiu   s1, s1, 1
    slti    v0, s1, 2
    bnez    v0, qol_scan_kind
    nop
qol_scan_card_next:
    addiu   s0, s0, 1
    slti    v0, s0, 2
    bnez    v0, qol_scan_chan
    nop
    lw      ra, 0x34(sp)
    lw      s0, 0x30(sp)
    lw      s1, 0x2C(sp)
    lw      s2, 0x28(sp)
    lw      s3, 0x24(sp)
    jr      ra
    addiu   sp, sp, 0x38
    .endarea
