;; =============================================================
;; QoL (separate enhancement build): hold a button to walk and turn at double
;; speed in the 3D dungeons (DNG.BIN).
;;
;; FieldWalk advances the view nine times per tile and draws a frame after
;; each advance (FieldStepView + FieldFrame, nine 20 Hz ticks). Running keeps
;; every one of those nine advances - so the tile, the collision checks, the
;; step counter and the exact landing position are unchanged - and only skips
;; drawn frames: a five-frame mask on one tile and a four-frame mask on the
;; next average 4.5 frames per tile, exactly half. Every drawn frame still
;; runs one FieldFrame, i.e. exactly one game tick, so the play clock and the
;; animation counters keep their real rate.
;;
;; FieldTurn swings the heading round in nine frames the same way, one
;; FieldFrame per frame; holding Cross skips frames on the same 5/4 masks, so
;; turning gets the same double speed while every heading step still runs.
;;
;; The button is the game's own run action, not a settings row of its own: the
;; controller page's action table gets one more action, and both field pad
;; types show it on Cross - the button the game also uses to cancel, which is
;; fine because cancel is edge-triggered while running only reads the held
;; pad. Cross is free in TYPE 2 and already CANCEL in TYPE 1, so the page
;; names it RUN/CANCEL in both. The walk and turn hooks wait for Cross
;; regardless of pad type. The page's 19-pointer name table sits directly in front of the
;; layout table with no room for a 20th, so runtext.py copies it into the
;; image extension with the run pointer appended and this file repoints
;; PadDrawLayout's table base at the copy. Wording comes from
;; translation/manual/terms.tsv (runtext.py -> build/runtext_dng.asm); nothing
;; in this file spells an action name.
;; =============================================================
.definelabel dngrun_step_begin,  0x80068C94    ; FieldStepBegin()
.definelabel dngrun_step_view,   0x80068AA0    ; FieldStepView()
.definelabel dngrun_frame,       0x800659B4    ; FieldFrame() - one 20 Hz tick
.definelabel dngrun_zone_tunes,  0x8007108C    ; FieldZoneTunes(0)
.definelabel dngrun_step_end,    0x80068B64    ; FieldStepEnd()
.definelabel dngrun_step_tick,   0x80069754    ; FieldStepTick()
.definelabel dngrun_walk_done,   0x80069010    ; FieldWalk's common return
.definelabel dngrun_scene_ptr,   0x800A10D8    ; g_scene; held pad is +0x6E504

;; The retail animation block: FieldStepBegin, 5x (StepView, Frame), the zone
;; tune, 4x (StepView, Frame), StepEnd, StepTick. The walk entry hooks it as a
;; whole; the nine advances become one counted loop with a frame mask.
.org 0x80068F64
    j       dngrun_walk
    nop

;; FieldTurn's own nine-frame loop: FieldSetHeading, then this FieldFrame.
;; The wrapper keeps the heading step and draws the frame only on the run
;; mask, so turning is as fast as walking while Cross is held.
.org DNG_TURN_FRAME
    jal     dngrun_turn_frame
    nop

;; PadDrawLayout: the action-name table now lives in the image extension (the
;; retail one has no room for a twentieth pointer).
.org DNG_PAD_DRAW_LUI
    lui     at, ((DNG_RUN_PAD_NAMES + 0x8000) >> 16) & 0xFFFF
.org DNG_PAD_DRAW_ADDIU
    addiu   at, at, DNG_RUN_PAD_NAMES & 0xFFFF

;; The run action on Cross in each field pad type's 3D column (the first ten
;; entries of a layout; entries 10..19 are the 2D column, which keeps its
;; retail names because running only applies to the 3D view). Cross reads
;; "CANCEL" in TYPE 1 and "UNUSED" in TYPE 2; the page names it RUN/CANCEL
;; in both.
.org DNG_PAD_LAYOUTS + DNG_PAD_CROSS
    .byte   DNG_PAD_RUN_INDEX
.org DNG_PAD_LAYOUTS + DNG_PAD_LAYOUT_ENTRIES + DNG_PAD_CROSS
    .byte   DNG_PAD_RUN_INDEX

