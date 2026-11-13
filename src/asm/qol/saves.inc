;; =============================================================
;; Shared addresses for the save / load QoL patch (qol/saves_*.asm).
;;
;; Every address is from this project's own binaries (SLPS-00500 first
;; release, ADV.BIN, EXE/OPEN.EXE); the reference decomp in references/
;; describes the same code at different addresses (a different pressing).
;; =============================================================

;; --- SLPS_005.00: the resident card code -------------------
.ifndef QOL_SAVES_INC
.definelabel QOL_SAVES_INC, 1
.definelabel QOL_CARD_POLL, 0x80013344          ; CardPollPorts(want0, want1) -> 1<<chan removed, 4<<chan new card
.definelabel QOL_CARD_LOAD, 0x800135C4          ; CardLoad(chan) -> 0 ready, 1 error, 2 no card, 4 unformatted
.definelabel QOL_CARD_SCAN, 0x800139A0          ; CardScanSaves(chan, kind, out) -> bits 0-6 present, 8-14 bad sum
.definelabel QOL_CARD_SAVE, 0x80013E2C          ; CardSave(chan, slot, kind)
.definelabel QOL_CARD_DELETE, 0x800144F4          ; CardDeleteFile(chan, slot, kind)
.definelabel QOL_CARD_CHECKFREE, 0x800137DC          ; CardCheckFree(chan) -> 0 if a 2-block file fits
.definelabel QOL_VSYNC, 0x80025C98

;; Save summaries use the battle decoder's bounded runtime scratch while
;; ADV is active; BTLP and ADV are mutually exclusive. The dialogue ring
;; starts AFTER this buffer and is not borrowed. Every scan initializes it.
;; Never use SLPS_FREE_START..SLPS_FREE_END: the CD driver writes there.
.definelabel QOL_LIST_KIND, 0x16C               ; bytes per kind (14 x 0x1A)
.definelabel QOL_LIST_ROW, 0x1A                ; bytes per row
.definelabel QOL_SUM_SERIAL, 0x18                ; u16 inside the summary block, past the fields the game uses
.definelabel QOL_SAVE_SUM, 0x8005E398          ; g_card_save + 0x18 (the number goes here before the XOR sum)
.definelabel QOL_ROWS, 14
.definelabel QOL_ROWS_PER_CARD, 7
.definelabel QOL_SAVE_EMPTY, 0xFF
.definelabel QOL_SERIAL_MAX, 0xFFFE       ; FFFF is erased/uninitialized, never an order
.definelabel qol_serial, BTLEVT_BUF_ADDR
.definelabel qol_kinds, qol_serial + 4
.definelabel qol_valid, qol_kinds + QOL_ROWS * 2
.definelabel qol_list, (qol_valid + QOL_ROWS + 3) & ~3
.if qol_list + QOL_LIST_KIND * 2 > BTLEVT_BUF_ADDR + BTLEVT_BUF_SIZE
    .error "save summaries exceed mutually exclusive battle scratch"
.endif

;; Shared row geometry, in pixels relative to the text origin.
.definelabel QOL_COL_W, 160
.definelabel QOL_TEXT_W, 128
.definelabel QOL_PANEL_Y, 40
.definelabel QOL_PANEL_H, 192
.definelabel QOL_ROW_Y, QOL_PANEL_Y + 12
.definelabel QOL_TEXT_X, 12
.definelabel QOL_CURSOR_X, 8
.definelabel QOL_ROW_W, 144
.definelabel QOL_X_LV, 0
.definelabel QOL_X_LEVEL, 24
.definelabel QOL_X_TIME, 48
.definelabel QOL_X_CLOCK, 88
.definelabel QOL_U_LV, 8
.definelabel QOL_V_LV, 0x78
.definelabel QOL_U_TIME, 0x10
.definelabel QOL_V_TIME, 0x6C

;; Retail code retired by this patch. Message relocation must not rewrite
;; its old references: these bytes now belong to the save-list assembly.
;; sysmsg.py reads these same declarations when emitting conditional refs.
.definelabel QOL_ADV_RETIRED_TOP_START, 0x8009AB60
.definelabel QOL_ADV_RETIRED_TOP_END, 0x8009ABF4
.definelabel QOL_ADV_RETIRED_PORTSTEP_START, 0x8009AEC8
.definelabel QOL_ADV_RETIRED_PORTSTEP_END, 0x8009B060
.definelabel QOL_ADV_RETIRED_SCAN_START, 0x8009BB7C
.definelabel QOL_ADV_RETIRED_SCAN_END, 0x8009BC78
.definelabel QOL_ADV_RETIRED_DRAW_START, 0x8009BDD0
.definelabel QOL_ADV_RETIRED_DRAW_END, 0x8009C1A8
.definelabel QOL_ADV_RETIRED_PORTOPEN_START, 0x8009C298
.definelabel QOL_ADV_RETIRED_PORTOPEN_END, 0x8009C4AC
.definelabel QOL_ADV_RETIRED_SELECTOR_START, 0x8009A728
.definelabel QOL_ADV_RETIRED_SELECTOR_END, 0x8009A820
.definelabel QOL_CARD_READY_FRAMES, 30

