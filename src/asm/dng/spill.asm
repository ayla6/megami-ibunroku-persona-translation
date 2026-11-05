;; =============================================================
;; DNG spill redirect (over-cap dungeon boxes live in the extension;
;; see tools/dngspill.py). The script interpreter streams box text inline
;; (s5 to FF01); when the 24 bytes at s5 match a spilled box's Japanese
;; prefix, s5 is redirected to the spill bytes. The box-end FF01 pops the
;; engine's own resume, so waits/pages/timing are untouched.
;; The spill data and this hook own DNG_SPILL_ADDR..DNG_SPILL_LIMIT.
;; The entry patch has its own explicit address.
;; =============================================================
.if DNG_SPILL_ADDR < dng_glue_end
    .error "dng spill overlaps the dialogue glue"
.endif
.if dng_spill_tab != DNG_SPILL_ADDR
    .error "dng spill table is outside its assigned extension"
.endif
.align 4
dng_spill_hook:
    la    at, dng_spill_tab
dng_spill_check:
    lw    v1, 0(at)
    nop
    beqz  v1, dng_spill_exit
    nop
    lwr   v0, 0(s5)                     ; little-endian order (lwr low, lwl
    lwl   v0, 3(s5)                     ; high: the PSX is LE - lwl-first is
    lw    v1, 0(at)                     ; the BE form and never matches)
    nop
    bne   v0, v1, dng_spill_adv
    nop
    lwr   v0, 4(s5)
    lwl   v0, 7(s5)
    lw    v1, 4(at)
    nop
    bne   v0, v1, dng_spill_adv
    nop
    lwr   v0, 8(s5)
    lwl   v0, 11(s5)
    lw    v1, 8(at)
    nop
    bne   v0, v1, dng_spill_adv
    nop
    lwr   v0, 12(s5)                     ; 24-byte fingerprint: a short box
    lwl   v0, 15(s5)                     ; and a longer box sharing its head
    lw    v1, 12(at)                     ; differ past byte 12 (FF01 vs FF04)
    nop
    bne   v0, v1, dng_spill_adv
    nop
    lwr   v0, 16(s5)
    lwl   v0, 19(s5)
    lw    v1, 16(at)
    nop
    bne   v0, v1, dng_spill_adv
    nop
    lwr   v0, 20(s5)
    lwl   v0, 23(s5)
    lw    v1, 20(at)
    nop
    bne   v0, v1, dng_spill_adv
    nop
    lw    s5, 24(at)                      ; MATCH: redirect to spill bytes
    j     dng_spill_exit
    nop
dng_spill_adv:
    addiu at, at, 28
    j     dng_spill_check
    nop
dng_spill_exit:
    lbu   v1, 0(s5)                       ; the displaced load
    j     0x80073F98
    ori   v0, zero, 0xff                  ; delay slot: restore displaced ori

dng_spill_hook_end:
.if dng_spill_hook_end > DNG_SPILL_LIMIT
    .error "dng spill data and hook overlap the map-title table"
.endif

;; --- interpreter entry patch ---
.org 0x80073F90
    j dng_spill_hook
    nop
