;; =============================================================
;; BTLP.BIN - demon reaction lines: script-pointer bound
;;
;; BtlSayDemonLine resolves a reaction line through the pack directory
;;   script = BTL_SCRATCH + answer_dir[slot]
;; and replaces the line with the "nothing" script when the resolved pointer
;; lies outside a hardcoded 64 KB scratch window:
;;   if ((u_long)(script - BTL_SCRATCH) > 0xFFFF) script = nothing;
;; That window was safe while every pack stayed under 64 KB. Translated TALK
;; packs already run past it (SINSI's text ends at 0x10CD0, KOUMAN's at
;; 0x10CEC), so a reaction line placed in the grown part would silently
;; become the "nothing" line.
;;
;; The real end of the text is the pack's own text length: header word 2 at
;; 0x801C0008, which the loader also adds to BTL_SCRATCH to form
;; g_btl_scratch_end (the line tables begin exactly there). The four
;; instructions that build the 0xFFFF window are rewritten in place:
;;   lui  v0,0x7fe4        -> lui  v1,0x801c
;;   addu v0,s0,v0         -> lw   v0,8(v1)          (header[2] = text length)
;;   ori  v1,zero,0xffff   -> subu v1,s0,v1          (script - BTL_SCRATCH)
;;   sltu v0,v1,v0         -> sltu v0,v1,v0          (offset < length)
;;   beqz v0,0x800686FC    -> bnez v0,0x800686FC
;;   ori  v1,zero,0xffff   -> ori  v1,zero,0xffff    (branch delay: slot-none)
;; Subtracting BTL_SCRATCH keeps the check wrap-safe: an address outside the
;; scratch, including one that wrapped below its base, produces an offset
;; larger than the length. The original kept 0xFFFF in v1 for the
;; slot == BTL_SLOT_NONE test that follows, so the delay slot restores it on
;; both paths.
;;
;; Every reaction line in the built packs resolves below its own text length,
;; so this bound rejects no real line; the junk rows whose second-table index
;; falls outside the file stay rejected exactly as before.
;; =============================================================

.org BTLP_DEMONLINE_BOUND_LUI
    lui     v1, 0x801c

.org BTLP_DEMONLINE_BOUND_LOAD
    lw      v0, 8(v1)                   ; g_btl_scratch_size: end of the text

.org BTLP_DEMONLINE_BOUND_SUB
    subu    v1, s0, v1                  ; resolved script - BTL_SCRATCH

.org BTLP_DEMONLINE_BOUND_SLTU
    sltu    v0, v1, v0                  ; offset < exclusive text end

.org BTLP_DEMONLINE_BOUND_BEQ
    bnez    v0, 0x800686FC              ; inside: keep the resolved line
    ori     v1, zero, 0xffff            ; branch delay: slot-none for the test below
