;; =============================================================
;; Run in dungeons: hold the run button to walk and turn at 2x, 3x or 4x
;; speed in 3D dungeons. The selected integer lives in dng_run_speed.
;;
;; Every tile and turn keeps all nine view/heading advances. Only drawn
;; frames are skipped: 2x draws 5/4 frames, 3x draws 3, and 4x draws 3/2/2/2.
;; Each mask includes the final advance. Every drawn frame still calls one
;; FieldFrame, keeping game ticks and the play clock at their real rate.
;;
;; The button is the game's own run action, not a settings row of its own: the
;; controller page's action table gets one more action, and both field pad
;; types show it on Cross - the button the game also uses to cancel, which is
;; fine because cancel is edge-triggered while running only reads the held
;; pad. Cross is free in TYPE 2 and already CANCEL in TYPE 1, so the page
;; names it RUN/CANCEL in both. The walk and turn hooks wait for the game's
;; Cross regardless of pad type; with the western controls
;; (mods/western-controls/slps.asm) that is the Circle button in TYPE 1, and the page
;; entry moves with it. The page's 19-pointer name table sits directly in front of the
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

;; FieldTurn's own nine-frame loop keeps every heading step and applies
;; the same selected-speed frame masks as walking while Cross is held.
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
.ifdef MOD_WESTERN_CONTROLS
.org DNG_PAD_LAYOUTS + DNG_PAD_CIRCLE   ; TYPE 1's cancel button is Circle now
.else
.org DNG_PAD_LAYOUTS + DNG_PAD_CROSS
.endif
    .byte   DNG_PAD_RUN_INDEX
.org DNG_PAD_LAYOUTS + DNG_PAD_LAYOUT_ENTRIES + DNG_PAD_CROSS
    .byte   DNG_PAD_RUN_INDEX

.org DNG_RUN_ADDR
;; The shared range writer patches this byte. Keep it first in the reserved
;; block so values.tsv's file offset remains independent of code size.
dng_run_speed:
    .byte   2
dng_run_parity:
    .byte   0
dng_run_mask:
    .halfword 0
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

    ;; Choose the selected speed's next complete-tile frame mask.
    jal     dngrun_next_mask
    nop
    move    s2, v0
    b       @@steps
    nop

@@retail:
    ;; Not running (or the button was released): draw every advance, and
    ;; restart the alternation so the next run tile begins on the 5-frame
    ;; mask.
    la      t0, dng_run_parity
    sb      zero, 0(t0)
    sh      zero, 1(t0)                     ; clear the cached mask too
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

;; Select a complete-tile mask. Every mask draws the final advance, so a
;; turn or tile always lands visibly at its exact endpoint. Over a cycle,
;; 2x draws 5+4 frames, 3x draws 3, and 4x draws 3+2+2+2.
dngrun_next_mask:
    la      t0, dng_run_speed
    lbu     t1, 0(t0)
    lbu     t2, 1(t0)
    ori     t3, zero, 3
    beq     t1, t3, @@triple
    nop
    ori     t3, zero, 4
    beq     t1, t3, @@quadruple
    nop
    andi    t2, t2, 1
    xori    t3, t2, 1
    sb      t3, 1(t0)
    sll     t3, t3, 8
    b       @@store
    ori     v0, t3, 0x254
@@triple:
    sb      zero, 1(t0)
    b       @@store
    ori     v0, zero, 0x248
@@quadruple:
    andi    t2, t2, 3
    addiu   t3, t2, 1
    andi    t3, t3, 3
    sb      t3, 1(t0)
    ori     v0, zero, 0x210
    bnez    t2, @@store
    nop
    ori     v0, zero, 0x310
@@store:
    sh      v0, 2(t0)
    jr      ra
    nop

;; ---- FieldTurn's frame ------------------------------------------------
;; Called from FieldTurn's loop after the heading has advanced, with s1 = the
;; frame number (1..9). Holding Cross draws only the frames the run mask
;; covers; otherwise every frame is drawn and the cycle restarts, exactly
;; like dngrun_walk's retail path.
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

    ;; Pick a mask only once per turn, sharing the cycle with walking.
    ori     t2, zero, 1
    beq     s1, t2, @@new_mask
    nop
    la      t0, dng_run_mask
    lhu     t1, 0(t0)
    nop
    bnez    t1, @@mask
    nop
@@new_mask:
    addiu   sp, sp, -0x18
    sw      ra, 0x10(sp)
    jal     dngrun_next_mask
    nop
    lw      ra, 0x10(sp)
    addiu   sp, sp, 0x18
@@mask:
    la      t0, dng_run_mask
    lhu     t1, 0(t0)
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
    sh      zero, 1(t0)                     ; a mid-turn press starts a mask
    j       dngrun_frame
    nop
@@done:
    jr      ra
    nop

.if . > DNG_RUN_LIMIT
    .error "mod/run: the run block overruns the loaded image extension (DNG_RUN_LIMIT)"
.endif
