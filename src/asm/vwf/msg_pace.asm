;; =============================================================
;; Dialogue pacing for MsgStep (ADV / DNG / S2D copies of the interpreter)
;;
;; MsgStep runs once per game frame. Retail printed at most one glyph per
;; call and then counted `delay` (MsgState +6) down from `speed` (+8) in
;; frames. English needs about twice the glyphs of the Japanese line, and
;; the overlays run at different frame rates (ADV 30, DNG 20, S2D 30 fps),
;; so the same setting printed slower in dungeons.
;;
;; A call now prints up to MSG_PACE_<OVL> glyphs: a glyph's tail continues
;; at the interpreter's `next` step (past the pause, delay and key/choice
;; checks) while the per-call budget lasts, then leaves through `done`,
;; which stores the read pointer exactly as the retail tails did. Only the
;; glyph tails continue, so a control code (key wait, choice, pause,
;; newline, end) still ends the call where retail did, and a press can
;; never satisfy two prompts in one frame. `delay` is still reloaded from
;; `speed` after every glyph, so a slower setting keeps its own wait
;; between batches; scripted pauses (+4 `wait`) are untouched.
;;
;; The budget lives in MsgState's padding (+0x3E); the digit buffer before
;; it ends at +0x3D. Its code takes the space of MsgStep's prologue copy:
;; the clut RECT is word-aligned in rodata, so the copy is two lw/sw
;; pairs, and the 64-word slot clear is a pointer loop.
;; =============================================================

MSG_BUDGET equ 0x3E
MSG_PACE_ENTRY equ 0x3C                ; the pacing check's offset in the reused run

.macro msg_pace, top, top_end, rect, slots, next, done, text_tail, sub_tail, insert_tail, glyphs
.org top
.area top_end - top
    la      a1, rect                    ; the clut RECT for this call's uploads
    lw      v0, 0(a1)
    lw      v1, 4(a1)
    lui     a0, (slots >> 16) & 0xFFFF
    sw      v0, 0x18(sp)
    sw      v1, 0x1C(sp)
    ori     a0, a0, slots & 0xFFFF
    addiu   a1, a0, 0x100               ; 64 slot words
@@clear:
    addiu   a0, a0, 4
    bne     a0, a1, @@clear
    sw      zero, -4(a0)
    ori     t0, zero, glyphs
    b       top_end
    sh      t0, MSG_BUDGET(s1)
;; a glyph tail: another step while the call's budget lasts
.if . != top + MSG_PACE_ENTRY
    .error "msg_pace: the pacing check moved; update MSG_PACE_ENTRY"
.endif
    lhu     t0, MSG_BUDGET(s1)
    nop
    addiu   t0, t0, -1
    bgtz    t0, next
    sh      t0, MSG_BUDGET(s1)
    b       done
    nop
.endarea
.org text_tail
    beqz    v1, top + MSG_PACE_ENTRY                  ; a script glyph (retail: store script, return)
.org sub_tail
    bnez    v0, top + MSG_PACE_ENTRY                  ; a name glyph, more left (retail: done)
.org insert_tail
    j       top + MSG_PACE_ENTRY                      ; a counted insert glyph (retail: done)
.endmacro
