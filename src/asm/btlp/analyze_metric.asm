;; The battle 16 px string renderer at 0x8007BF44 is a jump to btlp_str16
;; (btlp/vwf_hooks.asm, vwf/vwf_btlp_str16.asm), which replaces it whole;
;; nothing enters the retail body after that jump, so it holds this code.
.org ANALYZE_METRIC_ADDR
.area ANALYZE_METRIC_END - ANALYZE_METRIC_ADDR
;; The battle bridge's width lookup (btlp/smallfont_vwf.asm), out of its full
;; area. a1 = glyph code in, its width byte out. An ANALYZE spell row wider
;; than ANALYZE_SPELL_PX draws at the small font's condensed tier 1: the word
;; space advances 2 px instead of 4 (smallfont_vwf.tier_adv). The copy loop
;; (btlp/analyze_spells.asm) stores each row's tier in its last byte. t7 = the
;; row's descriptor; a0 holds the bridge's pen. Only a1-a3 and v1 change: the
;; bridge restores a2/a3 itself, and v1 is its scratch.
btl_sf_metric:
    lui     a2, hi(BTLP_SF_WIDTH_ADDR)
    addu    a2, a2, a1
    lbu     a2, lo(BTLP_SF_WIDTH_ADDR)(a2)
    bnez    a1, @@done                  ; only the word space changes
    move    a1, a2                      ; (two instructions after the load)
    lw      v1, 4(t7)                   ; the row's text
    lui     a3, hi(ANALYZE_SPELL_BUF)
    addiu   a3, a3, lo(ANALYZE_SPELL_BUF)
    subu    a3, v1, a3
    sltiu   a3, a3, ANALYZE_SPELL_END - ANALYZE_SPELL_BUF
    beqz    a3, @@done
    nop
    lbu     a3, ANALYZE_SPELL_STRIDE - 1(v1)
    nop
    srlv    a1, a1, a3                  ; tier 1: 4 -> 2 px (bearing nibble 0)
@@done:
    j       btl_sf_metric_back
    nop
;; Skill ids whose name needs tier 1 in the spell column, 0-terminated
;; (btlui.py; the battle page has no compact face, so no tier 2).
analyze_tier_ids:
    .include "../../build/analyze_tier_ids.asm"
.endarea
