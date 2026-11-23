;; =============================================================
;; BTLP.BIN - the effect drawers stop at the end of the 2D layer's half.
;;
;; The battle's 2D layer is built into its own buffer (addresses.inc, "BTLP's
;; 2D layer buffer"): BtlDrawUi points g_btl_prim_next at this frame's
;; 0x2800-byte half and every 2D drawer appends its primitives there, the
;; effects (BtlDrawEffects) last. Retail never checks the end. An effect row
;; is one 40-byte POLY_FT4 a glyph (BtlDrawGlyphs), and while an effect's box
;; opens or closes its frame is one POLY_FT4 an 8x8 piece (flat, once open,
;; an SPRT_8). The CONTACT stock list shows twelve names; with every slot
;; filled (a full card pack: trading a card or discarding one) the English
;; names, the list's opening frame, the message box and the prompt pass the
;; half, and the overrun is written over the other half, the one the GPU is
;; still reading, which freezes the console.
;;
;; Here a glyph or frame piece that does not fit in this frame's half ends
;; its row or piece instead (BtlDrawGlyphs and BtlDrawFramePiece answer 1 as
;; ever): the cells already written stay drawn. The checks sit in the copies
;; into the buffer, each of which has an unaligned branch for an unaligned
;; source or destination. The sources are scratchpad pads and the buffer is
;; only ever advanced by whole primitives (every one a multiple of four
;; bytes) from a word-aligned base, so those branches never run; the checks
;; take their room and the copies are the aligned ones (the flat piece's
;; only copy, written with unaligned loads and stores, becomes aligned).
;; =============================================================

;; BtlDrawGlyphs 0x800784D8: a3 = g_btl_prim_next, a2 = the pad's quad
;; (0x1F800020), a0 = their alignment. The aligned copy is 0x80078824.
.org 0x800787C8
    nop                                 ; was beqz a0, 0x80078824 (always taken)
.org 0x800787D0
.area 0x80078824 - 0x800787D0, 0
    jal     ui_half_end                 ; t7 = this frame's half end
    addiu   t8, a3, 0x28                ; (delay) this glyph's end
    sltu    t8, t7, t8
    beqz    t8, 0x80078824              ; it fits: the copy
    nop
    j       0x800788D8                  ; the half is full: the row ends here
    nop

;; t7 = the end of this frame's half of the 2D layer buffer. Leaf; t6, t7.
ui_half_end:
    lui     t6, hi(BTL_UI_OT_INDEX)
    lw      t6, lo(BTL_UI_OT_INDEX)(t6)
    lui     t7, hi(BTL_UI_PRIM_POOL + BTL_UI_PRIM_HALF)
    addiu   t7, t7, lo(BTL_UI_PRIM_POOL + BTL_UI_PRIM_HALF)
    negu    t6, t6
    andi    t6, t6, BTL_UI_PRIM_HALF    ; half 1: one half further
    jr      ra
    addu    t7, t7, t6
.endarea

;; BtlDrawFramePiece 0x80078C40, a flat piece: v1 = g_btl_prim_next, the
;; SPRT_8 in the pad at 0x1F800048 (s0 = 0x1F800000). The loop's end test
;; follows at 0x80078E0C; 0x80078E5C answers 1.
.org 0x80078DCC
.area 0x80078E0C - 0x80078DCC, 0
    jal     ui_half_end
    addiu   t8, v1, 0x10                ; (delay) this piece's end
    sltu    t8, t7, t8
    bnez    t8, 0x80078E5C              ; the half is full: the piece ends here
    lw      v0, 0x48(s0)                ; (delay) the SPRT_8
    lw      a0, 0x4C(s0)
    lw      a1, 0x50(s0)
    lw      a2, 0x54(s0)
    sw      v0, 0(v1)
    sw      a0, 4(v1)
    sw      a1, 8(v1)
    sw      a2, 12(v1)
.endarea

;; A rotated piece (the box opening or closing): a3 = g_btl_prim_next, a2 =
;; the pad's quad, v1 = their alignment. The aligned copy is 0x80079050;
;; 0x80079108 answers 1.
.org 0x80078FF4
    nop                                 ; was beqz v1, 0x80079050 (always taken)
.org 0x80078FFC
.area 0x80079050 - 0x80078FFC, 0
    jal     ui_half_end
    addiu   t8, a3, 0x28                ; (delay) this piece's end
    sltu    t8, t7, t8
    beqz    t8, 0x80079050              ; it fits: the copy
    nop
    j       0x80079108                  ; the half is full: the piece ends here
    nop
.endarea
