;; =============================================================
;; DNG.BIN - small-font VWF kit: writer hook + config + recorder +
;; renderer + the kit's own data + the full-name block.
;;
;; The kit's CODE and DATA live in this overlay's own dead functions and
;; extension (tools/deadfuncs.py finds no call, no pointer word and no
;; lui/addiu pair anywhere on the disc that names the dead functions;
;; the extension loads with the overlay and swaps with it, freshly zero
;; at every load). The never-wiped resident anchor - the sort gate and
;; the retail replays - lives in FONT.BIN (vwf/sf_font.asm); the sorter
;; stubs live in SLPS (vwf/sf_stubs.asm). The config is this overlay's
;; own block at the head of the renderer's dead run: it names the kit's
;; tables and this overlay's own map base, packet buffers and retail
;; fallback.
;;
;; A guard word (SF_REG_MAGIC) sits right before the renderer: the
;; FONT.BIN gate jumps through a registration cell only while that word
;; is intact. OPEN.EXE and every EXE in EXE/ load at 0x80080000, straight
;; over the overlay images and WITHOUT the game's overlay loader - a
;; stale registration would name EXE bytes. The guard breaks the match
;; and the sorter call takes the retail replay. The config's magic word
;; and the state's overlay id turn any remaining mistake into the
;; verbatim retail row writer instead of a crash.
;;
;; The full-name block (name_tails.py) holds the tails of over-10-glyph
;; item/demon names, their has-tail bitmaps, and item_name_copy /
;; demon_name_copy - read only while this overlay is the live one, so it
;; rides the extension like everything else here.
;; =============================================================

;; --- hook: the TileMapWriteRow loop entry becomes la t0,cfg / j sf_record ---
.if SF_VWF
.include "../../../../build/smallfont_fixed_dng.asm"
.org DNG_SF_HOOK_ADDR
    la      t0, sf_cfg_dng
    j       sf_record_dng
    nop

;; --- config: the first 0x20 bytes of the renderer's dead run ---
.org DNG_SF_CFG_ADDR
sf_cfg_dng:
    .word   SF_ENG_MAGIC                ; +0x00
    .word   DNG_SF_MAP_BASE             ; +0x04 the text map's cell array
    .word   sf_table_dng               ; +0x08 this overlay's row table
    .word   0                           ; +0x0C the victim counter
    .word   DNG_SF_BUFS_ADDR            ; +0x10 the packet-buffer pair
    .word   sf_widths_dng               ; +0x14 this overlay's advance table
    .word   sf_pool_dng                 ; +0x18 this overlay's affinity pool
    .word   DNG_SF_HOOK_ADDR + 0x0C     ; +0x1C the hook's delay slot, then the
                                        ; retail loop body; the recorder restores
                                        ; the displaced t0 = 0xFF

;; --- the recorder: the HELP dead run (inside the image) ---
.org DNG_SF_HELP_ADDR
    .include "../../../../build/smallfont_rec_dng.asm"
    .include "../../../../build/smallfont_center_dng.asm"

;; --- the guard + the renderer + thunks: after the config in the ROW run ---
.org DNG_SF_CFG_ADDR + SF_CFG_END
    .word   SF_REG_MAGIC                ; the gate's registration guard
    .include "../../../../build/smallfont_hook_dng.asm"

;; --- the kit's data: the extension, loaded with DNG.BIN ---
.org DNG_SF_DATA_ADDR
sf_state_dng:
    .fill   SF_ST_END, 0                ; zero at build; the recorder fills it
sf_widths_dng:
    .incbin "../../../../build/sf_field_width.bin"
sf_orig_dng:                            ; the original font's metrics (SF_ORIG_TABLE)
    .incbin "../../../../build/sf_field_orig.bin"
sf_pool_dng:
    .incbin "../../../../build/affinity_pool.bin"
.align 4
    .include "../../../../build/smallfont_helpers_dng.asm"
sf_data_end_dng:

.if (sf_record_end_dng - sf_record_dng) > DNG_SF_HELP_SIZE
    .error "smallfont: the DNG recorder overruns its HELP dead run"
.endif
.if sf_center_end_dng > DNG_SF_HELP_ADDR + DNG_SF_HELP_SIZE
    .error "smallfont: DNG centering helper exceeds the recorder run"
.endif
.if sf_orig_dng - sf_widths_dng != SF_ORIG_TABLE
    .error "smallfont: the DNG original-font table must follow the advance table"
.endif
.if sf_data_end_dng > DNG_ITEM_DATA_ADDR
    .error "smallfont: the DNG kit data overruns its window"
.endif
.if (sf_thunks_end_dng - sf_hook_bg_dng) > DNG_SF_ROW_SIZE - SF_CFG_END - 4
    .error "smallfont: the DNG renderer + thunks overrun the ROW dead run (past the config and its guard)"
.endif
.if DNG_SF_BUFS_ADDR + SF_BUFS * SF_BUF_SIZE > DNG_SF_BUFS_LIMIT
    .error "smallfont: the DNG packet buffers reach bg_map0/g_font_blank (DNG_SF_BUFS_LIMIT)"
.endif
.if DNG_ITEM_DATA_ADDR - DNG_SF_DATA_ADDR != SF_DATA_WINDOW
    .error "smallfont: DNG_ITEM_DATA_ADDR must stay DNG_SF_DATA_ADDR + SF_DATA_WINDOW (addresses.inc)"
.endif

.endif                              ; SF_VWF: nothing above exists when the kit is off

;; --- the full-name block: tails + bitmaps + the copy helpers ---
.org DNG_ITEM_DATA_ADDR
    .include "../../../../build/name_tails_dng.asm"
    .include "../../../../build/item_names_dng.asm"
sf_item_end_dng:
.if SF_VWF
.definelabel sf_table_dng, DNG_SF_TABLE_ADDR
.definelabel sf_table_end_dng, DNG_SF_TABLE_ADDR + SF_TABLE_SIZE
.if sf_table_end_dng != DNG_SF_TABLE_LIMIT
    .error "smallfont: the DNG row table must end at DNG_SF_TABLE_LIMIT"
.endif
.if DNG_ITEM_DATA_END != DNG_SF_TABLE_ADDR
    .error "smallfont: DNG_ITEM_DATA_END must stay DNG_SF_TABLE_ADDR (the image ends below the table)"
.endif
.endif
;; --- MsgStep cases 9-12: full names instead of the ten-glyph record head ---
.align 4
sf_msg_name_dng:
    sf_msg_name_stubs sf_msg_item_dng, sf_msg_skill_dng, sf_msg_demon_dng, \
                      sf_msg_persona_dng, sf_msg_tail_dng, \
                      item_name_copy_dng, demon_name_copy_dng, \
                      sf_name_scratch_dng, 0x80076B20
sf_msg_name_end_dng:

.align 4
sf_name_scratch_dng:
    .fill SF_NAME_BYTES, 0
sf_extension_end_dng:
.if sf_extension_end_dng > DNG_ITEM_DATA_END
    .error "smallfont: the DNG full-name block reaches the work area (DNG_ITEM_DATA_END)"
.endif

;; the text stat labels (vwf/stat_label.asm, menu_gfx.py) past the extension
.if SF_VWF
.align 4
stat_label_text_dng:
    stat_label_text stat_label_strings_dng, stat_label_writer_dng
stat_label_strings_dng:
.include "../../../../build/stat_label_strings.asm"
stat_label_end_dng:
.if stat_label_end_dng > DNG_ITEM_DATA_END
    .error "smallfont: the DNG text stat labels reach DNG_ITEM_DATA_END"
.endif
.endif
