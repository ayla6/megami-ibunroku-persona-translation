;; =============================================================
;; ADV.BIN - DrawSpellName reads the full skill name
;;
;; Retail (0x8007BA94) cleared the caller's ten cells and copied the spell
;; record's ten-glyph head straight into the row, so every translated skill
;; name over ten glyphs was cut. The rewrite builds the complete name with
;; skill_name_copy in the kit's scratch and hands THAT to the same recorder;
;; the recorder retains the whole terminated name and its tiered row still
;; occupies the caller's ten-cell (80 px) footprint.
;;
;; Same body as DNG's copy (dng/pdata.asm). s2 keeps the glyph base and s3
;; the fourth argument (retail's rule flag), so the empty-slot rule path is
;; unchanged. 0xB8 bytes used of the 0xBC-byte function.
;; =============================================================
.psx

.if SF_VWF

.org ADV_DRAW_SPELL_NAME
.area 0xBC

adv_spell_row:
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
    jal     ADV_TILEMAP_FILLRECT
    sw      v0, 0x10(sp)

    beqz    s0, @@rule
    lui     a0, ((sf_name_scratch_adv + 0x8000) >> 16) & 0xFFFF
    addiu   a0, a0, sf_name_scratch_adv & 0xFFFF
    move    a1, s0
    jal     skill_name_copy
    nop
    lui     a0, ((sf_name_scratch_adv + 0x8000) >> 16) & 0xFFFF
    addiu   a0, a0, sf_name_scratch_adv & 0xFFFF
    move    a1, s1
    andi    a2, s2, 0xFFFF
    j       @@call
    ori     a3, zero, 10

@@rule:
    ;; retail's eight-glyph rule under an empty slot (dst + 1 cell)
    sll     v0, s3, 16
    beqz    v0, @@out
    addiu   a1, s1, 2
    lui     a0, ((ADV_SPELL_RULE_GLYPHS + 0x8000) >> 16) & 0xFFFF
    addiu   a0, a0, ADV_SPELL_RULE_GLYPHS & 0xFFFF
    ori     a2, zero, 0xD7
    ori     a3, zero, 8

@@call:
    jal     ADV_SF_HOOK_ADDR
    nop

@@out:
    lw      ra, 0x28(sp)
    lw      s3, 0x24(sp)
    lw      s2, 0x20(sp)
    lw      s1, 0x1C(sp)
    lw      s0, 0x18(sp)
    jr      ra
    addiu   sp, sp, 0x30
adv_spell_row_end:
.fill ADV_DRAW_SPELL_NAME + 0xBC - adv_spell_row_end

.endarea

.endif                              ; SF_VWF
