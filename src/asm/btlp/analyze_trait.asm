;; =============================================================
;; ANALYZE status board: the complete affinity (trait) line - BTLP only.
;;
;; The retail producer copies exactly the 25 bytes of
;; g_resist_labels[a->resist] into g_btl_status_resist_cells and the row
;; descriptor draws 25 cells. An English line longer than its record's own
;; slot therefore loses its tail. affinity.py already writes the record's
;; first 25 glyphs as the line's head and puts exactly the remainder in the
;; small-font pool (smallfont_vwf.write_pool); this file appends that same
;; pool tail in battle.
;;
;; The 28-byte retail slot ends at g_btl_slot_owner, so the whole 47-cell
;; line reuses the mutually exclusive story-dialogue unpack buffer. The
;; descriptor's pointer and count follow it (btlui.py also moves its x).
;;
;; The append hook replaces the producer's `lw a1,(s0)` immediately after
;; the copy:
;;   0x800ADA90  jal btl_trait_tail
;;   0x800ADA94  lw  a1,(s0)        (delay slot)
;; and the routine reproduces the displaced `jal 0x800AE43C` before
;; continuing at 0x800ADA9C. a0/a1/a2/s0/sp are preserved for it.
;; =============================================================

.org BTLP_TRAIT_CODE_ADDR
.area 52

;; a3 = the trait row buffer, s0 = the actor, a1 already loaded by the
;; hook's delay slot. The 25-byte head is already in the buffer. The pool
;; index is keyed by the same record index the producer copied; 0xFF
;; means the record's own slot holds the whole line, so terminate at 25.
;;
;; The index is bounds-checked: retail indexes g_resist_labels[] with no
;; check, but an actor whose resist is not a record index (an empty Persona
;; slot leaves 0xFF) would otherwise read a live BTLP word as an offset and
;; copy from wherever it points. Out of range terminates at the head.
btl_trait_tail:
    lbu     t0, 0x5C(s0)                ; Char.resist = affinity record index
    addiu   t2, a3, 25                  ; (load delay) the record's slot is the head
    sltiu   t3, t0, 120
    beqz    t3, @@out_of_range
    ori     at, zero, 0xFF
    la      t3, BTLP_TRAIT_POOL_ADDR
    addu    t1, t3, t0                  ; &index[k]
    j       btl_trait_tail_continue
    lbu     t0, 0(t1)                   ; tail offset, 0xFF = none
@@out_of_range:
    j       btl_trait_terminate
    nop
.endarea

;; btlp.py emits the compact 120-byte index and shared tails into its
;; reserved immutable pool, rejecting offsets that do not fit a byte.

;; Move the retail trait buffer to the full-line buffer.
.org 0x800AD980
    la      a3, ANALYZE_TRAIT_BUF
.org 0x800ADE38
    la      a2, ANALYZE_TRAIT_BUF
;; The unanalysed row terminates its three `?` cells at buffer+3. Keep the
;; retail two-instruction shape (`lui at`, then the store through it); only
;; the buffer base and displacement change.
.org 0x800ADFDC
    lui     at, 0x8005
    sb      v0, (ANALYZE_TRAIT_BUF + 3) - 0x80050000(at)

;; Continue into the pool after the record's 25-cell head.
.org 0x800ADA90
    jal     btl_trait_tail
    lw      a1, (s0)

;; The board descriptor's text pointer and cell count follow the buffer.
;; The drawer stops at the line's FF, so the count is the buffer's bound.
.org 0x800DEBF8
    .word ANALYZE_TRAIT_BUF
.org 0x800DEBFC
    .byte ANALYZE_TRAIT_END - ANALYZE_TRAIT_BUF
