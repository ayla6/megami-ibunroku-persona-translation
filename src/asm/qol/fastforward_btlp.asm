;; =============================================================
;; QoL (--qol=fastforward): START fast-forwards a battle turn (BTLP.BIN).
;;
;; BtlDrawFrame 0x80080F14 presents every battle tick (the main loop at
;; 0x80092270 and ~280 scripted waits call it).
;;
;; START fast-forward (as the PSP's battle skip). START while a turn plays
;; out (g_btl_step != 0, or AUTO on) toggles it; START at the command menu
;; stays the game's (and --qol=debug's page). It ends by itself when the
;; command menu comes back for input (step 0 with AUTO off) and when the
;; results window opens. While it is on, a small ">>" shows at the top right.
;;
;; Every tick still runs the whole battle: logic, object scripts and
;; animation steps, BtlDrawObjects' own state work (positions handed to
;; shadows / attached pieces / markers, the colour fades, the flat / rotated
;; kind choice), the 2D layer, the VRAM queues and the GPU submit of the
;; ordering table, so nothing the battle sends the GPU is ever dropped. What
;; changes is which ticks are drawn and shown. The ticks run in groups of
;; FF_RATE:
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
;; The buffers alternate every tick as in retail, so packets and ordering
;; tables are never rewritten while the GPU reads them; FF_RATE is odd, so
;; the drawn ticks alternate buffers too and never draw into the one on
;; screen. On/off takes effect at a group's tick 0 only, so every shown
;; frame is a finished one. The display then runs at up to 60 fps while the
;; battle runs FF_RATE ticks per shown frame.
;;
;; --qol=battlespeed drops retail's second VSync of the half-rate mode
;; (qol/battle_speed_btlp.asm, one nop at 0x800811B8). That address is inside
;; the rewrite below, so with both options main.asm leaves that file out and
;; the rewrite has no second wait; with fastforward alone the rewrite keeps it.
;;
;; BtlDrawFrame is -O0 code (0x80080F14..0x8008136B); it is rewritten
;; compactly with the same calls in the same order, and the fast-forward lives
;; in the room this frees. The prologue up to BtlCheatWatch's call
;; (0x80080F24, which --qol=debug clears) and the epilogue at 0x80081358
;; (where --qol=debug's stub hooks in) keep their retail addresses. Nothing
;; jumps into the old body (only jal 0x80080F14).
;;
;; Battle globals (decomp src/btlp/drawframe.c), from s0 = 0x800D0000:
;;   -0xF95 g_btl_step    -0xF92 g_btl_no_help  -0xF8D g_btl_half_rate
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
    sb      zero, -0xF6B(s0)            ; g_btl_vsync_count = 0
    addiu   v0, v0, 1
    xori    v1, v1, 1
    sh      v0, -0xFA6(s0)              ; g_btl_tick++
    j       0x80081358                  ; the retail epilogue
    sb      v1, -0xF08(s0)              ; g_btl_frame ^= 1

;; At the frame start: FF_HIDE (no drawing) and FF_SHOW (vblank wait and
;; display) for this tick, per the group it is in. Leaf.
ff_plan:
    lui     t0, hi(ff_vars)
    addiu   t0, t0, lo(ff_vars)
    lbu     t1, FF_CNT(t0)
    lbu     t2, FF_ON(t0)
    bnez    t1, @@in_group
    lbu     a0, -0xF95(s0)              ; g_btl_step
    lbu     a1, 0x2250(s0)              ; AUTO
    nop
    or      a0, a0, a1
    bnez    a0, @@turn
    nop
    move    t2, zero                    ; the command menu is back: the fast-forward ends
    sb      zero, FF_ON(t0)
@@turn:
    sb      t2, FF_CNT(t0)              ; tick 0, shown; on: a group starts,
    sb      t2, FF_HIDE(t0)             ; and its tick 0 is hidden
    ori     v0, zero, 1
    jr      ra
    sb      v0, FF_SHOW(t0)
@@in_group:
    addiu   t1, t1, 1
    sltiu   at, t1, FF_RATE             ; still inside the group: hidden
    bnez    at, @@counted
    nop
    move    t1, zero                    ; the group's last tick draws the next shown frame
@@counted:
    sb      t1, FF_CNT(t0)
    sb      at, FF_HIDE(t0)
    jr      ra
    sb      zero, FF_SHOW(t0)

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
.ifndef QOL_BATTLESPEED
    lbu     v0, -0xF8D(s0)              ; g_btl_half_rate (30 fps effects) ...
    lbu     v1, -0xF6B(s0)              ; ... and no vblank counted since the last frame
    beqz    v0, @@one_wait
    nop
    bnez    v1, @@one_wait
    nop
    jal     0x80025C98                  ; the retail second VSync(0)
    move    a0, zero
@@one_wait:
.endif
    jal     0x80025C98                  ; VSync(0)
    move    a0, zero
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
    b       @@submit
    nop
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
@@submit:
    ori     a0, zero, 0xD6C0
    jal     0x8002BB4C                  ; DrawOTag
    addu    a0, s1, a0
    lw      ra, 0x24(sp)
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
;; is consumed. At the command menu (step 0, AUTO off) it stays the game's.
ff_pad:
    lui     at, 0x8010
    lhu     v1, -0x7710(at)             ; g_btl_pad1_edge
    lbu     a0, -0xF95(s0)              ; g_btl_step
    lbu     a1, 0x2250(s0)              ; AUTO
    andi    v0, v1, FF_START
    beqz    v0, @@pad_done
    or      a0, a0, a1
    beqz    a0, @@pad_done
    lui     t0, hi(ff_vars)
    lbu     v0, lo(ff_vars + FF_ON)(t0)
    xori    v1, v1, FF_START
    sh      v1, -0x7710(at)
    xori    v0, v0, 1
    sb      v0, lo(ff_vars + FF_ON)(t0)
@@pad_done:
    jr      ra
    nop

.endarea

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
;; v0 = the handler, a0 = the object: a hidden tick draws no object.
ff_obj_draw:
    lui     at, hi(ff_vars)
    lbu     at, lo(ff_vars + FF_HIDE)(at)
    nop
    bnez    at, @@obj_hidden
    nop
    jr      v0
@@obj_hidden:
    nop
    jr      ra
    nop

;; a0 = the frame buffer: while the fast-forward is on, link the two ">>"
;; triangles of this buffer first into the last OT entry (the text sprites').
ff_icon:
    lui     t0, hi(ff_vars)
    lbu     v0, lo(ff_vars + FF_ON)(t0)
    lbu     t1, -0xF08(s0)
    beqz    v0, @@icon_done
    ori     v1, zero, 0xE65C
    addu    a0, a0, v1                  ; the OT entry
    lui     a1, hi(ff_prims)
    addiu   a1, a1, lo(ff_prims)
    sll     t1, t1, 3
    sll     t2, t1, 2
    addu    t1, t1, t2                  ; 40 bytes per buffer
    addu    a1, a1, t1                  ; first triangle
    addiu   a2, a1, 20                  ; second
    lui     t3, 0x0400                  ; 4 words each
    lui     t4, 0x00FF
    ori     t4, t4, 0xFFFF
    lw      v0, 0(a0)
    and     v1, a2, t4
    or      v1, v1, t3
    sw      v1, 0(a1)                   ; first -> second
    and     v1, v0, t4
    or      v1, v1, t3
    sw      v1, 0(a2)                   ; second -> the entry's list
    srl     v0, v0, 24
    sll     v0, v0, 24
    and     v1, a1, t4
    or      v0, v0, v1
    sw      v0, 0(a0)                   ; entry -> first
@@icon_done:
    jr      ra
    nop

.align 4
ff_vars:
    .byte   0, 0, 0, 0                  ; BTLP is read anew for every battle: off at the start
ff_prims:                               ; buffer 0, buffer 1
    .word   0x04FFFFFF, FF_ICON_RGB
    .word   (FF_ICON_Y << 16) | (FF_ICON_X + 0)
    .word   ((FF_ICON_Y + 12) << 16) | (FF_ICON_X + 0)
    .word   ((FF_ICON_Y + 6) << 16) | (FF_ICON_X + 9)
    .word   0x04FFFFFF, FF_ICON_RGB
    .word   (FF_ICON_Y << 16) | (FF_ICON_X + 9)
    .word   ((FF_ICON_Y + 12) << 16) | (FF_ICON_X + 9)
    .word   ((FF_ICON_Y + 6) << 16) | (FF_ICON_X + 18)
    .word   0x04FFFFFF, FF_ICON_RGB
    .word   (FF_ICON_Y << 16) | (FF_ICON_X + 0)
    .word   ((FF_ICON_Y + 12) << 16) | (FF_ICON_X + 0)
    .word   ((FF_ICON_Y + 6) << 16) | (FF_ICON_X + 9)
    .word   0x04FFFFFF, FF_ICON_RGB
    .word   (FF_ICON_Y << 16) | (FF_ICON_X + 9)
    .word   ((FF_ICON_Y + 12) << 16) | (FF_ICON_X + 9)
    .word   ((FF_ICON_Y + 6) << 16) | (FF_ICON_X + 18)
.endarea

;; The results window (0x80098CF4: opens the window, then frames until a new
;; press) ends the fast-forward. Its prologue saved s0, which it first sets at
;; 0x80098D80; the two window calls before keep it.
.org 0x80098D30
    lui     s0, hi(ff_vars)             ; delay slot of jal 0x800AB650 (was nop)
.org 0x80098D38
    sb      zero, lo(ff_vars + FF_ON)(s0) ; delay slot of jal 0x800A9CEC (was nop)
