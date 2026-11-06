;; =============================================================
;; QoL (separate enhancement build): press Start to skip the movie.
;;
;; MOVIE.EXE plays every story FMV, the Philemon scenes among them. Its
;; frame loop already calls PadRead(1) at 0x80080FBC but throws the result
;; away, so the scene runs to its last frame. OPEN.EXE (the Zhuangzi quote)
;; and ATLUS.EXE (the logo) have their own loops and already leave on
;; Start.
;;
;; The loop's `jal VSync` at 0x80080FC4 runs with PadRead's result still in
;; v0: the subtitle hook at 0x80080FBC tail-jumps to PadRead, so its return
;; value reaches the loop. Replacing that call sends it through a stub
;; which raises g_movie_end - the flag StrGetReadyFrame raises two frames
;; from the end. The loop then leaves by the ordinary end-of-stream path,
;; so the movie-after table still sets the scene, map and position the
;; movie returns to.
;;
;; g_movie_end sits at gp+0 (the loop reads it with `lw v1,(gp)`), and
;; MOVIE.EXE's crt0 has set gp long before the first frame.
;;
;; The stub lives in the zero padding the EXE already carries between the
;; player's data and the subtitle blob at 0x80160000. That padding is
;; inside the loader's t_size (see movie_exe/subs_boot.asm), so the disc
;; image does not grow and the loader drops the stub straight into RAM.
;; =============================================================
.definelabel mov_vsync_call, 0x80080FC4    ; jal VSync; its delay slot sets a0 = 0
.definelabel mov_vsync,      0x8008AD88    ; VSync
.definelabel mov_pad_start,  0x0800        ; PADstart (PSY-Q 3.5 libetc.h: 1 << 11)
.definelabel mov_skip_stub,  0x8015FF00    ; the EXE's loaded zero padding

.org mov_vsync_call
    jal     mov_skip_stub

.org mov_skip_stub
    addiu   sp, sp, -0x18
    sw      ra, 0x14(sp)
    andi    t0, v0, mov_pad_start
    beqz    t0, mov_skip_vsync
    nop
    li      t0, 1
    sw      t0, 0(gp)                       ; g_movie_end = 1
mov_skip_vsync:
    jal     mov_vsync
    move    a0, zero
    lw      ra, 0x14(sp)
    addiu   sp, sp, 0x18
    jr      ra
    nop