;; --- ADV.BIN: the in-game save screen ----------------------
.definelabel QOL_MENU, 0x800BC43C          ; g_menu (a pointer)
.definelabel QOL_KINDS_OLD, 0x800BC45C
.definelabel QOL_STATE_A, 0x800BD0F8          ; g_card_state_a
.definelabel QOL_STATE_B, 0x800BD0FC          ; g_card_state_b
.definelabel QOL_STEP, 0x800BCB3C          ; g_persona_data_step
.definelabel QOL_TM0, 0x800EE180          ; g_tilemap0 (frames)
.definelabel QOL_TM1, 0x800EF580          ; g_tilemap1 (text)
.definelabel QOL_DIGITS, 0x800CCD14          ; g_hud_digits (FormatDecimal's scratch)
.definelabel QOL_STRRUN, 0x800B22A0          ; str_cell_run (0, 1, 2 ... a label run)
.definelabel QOL_BGLAYERS, 0x800B8E68          ; g_bg_layers[0]; .x .y .w .h at +4 +6 +8 +10

.definelabel QOL_SLOTSETPOS, 0x80065FDC          ; SlotSetPos(slot, attr, x, y)
.definelabel QOL_MENULISTINIT, 0x80067DD4          ; MenuListInit(list, cur, lo, hi, repeat)
.definelabel QOL_MENUSETLAYERS, 0x8008F3E0          ; MenuSetLayers(n)
.definelabel QOL_FILLRECT, 0x80067CEC          ; TileMapFillRect(dst, value, w, h, stride)
.definelabel QOL_WRITEROW, 0x80067C00          ; TileMapWriteRow(src, dst, base, count) (VWF hooked)
.definelabel QOL_WRITEREV, 0x80067CA0          ; TileMapWriteRowRev(src, dst, base, count)
.definelabel QOL_DRAWBOX, 0x8007AF1C          ; TileMapDrawBox(dst, w, h, stride)
.definelabel QOL_DRAWWINDOW, 0x8007AC30          ; TileMapDrawWindow(dst, w, h, stride)
.definelabel QOL_FMTDEC, 0x800665EC          ; FormatDecimal(value, dst, width) -> digits written

;; cells of the menu font (ADV's CellsInit atlas)
.definelabel QOL_CELL_LV, 0x383               ; "Lv", 2 cells
.definelabel QOL_CELL_TIME, 0x364               ; "TIME", 4 cells
.definelabel QOL_CELL_DIGIT, 0xC0                ; '0'.. at 0xC0..0xC9
.definelabel QOL_CELL_COLON, 0xCB                ; ':'
.definelabel QOL_CELL_DASH, 0x1A3               ; the blank/dash an empty row is filled with
.definelabel QOL_CELL_BULLET0, 0x47C               ; the save-kind bullet (kind 0 / kind 1)
.definelabel QOL_CELL_BULLET1, 0x47D
.definelabel QOL_GLYPH_N, 0xB2                ; 'N'
.definelabel QOL_GLYPH_L, 0xB1                ; 'L' (0xB0 is 'K')
.definelabel QOL_GLYPH_V, 0x45                ; 'v' (lowercase, 0x44 is 'y')
.definelabel QOL_GLYPH_O, 0x3A                ; 'o' (small-font lowercase, tools/smallfont_lc.py)
.definelabel QOL_GLYPH_DOT, 0x47                ; '.'

;; --- EXE/OPEN.EXE: the title's load list -------------------
.definelabel QOL_O_SPRITES, 0x80111484          ; g_sprites (36-byte GsSPRITE records)
.definelabel QOL_O_OT, 0x801146F0          ; g_ot (2 x 20 bytes)
.definelabel QOL_O_BUFF, 0x800B357C          ; g_active_buff
.definelabel QOL_O_MENU_STATE, 0x800B35AC          ; g_menu_state
.definelabel QOL_O_CARDSCAN_VAR, 0x800B359C     ; g_card_scan (the game's scan mask)
.definelabel QOL_O_SAVELIST, 0x80120E44          ; g_save_list (7 x 0x1A - ours is 14)
.definelabel QOL_O_SPRITE_SLOT, 23                  ; g_sprites[23] is the row cursor
.definelabel QOL_O_GSPRITES, 0x80111484          ; g_sprites (36-byte GsSPRITE records)
.definelabel QOL_O_GFLAGS, 0x8011E804          ; g_sprite_flags (one int each, 0x80 draws)
.definelabel QOL_O_SPRITEINIT, 0x800828E8          ; OpenSpriteInit(no, w, h, tpage, u, v, cx, cy)

.definelabel QOL_O_CLEAROT, 0x8008E6E0          ; GsClearOt(0, 0, ot)
.definelabel QOL_O_VSYNC, 0x80093708
.definelabel QOL_O_CARDCHECK, 0x800877FC          ; CardCheckSave(chan, kind, slot)
.definelabel QOL_O_CARDLOADSAVE, 0x800880C8          ; CardLoadSave(chan, slot, kind)
.definelabel QOL_O_CARDDELETE, 0x80088234          ; CardDeleteFile(chan, slot, kind)
.definelabel QOL_O_CARDSCAN, 0x80087574          ; CardScanSaves(chan, kind, out)
.definelabel QOL_O_CARDLOAD, 0x80087198          ; CardLoad(chan)
.definelabel QOL_O_LISTINIT, 0x80084CE4          ; OpenSaveListInit(kind, mask, cursor)
.definelabel QOL_O_MSGOPEN, 0x800861D0          ; OpenMessageOpen(w, h, x, y, text)
.definelabel QOL_O_PROMPT, 0x80086018          ; OpenCardPrompt(kind, port, arg2)
.definelabel QOL_O_RESET, 0x80084140          ; OpenLoadMenuReset(kind)
.definelabel QOL_O_SEQ, 0x80082788          ; OpenPlaySeq(i)
.endif
