;; The battle's original font (btlp/smallfont_vwf.asm, btlp/analyze_metric.asm):
;; the shared metric lookup and the party markers' centring, in the body of
;; the retail text-window glyph function (BTLP_GLYPH_FREE_ADDR).
.org BTLP_GLYPH_FREE_ADDR
.area BTLP_GLYPH_FREE_END - BTLP_GLYPH_FREE_ADDR

;; a1 = glyph code -> a1 = its original-font metric (bearing << 4 | advance):
;; two runs of codes in the resident btl_orig_width (smallfont_vwf.
;; btl_orig_runs); any other code is its retail 8 px cell. a2/a3 scratch;
;; a1 is ready when this returns.
btl_orig_lookup:
    sltiu   a3, a1, BTL_ORIG_LOW_N
    bnez    a3, @@hit
    move    a2, a1                      ; (delay) the index in the low run
    addiu   a2, a1, BTL_ORIG_LOW_N - BTL_ORIG_HIGH_FIRST
    addiu   a3, a1, -BTL_ORIG_HIGH_FIRST
    sltiu   a3, a3, BTL_ORIG_HIGH_N
    bnez    a3, @@hit
    nop
    jr      ra
    ori     a1, zero, 8                 ; outside both runs: 8 px
@@hit:
    lui     a3, hi(btl_orig_width)
    addu    a3, a3, a2
    lbu     a1, lo(btl_orig_width)(a3)
    jr      ra
    nop

;; The original-font metric of a glyph of row t7 (a0 = the row's pen word).
;; A race tag is the original font and the demon name after it the regular
;; face: the ANALYZE header ("Night: Nightmare", one row) starts in the
;; original font (btl_board_pools) and its first word space - the gap
;; analyze_race_gap puts after the race colon; no race tag holds a space -
;; clears the pen word's original-font bit, so the space and the name take
;; the regular face. a2/a3 scratch, as btl_orig_lookup.
btl_orig_glyph:
    bnez    a1, btl_orig_lookup         ; only a word space can end the race
    lw      a2, 4(t7)                   ; (delay) the row's text
    lui     a3, hi(ANALYZE_NAME_BUF)
    addiu   a3, a3, lo(ANALYZE_NAME_BUF)
    bne     a2, a3, btl_orig_lookup
    nop
    sll     a0, a0, 1
    j       btl_orig_lookup
    srl     a0, a0, 1                   ; (delay) bit 31 clear: the regular face
;; A party marker's name (a0, at most 8 cells, FF ends it) is centred on 12
;; as retail centres it, on its drawn width: v0 = (24 - width) / 2 for the
;; original font the marker draws in (retail: 12 - 4 * cells at 8 px).
;; a0-a3, t2, t4 change.
btl_marker_x:
    move    t2, ra
    addiu   t4, a0, 8                   ; NAME_CELLS bound
    ori     v0, zero, 24
@@glyph:
    lbu     a1, 0(a0)
    addiu   a0, a0, 1
    xori    a2, a1, 0xFF
    beqz    a2, @@centred
    nop
    jal     btl_orig_lookup
    nop
    andi    a1, a1, 15
    bne     a0, t4, @@glyph
    subu    v0, v0, a1
@@centred:
    jr      t2
    sra     v0, v0, 1

.align 4
;; Board text drawn in the original font: [start, end) pairs, 0-terminated
;; (battle_board_text.py; btl_row_face).
btl_board_pools:
    .word   ANALYZE_LABEL_BUF, ANALYZE_LABEL_END    ; ANALYZE's stat labels (btlui.py)
    .word   ANALYZE_RANK_BUF, ANALYZE_KIND_END      ; its rank and kind rows
    .word   ANALYZE_NAME_BUF, ANALYZE_NAME_END      ; its header: the race (btl_orig_glyph)
    .word   BTLP_BOARD23_TAG_TABLE, BTLP_BOARD23_TAG_TABLE_END  ; the race tags (CONTACT list)
    .include "../../build/btl_board_pools.asm"

.endarea
