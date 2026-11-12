;; =============================================================
;; S2D.BIN - pacing of the text-object interpreter (0x8009B2F4: overworld
;; party comments, door texts, the arrival banner and area labels)
;;
;; Retail read one item per call. A glyph set flags 0x14 and the object's
;; delay (+0x14) to its speed (+0x16) + 1; each call counted it down, and the
;; call that reached zero only cleared the flags, so the next glyph waited
;; for the following call. When the delay ends, the call now goes back to
;; its read while its budget lasts: S2D_TEXT_PACE glyphs per call at speed
;; 0, one call fewer per glyph above it. The rest of the call (the page
;; check, the button poll and its flags) still runs once per call.
;;
;; The budget is sp+0x20 of the 0x38 frame (only +0x10, the glyph decoder's
;; output, and the saved registers are used). It is set in two load-delay
;; slots of the entry path; the count-down block gains its slots from a
;; redundant flags reload and the 16-bit test of a 16-bit delay.
;; =============================================================
S2DT_ENTRY_SLOT         equ 0x8009B310          ; nop after the entry's flags load
S2DT_READ               equ 0x8009B35C          ; lhu v1,2(s1): the read's flags
S2DT_READ_SLOT          equ 0x8009B360          ; its load-delay nop
S2DT_READ_TEST          equ 0x8009B364          ; andi v0,v1,4: v1 = the flags
S2DT_DELAY              equ 0x8009BA4C          ; the delay count-down
S2DT_DELAY_END          equ 0x8009BA78          ; the button poll
S2DT_BUDGET             equ 0x20
S2D_TEXT_PACE           equ 2

.org S2DT_ENTRY_SLOT
    ori     t0, zero, S2D_TEXT_PACE     ; (both entry paths reach the read)
.org S2DT_READ_SLOT
    sw      t0, S2DT_BUDGET(sp)

.org S2DT_DELAY
.area S2DT_DELAY_END - S2DT_DELAY
    lhu     v0, 0x14(s1)                ; delay
    lhu     v1, 2(s1)                   ; flags
    addiu   v0, v0, -1
    bnez    v0, S2DT_DELAY_END
    sh      v0, 0x14(s1)
    andi    v1, v1, 0xFFEB              ; the delay is over: read again
    lw      t0, S2DT_BUDGET(sp)
    sh      v1, 2(s1)
    addiu   t0, t0, -1
    bgtz    t0, S2DT_READ_TEST          ; in this call while the budget lasts
    sw      t0, S2DT_BUDGET(sp)
.endarea
