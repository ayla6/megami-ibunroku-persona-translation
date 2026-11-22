;; =============================================================
;; Battle speedup, the `entry` range: the dungeon's field -> battle
;; transitions at that speed, 1 being retail (DNG.BIN).
;;
;; A battle opens with FieldFxRun (the shattering, 64 steps of FieldFxStep)
;; or FieldWaveFxRun (the wave, 65 steps of FieldWaveFxStep); decomp
;; src/dng/field/fieldfx.c, fieldfxwave.c. Each step moves every tile or
;; column, sorts it into the ordering table of the buffer being drawn, then
;; VSync(2), FieldClockTick(2), GsSwapDispBuff, GsSortClear, GsDrawOt.
;;
;; The step's VSync / clock pair goes through bsd_gate. Of every BSD_SPEED
;; steps, the last is drawn: it waits and ticks the play clock as retail and
;; goes on to the swap and the draw. The others return straight through the
;; step's epilogue: every tile still moves, but the buffer is neither swapped
;; nor drawn, so the next step clears and rebuilds the same one. BSD_SPEED
;; steps per shown frame: the transition runs BSD_SPEED times as fast, at
;; retail's frame rate, and the play clock counts the real time.
;;
;; A hidden step also skips what only drawing needs: FieldFxStep's tile
;; transform (0x80071A98, where both of a tile's move paths meet, up to the
;; loop's step at 0x80071BE8: matrices, RotNclip4, GsSortPoly) through
;; bsd_tile, and FieldWaveFxStep's GsSortSprite per column through
;; bsd_sprite. So a hidden step costs only the moves, and the group's steps
;; fit in the drawn step's two vblanks.
;;
;; bsd_vars is at a fixed address: the `entry` range writes its first byte
;; in the built file (values.tsv). At 1 every step is the group's last, so
;; each one is drawn as retail.
;; =============================================================
.definelabel bsd_vsync, 0x80025C98      ; VSync(n)
.definelabel bsd_clock, 0x800678AC      ; FieldClockTick(n)
.definelabel bsd_sort_sprite, 0x80033438 ; GsSortSprite(sprite, ot, pri)

.org 0x80071C00                         ; FieldFxStep: VSync(2), FieldClockTick(2)
    jal     bsd_gate
    nop
    beqz    v0, 0x80071C7C              ; hidden: the epilogue
    nop
.org 0x80071A98                         ; FieldFxStep's tile transform: lui a0, 0x800A / addiu a0, 0xA74
    jal     bsd_tile
    nop
.org 0x8007258C                         ; FieldWaveFxStep's jal GsSortSprite (its delay slot stays)
    jal     bsd_sprite
.org 0x800725A0                         ; FieldWaveFxStep: the same pair
    jal     bsd_gate
    nop
    beqz    v0, 0x80072618
    nop

.org DNG_BSD_ADDR
.area DNG_BSD_LIMIT - DNG_BSD_ADDR
bsd_vars:
    .byte   1                           ; SPEED: written by the `entry` range
    .byte   0                           ; steps since the last drawn one
.align 4
;; v0 = 1: this step is drawn (VSync(2) and FieldClockTick(2) done); 0: hidden.
bsd_gate:
    lui     t0, hi(bsd_vars)
    addiu   t0, t0, lo(bsd_vars)
    lbu     t1, 1(t0)
    lbu     t2, 0(t0)
    addiu   t1, t1, 1
    sltu    at, t1, t2                  ; not yet the group's last step
    beqz    at, @@drawn
    nop
    sb      t1, 1(t0)
    jr      ra
    move    v0, zero
@@drawn:
    sb      zero, 1(t0)
    addiu   sp, sp, -0x18
    sw      ra, 0x10(sp)
    jal     bsd_vsync
    ori     a0, zero, 2
    jal     bsd_clock
    ori     a0, zero, 2
    lw      ra, 0x10(sp)
    ori     v0, zero, 1
    jr      ra
    addiu   sp, sp, 0x18

;; t1 = 1: this step is hidden (not yet the group's last; bsd_gate counts it
;; at the step's end).
bsd_hidden:
    lui     t0, hi(bsd_vars)
    lbu     t1, lo(bsd_vars + 1)(t0)
    lbu     t2, lo(bsd_vars)(t0)
    addiu   t1, t1, 1
    jr      ra
    sltu    t1, t1, t2

;; FieldFxStep's tile transform: drawn, retail's a0 and on; hidden, the next tile.
bsd_tile:
    move    t3, ra
    jal     bsd_hidden
    nop
    bnez    t1, @@skip
    lui     a0, 0x800A                  ; (delay) &g_fx_shift, as retail
    jr      t3
    addiu   a0, a0, 0xA74
@@skip:
    j       0x80071BE8
    nop

;; FieldWaveFxStep's GsSortSprite (a0-a2 as retail): drawn, sorted; hidden, not.
bsd_sprite:
    move    t3, ra
    jal     bsd_hidden
    nop
    bnez    t1, @@unsorted
    move    ra, t3                      ; (delay)
    j       bsd_sort_sprite
    nop
@@unsorted:
    jr      ra
    nop
.endarea
.if bsd_vars != DNG_BSD_ADDR
    .error "bsd_vars moved: values.tsv writes its offset"
.endif
