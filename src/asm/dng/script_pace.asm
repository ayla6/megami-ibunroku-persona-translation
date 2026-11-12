;; =============================================================
;; DNG.BIN - pacing of the dungeon SCRIPT boxes (FieldRunScript, D0x events)
;;
;; Retail printed one glyph, ran `speed` (fp, the Message Speed setting
;; 0/1/2) FieldFrames and then the pass's own FieldFrame: one glyph per
;; 3/6/9 vsyncs. A batch of glyphs now shares those waits: three on Fast
;; (one glyph per vsync, ADV's doubled Fast rate), two otherwise (twice the
;; retail rate). Glyphs before the last of a batch set the pass's `nowait`
;; (sp+0x40, cleared after every pass) and skip the `speed` frames; the
;; last one runs both as retail did.
;;
;; The batch counter is sp+0x48, inside the 0x44..0x7C run of the 0xA8
;; frame that FieldRunScript never touches. It is never initialised: the
;; unsigned compare makes any stale value end a batch on the first glyph.
;; The code takes the space of the two glyph tails, which carried a
;; duplicated `beqz fp` test and a j/nop loop each.
;; =============================================================
DNGS_GLYPH_TAIL         equ 0x80074E68          ; single-byte glyph: after FieldMsgPutGlyph
DNGS_GLYPH_TAIL_END     equ 0x80074E94          ; the two-byte glyph's decode starts here
DNGS_WIDE_TAIL          equ 0x80074EA8          ; two-byte glyph: after FieldMsgPutGlyph
DNGS_PASS_END           equ 0x80074ECC          ; nowait test, then the pass's FieldFrame
DNGS_FIELD_FRAME        equ 0x800659B4
DNGS_NOWAIT             equ 0x40
DNGS_BATCH              equ 0x48

.org DNGS_GLYPH_TAIL
.area DNGS_GLYPH_TAIL_END - DNGS_GLYPH_TAIL, 0
dngs_glyph_paced:
    lw      t2, DNGS_BATCH(sp)
    sltiu   v0, fp, 1                   ; Fast
    addiu   t2, t2, 1
    addiu   v0, v0, 2                   ; glyphs per batch: 3 on Fast, else 2
    sltu    v0, t2, v0
    beqz    v0, dngs_glyph_wait
    sw      t2, DNGS_BATCH(sp)
    ori     v0, zero, 1
    j       DNGS_PASS_END
    sw      v0, DNGS_NOWAIT(sp)         ; no frame for this glyph
.endarea

.org DNGS_WIDE_TAIL
.area DNGS_PASS_END - DNGS_WIDE_TAIL
    b       dngs_glyph_paced            ; the same batch for a two-byte glyph
    nop
dngs_glyph_wait:                        ; the batch's last glyph: retail's waits
    sw      zero, DNGS_BATCH(sp)
    beqz    fp, DNGS_PASS_END
    move    s0, zero
@@frames:
    jal     DNGS_FIELD_FRAME
    addiu   s0, s0, 1
    slt     v0, s0, fp
    bnez    v0, @@frames                ; delay slot: the pass end's nowait load
.endarea
