;; =============================================================
;; SLPS_005.00 - home of the dialogue VWF engine
;;
;; The engine and its tables live in functions of the main
;; executable that no code or data on the disc references (found with
;; tools/deadfuncs.py; never executed in runtime breakpoint tests). The main
;; executable is resident, so this memory is never reused for anything else.
;; Its ring uses the runtime scratch in addresses.inc; English glyph bitmaps
;; live in unused FONT.BIN slots (font/vwf_glyphs.asm).
;; =============================================================

.include "vwf/vwf_btlp_defs.asm"

.org VWF_CODE_A_ADDR
.area VWF_CODE_A_SIZE
.include "vwf/vwf_dialog.asm"
.include "vwf/vwf_dialog_cfg.asm"
.endarea

.org VWF_CODE_B_ADDR
.area VWF_CODE_B_SIZE
.include "vwf/vwf_dialog_draw.asm"
.if SF_VWF
.include "vwf/vwf_offer_lookup.asm"
.endif
.endarea

.org VWF_NAME_CODE_ADDR
.area VWF_NAME_CODE_SIZE
.include "vwf/vwf_name_map.asm"
.if SF_VWF
.include "../../build/btl_art.asm"
.align 4
;; The gate records the row's art mode in `at` for the quad renderer's eight
;; glyph loads (vwf/vwf_offer_art.asm) - position phase only, because the
;; advance phase's retail `sw v0,-0x7c58(at)` delay slot still stores through
;; it. Gated position rows end here; every other row ends at offer_name_ret,
;; which is shared with the advance phase and so masks `at` with t4-1: -1 when
;; the row is being positioned, untouched when it has advanced.
offer_name_ret:
    addiu   t5, t4, -1
    or      at, at, t5
    jr      ra
    nop
offer_finish_position:
    li at, 0
    jr ra
    subu v0, s4, t1
.endif
;; The dead run's spare tail: the shared dialogue / VWF pen state (DLG_PX,
;; DLG_LINE, DLG_INIT, DLG_LAST, colours). Retail never touches these bytes;
;; every writer and reader reaches them through the symbol.
.if . > VWF_STATE_ADDR
    .error "vwf_name_map run reaches the VWF state"
.endif
.org VWF_STATE_ADDR
vwf_dlg_state:
    .halfword 0, 0xFFFF, 0xFFFF, 0
    .byte 2, 1, 1, 0                    ; DLG_COLOR_MAIN, DLG_COLOR_SHADOW, DLG_SHADOW_DX (1 px: retail convention)
.endarea

.org VWF_DATA_ADDR
.area VWF_DATA_SIZE
.align 4
;; vwf_dlg_state lives in the spare tail of the party-name wrapper's dead
;; function (VWF_STATE_ADDR, party_name_vwf.asm): its 12 bytes are what lets
;; the battle art selector below keep the non-text-cell check inside this area.
.include "vwf/vwf_dialog_cfg_data.asm"
.if SF_VWF
.align 4
btl_item_vwf_flags:
    .incbin "../../build/btl_item_vwf_flags.bin"
btl_item_owner:
    .byte 0
.align 4
;; at = latched row mode, a0 = encoded glyph -> sampled atlas cell.
;; Fixed rows retain their original cell; only owned VWF rows use the
;; separate proportional artwork. Inside an owned row a NON-text cell (a
;; number, an icon, kana, or the unanalysed `?` placeholder) still keeps its
;; original small-font cell: the battle width table gives every such code
;; bearing 0 / advance 8, the metric its pen already uses, and no text cell
;; carries 0x08. Only at/a0 change, and at stays non-negative on every
;; gated exit. The branch before the first a0 read also supplies the
;; caller's glyph-load delay slot; the bias adds below ride branch delay
;; slots so the whole selector fits the dead run.
btl_sf_art_code:
    bltz    at, @@done
    nop
    beqz    a0, @@done
    nop
    la      at, BTLP_SF_WIDTH_ADDR
    addu    at, at, a0
    lbu     at, 0(at)
    nop                             ; load delay: the next instruction reads at
    addiu   at, at, -8
    beqz    at, @@done
    sltiu   at, a0, BTL_ART_LOW_END ; text cell: classify in the delay slot
    beqz    at, @@upper
    addiu   a0, a0, BTL_ART_LOW_BIAS
    jr      ra
    nop
@@upper:
    sltiu   at, a0, BTL_ART_UPPER_END + BTL_ART_LOW_BIAS
    bnez    at, @@capital
    addiu   a0, a0, BTL_ART_NUM_BIAS - BTL_ART_LOW_BIAS
    jr      ra
    nop
@@capital:
    addiu   a0, a0, BTL_ART_UPPER_BIAS - BTL_ART_NUM_BIAS
@@done:
    jr      ra
    nop
btl_sf_rot_art:
    lw      at, 0x68(sp)
    sw      ra, 0x6C(sp)
    jal     btl_sf_art_code
    lbu     a0, 0(s4)
    lw      ra, 0x6C(sp)
    nop
    j       0x80089378
    nop
