;; =============================================================
;; Shared addresses for the unified save menu (its adv / open / slps.asm).
;;
;; Every address is from this project's own binaries (SLPS-00500 first
;; release, ADV.BIN, EXE/OPEN.EXE); the reference decomp in references/
;; describes the same code at different addresses (a different pressing).
;; =============================================================

;; --- SLPS_005.00: the resident card code -------------------
.ifndef MOD_SAVES_INC
.definelabel MOD_SAVES_INC, 1
.definelabel MOD_CARD_POLL, 0x80013344          ; CardPollPorts(want0, want1) -> 1<<chan removed, 4<<chan new card
.definelabel MOD_CARD_LOAD, 0x800135C4          ; CardLoad(chan) -> 0 ready, 1 error, 2 no card, 4 unformatted
.definelabel MOD_CARD_SCAN, 0x800139A0          ; CardScanSaves(chan, kind, out) -> bits 0-6 present, 8-14 bad sum
.definelabel MOD_CARD_SAVE, 0x80013E2C          ; CardSave(chan, slot, kind)
.definelabel MOD_CARD_DELETE, 0x800144F4          ; CardDeleteFile(chan, slot, kind)
.definelabel MOD_CARD_CHECKFREE, 0x800137DC          ; CardCheckFree(chan) -> 0 if a 2-block file fits
.definelabel MOD_VSYNC, 0x80025C98

;; Save summaries use the battle decoder's bounded runtime scratch while
;; ADV is active; BTLP and ADV are mutually exclusive. The dialogue ring
;; starts AFTER this buffer and is not borrowed. Every scan initializes it.
;; Never use SLPS_FREE_START..SLPS_FREE_END: the CD driver writes there.
.definelabel MOD_LIST_KIND, 0x16C               ; bytes per kind (14 x 0x1A)
.definelabel MOD_LIST_ROW, 0x1A                ; bytes per row
.definelabel MOD_SUM_SERIAL, 0x18                ; u16 inside the summary block, past the fields the game uses
.definelabel MOD_SAVE_SUM, 0x8005E398          ; g_card_save + 0x18 (the number goes here before the XOR sum)
.definelabel MOD_ROWS, 14
.definelabel MOD_ROWS_PER_CARD, 7
.definelabel MOD_SAVE_EMPTY, 0xFF
.definelabel MOD_SERIAL_MAX, 0xFFFE       ; FFFF is erased/uninitialized, never an order
.definelabel mod_serial, BTLEVT_BUF_ADDR
.definelabel mod_kinds, mod_serial + 4
.definelabel mod_valid, mod_kinds + MOD_ROWS * 2
.definelabel mod_list, (mod_valid + MOD_ROWS + 3) & ~3
.if mod_list + MOD_LIST_KIND * 2 > BTLEVT_BUF_ADDR + BTLEVT_BUF_SIZE
    .error "save summaries exceed mutually exclusive battle scratch"
.endif

;; Shared row geometry, in pixels relative to the text origin.
.definelabel MOD_COL_W, 160
.definelabel MOD_TEXT_W, 128
.definelabel MOD_PANEL_Y, 40
.definelabel MOD_PANEL_H, 192
.definelabel MOD_ROW_Y, MOD_PANEL_Y + 12
.definelabel MOD_TEXT_X, 12
.definelabel MOD_CURSOR_X, 8
.definelabel MOD_ROW_W, 144
.definelabel MOD_X_LV, 0
.definelabel MOD_X_LEVEL, 24
.definelabel MOD_X_TIME, 48
.definelabel MOD_X_CLOCK, 88
.definelabel MOD_U_LV, 8
.definelabel MOD_V_LV, 0x78
.definelabel MOD_U_TIME, 0x10
.definelabel MOD_V_TIME, 0x6C

;; Retail code retired by this patch. Message relocation must not rewrite
;; its old references: these bytes now belong to the save-list assembly.
;; sysmsg.py reads these same declarations when emitting conditional refs.
.definelabel MOD_ADV_RETIRED_TOP_START, 0x8009AB60
.definelabel MOD_ADV_RETIRED_TOP_END, 0x8009ABF4
.definelabel MOD_ADV_RETIRED_PORTSTEP_START, 0x8009AEC8
.definelabel MOD_ADV_RETIRED_PORTSTEP_END, 0x8009B060
.definelabel MOD_ADV_RETIRED_SCAN_START, 0x8009BB7C
.definelabel MOD_ADV_RETIRED_SCAN_END, 0x8009BC78
.definelabel MOD_ADV_RETIRED_DRAW_START, 0x8009BDD0
.definelabel MOD_ADV_RETIRED_DRAW_END, 0x8009C1A8
.definelabel MOD_ADV_RETIRED_PORTOPEN_START, 0x8009C298
.definelabel MOD_ADV_RETIRED_PORTOPEN_END, 0x8009C4AC

