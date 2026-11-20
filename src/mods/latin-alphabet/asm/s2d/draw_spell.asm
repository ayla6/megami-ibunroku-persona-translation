;; =============================================================
;; S2D.BIN - DrawSpellName reads the full skill name
;;
;; S2D compiles its own copy of the skill-row writer (0x8007A908); retail
;; copied the spell record's ten-glyph head, cutting translated names. The
;; rewrite is the same body as ADV's (adv/draw_spell.asm): build the full
;; name in this overlay's scratch with skill_name_copy, then let the
;; recorder draw it inside the caller's ten-cell (80 px) footprint.
;; 0xB8 bytes used of the 0xBC-byte function.
;; =============================================================
.psx

.if SF_VWF

.org S2D_DRAW_SPELL_NAME
.area 0xBC

s2d_spell_row:
    addiu   sp, sp, -0x30
    sw      ra, 0x28(sp)
    sw      s0, 0x18(sp)
    sll     s0, a0, 16                  ; spell id, sign-extended short
    sw      s1, 0x1C(sp)
    sra     s0, s0, 16
    sw      s2, 0x20(sp)
    move    s1, a1                      ; dst
    sw      s3, 0x24(sp)
    move    s2, a2                      ; base
    move    s3, a3                      ; retail's rule flag
    ori     v0, zero, 0x28
    move    a0, s1
    addu    a1, zero, zero
    ori     a2, zero, 10
    ori     a3, zero, 1
    jal     S2D_TILEMAP_FILLRECT
    sw      v0, 0x10(sp)

    beqz    s0, @@rule
    lui     a0, ((sf_name_scratch_s2d + 0x8000) >> 16) & 0xFFFF
    addiu   a0, a0, sf_name_scratch_s2d & 0xFFFF
    move    a1, s0
    jal     skill_name_copy
    nop
    lui     a0, ((sf_name_scratch_s2d + 0x8000) >> 16) & 0xFFFF
    addiu   a0, a0, sf_name_scratch_s2d & 0xFFFF
    move    a1, s1
    andi    a2, s2, 0xFFFF
    j       @@call
    ori     a3, zero, 10

@@rule:
    ;; retail's eight-glyph rule under an empty slot (dst + 1 cell)
    sll     v0, s3, 16
    beqz    v0, @@out
    addiu   a1, s1, 2
    lui     a0, ((S2D_SPELL_RULE_GLYPHS + 0x8000) >> 16) & 0xFFFF
    addiu   a0, a0, S2D_SPELL_RULE_GLYPHS & 0xFFFF
    ori     a2, zero, 0xD7
    ori     a3, zero, 8

@@call:
    jal     S2D_SF_HOOK_ADDR
    nop

@@out:
    lw      ra, 0x28(sp)
    lw      s3, 0x24(sp)
    lw      s2, 0x20(sp)
    lw      s1, 0x1C(sp)
    lw      s0, 0x18(sp)
    jr      ra
    addiu   sp, sp, 0x30
s2d_spell_row_end:
.fill S2D_DRAW_SPELL_NAME + 0xBC - s2d_spell_row_end

.endarea

.endif                              ; SF_VWF
