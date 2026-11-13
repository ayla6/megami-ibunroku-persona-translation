;; ANALYZE board: full spell names, and the rank/kind rows in owned scratch.
;;
;; Retail copies each name's 10-byte record field into 11-byte rows at
;; 0x800F8780. The rows move to ANALYZE_SPELL_BUF (24-byte rows, the battle
;; skill menu's SKILL_MAXLEN + FF) and are filled by skill_name_copy_full,
;; which appends the long names' tails and ends each row with FF; the row's
;; last byte is its condensed tier for the battle bridge.
.if ANALYZE_SPELL_STRIDE != 24
    .error "the copy loop multiplies by 24"
.endif
.if ANALYZE_SPELL_STRIDE - 1 != SKILL_MAXLEN
    .error "a spell row holds one skill menu name"
.endif

;; BtlStatusFill's copy loop. s1 = row, s2 = the enemy record (spell ids at
;; +0x2E). skill_name_copy_full keeps t*, so the row and id stay in t1/t2
;; for the tier byte after it: 1 when the id is in analyze_tier_ids (the
;; name is wider than the column), else 0. The loop ends on the retail
;; `j 0x800AE070` that follows the area.
.org 0x800ADDC0
.area 0x800ADE28 - 0x800ADDC0
@@row:
    addu    v0, s2, s1
    lbu     t2, 0x2E(v0)                ; spell id (0 = none: record 0 is FF)
    sll     t1, s1, 1
    addu    t1, t1, s1
    sll     t1, t1, 3                   ; row * ANALYZE_SPELL_STRIDE
    lui     at, hi(ANALYZE_SPELL_BUF)
    addiu   at, at, lo(ANALYZE_SPELL_BUF)
    addu    t1, t1, at
    move    a0, t1
    li      a2, ANALYZE_SPELL_STRIDE - 1
    jal     skill_name_copy_full
    move    a1, t2
    lui     at, hi(analyze_tier_ids)
    addiu   at, at, lo(analyze_tier_ids)
@@scan:
    lbu     v0, 0(at)
    addiu   at, at, 1
    beqz    v0, @@store                 ; the list's end: tier 0
    nop
    bne     v0, t2, @@scan
    nop
@@store:
    sltu    v1, zero, v0                ; matched id -> 1
    sb      v1, ANALYZE_SPELL_STRIDE - 1(t1)
    addiu   s1, s1, 1
    slti    v0, s1, 6
    bnez    v0, @@row
    nop
.endarea

;; The unanalysed board ends every row at its first cell: same loop, the
;; new base and stride.
.org 0x800ADFD4
    ori     v1, zero, 5 * ANALYZE_SPELL_STRIDE
.org 0x800AE054
    lui     at, hi(ANALYZE_SPELL_BUF)
    addiu   at, at, lo(ANALYZE_SPELL_BUF)
.org 0x800AE064
    addiu   v1, v1, -ANALYZE_SPELL_STRIDE

;; The six row descriptors (board rows 16-21): retail's column (level with
;; St.), the row pointer and a count the drawer cuts at each FF.
.org 0x800DEB04
    .halfword 56
.org 0x800DEB08
    .word ANALYZE_SPELL_BUF + 0 * ANALYZE_SPELL_STRIDE
.org 0x800DEB0C
    .byte ANALYZE_SPELL_STRIDE - 1
.org 0x800DEB10
    .halfword 56
.org 0x800DEB14
    .word ANALYZE_SPELL_BUF + 1 * ANALYZE_SPELL_STRIDE
.org 0x800DEB18
    .byte ANALYZE_SPELL_STRIDE - 1
.org 0x800DEB1C
    .halfword 56
.org 0x800DEB20
    .word ANALYZE_SPELL_BUF + 2 * ANALYZE_SPELL_STRIDE
.org 0x800DEB24
    .byte ANALYZE_SPELL_STRIDE - 1
.org 0x800DEB28
    .halfword 56
.org 0x800DEB2C
    .word ANALYZE_SPELL_BUF + 3 * ANALYZE_SPELL_STRIDE
.org 0x800DEB30
    .byte ANALYZE_SPELL_STRIDE - 1
.org 0x800DEB34
    .halfword 56
.org 0x800DEB38
    .word ANALYZE_SPELL_BUF + 4 * ANALYZE_SPELL_STRIDE
.org 0x800DEB3C
    .byte ANALYZE_SPELL_STRIDE - 1
.org 0x800DEB40
    .halfword 56
.org 0x800DEB44
    .word ANALYZE_SPELL_BUF + 5 * ANALYZE_SPELL_STRIDE
.org 0x800DEB48
    .byte ANALYZE_SPELL_STRIDE - 1

;; The rank and kind rows (retail 0x800F8248 / 0x800F8300) move next to the
;; spell rows so their text is VWF under the same ownership entry. Every
;; writer is a lui/addiu or lui/sb pair on the buffer: the producers' copy
;; destinations, the unanalysed blanks and their end cells.
.org 0x800ADB78
    lui     a2, hi(ANALYZE_RANK_BUF)
    addiu   a2, a2, lo(ANALYZE_RANK_BUF)
.org 0x800ADD38
    lui     a2, hi(ANALYZE_KIND_BUF)
    addiu   a2, a2, lo(ANALYZE_KIND_BUF)
.org 0x800ADF90
    lui     a2, hi(ANALYZE_RANK_BUF)
    addiu   a2, a2, lo(ANALYZE_RANK_BUF)
.org 0x800ADFB0
    lui     a2, hi(ANALYZE_KIND_BUF)
    addiu   a2, a2, lo(ANALYZE_KIND_BUF)
.org 0x800AE044
    lui     at, hi(ANALYZE_RANK_BUF + 3)
    sb      v0, lo(ANALYZE_RANK_BUF + 3)(at)
    lui     at, hi(ANALYZE_KIND_BUF + 3)
    sb      v0, lo(ANALYZE_KIND_BUF + 3)(at)
;; board rows 14 and 15
.org 0x800DEAF0
    .word ANALYZE_RANK_BUF
.org 0x800DEAFC
    .word ANALYZE_KIND_BUF