;; --- ADV.BIN: the in-game save screen ----------------------
.definelabel MOD_MENU, 0x800BC43C          ; g_menu (a pointer)
.definelabel MOD_KINDS_OLD, 0x800BC45C
.definelabel MOD_STATE_A, 0x800BD0F8          ; g_card_state_a
.definelabel MOD_STATE_B, 0x800BD0FC          ; g_card_state_b
.definelabel MOD_STEP, 0x800BCB3C          ; g_persona_data_step
.definelabel MOD_TM0, 0x800EE180          ; g_tilemap0 (frames)
.definelabel MOD_TM1, 0x800EF580          ; g_tilemap1 (text)
.definelabel MOD_DIGITS, 0x800CCD14          ; g_hud_digits (FormatDecimal's scratch)
.definelabel MOD_STRRUN, 0x800B22A0          ; str_cell_run (0, 1, 2 ... a label run)
.definelabel MOD_BGLAYERS, 0x800B8E68          ; g_bg_layers[0]; .x .y .w .h at +4 +6 +8 +10

.definelabel MOD_SLOTSETPOS, 0x80065FDC          ; SlotSetPos(slot, attr, x, y)
.definelabel MOD_MENULISTINIT, 0x80067DD4          ; MenuListInit(list, cur, lo, hi, repeat)
.definelabel MOD_MENUSETLAYERS, 0x8008F3E0          ; MenuSetLayers(n)
.definelabel MOD_FILLRECT, 0x80067CEC          ; TileMapFillRect(dst, value, w, h, stride)
.definelabel MOD_WRITEROW, 0x80067C00          ; TileMapWriteRow(src, dst, base, count) (VWF hooked)
.definelabel MOD_WRITEREV, 0x80067CA0          ; TileMapWriteRowRev(src, dst, base, count)
.definelabel MOD_DRAWBOX, 0x8007AF1C          ; TileMapDrawBox(dst, w, h, stride)
.definelabel MOD_DRAWWINDOW, 0x8007AC30          ; TileMapDrawWindow(dst, w, h, stride)
.definelabel MOD_FMTDEC, 0x800665EC          ; FormatDecimal(value, dst, width) -> digits written

;; cells of the menu font (ADV's CellsInit atlas)
.definelabel MOD_CELL_LV, 0x383               ; "Lv", 2 cells
.definelabel MOD_CELL_TIME, 0x364               ; "TIME", 4 cells
.definelabel MOD_CELL_DIGIT, 0xC0                ; '0'.. at 0xC0..0xC9
.definelabel MOD_CELL_COLON, 0xCB                ; ':'
.definelabel MOD_CELL_DASH, 0x1A3               ; the blank/dash an empty row is filled with
.definelabel MOD_CELL_BULLET0, 0x47C               ; the save-kind bullet (kind 0 / kind 1)
.definelabel MOD_CELL_BULLET1, 0x47D
.definelabel MOD_GLYPH_N, 0xB2                ; 'N'
.definelabel MOD_GLYPH_L, 0xB1                ; 'L' (0xB0 is 'K')
.definelabel MOD_GLYPH_V, 0x45                ; 'v' (lowercase, 0x44 is 'y')
.definelabel MOD_GLYPH_O, 0x3A                ; 'o' (small-font lowercase, tools/smallfont_lc.py)
.definelabel MOD_GLYPH_DOT, 0x47                ; '.'

;; --- EXE/OPEN.EXE: the title's load list -------------------
.definelabel MOD_O_SPRITES, 0x80111484          ; g_sprites (36-byte GsSPRITE records)
.definelabel MOD_O_OT, 0x801146F0          ; g_ot (2 x 20 bytes)
.definelabel MOD_O_BUFF, 0x800B357C          ; g_active_buff
.definelabel MOD_O_MENU_STATE, 0x800B35AC          ; g_menu_state
.definelabel MOD_O_CARDSCAN_VAR, 0x800B359C     ; g_card_scan (the game's scan mask)
.definelabel MOD_O_SAVELIST, 0x80120E44          ; g_save_list (7 x 0x1A - ours is 14)
.definelabel MOD_O_SPRITE_SLOT, 23                  ; g_sprites[23] is the row cursor
.definelabel MOD_O_GSPRITES, 0x80111484          ; g_sprites (36-byte GsSPRITE records)
.definelabel MOD_O_GFLAGS, 0x8011E804          ; g_sprite_flags (one int each, 0x80 draws)
.definelabel MOD_O_SPRITEINIT, 0x800828E8          ; OpenSpriteInit(no, w, h, tpage, u, v, cx, cy)

.definelabel MOD_O_CLEAROT, 0x8008E6E0          ; GsClearOt(0, 0, ot)
.definelabel MOD_O_VSYNC, 0x80093708
.definelabel MOD_O_CARDCHECK, 0x800877FC          ; CardCheckSave(chan, kind, slot)
.definelabel MOD_O_CARDLOADSAVE, 0x800880C8          ; CardLoadSave(chan, slot, kind)
.definelabel MOD_O_CARDDELETE, 0x80088234          ; CardDeleteFile(chan, slot, kind)
.definelabel MOD_O_CARDSCAN, 0x80087574          ; CardScanSaves(chan, kind, out)
.definelabel MOD_O_CARDLOAD, 0x80087198          ; CardLoad(chan)
.definelabel MOD_O_LISTINIT, 0x80084CE4          ; OpenSaveListInit(kind, mask, cursor)
.definelabel MOD_O_MSGOPEN, 0x800861D0          ; OpenMessageOpen(w, h, x, y, text)
.definelabel MOD_O_PROMPT, 0x80086018          ; OpenCardPrompt(kind, port, arg2)
.definelabel MOD_O_RESET, 0x80084140          ; OpenLoadMenuReset(kind)
.definelabel MOD_O_SEQ, 0x80082788          ; OpenPlaySeq(i)
.endif
