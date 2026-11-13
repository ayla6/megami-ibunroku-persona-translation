;; =============================================================
;; QoL (--qol=debug): fast-forward and movie skip in the endings
;; (END.EXE), to reach any page of a real ending script quickly.
;;
;; END.EXE paces its script with EndDraw's VSync(2) (0x80082518): every
;; wait, fade step and page of the staff roll is one pass of that loop.
;; While R1 is held the pass returns without waiting for the vblanks,
;; so the script runs as fast as it can draw; releasing R1 goes back to
;; the retail pace on whatever page is up. Start during an ending movie
;; (EndPlayMovie's VSync(0), 0x80082878) sets g_end_movie_done, the
;; flag the stream's own end raises, so the player leaves through its
;; retail exit and the script goes on.
;;
;; gp-relative END.EXE globals (gp = 0x800AD2B4): 0 g_end_movie_done,
;; 4 g_end_pad (held), 12 g_end_pad_trig (fresh presses). The code sits
;; in libgpu's SetGraphDebug (0x80083D60..0x80083EF4), which nothing in
;; END.EXE calls. Both stubs end in VSync's own return value.
;; =============================================================

.org 0x80082518
    jal     dbg_end_draw_vsync          ; a0 = 2 stays in the delay slot

.org 0x80082878
    jal     dbg_end_movie_vsync         ; a0 = 0 stays in the delay slot

.org DBG_END_CAVE
.area DBG_END_CAVE_END - DBG_END_CAVE
dbg_end_draw_vsync:
    lw      v0, 4(gp)                   ; g_end_pad
    nop
    andi    v0, v0, 0x8                 ; R1 held: no vblank wait
    beqz    v0, @@wait
    nop
    jr      ra
    nop
@@wait:
    j       DBG_END_VSYNC
    nop

dbg_end_movie_vsync:
    lw      v0, 12(gp)                  ; g_end_pad_trig
    nop
    andi    v0, v0, 0x800               ; Start
    beqz    v0, @@wait
    ori     v0, zero, 1
    sw      v0, 0(gp)                   ; g_end_movie_done
@@wait:
    j       DBG_END_VSYNC
    nop
.endarea
