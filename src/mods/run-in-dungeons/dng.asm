;; =============================================================
;; Run in dungeons: hold the run button to walk and turn at 2x, 3x or 4x
;; speed in 3D dungeons. The selected integer lives in dng_run_speed.
;;
;; Every tile and turn keeps all nine view/heading advances. Only drawn
;; frames are skipped. The field's main loop draws one frame of its own after
;; every step or turn (FieldUpdate, then FieldFrame), and that frame shows the
;; final advance, so a tile costs the walk's frames plus that one (ten in
;; retail). The masks leave the final advance to it: 2x draws 4 frames in the
;; walk (5 with the loop's), 3x draws 3/2/2 (4/3/3), and 4x 2/1 (3/2). Every drawn
;; frame still calls one FieldFrame, keeping game ticks and the play clock
;; at their real rate.
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
.definelabel dngrun_turn_start,  0x80069040    ; FieldTurn's jal FieldPauseBgm
.definelabel dngrun_pause_bgm,   0x8006A6D0    ; FieldPauseBgm()
.definelabel dngrun_turn_end,    0x800690D4    ; FieldTurn's epilogue
.definelabel dngrun_vsync,       0x80025C98    ; VSync(n)
DNGRUN_TURN_REPEAT equ 27                      ; vblanks: a retail turn's nine 3-vblank frames

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
;; FieldTurn's start (its call to FieldPauseBgm, s0-s3 and ra saved): a held
;; direction repeats a running turn no faster than retail's (dngrun_turn_gate).
.org dngrun_turn_start
    jal     dngrun_turn_gate

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
dng_run_turned:
    .word   0                           ; vblank count when the last turn started
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

;; Select a complete-tile mask. No mask draws the final advance: the main
;; loop's frame after the step or turn shows the exact endpoint. Counting
;; that frame, retail draws 10 per tile; 2x draws 5, 3x 4+3+3, and 4x 3+2.
;; dng_run_parity is the position in the speed's cycle.
dngrun_next_mask:
    la      t0, dng_run_speed
    lbu     t1, 0(t0)
    lbu     t2, 1(t0)
    ori     t3, zero, 3
    beq     t1, t3, @@triple
    ori     t3, zero, 4
    beq     t1, t3, @@quadruple
    nop
    sb      zero, 1(t0)
    b       @@store
    ori     v0, zero, 0x154                 ; 2 4 6 8
@@triple:
    addiu   t3, t2, 1
    sltiu   at, t3, 3
    bnez    at, @@triple_next
    nop
    move    t3, zero
@@triple_next:
    sb      t3, 1(t0)
    bnez    t2, @@store
    ori     v0, zero, 0x048                 ; 3 6
    b       @@store
    ori     v0, zero, 0x094                 ; 2 4 7
@@quadruple:
    xori    t3, t2, 1
    andi    t3, t3, 1
    sb      t3, 1(t0)
    bnez    t2, @@store
    ori     v0, zero, 0x010                 ; 4
    ori     v0, zero, 0x048                 ; 3 6
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

;; ---- FieldTurn's start -------------------------------------------------
;; Running (Cross held), a turn starts at once on a fresh press of Left or
;; Right; while the direction stays held from the turn before, the next one
;; waits until DNGRUN_TURN_REPEAT vblanks (a retail turn's nine frames) have
;; passed since that turn started, and FieldTurn returns through its own
;; epilogue meanwhile (the main loop draws its frame and asks again). A tap
;; turns at the run speed; a held direction spins no faster than retail.
;; Walking keeps every turn as retail. Tail-calls FieldPauseBgm when the
;; turn goes ahead, so FieldTurn carries on as retail.
dngrun_turn_gate:
    addiu   sp, sp, -0x18
    sw      ra, 0x10(sp)
    jal     dngrun_vsync
    addiu   a0, zero, -1                        ; VSync(-1): the vblank count
    lw      ra, 0x10(sp)
    addiu   sp, sp, 0x18
    la      t0, dng_run_turned
    lw      t1, 0(t0)
    lui     t2, ((dngrun_scene_ptr + 0x8000) >> 16) & 0xFFFF
    lw      t2, (dngrun_scene_ptr & 0xFFFF)(t2)
    lui     t3, 7
    addu    t2, t2, t3
    lw      t4, -0x1AFC(t2)                     ; scene->pad_held
    lw      t5, -0x1AF8(t2)                     ; scene->pad_new
    andi    t4, t4, 0x40                        ; Cross
    beqz    t4, @@turn
    andi    t5, t5, 0xA000                      ; (delay) a fresh Left or Right
    bnez    t5, @@turn
    subu    t1, v0, t1                          ; (delay) vblanks since the last turn
    sltiu   at, t1, DNGRUN_TURN_REPEAT
    beqz    at, @@turn
    nop
    j       dngrun_turn_end                     ; held, too soon: no turn this time
    nop
@@turn:
    sw      v0, 0(t0)
    j       dngrun_pause_bgm
    nop

.if . > DNG_RUN_LIMIT
    .error "mod/run: the run block overruns the loaded image extension (DNG_RUN_LIMIT)"
.endif
