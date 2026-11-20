;; =============================================================
;; BTLP.BIN - negotiation choice box: answer-pointer bound
;;
;; BtlMenuOpenChoices builds each entry's script pointer as
;;   BTL_SCRATCH + g_btl_choice_text + answer_dir[id]
;; and rejects pointers past a hardcoded retail scratch limit of 0x801CFFFF,
;; replacing them with directory entry 0. That limit was safe while the whole
;; 64 KB scratch held the JP text; the translated answer pool legitimately runs
;; past it (the file's own section 1 ends at header word 2), so every late
;; answer was replaced by entry 0. For SINSI entry 0 is "I have a lot.", which
;; is why a three-entry box showed that line three times.
;;
;; The bound is the file's own answer-pool end, which the loader leaves in
;; header word 2 (g_btl_scratch_size, 0x801C0008), added to BTL_SCRATCH. fp
;; already holds BTL_SCRATCH at this point, so the two instructions that
;; materialised 0x801CFFFF are replaced in place:
;;   lui v1,0x801c            -> lw   v1,8(fp)     (header[2] = pool end)
;;   ori v1,v1,0xffff         -> addu v1,v1,fp     (address just past it)
;; The comparison is reversed so the exclusive end itself is rejected. The loaded pool ends range from
;; 0x801C2004 to 0x801D0CEC: for 26 of the 29 files the bound is tighter than
;; retail's 0x801CFFFF; for KOROU, SINSI and KOUMAN it extends a little past
;; that constant to the file's real end, which is exactly the region retail
;; wrongly rejected. It follows every loaded file as the answer pool grows.
;; =============================================================

.org BTLP_CHOICE_BOUND_LOAD
    lw      v1, 8(fp)                   ; g_btl_scratch_size: end of the answer pool

.org BTLP_CHOICE_BOUND_ADD
    addu    v1, v1, fp                  ; BTL_SCRATCH + pool end

.org BTLP_CHOICE_BOUND_ADD + 12
    sltu    v1, v0, v1                  ; answer < exclusive end
    bnez    v1, 0x8007E334
