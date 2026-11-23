;; =============================================================
;; Overworld run speed (--mods=overworld-run-speed): the overworld map's own
;; run at the selected 2-4x of walking (S2D.BIN).
;;
;; A step on the map starts in the walking mode (0x8008D3D0) with a call to
;; the step start 0x8008B2F4(step) at 0x8008D73C: the step's remaining count
;; is set to 0x1000 and the position tick (0x8008B39C, once per 15 Hz update)
;; draws the party at remaining x direction, then takes `step` off it; at 0
;; or below the party has arrived (walk cycle, arrival handlers). Walking
;; passes 0x400 (four ticks a cell); holding the pad type's run button (the
;; bind at 0x800B15D8 against the held pad 0x800B15C4) passes 0x800 (two
;; ticks): the game's own run, twice walking.
;;
;; The count starts afresh every step, so a step takes a whole number of
;; ticks. owrun_start replaces the run's 0x800 by the selected speed's cycle:
;; 2x keeps 0x800 (two ticks a cell, retail), 4x passes 0x1000 (one tick a
;; cell), 3x passes 0x1000, 0x1000, 0x800 in turn (three cells in four
;; ticks). Walking keeps 0x400 and restarts the 3x cycle.
;;
;; A one-tick step must still end the forced step. Arriving on a cell flagged
;; 0x1000 in the map sets the forced-step bit 0x80 of 0x800A560C, and the
;; walking mode then starts one more step in the last direction without input.
;; Retail clears that bit (0x560C &= ~0x81 at 0x8008DDD4) only in a walking
;; mode tick that finds the step still in progress (0x800A53F8 != 1). A step
;; of 0x1000 arrives in the tick it starts, so no such tick ever comes: the
;; forced step would repeat every step, carrying the party past the map's
;; edge cells into the blocking event cells, whose script ("that's the way
;; out of town") then runs again after every forced try. owrun_start does
;; that clear itself whenever it passes 0x1000; nothing between the step
;; start and the next walking mode tick reads 0x800A560C.
;;
;; owrun_vars sits at a fixed address, the dead StatusSlotDraw's bytes from
;; +0x180 (battle-speedup's s2d.asm has the first 0x180): the `speed` range
;; writes its first byte in the built file (values.tsv).
;; =============================================================
.definelabel owrun_step_start, 0x8008B2F4   ; step start (a0 = the per-tick step)
.definelabel owrun_walk_flags, 0x800A560C   ; 0x80: forced step; low nibble: its direction

.org 0x8008D73C                         ; the walking mode's jal step start (delay slot nop stays)
    jal     owrun_start

.org S2D_BSD_ADDR + 0x180
.area S2D_BSD_LIMIT - (S2D_BSD_ADDR + 0x180)
owrun_vars:
    .byte   3                           ; SPEED: written by the `speed` range
    .byte   0                           ; the 3x cycle's place
.align 4
;; a0 = 0x400 (walking) or 0x800 (the run): the run's step for the speed.
owrun_start:
    lui     t1, hi(owrun_vars)
    addiu   t1, t1, lo(owrun_vars)
    ori     t0, zero, 0x800
    bne     a0, t0, @@walk
    lbu     t2, 0(t1)                   ; (delay) the speed
    lbu     t3, 1(t1)
    ori     t0, zero, 3
    beq     t2, t0, @@triple
    ori     t0, zero, 4
    bne     t2, t0, @@start             ; 2x: retail's 0x800
    nop
    b       @@one_tick                  ; 4x: one tick a cell
    nop
@@triple:
    addiu   t4, t3, 1
    xori    at, t4, 3
    bnez    at, @@next
    nop
    move    t4, zero
@@next:
    sb      t4, 1(t1)
    ori     t0, zero, 2
    beq     t3, t0, @@start             ; the cycle's third: 0x800
    nop
@@one_tick:                             ; its first two, and 4x: 0x1000
    lui     t0, hi(owrun_walk_flags)
    lw      t2, lo(owrun_walk_flags)(t0)
    addiu   at, zero, -0x81
    and     t2, t2, at                  ; the walking mode's in-progress clear
    sw      t2, lo(owrun_walk_flags)(t0)
    j       owrun_step_start
    ori     a0, zero, 0x1000            ; (delay)
@@start:
    j       owrun_step_start
    nop
@@walk:
    j       owrun_step_start
    sb      zero, 1(t1)                 ; (delay) walking restarts the cycle
.endarea
.if owrun_vars != S2D_BSD_ADDR + 0x180
    .error "owrun_vars moved: values.tsv writes its offset"
.endif
