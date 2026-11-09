;; =============================================================
;; BTLP.BIN - negotiation stock list: complete Persona names
;;
;; BtlTalkStockMenu copies at most ten glyphs of each stock Persona's record
;; into a 12-byte slot and terminates there, so longer names are cut off.
;; The rows are drawn by BtlDrawGlyphs, which the offer gate already renders
;; proportionally for the CONTACT personality bank. Write the names into
;; 21-byte slots in the free battle scratch instead (BTLP_STOCK_FULL_ADDR),
;; continue with the source-derived tail from OFFER_NAME_BANK when the
;; ten-byte record head fills, and let the offer gate draw the whole name.
;; =============================================================

.org 0x80067cc0                         ; retail 12-byte name array -> 21-byte slots
    la      t0, BTLP_STOCK_FULL_ADDR

.org 0x80067d30                         ; retail head copy, ten glyphs maximum
.area 0x80067dbc - 0x80067d30, 0
    lbu     v1, 0(t1)                   ; the stock's 1-based Persona record id
    move    a1, t0                      ; destination cursor
    sll     v0, v1, 3
    subu    v0, v0, v1
    sll     v0, v0, 3                   ; id * 0x38
    addu    t3, v0, t4                  ; the record itself
    move    a0, zero                    ; copied glyphs
@@copy:
    slti    v0, a0, 10
    beqz    v0, @@full                  ; the record head is exactly ten bytes
    addu    v0, t3, a0
    lbu     v0, 0(v0)
    addiu   a0, a0, 1                   ; fills the load delay
    beq     v0, t5, @@term              ; a short name ends inside the head
    sb      v0, 0(a1)                   ; harmless terminator store on the taken path
    b       @@copy
    addiu   a1, a1, 1
@@term:
    sb      t5, 0(a1)
    b       @@next
    nop
@@full:
    move    t3, t0                      ; offer_tail: t3 = destination base
    move    a1, a0                      ; ... a1 = first glyph past the head
    sw      t1, 0x00(sp)                ; the surrounding retail loop keeps both
    sw      t2, 0x04(sp)
    lui     t0, hi(OFFER_NAME_BANK)
    addiu   t0, t0, lo(OFFER_NAME_BANK)
    ori     v0, zero, 0xff              ; offer_tail's entry sentinel
    jal     offer_tail
    nop
    lw      t1, 0x00(sp)
    lw      t2, 0x04(sp)
    move    t0, t3                      ; restore the slot cursor
    addu    v0, t0, a1                  ; a1 = complete glyph count
    sb      t5, 0(v0)
@@next:
.endarea

.org 0x80067dc4                         ; next 21-byte slot, not retail's 12
    addiu   t0, t0, BTLP_STOCK_FULL_STRIDE
