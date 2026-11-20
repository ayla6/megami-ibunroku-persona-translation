;; =============================================================
;; BTLP.BIN - command-stage member boards: full-length Persona names
;;
;; Small-font VWF only: the 16-cell row is drawn through the proportional
;; renderer.  Without SF_VWF the retail 10-cell path stays untouched.
;;
;; The five bottom member boards each carry a Persona row at x = 44.  Retail
;; copies the master record's ten-glyph name head into five 10-byte buffers
;; and draws ten fixed cells, so a name longer than ten glyphs is cut
;; ("Seimen Kon").  The names are already produced in full by
;; persona_name_copy (slps_005.00/persona_names.asm); this file gives the row
;; the same treatment as the skill-menu header and PRS-CHG:
;;
;;   * the five descriptors point at 16-glyph buffers in the dead SLPS run
;;     (BTLP_STATUS_PERSONA_BUF, allocated by persona_names.asm);
;;   * the single write site (BTLP 0x800A9F6C..0x800AA038) reads the master
;;     key from the battle record (+0x1E) and calls persona_name_copy;
;;   * the empty-slot write at 0x800AA044 terminates the 16-cell buffer;
;;   * the member loop's Persona-buffer stride becomes 0x10.
;;
;; Only the Persona text after "Pr." is touched.  The member names, the
;; fixed "Pr." glyph, levels, HP/SP and status labels keep their own retail
;; buffers and renderers.
;; =============================================================

.if SF_VWF
.if BTLP_STATUS_PERSONA_END - BTLP_STATUS_PERSONA_BUF != 5 * PERSONA_MAXLEN
    .error "status Persona bank must be five 16-glyph rows"
.endif

;; --- the five row descriptors: 16 glyphs, one bank slot per member ---------
.org 0x800DCCF4 + 4
    .word BTLP_STATUS_PERSONA_BUF
.org 0x800DCCF4 + 8
    .byte PERSONA_MAXLEN
.org 0x800DCDA8 + 4
    .word BTLP_STATUS_PERSONA_BUF + PERSONA_MAXLEN
.org 0x800DCDA8 + 8
    .byte PERSONA_MAXLEN
.org 0x800DCE5C + 4
    .word BTLP_STATUS_PERSONA_BUF + 2 * PERSONA_MAXLEN
.org 0x800DCE5C + 8
    .byte PERSONA_MAXLEN
.org 0x800DCF10 + 4
    .word BTLP_STATUS_PERSONA_BUF + 3 * PERSONA_MAXLEN
.org 0x800DCF10 + 8
    .byte PERSONA_MAXLEN
.org 0x800DCFC4 + 4
    .word BTLP_STATUS_PERSONA_BUF + 4 * PERSONA_MAXLEN
.org 0x800DCFC4 + 8
    .byte PERSONA_MAXLEN

;; --- the one Persona-name write: master key -> persona_name_copy ----------
;; Retail copies 10 bytes from the battle record's name head (0x8005CDA8 +
;; persona*0x48 + 0x1F).  Replace that copy with the resident full-name
;; producer.
;;
;; The patch starts at 0x800A9F6C, not at the copy itself: the retail code
;; between there and 0x800A9FDC loads the name into v1, so v1 no longer holds
;; the Persona slot by the time the copy runs.  Starting here keeps v1 (the
;; BtlActorPersona result) live and rebuilds persona*0x48 from it.  The first
;; instruction is the bnez's delay slot, so it also runs on the blocked path.
;;
;; v1 = Persona slot, t3 = member * 0x10.  The producer clobbers
;; v0/v1/a0/a1/a2/at and is non-leaf; the function's ra is saved.
.org 0x800A9F6C
.area 0x800AA03C - 0x800A9F6C
    sll     v0, v1, 3
    addu    v0, v0, v1
    lw      t3, 0x28(sp)                ; this member's row offset
    sll     v0, v0, 3                   ; persona * 0x48
    lui     at, 0x8006
    addiu   at, at, -0x3258             ; 0x8005CDA8: battle record base
    addu    at, at, v0
    lbu     a1, 0x1E(at)                ; master-table key
    lui     a0, hi(BTLP_STATUS_PERSONA_BUF)
    addiu   a0, a0, lo(BTLP_STATUS_PERSONA_BUF)
    addu    a0, a0, t3                  ; this member's 16-glyph row
    jal     persona_name_copy
    nop
    j       0x800AA05C
    nop
    .fill 0x800AA03C - ., 0
.endarea

;; --- empty / blocked slot: terminate its own 16-cell row ---------------------
.org 0x800AA04C
    lui     at, hi(BTLP_STATUS_PERSONA_BUF)
    addiu   at, at, lo(BTLP_STATUS_PERSONA_BUF)
.org 0x800AA444
    addiu   t3, t3, PERSONA_MAXLEN      ; row stride 0x10, not retail 0x0A
.endif
