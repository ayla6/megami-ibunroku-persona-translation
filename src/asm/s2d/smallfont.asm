;; =============================================================
;; S2D.BIN - small-font VWF kit: writer hook + config + recorder +
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
.include "../../build/smallfont_fixed_s2d.asm"
.org S2D_SF_HOOK_ADDR
    la      t0, sf_cfg_s2d
    j       sf_record_s2d
    nop

;; --- config: the first 0x20 bytes of the renderer's dead run ---
.org S2D_SF_CFG_ADDR
sf_cfg_s2d:
    .word   SF_ENG_MAGIC                ; +0x00
    .word   S2D_SF_MAP_BASE             ; +0x04 the text map's cell array
    .word   sf_table_s2d               ; +0x08 this overlay's row table
    .word   0                           ; +0x0C the victim counter
    .word   S2D_SF_BUFS_ADDR            ; +0x10 the packet-buffer pair
    .word   sf_widths_s2d               ; +0x14 this overlay's advance table
    .word   sf_pool_s2d                 ; +0x18 this overlay's affinity pool
    .word   S2D_SF_HOOK_ADDR + 0x0C     ; +0x1C the hook's delay slot, then the
                                        ; retail loop body; the recorder restores
                                        ; the displaced t0 = 0xFF

;; --- the recorder: the HELP dead run (inside the image) ---
.org S2D_SF_HELP_ADDR
    .include "../../build/smallfont_rec_s2d.asm"
    .include "../../build/smallfont_center_s2d.asm"

;; --- the guard + the renderer + thunks: after the config in the ROW run ---
.org S2D_SF_CFG_ADDR + SF_CFG_END
    .word   SF_REG_MAGIC                ; the gate's registration guard
    .include "../../build/smallfont_hook_s2d.asm"

;; --- the kit's data: the extension, loaded with S2D.BIN ---
.org S2D_SF_DATA_ADDR
sf_state_s2d:
    .fill   SF_ST_END, 0                ; zero at build; the recorder fills it
sf_widths_s2d:
    .incbin "../../build/sf_field_width.bin"
sf_pool_s2d:
    .incbin "../../build/affinity_pool.bin"
.align 4
    .include "../../build/smallfont_helpers_s2d.asm"
sf_data_end_s2d:

.if (sf_record_end_s2d - sf_record_s2d) > S2D_SF_HELP_SIZE
    .error "smallfont: the S2D recorder overruns its HELP dead run"
.endif
.if sf_center_end_s2d > S2D_SF_HELP_ADDR + S2D_SF_HELP_SIZE
    .error "smallfont: S2D centering helper exceeds the recorder run"
.endif
.if (sf_thunks_end_s2d - sf_hook_bg_s2d) > S2D_SF_ROW_SIZE - SF_CFG_END - 4
    .error "smallfont: the S2D renderer + thunks overrun the ROW dead run (past the config and its guard)"
.endif
.if S2D_SF_BUFS_ADDR + SF_BUFS * SF_BUF_SIZE > S2D_SF_BUFS_LIMIT
    .error "smallfont: the S2D packet buffers reach bg_map0/g_font_blank (S2D_SF_BUFS_LIMIT)"
.endif
.if S2D_ITEM_DATA_ADDR - S2D_SF_DATA_ADDR != SF_DATA_WINDOW
    .error "smallfont: S2D_ITEM_DATA_ADDR must stay S2D_SF_DATA_ADDR + SF_DATA_WINDOW (addresses.inc)"
.endif

.endif                              ; SF_VWF: nothing above exists when the kit is off

;; --- the full-name block: tails + bitmaps + the copy helpers ---
.org S2D_ITEM_DATA_ADDR
    .include "../../build/name_tails_s2d.asm"
    .include "../../build/item_names_s2d.asm"
sf_item_end_s2d:
.if SF_VWF
.align 4
sf_table_s2d:
    .fill SF_TABLE_SIZE, 0
sf_table_end_s2d:
.endif
.align 4
sf_name_scratch_s2d:
    .fill SF_NAME_BYTES, 0
sf_extension_end_s2d:
.if sf_extension_end_s2d > S2D_ITEM_DATA_END
    .error "smallfont: the S2D full-name block reaches the work area (S2D_ITEM_DATA_END)"
.endif
