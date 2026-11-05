;; =============================================================
;; Per-overlay entry stubs for vwf_dialog_emit
;; (config blocks: vwf_dialog_cfg_data.asm)
;;
;; INVARIANT (palette-inversion root fix): no draw path
;; inherits DLG_COLOR_MAIN/SHADOW. Every putter stub establishes its pair
;; before its first draw — ADV dialogue 2/1, S2D map/banner + DNG script
;; + S2D dialogue delegation 1/2, and BTLP dialogue/strings 1/2 — while
;; vwf_dialog_emit/draw never write them. A path that reads colors it did
;; not set inverts when another overlay drew last.
;; =============================================================

.macro vwf_dialog_stub, name, cfg, path, main, shadow
name:
    lui     a0, ((cfg + 0x8000) >> 16) & 0xFFFF   ; %hi with addiu sign adjust
    addiu   a0, a0, cfg & 0xFFFF
    la      t0, vwf_dlg_state
    li      t1, (shadow << 8) | main
    sh      t1, DLG_COLOR_MAIN(t0)      ; both color bytes at once (little-endian)
    j       vwf_dialog_emit
    li      a1, path                    ; 0 = text path, 1 = name-insertion path
.endmacro

vwf_dialog_stub vwf_adv_emit, vwf_cfg_adv, 0, 2, 1
vwf_dialog_stub vwf_adv_name_emit, vwf_cfg_adv, 1, 2, 1
vwf_dialog_stub vwf_dng_emit, vwf_cfg_dng, 0, 1, 2
vwf_dialog_stub vwf_dng_name_emit, vwf_cfg_dng, 1, 1, 2
vwf_dialog_stub vwf_s2d_emit, vwf_cfg_s2d, 0, 1, 2
vwf_dialog_stub vwf_s2d_name_emit, vwf_cfg_s2d, 1, 1, 2

;; Both BTLP entry paths already pass their own config and path arguments.
;; Retail battle CLUT index 1 is ink, index 2 shadow; set both together on
;; every glyph so no previously active overlay can determine their polarity.
vwf_btlp_dialog_emit:
    lui     t0, ((vwf_dlg_state + DLG_COLOR_MAIN + 0x8000) >> 16) & 0xFFFF
    li      t1, 0x0201
    j       vwf_dialog_emit
    sh      t1, (vwf_dlg_state + DLG_COLOR_MAIN) & 0xFFFF(t0)
