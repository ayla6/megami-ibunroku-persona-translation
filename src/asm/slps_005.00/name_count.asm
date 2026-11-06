;; =============================================================
;; SLPS_005.00 - resident name-insert count glue
;;
;; Every message machine stores the number of glyphs an inserted name prints
;; with `sb v1,0x35(s1)` (s1 = the message state). Retail hardcodes 5 at both
;; sites (the hero's slot and a party member's). The 10-byte name slots now
;; hold one of two forms:
;;   * compact VWF bytes (the hero's typed name, or a generated party slot):
;;     one byte per character, never below 0x88, then FF 01. The first byte
;;     tells the forms apart, because a legacy slot's first byte is 0x00 (a
;;     leading glyph 0) or 0x80-0x87 (a two-byte glyph lead).
;;   * a legacy save: five two-byte retail glyphs = exactly ten bytes with no
;;     terminator, or fewer + FF 01.
;; so the ported dialogue reads the slot itself: the compact form's glyph
;; count is the FF position (the writers always leave one), and a legacy slot
;; keeps retail's five. The engines print exactly `left` glyphs - they do not
;; stop at FF - so a short compact name must not be padded out to eight.
;;
;; Entered from the per-overlay stubs (src/injection_tools/partynames.py)
;; after the site's delay slot has decremented v0, with
;;   a0 = the name base (PARTY_NAMES_ADDR, or +10 for a given name)
;;   v0 = id - 1
;;   s1 = the message state
;; Returns to the site. name_count_store preserves a0, v0, a1-a3, v1 and the
;; s-registers; it clobbers t0-t3 and at (the site's next code reloads what it
;; needs). name_count_surname needs a0 for the +10 base and t9 for the nested
;; return address, so it clobbers those two; none of the three sites reads
;; either after the call.
;;
;; Code 16 prints the first half and then jumps back into the message machine
;; for the second half (MSG_SURNAME), where retail stores a hardcoded 5. That
;; branch first prints one blank separator glyph (glyph 0, between the two
;; halves) and counts it in `left`, so the second half needs one more than its
;; glyph count. The site has no name base in a0, so it calls name_count_surname,
;; which supplies the +10 base, runs the same scan, and adds the separator.
;; =============================================================
.org NAME_COUNT_ADDR
.area NAME_COUNT_SIZE

name_count_store:
    sll     t0, v0, 2
    addu    t0, t0, v0
    sll     t0, t0, 2
    addu    t0, t0, a0                  ; t0 = slot = base + 20 * (id - 1)
    lbu     t3, 0(t0)
    move    t1, t0                      ; (also the load-delay filler)
    sltiu   t3, t3, 0x88                ; 1 = a legacy slot (00 / 80-87 first)
    bnez    t3, @@store                 ; legacy keeps retail's five
    li      t2, 5
    li      at, 0xFF                    ; compact: count = FF position
@@scan:
    lbu     t3, 0(t1)
    addiu   t1, t1, 1
    bne     t3, at, @@scan
    nop
    subu    t2, t1, t0
    addiu   t2, t2, -1
@@store:
    jr      ra
    sb      t2, 0x35(s1)

;; The MSG_SURNAME continuation (code 16's second half): same scan on the
;; +10 slot, plus the separator glyph that branch prints before it. t9 holds
;; the overlay return address across the nested call.
name_count_surname:
    move    t9, ra
    li      a0, PARTY_NAMES_ADDR + 10
    jal     name_count_store
    nop
    addiu   t2, t2, 1
    jr      t9
    sb      t2, 0x35(s1)

.endarea