;; Semantic name-range table (btl_name_owner.asm reads it with `la`). Each
;; bank is its own range: the Persona bank's three name slots (3 x 16 bytes)
;; own bits 0..2, the skill slots (7 x 24 bytes) own bits 3..9. The Persona
;; bank's fourth slot holds the static "Cost" label but is outside this range,
;; so it keeps the retail fixed-width path. Entries are 28 bytes, terminated
;; by a zero base.
.align 4
btl_name_ranges:
    .word PERSONA_HDR_BUF
    .halfword 3 * PERSONA_HDR_STRIDE, PERSONA_HDR_STRIDE
    .word 0
    .halfword 0, 0xFFFF, PERSONA_BIT_OFFSET + 3, PERSONA_BIT_OFFSET
    .word SKILL_VWF_SLOTS_ADDR, 0
    .word SKILL_MENU_BUF
    .halfword SKILL_MENU_BUF_END - SKILL_MENU_BUF, SKILL_MENU_STRIDE
    .word 0
    .halfword 0, 0xFFFF, SKILL_BIT_OFFSET + 7, SKILL_BIT_OFFSET
    .word SKILL_VWF_SLOTS_ADDR, 0
    .word BTLP_ITEM_FULL_ADDR
    .halfword BTLP_ITEM_ROWS * BTLP_ITEM_FULL_STRIDE, BTLP_ITEM_FULL_STRIDE
    .word BTLP_ITEM_IDS_ADDR
    .halfword 2, 0x1FF, BTLP_ITEM_ID_COUNT, 0
    .word btl_item_vwf_flags, btl_item_owner
    .word 0
;; The banks are fixed-size windows carved out of dead code, so their geometry
;; is asserted here: the skill slots fill the dead run up to the live function
;; 0x8002C2F0, and every slot keeps one byte for the FF terminator.
.if SKILL_MENU_BUF + 7 * SKILL_MENU_STRIDE != SKILL_MENU_BUF_END
    .error "skill slot bank does not fill its dead code run"
.endif
.if SKILL_MAXLEN != SKILL_MENU_STRIDE - 1
    .error "skill slot glyph bound must leave the FF terminator byte"
.endif
.if PERSONA_HDR_BUF + 4 * PERSONA_HDR_STRIDE != PERSONA_HDR_BUF_END || PERSONA_HDR_BUF_END > PERSONA_HDR_LIMIT
    .error "Persona name bank does not fill its dead run"
.endif
.if . > PARTY_NAME_VWF_ADDR
    .error "battle name ownership overlaps the resident party-name wrapper"
.endif
.endif
.endarea

.org VWF_TABLE_ADDR
.area VWF_TABLE_SIZE
vwf_font_index:                         ; u16 offset of each glyph inside FONT.BIN
    .incbin "font/vwf_index.bin"
vwf_font_width:                         ; u8 pen advance
    .incbin "font/vwf_width.bin"
.align 4
.include "../../build/name_vwf_tables.asm"    ; vwf_name_lc, vwf_name_sym (tools/name_grid.py)
;; ENGLISH-PRODUCER BUFFERS outside every ownership range above. A row that
;; points into one of these buffers is owned (VWF) even though the battle
;; renderers do not know the row's producer. These are the buffers the
;; translated producers write, never descriptor addresses: the ANALYZE board's
;; untranslated rows (ailments, full-width rank/kind labels, the MAG ATK /
;; MAG DEF labels, the shared kana label bank) stay fixed because their text
;; lives elsewhere. The trait value line is translated, so it is owned; its
;; unanalysed placeholder is a non-text cell and keeps the retail 8 px `?`.
;; Checked only when the range directory above has no match; the entries are
;; {base, span} with a zero base terminating the list.
.align 4
btl_owned_spans:
    .word ANALYZE_NAME_BUF
    .halfword ANALYZE_NAME_END - ANALYZE_NAME_BUF, 0
    .word ANALYZE_SPELL_BUF
    .halfword ANALYZE_SPELL_END - ANALYZE_SPELL_BUF, 0
    .word ANALYZE_TRAIT_BUF
    .halfword ANALYZE_TRAIT_END - ANALYZE_TRAIT_BUF, 0
    .word 0
btl_owned_span:
    la      v1, btl_owned_spans
@@loop:
    lw      a1, 0(v1)
    nop                                  ; R3000 load delay: a1 retires here
    beqz    a1, @@no
    nop
    lhu     a2, 4(v1)
    subu    v0, a0, a1
    sltu    v0, v0, a2
    bnez    v0, @@yes
    addiu   v1, v1, 8
    b       @@loop
    nop
@@yes:
    ori     v0, zero, 1
@@no:
    jr      ra
    nop
btl_owned_span_end:
.if btl_owned_span_end > VWF_TABLE_ADDR + VWF_TABLE_SIZE
    .error "battle-owned span table overlaps the next resident function"
.endif
.endarea

;; BTLP (negotiation text) hook code: unreferenced SLPS fragment
.org VWF_BTLP_CODE_ADDR
.area VWF_BTLP_CODE_SIZE
.include "vwf/vwf_btlp_activate.asm"
.endarea
.org VWF_BTLP_CODE2_ADDR
.area VWF_BTLP_CODE2_SIZE
.include "vwf/vwf_btlp.asm"
.align 4
.include "vwf/vwf_btlp_str16_act.asm"
.endarea