.org DNG_RUN_ADDR
;; ---- the walk hook ---------------------------------------------------
;; Entry: s1 = FieldWalk's return argument (must reach the common return in
;; v0); s0 and s1 are FieldWalk's saved scratch; ra is FieldWalk's return
;; address and is restored by dngrun_walk_done. FieldWalk does not save s2, so
;; the frame mask uses it and saves it here.
dngrun_walk:
    addiu   sp, sp, -0x18
    sw      s2, 0x10(sp)
    jal     dngrun_step_begin
    nop

    ;; Cross runs in both pad types. This is the same button the controller
    ;; page now draws the run action against.
    lui     t2, ((dngrun_scene_ptr + 0x8000) >> 16) & 0xFFFF
    lw      t2, (dngrun_scene_ptr & 0xFFFF)(t2)
    lui     t3, 7                               ; fills the scene load's delay slot
    addu    t2, t2, t3
    lw      t2, -0x1AFC(t2)                     ; scene->pad_held
    nop
    andi    t1, t2, 0x40                        ; Cross
    beqz    t1, @@retail
    nop

    ;; Running. Frames are drawn after step 2, 4, 6, 9 and, on alternate
    ;; tiles, step 8: the 5-frame mask on even tiles and the 4-frame mask on
    ;; odd ones average exactly 4.5 of the nine advances.
    la      t0, dng_run_parity
    lbu     t1, 0(t0)
    nop
    andi    t1, t1, 1
    xori    t2, t1, 1
    sb      t2, 0(t0)
    sll     t2, t2, 8
    ori     s2, t2, 0x254
    b       @@steps
    nop

@@retail:
    ;; Not running (or the button was released): draw every advance, and
    ;; restart the alternation so the next run tile begins on the 5-frame
    ;; mask.
    la      t0, dng_run_parity
    sb      zero, 0(t0)
    ori     s2, zero, 0x3FE

@@steps:
    move    s0, zero
@@step:
    addiu   s0, s0, 1
    jal     dngrun_step_view
    nop
    ori     t0, zero, 1
    sllv    t0, t0, s0
    and     t0, t0, s2
    beqz    t0, @@no_frame
    nop
    jal     dngrun_frame
    nop
@@no_frame:
    ori     t0, zero, 5
    bne     s0, t0, @@after_zone
    nop
    jal     dngrun_zone_tunes
    move    a0, zero
@@after_zone:
    slti    v0, s0, 9
    bnez    v0, @@step
    nop

    jal     dngrun_step_end
    nop
    jal     dngrun_step_tick
    nop
    lw      s2, 0x10(sp)
    addiu   sp, sp, 0x18
    j       dngrun_walk_done
    move    v0, s1

;; Which tile of a run is drawn with the 5-frame mask (1) or the 4-frame one
;; (0). FieldWalk's own code leaves it 0, so the first run tile is the dense
;; one. Turns share it, so a turn also alternates the masks.
dng_run_parity:
    .byte   0
.align 4

;; ---- FieldTurn's frame ------------------------------------------------
;; Called from FieldTurn's loop after the heading has advanced, with s1 = the
;; frame number (1..9). Holding Cross draws only the frames the run mask
;; covers; otherwise every frame is drawn and the parity is put back to the
;; dense tile, exactly like dngrun_walk's retail path.
dngrun_turn_frame:
    lui     t2, ((dngrun_scene_ptr + 0x8000) >> 16) & 0xFFFF
    lw      t2, (dngrun_scene_ptr & 0xFFFF)(t2)
    lui     t3, 7
    addu    t2, t2, t3
    lw      t2, -0x1AFC(t2)                     ; scene->pad_held
    nop
    andi    t2, t2, 0x40                        ; Cross
    beqz    t2, @@retail
    nop

    ;; Toggle the shared parity once per turn, on the first frame.
    la      t0, dng_run_parity
    lbu     t1, 0(t0)
    ori     t2, zero, 1
    bne     s1, t2, @@mask
    nop
    xori    t1, t1, 1
    sb      t1, 0(t0)
@@mask:
    andi    t1, t1, 1
    sll     t1, t1, 8
    ori     t1, t1, 0x254
    ori     t0, zero, 1
    sllv    t0, t0, s1
    and     t0, t0, t1
    beqz    t0, @@done
    nop
    j       dngrun_frame
    nop

@@retail:
    la      t0, dng_run_parity
    sb      zero, 0(t0)
    j       dngrun_frame
    nop
@@done:
    jr      ra
    nop

.if . > DNG_RUN_LIMIT
    .error "qol/run: the run block overruns the loaded image extension (DNG_RUN_LIMIT)"
.endif
