;; =============================================================
;; Battle speedup, the `entry` range: the overworld's field -> battle
;; transition at that speed, 1 being retail (S2D.BIN).
;;
;; S2dRunMap's exit switch (jump table 0x80064EF4, on g_s2d_exit; decomp
;; src/s2d/game/s2drun.c) sends a battle (exit 2, 0x8008B8A0) to the
;; transition at 0x80092828 (Rev 1 func_8009224C). Its frame loop
;; (0x80092BFC..0x80092F98) runs until every one of its 300 pieces has
;; settled (piece +0x10 back to 0), each frame in three parts:
;;   0x80092C68  every piece moves (position, fall, size; started by the
;;               timer s5) - cheap
;;   0x80092D08  every piece is transformed and sorted (matrices, RotTrans,
;;               GsSortPoly) - the expensive part
;;   0x80092ED4  the timer s5 steps, DrawSync(0), then VSync(0),
;;               ResetGraph(1), GsSwapDispBuff, GsSortClear, GsDrawOt
;; and the settled test at 0x80092F70 (s2 = 0) closes it.
;;
;; Of every BSS_SPEED frames the last is drawn as retail (bss_plan, at the
;; transform loop's start; bss_present, at its VSync). The others move the
;; pieces and step the timer, then skip the transform loop and everything
;; from the VSync to the draw (no swap, so the next frame clears and builds
;; the same buffer). Such a frame costs only the piece moves, so the
;; transition runs BSS_SPEED times as fast at retail's frame rate.
;;
;; bss_vars is at a fixed address: the `entry` range writes its first byte
;; in the built file (values.tsv). At 1 every frame is drawn, as retail.
;; =============================================================
.definelabel bss_vsync, 0x80025C98      ; VSync(n)
.definelabel bss_reset, 0x8002B14C      ; ResetGraph(n)
.definelabel bss_timer, 0x80092ED4      ; after the transform loop: the timer step
.definelabel bss_settled, 0x80092F70    ; the settled test (s2 = 0)

.org 0x80092D08                         ; the transform loop's start: move s2, zero / move s3, s4
    jal     bss_plan
    move    s3, s4
.org 0x80092F08                         ; jal VSync / move a0, zero / jal ResetGraph / ori a0, 1
    jal     bss_present
    move    a0, zero
    nop
    nop

;; The dead StatusSlotDraw's first 0x180 bytes; overworld-run-speed's
;; s2d.asm has the rest.
.org S2D_BSD_ADDR
.area 0x180
bss_vars:
    .byte   1                           ; SPEED: written by the `entry` range
    .byte   0                           ; frames since the last drawn one
    .byte   0                           ; this frame is hidden
.align 4
;; At the transform loop's start (s2 = 0 for it): the group's last frame goes
;; on into the loop; the others skip it to the timer step, with the loop
;; branch's delay-slot value (v1 = s5 - 0x320) the step takes.
bss_plan:
    lui     t0, hi(bss_vars)
    addiu   t0, t0, lo(bss_vars)
    lbu     t1, 1(t0)
    lbu     t2, 0(t0)
    addiu   t1, t1, 1
    sltu    at, t1, t2                  ; not yet the group's last frame
    bnez    at, @@hidden
    move    s2, zero                    ; (delay)
    sb      zero, 1(t0)
    jr      ra
    sb      zero, 2(t0)                 ; (delay) drawn
@@hidden:
    sb      t1, 1(t0)
    ori     at, zero, 1
    sb      at, 2(t0)
    j       bss_timer
    addiu   v1, s5, -0x320              ; (delay)

;; At the frame's VSync (a0 = 0): a drawn frame waits and resets as retail
;; and goes on to the swap and the draw; a hidden one goes straight to the
;; settled test.
bss_present:
    lui     t0, hi(bss_vars)
    lbu     t1, lo(bss_vars + 2)(t0)
    nop
    bnez    t1, @@hidden
    nop
    addiu   sp, sp, -0x18
    sw      ra, 0x10(sp)
    jal     bss_vsync
    move    a0, zero
    jal     bss_reset
    ori     a0, zero, 1
    lw      ra, 0x10(sp)
    nop
    jr      ra
    addiu   sp, sp, 0x18
@@hidden:
    j       bss_settled
    move    s2, zero                    ; (delay)
.endarea
.if bss_vars != S2D_BSD_ADDR
    .error "bss_vars moved: values.tsv writes its offset"
.endif
