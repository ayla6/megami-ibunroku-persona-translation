;; =============================================================
;; BTLP.BIN - negotiation text VWF hooks (engine: vwf/vwf_btlp.asm)
;; =============================================================
.org BTLP_TEXT_EMIT_JAL_ADDR
    jal     btlp_vwf_emit
.org BTLP_TEXT_EMIT2_JAL_ADDR
    jal     btlp_vwf_emit


;; 16 px string renderer (command windows, header) -> VWF (vwf/vwf_btlp_str16.asm)
.org 0x8007BF44
    j       btlp_str16
    nop

;; Second BTLP text window (battle help lines, definition texts, choice help):
;; draw one sprite per STAGED cell, not per retail character.
;;
;; The window keeps two counters: struct+0x1C is the retail character cursor
;; (also the VWF engine's pos, so it never claims a line start it has not
;; reached) and struct+0x20 is the staging/sprite counter that btlp_activate
;; keeps at "highest activated cell + 1".  A line whose pen reaches cell 14
;; (225-240 px) has pos 14 but 15 activated cells, and drawing by pos dropped
;; the sprite in the last column - the last glyph of the line vanished
;; (e.g. the ")" of "Special Phys damage+Charge (1 foe)").  The sequencer
;; window already draws by +0x20 (0x8007D124); make this window agree.
;; 0x8007DCE8 uses dx (struct+0x268) as its base: staged = dx - 0x248.
.org 0x8007D720
    lw      v0, -0x44DC(v0)
.org 0x8007D804
    lw      v0, -0x44DC(v0)
.org 0x8007DA74
    lw      v1, -0x44DC(v1)
.org 0x8007DB88
    lw      v0, -0x44DC(v0)
.org 0x8007DCE8
    lw      v1, -0x248(s3)

;; "LV13 <name>" header builder (0x8007C248..): btl_name_copy (btlp/name_lowercase.asm)
;; maps typed names like in the battle messages. a0 returns the FF position.
.org 0x8007C258
.area 0x8007C29C - 0x8007C258
    lui     a0, 0x800F
    addiu   a0, a0, -0x1448             ; name buffer
    move    a1, s2                      ; stored name
    jal     btl_name_copy
    li      a2, 8
    lui     v1, 0x800F
    addiu   v1, v1, -0x1448
    subu    s1, a0, v1                  ; s1 = bytes written (the code behind stores FF F5 at buffer + s1)
    j       0x8007C29C                  ; continue after the copy loop
    nop
.endarea
