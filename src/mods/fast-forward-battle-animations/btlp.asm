;; =============================================================
;; Fast forward battle animations (--mods=fast-forward-battle-animations): START fast-forwards a battle turn (BTLP.BIN).
;;
;; BtlDrawFrame 0x80080F14 presents every battle tick (the main loop at
;; 0x80092270 and ~280 scripted waits call it).
;;
;; START fast-forward (as the PSP's battle skip). START while a turn plays
;; out (g_btl_stage is BtlStageRound, or AUTO on) toggles it; START anywhere in
;; BtlStageCommand (the picker, the per-member walk and its formation grid, a
;; negotiation) stays the game's (and --mods=debug-tools's page). g_btl_step is no
;; test: BtlStageCommand and BtlCommandEntry use it as their own inner state.
;; It ends by itself when the round is over (stage no longer BtlStageRound,
;; AUTO off), and for good when
;; the battle is over: the round flow's battle-over branch (victory and defeat
;; alike, before the experience count, the level-up board or the defeat line)
;; switches it off and START is the game's again until the next battle. While
;; it is on, a small ">>" shows at the top right.
;;
;; Every tick still runs the whole battle: logic, object scripts and
;; animation steps, BtlDrawObjects' own state work (positions handed to
;; shadows / attached pieces / markers, the colour fades, the flat / rotated
;; kind choice), the 2D layer, the VRAM queues and the GPU submit of the
;; ordering table, so nothing the battle sends the GPU is ever dropped. What
;; changes is which ticks are drawn and shown. The ticks run in groups of
;; FF_MULT (the `rate` range, FF_RATE by default) times the turn's own speed
;; (1, or battle-speedup's):
;;   tick 0   waits for the vblank and shows the frame the last group drew
;;   tick 1.. HIDDEN: no object is drawn (BtlDrawObjects' per-object handler
;;            call 0x80082A9C goes through ff_obj_draw, which returns at once;
;;            the handlers only build primitives, decomp src/btlp/obj*.c), the
;;            arena faces and the floor mesh are not built (0x80082E6C ->
;;            ff_arena), and the ordering table goes to the GPU with an EMPTY
;;            drawing area (clip 1,1 size 0,0 -> GP0 E3 (1,1), E4 (0,0)) and no
;;            background fill, so what is still linked rasterises nothing.
;;            VRAM transfers and copies are not clipped and still happen.
;;            These ticks skip the GTE transforms and primitive building that
;;            make a battle tick expensive, so they cost logic time only.
;;   last     draws normally (into the back buffer); the next tick 0 shows it.
;; A drawn tick flips the buffers as in retail, so packets and ordering
;; tables are never rewritten while the GPU reads them (see Buffers below).
;; On/off takes effect at a group's tick 0 only, so every shown
;; frame is a finished one. The display then runs at up to 60 fps while the
;; battle runs that many ticks per shown frame.
;;
;; With --mods=battle-speedup on, its own copy of this rewrite
;; (mods/battle-speedup/btlp.asm) is left out and this one runs its speeds.
;; A group's size is chosen at its tick 0 (ff_plan). While a turn plays out
;; (BtlStageRound or AUTO; the command picker, the formation grid and a
;; negotiation stay retail) it is FF_SKILLS in summons and skills and
;; FF_ACTIONS in the rest of the turn (attacks, the enemies' actions, the
;; messages); while the entry camera moves (g_btl_intro_step 4) FF_ENTRY;
;; else 1. Fast-forwarding multiplies it by FF_MULT. The three speeds are 1
;; unless battle-speedup's ranges write them (its values.tsv, at ff_vars'
;; fixed address). A shown tick
;; keeps retail's waits (the vblank count behind the half-rate second wait is
;; reset on shown ticks only, so a group's own time counts), so N ticks per
;; shown frame are N times retail speed, at retail's frame rate, with only
;; one tick in N drawn.
;;
;; Buffers: a drawn tick flips g_btl_frame as retail; a hidden tick does not,
;; so the next tick builds in the same buffer and a drawn tick always draws
;; into the buffer that is not on screen, whatever the group size. A hidden
;; tick pre-flips it and waits for its (empty) submit to finish (DrawSync)
;; before the next tick rewrites that buffer's ordering table and packets.
;;
;; BtlDrawFrame is -O0 code (0x80080F14..0x8008136B); it is rewritten
;; compactly with the same calls in the same order, and the fast-forward lives
;; in the room this frees. The prologue up to BtlCheatWatch's call
;; (0x80080F24, which --mods=debug-tools clears) and the epilogue at 0x80081358
;; (where --mods=debug-tools's stub hooks in) keep their retail addresses. Nothing
;; jumps into the old body (only jal 0x80080F14).
;;
;; Battle globals (decomp src/btlp/drawframe.c), from s0 = 0x800D0000:
;;   -0xF96 g_btl_stage   -0xF95 g_btl_step    -0xF92 g_btl_no_help  -0xF8D g_btl_half_rate
;;   -0xF8F g_btl_intro_step (4: the entry camera moves; Rev 1 0x800CCA25 + 0x264C)
;;   -0xF8C g_btl_closing -0xF6D g_btl_frame_due -0xF6B g_btl_vsync_count
;;   -0xF68 g_btl_prim_pool  -0xF08 g_btl_frame  -0xF0C g_btl_interlace
;;   -0xF0B g_btl_blank_on_load  -0xF05 g_btl_auto_confirm
;;   -0xFA8 g_btl_delay  -0xFA6 g_btl_tick  +0x2250 AUTO mode
;; Frame buffer f: g_btl_prim_pool + f * 0xE660 = DRAWENV, +0x5C DISPENV,
;; +0xD6C0 the ordering table (1000 entries), +0xE65C its last entry.
;; =============================================================
.org 0x80080F2C                         ; after jal BtlDrawDebugHud / jal BtlCheatWatch
.area 0x80081358 - 0x80080F2C
    lui     s0, 0x800D                  ; the battle globals
    lbu     v0, -0xF6D(s0)              ; g_btl_frame_due: put the reverb back
    nop
    beqz    v0, @@no_reverb
    nop
    jal     0x8001950C                  ; SsUtSetReverbType(4)
    ori     a0, zero, 4
    ori     a0, zero, 0x7F
    jal     0x8001B6DC                  ; SsSetRVol(0x7F, 0x7F)
    ori     a1, zero, 0x7F
    ori     a0, zero, 0x38
    jal     0x8001B06C                  ; SsUtSetReverbDepth(0x38, 0x38)
    ori     a1, zero, 0x38
    jal     0x80018E2C                  ; SsUtReverbOn
    nop
    lui     v0, 0x8010
    lbu     v0, -0x7F7C(v0)             ; g_btl_bgm_index
    nop
    addu    at, s0, v0
    lbu     v1, 0x7A08(at)              ; g_btl_bgm_kinds[]
    ori     v0, zero, 3
    move    a0, zero
    bne     v1, v0, @@se
    move    a1, zero
    ori     a1, zero, 2
@@se:
    jal     0x80082310                  ; BtlSePlay(0, 0 or 2)
    nop
    sb      zero, -0xF6D(s0)
@@no_reverb:
    lw      v1, -0xFE0(s0)
    lbu     v0, -0xF08(s0)              ; g_btl_frame
    sw      v1, -0xF4C(s0)              ; g_btl_draw_dist = g_btl_screen_dist
    lw      v1, -0xF68(s0)
    ori     at, zero, 0xE660
    multu   v0, at
    mflo    v0
    addu    v0, v0, v1
    jal     ff_plan                     ; is this tick drawn, is it shown?
    sw      v0, 0x14(sp)                ; this tick's frame buffer (retail leaves the slot unused)
    lw      v0, 0x14(sp)
    ori     a0, zero, 0xD6C0
    addu    a0, v0, a0
    jal     0x8002B99C                  ; ClearOTag(ot, 1000)
    ori     a1, zero, 0x3E8
    jal     0x8008B620                  ; BtlTickObjects
    nop
    jal     0x8008AF14                  ; BtlStepCluts
    nop
    jal     0x8008B230                  ; BtlStepObjScripts
    nop
    jal     0x8008B13C                  ; BtlWaveMesh
    nop
    jal     0x80082718                  ; BtlDrawObjects
    nop
    lbu     v0, -0xF8C(s0)              ; g_btl_closing
    nop
    bnez    v0, @@closing
    nop
    lw      v0, 0x14(sp)
    ori     a0, zero, 0xE65C
    jal     0x8006B8EC                  ; BtlDrawBehind(last OT entry)
    addu    a0, v0, a0
    lw      v0, 0x14(sp)
    ori     a0, zero, 0xE65C
    jal     0x80065E98                  ; BtlDrawFront(last OT entry)
    addu    a0, v0, a0
    lw      a0, 0x14(sp)
    jal     ff_icon                     ; ">>" while fast-forwarding
    nop
    jal     0x800667BC                  ; BtlFlushVramQueues
    nop
@@closing:
    lw      v1, -0xF68(s0)              ; both DISPENVs take g_btl_interlace
    lbu     v0, -0xF0C(s0)
    lui     at, 1
    sb      v0, 0x6C(v1)
    addu    at, at, v1
    sb      v0, -0x1934(at)             ; + 0xE660 + 0x6C
    lbu     v0, -0xF0B(s0)              ; g_btl_blank_on_load
    nop
    beqz    v0, @@mask_kept
    nop
    jal     0x8002B54C                  ; SetDispMask(0)
    move    a0, zero
@@mask_kept:
    lbu     v0, -0xF8C(s0)
    nop
    bnez    v0, @@no_clut
    nop
    lw      a1, -0xFC0(s0)              ; g_btl_actor_clut
    jal     0x8002B810                  ; LoadImage(&g_btl_clut_block, ...)
    addiu   a0, s0, -0xEC4
@@no_clut:
    jal     0x8002B5E8                  ; DrawSync(0)
    move    a0, zero
    lbu     v0, -0xF0B(s0)
    nop
    beqz    v0, @@mask_done
    nop
    jal     0x8002B54C                  ; SetDispMask(1)
    ori     a0, zero, 1
@@mask_done:
    lw      a0, 0x14(sp)
    jal     ff_present                  ; VSync, PutDispEnv, PutDrawEnv, DrawOTag
    nop
    jal     0x8008E980                  ; BtlPadRead
    nop
    jal     ff_pad                      ; START during a turn: the fast-forward's
    nop
    lui     at, 0x8010
    lhu     v1, -0x7710(at)             ; g_btl_pad1_edge
    lui     v0, 0x800F
    lhu     v0, 0x7E04(v0)              ; g_btl_help_key
    nop
    and     v0, v1, v0
    beqz    v0, @@help_kept
    nop
    lbu     v0, -0xF92(s0)
    nop
    xori    v0, v0, 1
    sb      v0, -0xF92(s0)
@@help_kept:
    lbu     v0, -0xF05(s0)              ; g_btl_auto_confirm presses Confirm
    nop
    beqz    v0, @@no_auto
    ori     v0, v1, 0x20
    sh      v0, -0x7710(at)
@@no_auto:
    lh      v0, -0xFA8(s0)              ; g_btl_delay
    nop
    blez    v0, @@no_delay
    addiu   v0, v0, -1
    sh      v0, -0xFA8(s0)
@@no_delay:
    lhu     v0, -0xFA6(s0)
    lbu     v1, -0xF08(s0)
    addiu   v0, v0, 1
    xori    v1, v1, 1
    sh      v0, -0xFA6(s0)              ; g_btl_tick++
    j       0x80081358                  ; the retail epilogue
    sb      v1, -0xF08(s0)              ; g_btl_frame ^= 1 (a hidden tick pre-flipped it)

;; At the frame start: FF_HIDE (no drawing) and FF_SHOW (vblank wait and
;; display) for this tick, per the group it is in. A group's size is chosen
;; at its tick 0 (see the header): in a turn (ff_plan_turn) FF_SKILLS or
;; FF_ACTIONS, during the entry camera FF_ENTRY, else 1 (no group: every
;; tick drawn and shown, as retail); times FF_MULT while fast-forwarding
;; (ff_plan_mult). FF_CNT counts the group's ticks still to come; the last
;; one (0) draws. Leaf.
ff_plan:
    lui     t0, hi(ff_vars)
    lbu     t1, lo(ff_vars + FF_CNT)(t0)
    addiu   t0, t0, lo(ff_vars)
    bnez    t1, ff_plan_group
    lbu     a0, -0xF96(s0)              ; (delay) g_btl_stage
    lbu     a1, 0x2250(s0)              ; AUTO
    xori    a0, a0, 2                   ; 0 in BtlStageRound (stage 2)
    beqz    a0, ff_plan_turn
    lbu     v1, FF_SKILLS(t0)           ; (delay)
    bnez    a1, ff_plan_turn
    lbu     a0, -0xF8F(s0)              ; (delay) g_btl_intro_step
    lbu     v1, FF_ENTRY(t0)
    xori    a0, a0, 4                   ; 4: the entry camera is moving
    beqz    a0, ff_plan_rate            ; (START only turns the fast-forward on in a turn)
    nop
    ori     v1, zero, 1                 ; no group
ff_plan_rate:
    addiu   t1, v1, -1                  ; the group's ticks after this one
    ori     v0, zero, 1
    b       ff_plan_store
    sb      v0, FF_SHOW(t0)             ; tick 0 is shown
ff_plan_group:
    addiu   t1, t1, -1
    sb      zero, FF_SHOW(t0)
ff_plan_store:
    sltu    at, zero, t1                ; ticks still to come: this one is hidden
    sb      t1, FF_CNT(t0)
    jr      ra
    sb      at, FF_HIDE(t0)

;; The tail of the frame (a0 = the frame buffer): show, then submit this
;; tick's ordering table.
ff_present:
    addiu   sp, sp, -0x28
    sw      ra, 0x24(sp)
    sw      s1, 0x20(sp)
    move    s1, a0
    lui     t0, hi(ff_vars)
    lbu     v0, lo(ff_vars + FF_SHOW)(t0)
    nop
    beqz    v0, @@no_show
    nop
    lbu     v0, -0xF8D(s0)              ; g_btl_half_rate (30 fps effects) ...
    lbu     v1, -0xF6B(s0)              ; ... and no vblank counted since the last frame
    beqz    v0, @@one_wait
    nop
    bnez    v1, @@one_wait
    nop
    jal     0x80025C98                  ; the retail second VSync(0)
    move    a0, zero
@@one_wait:
    jal     0x80025C98                  ; VSync(0)
    move    a0, zero
    sb      zero, -0xF6B(s0)            ; g_btl_vsync_count = 0: counts from this frame
    jal     0x8002BD98                  ; PutDispEnv: the frame drawn last tick
    addiu   a0, s1, 0x5C
@@no_show:
    lui     t0, hi(ff_vars)
    lbu     v0, lo(ff_vars + FF_HIDE)(t0)
    nop
    bnez    v0, @@empty
    nop
    jal     0x8002BBC0                  ; PutDrawEnv(the frame's own)
    move    a0, s1
    ori     a0, zero, 0xD6C0
    jal     0x8002BB4C                  ; DrawOTag
    addu    a0, s1, a0
    b       @@done
    lw      ra, 0x24(sp)
@@empty:
    lw      t3, 0(s1)                   ; clip x, y
    lw      t4, 4(s1)                   ; clip w, h
    lbu     t5, 0x18(s1)                ; isbg
    sw      t3, 0x10(sp)
    sw      t4, 0x14(sp)
    sw      t5, 0x18(sp)
    lui     t3, 1
    ori     t3, t3, 1
    sw      t3, 0(s1)                   ; clip 1,1
    sw      zero, 4(s1)                 ; size 0,0: the drawing area is empty
    sb      zero, 0x18(s1)              ; no background fill
    jal     0x8002BBC0                  ; PutDrawEnv
    move    a0, s1
    lw      t3, 0x10(sp)
    lw      t4, 0x14(sp)
    lw      t5, 0x18(sp)
    sw      t3, 0(s1)                   ; the frame's DRAWENV as it was
    sw      t4, 4(s1)
    sb      t5, 0x18(s1)
    lbu     t3, -0xF08(s0)              ; g_btl_frame: the tail flips it, so a
    ori     a0, zero, 0xD6C0
    xori    t3, t3, 1                   ; hidden tick pre-flips it and the next
    sb      t3, -0xF08(s0)              ; tick builds in this same buffer
    jal     0x8002BB4C                  ; DrawOTag
    addu    a0, s1, a0
    jal     0x8002B5E8                  ; DrawSync(0): before the next tick rewrites it
    move    a0, zero
    lw      ra, 0x24(sp)
@@done:
    lw      s1, 0x20(sp)
    jr      ra
    addiu   sp, sp, 0x28

;; BtlDrawObjects 0x80082E6C (the arena test): a hidden tick builds neither
;; the arena faces nor the floor mesh; it sets the screen distance the retail
;; tail leaves (100) and returns through BtlDrawObjects' epilogue.
ff_arena:
    lui     at, hi(ff_vars)
    lbu     at, lo(ff_vars + FF_HIDE)(at)
    lui     v0, 0x800D
    bnez    at, @@arena_hidden
    lbu     v0, -0xF06(v0)              ; g_btl_arena_show, as retail
    j       0x80082E74
    nop
@@arena_hidden:
    jal     0x80029E8C                  ; SetGeomScreen(100)
    ori     a0, zero, 0x64
    j       0x800830FC                  ; BtlDrawObjects' epilogue (it saved ra)
    nop

;; After BtlPadRead: a fresh START during a turn toggles the fast-forward and
;; is consumed. Outside BtlStageRound with AUTO off (the command picker, the
;; per-member walk, the formation grid, a negotiation) it stays the game's.
ff_pad:
    lui     at, 0x8010
    lhu     v1, -0x7710(at)             ; g_btl_pad1_edge
    lbu     a0, -0xF96(s0)              ; g_btl_stage
    lbu     a1, 0x2250(s0)              ; AUTO
    lui     t0, hi(ff_vars)
    xori    a0, a0, 2
    sltiu   a0, a0, 1                   ; 1 in BtlStageRound (stage 2)
    or      a0, a0, a1
    bnez    a0, @@in_turn
    andi    v0, v1, FF_START
    jr      ra
    sb      zero, lo(ff_vars + FF_ON)(t0) ; the turn is over: the fast-forward ends
@@in_turn:
    beqz    v0, @@pad_done
    lbu     v0, lo(ff_vars + FF_OVER)(t0)
    nop
    bnez    v0, @@pad_done              ; the battle is over: START is the game's
    lbu     v0, lo(ff_vars + FF_ON)(t0)
    xori    v1, v1, FF_START
    sh      v1, -0x7710(at)
    xori    v0, v0, 1
    sb      v0, lo(ff_vars + FF_ON)(t0)
@@pad_done:
    jr      ra
    nop

;; The round flow's battle-over branch (0x8008FB68, reached once the last
;; turn's HUD and message box are done, for a victory and a defeat alike): the
;; fast-forward ends and stays off. Then retail's own first instructions:
;; v0 = g_btl_party_lost (its consumer's load-delay nop follows the call).
ff_battle_over:
    lui     at, hi(ff_vars)
    sb      zero, lo(ff_vars + FF_ON)(at)
    ori     v0, zero, 1
    sb      v0, lo(ff_vars + FF_OVER)(at)
    lui     v0, 0x800D
    jr      ra
    lbu     v0, 0xB07(v0)               ; (delay) g_btl_party_lost, as retail

.endarea

.org 0x8008FB68
    jal     ff_battle_over              ; was lui v0, 0x800D / lbu v0, 0xB07(v0)
    nop

;; BtlDrawObjects' per-object handler call: g_btl_obj_draw[o->draw](o).
.org 0x80082A9C
    jal     ff_obj_draw                 ; was jalr v0 (delay slot: move a0, s0)
.org 0x80082E6C
    j       ff_arena                    ; was lui v0, 0x800D / lbu v0, -0xF06(v0)
    nop

;; BtlFrontPost (0x80065D88..0x80065E8F) and the empty function after it
;; (..0x80065E97): the only code that would start BtlDrawFront's step, and
;; nothing calls either (decomp src/btlp/frontpost.c; no jal, no pointer).
.org 0x80065D88
.area 0x80065E98 - 0x80065D88
;; At the area's start, a fixed address: battle-speedup's ranges write the
;; three speeds and this mod's `rate` range FF_MULT in the built file (the
;; mods' values.tsv).
ff_vars:
    .byte   0, 0, 0, 0, 0               ; ON CNT HIDE SHOW OVER: BTLP is read anew every battle
    .byte   1, 1, 1                     ; ACTIONS SKILLS ENTRY: no group unless battle-speedup's ranges set them
    .byte   FF_RATE                     ; MULT: the `rate` range (values.tsv)
.align 4
;; v0 = the handler, a0 = the object: a hidden tick draws no object.
ff_obj_draw:
    lui     at, hi(ff_vars)
    lbu     at, lo(ff_vars + FF_HIDE)(at)
    nop
    beqz    at, @@obj_drawn
    nop
    move    v0, ra                      ; hidden: straight back
@@obj_drawn:
    jr      v0
    nop

;; ff_plan in a turn: FF_SKILLS in the half-rate effects (g_btl_half_rate:
;; skills, the Persona's motion in a summon) and while a summon's cast
;; circle (g_btl_hud_obj, -0xFF0(s0)) is shown (BTL_OBJ_HIDDEN, attr bit
;; 30, clear: the circle, the pose, the Persona and its exit), else
;; FF_ACTIONS; then FF_MULT times that while fast-forwarding.
ff_plan_turn:                           ; v1 = FF_SKILLS
    lbu     a0, -0xF8D(s0)              ; g_btl_half_rate
    lw      a2, -0xFF0(s0)              ; g_btl_hud_obj
    bnez    a0, @@mult
    lbu     a0, FF_ON(t0)               ; (delay)
    beqz    a2, @@actions
    lw      a2, 0(a2)                   ; (delay) its attr (none: reads RAM word 0, unused)
    nop
    sll     a2, a2, 1                   ; BTL_OBJ_HIDDEN to the sign
    bgez    a2, @@mult                  ; shown: the summon is running
    nop
@@actions:
    lbu     v1, FF_ACTIONS(t0)
@@mult:
    lbu     a1, FF_MULT(t0)
    beqz    a0, ff_plan_rate            ; a0 = FF_ON
    nop
    multu   v1, a1
    j       ff_plan_rate
    mflo    v1                          ; (delay)

;; a0 = the frame buffer: while the fast-forward is on, link this buffer's
;; ">>" packet first into the last OT entry (the text sprites'). An OT entry's
;; tag has length 0, so its link is the packet's and the packet's address
;; is the entry's.
ff_icon:
    lui     t0, hi(ff_vars)
    lbu     v0, lo(ff_vars + FF_ON)(t0)
    lbu     t1, -0xF08(s0)
    beqz    v0, @@icon_done
    ori     v1, zero, 0xE65C
    addu    a0, a0, v1                  ; the OT entry
    lui     a1, hi(ff_prims)
    addiu   a1, a1, lo(ff_prims)
    sll     t2, t1, 5
    sll     t1, t1, 2
    addu    t1, t1, t2                  ; 36 bytes per buffer
    addu    a1, a1, t1
    lw      v0, 0(a0)
    lui     t3, 0x0800                  ; 8 words: two POLY_F3
    or      v0, v0, t3
    sw      v0, 0(a1)                   ; packet -> the entry's list
    sll     v1, a1, 8
    srl     v1, v1, 8
    sw      v1, 0(a0)                   ; entry -> packet
@@icon_done:
    jr      ra
    nop

.align 4
ff_prims:                               ; buffer 0, buffer 1: a tag and two POLY_F3
    .word   0x08FFFFFF
    .word   FF_ICON_RGB
    .word   (FF_ICON_Y << 16) | (FF_ICON_X + 0)
    .word   ((FF_ICON_Y + 12) << 16) | (FF_ICON_X + 0)
    .word   ((FF_ICON_Y + 6) << 16) | (FF_ICON_X + 9)
    .word   FF_ICON_RGB
    .word   (FF_ICON_Y << 16) | (FF_ICON_X + 9)
    .word   ((FF_ICON_Y + 12) << 16) | (FF_ICON_X + 9)
    .word   ((FF_ICON_Y + 6) << 16) | (FF_ICON_X + 18)
    .word   0x08FFFFFF
    .word   FF_ICON_RGB
    .word   (FF_ICON_Y << 16) | (FF_ICON_X + 0)
    .word   ((FF_ICON_Y + 12) << 16) | (FF_ICON_X + 0)
    .word   ((FF_ICON_Y + 6) << 16) | (FF_ICON_X + 9)
    .word   FF_ICON_RGB
    .word   (FF_ICON_Y << 16) | (FF_ICON_X + 9)
    .word   ((FF_ICON_Y + 12) << 16) | (FF_ICON_X + 9)
    .word   ((FF_ICON_Y + 6) << 16) | (FF_ICON_X + 18)
.endarea
.if ff_vars != 0x80065D88
    .error "ff_vars moved: mods/battle-speedup/values.tsv writes its offsets"
.endif
