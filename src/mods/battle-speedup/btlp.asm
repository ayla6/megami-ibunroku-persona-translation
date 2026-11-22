;; =============================================================
;; Battle speedup (--mods=battle-speedup): a battle's turns and its entry
;; camera at the selected 1-4x speeds (BTLP.BIN).
;;
;; BtlDrawFrame 0x80080F14 presents every battle tick (the main loop at
;; 0x80092270 and ~280 scripted waits call it). Retail shows every tick; the
;; effect players (summons, skill / magic effects) set g_btl_half_rate, and a
;; shown tick then waits for two vblanks (30 fps).
;;
;; The speedup runs the ticks in groups, chosen at a group's tick 0
;; (bs_plan). While a turn plays out (g_btl_stage BtlStageRound, or AUTO
;; on; the command picker, the formation grid and a negotiation stay retail)
;; a group is BS_SKILLS ticks in summons and skills and BS_ACTIONS in the
;; rest of the turn (attacks, the enemies' actions, the messages); while the
;; entry camera moves (g_btl_intro_step 4) BS_ENTRY; else 1 (no group:
;; retail). Once the battle is over (the round flow's battle-over branch,
;; bs_battle_over: BS_OVER) every group is 1 until the next battle: the
;; results board and the level-up boards are retail, even when the fight
;; ended on AUTO (AUTO stays on through them). The three are bytes at
;; bs_vars' fixed address that the
;; `skills`, `actions` and `entry` ranges write in the built file
;; (values.tsv, 1-4; 1 is retail).
;;   tick 0   keeps retail's waits (one vblank, two at half rate unless a
;;            vblank already passed since the last shown frame: the count
;;            is reset on shown ticks only, so a group's own time counts)
;;            and shows the frame the last group drew
;;   tick 1.. HIDDEN: every tick still runs the whole battle (logic, object
;;            scripts, animation steps, BtlDrawObjects' state work, the 2D
;;            layer, VRAM queues, the GPU submit), but no object is drawn
;;            (the per-object handler call 0x80082A9C goes through
;;            bs_obj_draw, which returns at once; the handlers only build
;;            primitives, decomp src/btlp/obj*.c), the arena faces and floor
;;            mesh are not built (0x80082E6C -> bs_arena), and the ordering
;;            table goes to the GPU with an EMPTY drawing area (clip 1,1 size
;;            0,0) and no background fill. These ticks skip the GTE transforms
;;            and primitive building that make a battle tick expensive.
;;   last     draws normally; the next tick 0 shows it.
;; So N ticks per shown frame are N times retail speed at retail's frame
;; rate, with one tick in N drawn: the speed holds on real hardware too,
;; where drawing every tick would not fit in a vblank.
;;
;; Buffers: a drawn tick flips g_btl_frame as retail; a hidden tick does not,
;; so the next tick builds in the same buffer and a drawn tick always draws
;; into the buffer that is not on screen, whatever the group size. A hidden
;; tick waits for its (empty) submit to finish (DrawSync) before the next
;; tick rewrites that buffer's ordering table and packets.
;;
;; Sound is not touched: the SPU plays every sample at its own pitch and
;; length, so voices ("Persona!") and effect sounds keep their speed and only
;; start earlier.
;;
;; With --mods=fast-forward-battle-animations on, this file is left out
;; (asm.tsv): fast-forward's own BtlDrawFrame rewrite runs these speeds too.
;;
;; BtlDrawFrame is -O0 code (0x80080F14..0x8008136B); it is rewritten
;; compactly with the same calls in the same order, and the speedup lives
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
    jal     bs_plan                     ; is this tick drawn, is it shown?
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
    jal     bs_present                  ; VSync, PutDispEnv, PutDrawEnv, DrawOTag
    nop
    jal     0x8008E980                  ; BtlPadRead
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

;; At the frame start: BS_HIDE (no drawing) and BS_SHOW (vblank wait and
;; display) for this tick, per the group it is in (chosen at its tick 0, see
;; the header). BS_CNT counts the group's ticks still to come; the last one
;; (0) draws. Leaf.
bs_plan:
    lui     t0, hi(bs_vars)
    lbu     t1, lo(bs_vars + BS_CNT)(t0)
    addiu   t0, t0, lo(bs_vars)
    bnez    t1, bs_plan_group
    lbu     a0, -0xF96(s0)              ; (delay) g_btl_stage
    lbu     a1, 0x2250(s0)              ; AUTO
    lbu     v0, BS_OVER(t0)
    xori    a0, a0, 2                   ; 0 in BtlStageRound (stage 2)
    bnez    v0, bs_plan_rate            ; the battle is over: the results and level-ups
    ori     v1, zero, 1                 ; (delay) draw every tick, AUTO or not (no group)
    beqz    a0, bs_plan_turn
    lbu     v1, BS_SKILLS(t0)           ; (delay)
    bnez    a1, bs_plan_turn
    lbu     a0, -0xF8F(s0)              ; (delay) g_btl_intro_step
    lbu     v1, BS_ENTRY(t0)
    xori    a0, a0, 4                   ; 4: the entry camera is moving
    beqz    a0, bs_plan_rate
    nop
    ori     v1, zero, 1                 ; no group
bs_plan_rate:
    addiu   t1, v1, -1                  ; the group's ticks after this one
    ori     v0, zero, 1
    b       bs_plan_store
    sb      v0, BS_SHOW(t0)             ; tick 0 is shown
bs_plan_group:
    addiu   t1, t1, -1
    sb      zero, BS_SHOW(t0)
bs_plan_store:
    sltu    at, zero, t1                ; ticks still to come: this one is hidden
    sb      t1, BS_CNT(t0)
    jr      ra
    sb      at, BS_HIDE(t0)

;; The tail of the frame (a0 = the frame buffer): show, then submit this
;; tick's ordering table.
bs_present:
    addiu   sp, sp, -0x28
    sw      ra, 0x24(sp)
    sw      s1, 0x20(sp)
    move    s1, a0
    lui     t0, hi(bs_vars)
    lbu     v0, lo(bs_vars + BS_SHOW)(t0)
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
    lui     t0, hi(bs_vars)
    lbu     v0, lo(bs_vars + BS_HIDE)(t0)
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
bs_arena:
    lui     at, hi(bs_vars)
    lbu     at, lo(bs_vars + BS_HIDE)(at)
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


.endarea


.org 0x8008FB68
    jal     bs_battle_over              ; was lui v0, 0x800D / lbu v0, 0xB07(v0)
    nop

;; BtlDrawObjects' per-object handler call: g_btl_obj_draw[o->draw](o).
.org 0x80082A9C
    jal     bs_obj_draw                 ; was jalr v0 (delay slot: move a0, s0)
.org 0x80082E6C
    j       bs_arena                    ; was lui v0, 0x800D / lbu v0, -0xF06(v0)
    nop

;; BtlFrontPost (0x80065D88..0x80065E8F) and the empty function after it
;; (..0x80065E97): the only code that would start BtlDrawFront's step, and
;; nothing calls either (decomp src/btlp/frontpost.c; no jal, no pointer).
.org 0x80065D88
.area 0x80065E98 - 0x80065D88
;; At the area's start, a fixed address: the `actions`, `skills` and `entry`
;; ranges write their bytes in the built file (values.tsv).
bs_vars:
    .byte   0, 0, 0, 0, 0               ; -, CNT HIDE SHOW OVER: BTLP is read anew every battle
    .byte   1, 1, 1                     ; ACTIONS SKILLS ENTRY: written by the ranges of the same names
.align 4
;; v0 = the handler, a0 = the object: a hidden tick draws no object.
bs_obj_draw:
    lui     at, hi(bs_vars)
    lbu     at, lo(bs_vars + BS_HIDE)(at)
    nop
    bnez    at, @@obj_hidden
    nop
    jr      v0
@@obj_hidden:
    nop
    jr      ra
    nop

;; bs_plan in a turn (v1 = BS_SKILLS): BS_SKILLS in the half-rate effects
;; (g_btl_half_rate: skills, the Persona's motion in a summon) and while a
;; summon's cast circle (g_btl_hud_obj, -0xFF0(s0)) is shown (BTL_OBJ_HIDDEN,
;; attr bit 30, clear: the circle, the pose, the Persona and its exit), else
;; BS_ACTIONS.
bs_plan_turn:
    lbu     a0, -0xF8D(s0)              ; g_btl_half_rate
    lw      a2, -0xFF0(s0)              ; g_btl_hud_obj
    bnez    a0, bs_plan_rate
    nop
    beqz    a2, @@actions
    lw      a2, 0(a2)                   ; (delay) its attr (none: reads RAM word 0, unused)
    nop
    sll     a2, a2, 1                   ; BTL_OBJ_HIDDEN to the sign
    bgez    a2, bs_plan_rate            ; shown: the summon is running
    nop
@@actions:
    lbu     v1, BS_ACTIONS(t0)
    j       bs_plan_rate
    nop

;; The round flow's battle-over branch (0x8008FB68, reached once the last
;; turn's HUD and message box are done, for a victory and a defeat alike):
;; no more groups, so the results board and the level-ups draw every tick
;; even when the fight ended on AUTO. Then retail's own first instructions:
;; v0 = g_btl_party_lost (its consumer's load-delay nop follows the call).
bs_battle_over:
    lui     at, hi(bs_vars)
    ori     v0, zero, 1
    sb      v0, lo(bs_vars + BS_OVER)(at)
    lui     v0, 0x800D
    jr      ra
    lbu     v0, 0xB07(v0)               ; (delay) g_btl_party_lost, as retail

.endarea
.if bs_vars != 0x80065D88
    .error "bs_vars moved: values.tsv writes its offsets"
.endif
