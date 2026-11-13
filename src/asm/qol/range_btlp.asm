;; =============================================================
;; QoL (--qol=range): the reach of a move painted on the battle floor
;; (BTLP.BIN), like the PSP version's panels.
;;
;; Retail never shows a move's reach: the target cursor only stops on the
;; fighters it reaches. The reach is a grid seen from above (decomp
;; src/btlp/reach.c): g_btl_reach[5 lanes][15 rows], the enemies in rows 0..4,
;; the party in rows 10..14, the empty ground between. BtlMarkMoveArea throws
;; a weapon's or a spell's line into it, BtlMarkEnemiesAround /
;; BtlMarkPartyAround a burst round the fighter under the cursor; a pick puts
;; the fighters it would hit on the target motion (BtlObj.motion 10, 11 for the
;; cursor's own in a burst).
;;
;; The picks are the sword's and the gun's command (BtlCommandAttack, through
;; g_btl_command_fn), BtlPickMoveTarget (the cast's and the item's), and the
;; item command's three own picks (BtlPickTargetMember / Party / Enemies).
;; Each runs inside rng_wrap, which raises rng_state for as long as it runs:
;; only then does the target motion count, so the other users of motion 10 -
;; the negotiation's demons, BtlSingleOutMember bobbing the acting member
;; through the whole command (decomp src/btlp/dimsides.c) - paint nothing. A
;; party member counts only in a party pick (rng_state 3: the item command's
;; member and party picks, and BtlPickMoveTarget's once it calls
;; BtlSetPartyPickable), and then the acting member as much as any.
;;
;; Before the pick runs, rng_wrap fills g_btl_reach with the side it reaches
;; - the side the move's kind picks from for BtlPickMoveTarget, the party or
;; the enemies for the item command's own picks - since only the line and
;; burst picks write the grid themselves (and they write it over the fill).
;;
;; So, every frame: while a pick is up and a fighter is on the target motion,
;; the cells of the reach grid are painted orange and the cells of the
;; fighters it would hit red.
;;
;; Three menus preview the reach of what is under their cursor, all red, as
;; the PSP does before a move is chosen: the command menu on the sword and the
;; gun (the weapon's line, BtlMarkMoveArea with its area and swing), the skill
;; board, and the item board (the move the skill or the item makes, as the pick
;; will throw or fill it; the item command's own three pick the party, the
;; party, or the enemies). The preview writes g_btl_reach and the enemies'
;; pickable flags exactly as the pick does, and the pick marks both again
;; before it reads them. rng_hover holds the preview for two frames, so it
;; ends with the menu; a pick with a target up wins over it.
;;
;; Drawing: the retail debug grid (BtlDrawObjects 0x80082B78..0x80082E6B,
;; behind g_btl_debug_hud and g_btl_debug_grid, which nothing in the game
;; sets) already projects the 5 x 15 field onto the floor: cell (lane, row)
;; spans x -75 + 30 * lane (30 across), y -150 + 20 * row (20 deep), z 0,
;; through the battle camera BtlDrawObjects has just loaded into the GTE. It
;; is replaced by this overlay. Each lane's run of same-coloured rows is one
;; semi-transparent POLY_F4 (the floor is a plane, so the four projected
;; corners are exact; they go straight into the GTE's vertex registers),
;; allocated from the frame's POLY_G4 run behind the effect quads with its end
;; checked, and linked into the arena's ordering table entry like the debug
;; grid's squares: drawn after the arena floor and the mesh, before every
;; fighter. One DR_MODE linked last (so drawn first) selects blend 3 (floor +
;; a quarter of the panel colour), so the floor keeps its own brightness under
;; a light tint. The cell colours are built in the debug grid's own 75-byte
;; buffer, which only the debug grid read.
;;
;; Code homes: the debug grid's block (the overlay), BtlDebugPause
;; (0x8008EF60..0x8008F05B), BtlLoadDebugGrid (0x80098C18..0x80098CF3), and
;; BtlDebugWait / BtlDebugWaitArgs (0x8008F2F4..0x8008F5DB). Nothing calls,
;; jumps to or points at the first two in any image (decomp
;; src/btlp/debughud.c: "BtlDebugPause has no caller"; debuggrid.c), and the
;; debug grid they served is the one this replaces; the last two are called
;; only behind g_btl_debug (decomp src/btlp/entry.c), which no code stores to.
;; =============================================================
.org 0x80082B78
.area 0x80082E6C - 0x80082B78
    lui     t0, hi(RNG_REACH)
    addiu   t0, t0, lo(RNG_REACH)
    lui     t1, hi(RNG_CELLS)
    addiu   t1, t1, lo(RNG_CELLS)
    ori     t2, zero, 75
@@copy:                                 ; cells = 1 where the reach is lit
    lbu     v0, 0(t0)
    addiu   t0, t0, 1
    sltu    v0, zero, v0
    sb      v0, 0(t1)
    addiu   t2, t2, -1
    bnez    t2, @@copy
    addiu   t1, t1, 1

    lui     t0, hi(RNG_ACTORS)
    addiu   t0, t0, lo(RNG_ACTORS)
    addiu   t1, t1, -75                 ; the cells again
    move    t3, zero                    ; record 0..13
    move    t4, zero                    ; a fighter is on the target motion
    lui     t7, hi(rng_state)
    lbu     t7, lo(rng_state)(t7)       ; 1: a pick is up, 3: a pick of party members
    nop
    beqz    t7, @@scanned               ; no pick: the target motion means nothing
    nop
@@actor:
    lbu     v0, 0x3E(t0)                ; c.key: the record is in use
    lw      a0, 0x60(t0)                ; obj
    beqz    v0, @@next
    nop
    beqz    a0, @@next
    nop
    lbu     v0, 0xD1(a0)                ; motion
    nop
    addiu   v0, v0, -10
    sltiu   v0, v0, 2                   ; 10 or 11
    beqz    v0, @@next
    lbu     v1, 0xB0(a0)                ; col2: the lane, doubled
    lb      v0, 0xB1(a0)                ; row, within its own side
    sltiu   at, t3, 5
    beqz    at, @@side
    srl     v1, v1, 1
    andi    at, t7, 2
    beqz    at, @@next                  ; members are targets only in a party pick
    addiu   v0, v0, 10                  ; a member stands ten rows further on
@@side:
    sltiu   at, v1, 5
    beqz    at, @@next
    sltiu   at, v0, 15
    beqz    at, @@next
    sll     a1, v1, 4
    subu    a1, a1, v1                  ; lane * 15
    addu    a1, a1, v0
    addu    a1, a1, t1
    ori     v0, zero, 2
    sb      v0, 0(a1)                   ; red
    ori     t4, zero, 1
@@next:
    addiu   t3, t3, 1
    sltiu   at, t3, 14
    bnez    at, @@actor
    addiu   t0, t0, RNG_ACTOR_SIZE
@@scanned:
    lui     t5, hi(rng_hover)
    lbu     t6, lo(rng_hover)(t5)
    bnez    t4, @@draw                  ; a pick is up: it wins over the preview
    nop
    beqz    t6, @@leave                 ; neither a pick nor a menu's preview
    addiu   t6, t6, -1
    sb      t6, lo(rng_hover)(t5)
@@draw:
    lui     s0, hi(RNG_POLYG4_NEXT)
    lw      s1, lo(RNG_POLYG4_NEXT)(s0) ; the next free POLY_G4 slot
    lui     at, 0x800D
    lbu     v0, -0xF08(at)              ; g_btl_frame
    lw      v1, -0xF68(at)              ; g_btl_prim_pool
    ori     a0, zero, 0xE660
    multu   v0, a0
    mflo    v0
    addu    v0, v0, v1                  ; this frame's half of the pool
    addiu   s2, v0, 0x7568              ; end of its POLY_G4 run (LINE_G2 follows)
    ori     s3, zero, 0xD6C0
    addu    s3, v0, s3                  ; the arena's ordering-table entry
    move    s4, t1                      ; the cells
    .word   0x48800000 | (0 << 16) | (1 << 11)      ; mtc2 zero, VZ0: every corner's z is 0
    .word   0x48800000 | (0 << 16) | (3 << 11)      ; mtc2 zero, VZ1
    .word   0x48800000 | (0 << 16) | (5 << 11)      ; mtc2 zero, VZ2
    lui     a3, hi(RNG_RGB_TARGET | 0x2A000000)     ; POLY_F4, semi-transparent
    addiu   a3, a3, lo(RNG_RGB_TARGET | 0x2A000000)
    beqz    t4, @@colours               ; a menu's preview: the area all red
    move    a2, a3
    lui     a2, hi(RNG_RGB_AREA | 0x2A000000)   ; a pick: the area orange
    addiu   a2, a2, lo(RNG_RGB_AREA | 0x2A000000)
@@colours:
    lui     t3, 0x00FF
    ori     t3, t3, 0xFFFF              ; the link mask
    move    s5, zero                    ; lane
@@lane:
    move    s6, zero                    ; row
@@row:
    sll     a1, s5, 4
    subu    a1, a1, s5
    addu    a1, a1, s6
    addu    a1, a1, s4
    lbu     s7, 0(a1)                   ; this cell's colour
    nop
    beqz    s7, @@empty_cell
    move    fp, s6                      ; the run starts here
@@run:
    addiu   s6, s6, 1
    sltiu   at, s6, 15
    beqz    at, @@quad
    nop
    lbu     v0, 1(a1)
    addiu   a1, a1, 1
    beq     v0, s7, @@run
    nop
@@quad:                                 ; lane s5, rows fp .. s6 - 1
    addiu   at, s1, 36
    sltu    at, s2, at
    bnez    at, rng_finish              ; the run is full: draw what fits
    sll     v0, s5, 5
    sll     v1, s5, 1
    subu    v0, v0, v1
    addiu   t5, v0, -75                 ; x0
    andi    t5, t5, 0xFFFF
    addiu   t6, t5, 30                  ; x1 (the low half is all a vertex keeps)
    andi    t6, t6, 0xFFFF
    sll     v0, fp, 4
    sll     v1, fp, 2
    addu    v0, v0, v1
    addiu   t7, v0, -150                ; near edge
    sll     t7, t7, 16
    sll     v0, s6, 4
    sll     v1, s6, 2
    addu    v0, v0, v1
    addiu   t8, v0, -150                ; far edge
    sll     t8, t8, 16
    or      v0, t5, t7
    .word   0x48800000 | (2 << 16) | (0 << 11)      ; mtc2 v0, VXY0: (x0, near)
    or      v0, t6, t7
    .word   0x48800000 | (2 << 16) | (2 << 11)      ; mtc2 v0, VXY1: (x1, near)
    or      v0, t5, t8
    .word   0x48800000 | (2 << 16) | (4 << 11)      ; mtc2 v0, VXY2: (x0, far)
    or      t5, t6, t8                  ; (x1, far), for the fourth corner
    nop
    .word   0x4A280030                                  ; rtpt
    .word   0xE8000000 | (17 << 21) | (12 << 16) | 8    ; swc2 SXY0, 8(s1)
    .word   0xE8000000 | (17 << 21) | (13 << 16) | 12   ; swc2 SXY1, 12(s1)
    .word   0xE8000000 | (17 << 21) | (14 << 16) | 16   ; swc2 SXY2, 16(s1)
    .word   0x48800000 | (13 << 16) | (0 << 11)     ; mtc2 t5, VXY0
    nop
    nop
    .word   0x4A180001                                  ; rtps
    .word   0xE8000000 | (17 << 21) | (14 << 16) | 20   ; swc2 SXY2, 20(s1)
    ori     at, zero, 2
    beq     s7, at, @@colour
    move    v0, a3                      ; red
    move    v0, a2                      ; orange
@@colour:
    sw      v0, 4(s1)
    lw      v0, 0(s3)                   ; addPrim(arena entry, quad)
    lui     a0, 0x0500
    and     v1, v0, t3
    or      v1, v1, a0
    sw      v1, 0(s1)                   ; 5 words, then the entry's list
    and     a0, s1, t3
    srl     v0, v0, 24
    sll     v0, v0, 24
    or      v0, v0, a0
    sw      v0, 0(s3)
    b       @@row_end
    addiu   s1, s1, 36                  ; a POLY_G4 slot
@@empty_cell:
    addiu   s6, s6, 1
@@row_end:
    sltiu   at, s6, 15
    bnez    at, @@row
    nop
    addiu   s5, s5, 1
    sltiu   at, s5, 5
    bnez    at, @@lane
    nop
    j       rng_finish
    nop
@@leave:
    j       0x80082E6C                  ; the arena, as after the debug grid
    nop

;; BtlPickMoveTarget's two party picks (one member, the whole party) start
;; with BtlSetPartyPickable: from then on the members it puts on the target
;; motion are targets, the acting member as much as any.
rng_party_on:
    lui     at, hi(rng_state)
    ori     v0, zero, 3
    j       RNG_SET_PARTY_PICKABLE
    sb      v0, lo(rng_state)(at)

;; The preview is up for two more frames.
rng_shown:
    lui     at, hi(rng_hover)
    ori     v0, zero, 2
    jr      ra
    sb      v0, lo(rng_hover)(at)
.endarea

.org 0x8008EF60
.area 0x8008F05C - 0x8008EF60
;; BtlCommandCast's call of BtlPersonaSpellUpdate(&row): the frame of the
;; skill board, then the preview of the move now under the cursor.
rng_board_frame:
    addiu   sp, sp, -0x20
    sw      ra, 0x1C(sp)
    jal     RNG_SPELL_UPDATE
    sw      a0, 0x18(sp)
    sw      v0, 0x14(sp)
    lui     a0, hi(RNG_ACTOR_TURN)
    lh      a0, lo(RNG_ACTOR_TURN)(a0)
    jal     RNG_ACTOR_PERSONA           ; (a0 lands before the call reads it)
    nop
    lw      a1, 0x18(sp)
    sll     v1, v0, 3
    addu    v1, v1, v0
    sll     v1, v1, 3                   ; * 0x48
    lh      a1, 0(a1)                   ; the row
    lui     at, hi(RNG_PERSONA_SPELLS)
    addiu   at, at, lo(RNG_PERSONA_SPELLS)
    addu    v1, v1, at
    addu    v1, v1, a1
    lbu     a3, 0(v1)                   ; the move
    nop
    beqz    a3, rng_frame_end
    nop
    jal     rng_show_move
    nop
;; The menus' frames end here: the menu's own answer back in v0.
rng_frame_end:
    lw      ra, 0x1C(sp)
    lw      v0, 0x14(sp)
    jr      ra
    addiu   sp, sp, 0x20

;; The preview of move a3: the side it reaches, or its line thrown from the
;; acting member as BtlPickMoveTarget throws it.
rng_show_move:
    addiu   sp, sp, -0x18
    sw      ra, 0x14(sp)
    jal     rng_move_side               ; t0 = its spell record, v0 = aimed by it
    nop
    beqz    v0, @@done
    nop
    jal     rng_turn_actor
    nop
    lbu     a1, 0x0D(t0)                ; target: the line's shape
    lbu     a2, 0x10(t0)
    jal     RNG_MARK_AREA
    andi    a2, a2, 0xF
@@done:
    lw      ra, 0x14(sp)
    j       rng_shown
    addiu   sp, sp, 0x18
.endarea

.org 0x8008F2F4
.area 0x8008F5DC - 0x8008F2F4
;; The picks, each run with rng_state raised (3 for a party pick, else 1) and
;; g_btl_reach filled first with the side it reaches: t9 = the pick, t2 = that
;; side's first row (0 the enemies, 10 the party), or -1 for the side of the
;; move in a1.
rng_wrap_move:                               ; BtlPickMoveTarget(actor, move)
    lui     t9, hi(RNG_PICK_MOVE)
    addiu   t9, t9, lo(RNG_PICK_MOVE)
    b       rng_wrap
    addiu   t2, zero, -1
rng_wrap_member:                        ; BtlPickTargetMember(actor)
    lui     t9, hi(RNG_PICK_MEMBER)
    addiu   t9, t9, lo(RNG_PICK_MEMBER)
    b       rng_wrap
    ori     t2, zero, 10
rng_wrap_party:                         ; BtlPickTargetParty(actor)
    lui     t9, hi(RNG_PICK_PARTY)
    addiu   t9, t9, lo(RNG_PICK_PARTY)
    b       rng_wrap
    ori     t2, zero, 10
rng_wrap_enemies:                       ; BtlPickTargetEnemies(actor)
    lui     t9, hi(RNG_PICK_ENEMIES)
    addiu   t9, t9, lo(RNG_PICK_ENEMIES)
    b       rng_wrap
    move    t2, zero
rng_wrap_attack:                             ; BtlCommandAttack(): marks its own line
    lui     t9, hi(RNG_ATTACK)
    addiu   t9, t9, lo(RNG_ATTACK)
    move    t2, zero
rng_wrap:
    addiu   sp, sp, -0x20
    sw      ra, 0x1C(sp)
    sw      a0, 0x18(sp)
    sw      a1, 0x14(sp)
    sw      t9, 0x10(sp)
    xori    v0, t2, 10
    sltiu   v0, v0, 1
    sll     v0, v0, 1
    ori     v0, v0, 1                   ; 3 for the party's side, else 1
    lui     at, hi(rng_state)
    bgez    t2, @@side
    sb      v0, lo(rng_state)(at)
    jal     rng_move_side
    move    a3, a1
    b       @@run
    nop
@@side:
    jal     rng_fill
    nop
@@run:
    lw      t9, 0x10(sp)
    lw      a0, 0x18(sp)
    lw      a1, 0x14(sp)
    jalr    t9
    nop
    lui     at, hi(rng_state)
    sb      zero, lo(rng_state)(at)
    lw      ra, 0x1C(sp)
    nop
    jr      ra
    addiu   sp, sp, 0x20

;; Move a3: t0 = its spell record. The moves aimed by their own data
;; (0x75..0x8B, 0xA3 on but 0xDB: decomp src/btlp/pickmove.c) answer v0 = 1;
;; every other fills g_btl_reach with the side it reaches and answers 0: the
;; support kinds the party's (but five of their moves pick an enemy), every
;; other kind the enemies'.
rng_move_side:
    sll     v0, a3, 2
    addu    v0, v0, a3
    sll     v0, v0, 2                   ; * 0x14
    lui     t0, hi(RNG_SPELL_DATA)
    addiu   t0, t0, lo(RNG_SPELL_DATA)
    addu    t0, t0, v0
    addiu   v0, a3, -0x75
    sltiu   v0, v0, 0x17
    bnez    v0, @@aimed
    sltiu   v0, a3, 0xA3
    bnez    v0, @@by_kind
    xori    v0, a3, 0xDB
    bnez    v0, @@aimed
    nop
@@by_kind:
    lbu     v0, 0x0A(t0)
    lui     at, 0x0200
    ori     at, at, 0xE400              ; kinds 0x14 0x1A 0x1C 0x1E 0x32 (SPELL_KIND_MASK 0x3E), halved
    srl     v0, v0, 1
    andi    v0, v0, 0x1F
    srlv    v0, at, v0
    andi    v0, v0, 1
    beqz    v0, rng_fill
    move    t2, zero                    ; first row: the enemies
    addiu   v0, a3, -0x53
    sltiu   v0, v0, 3
    bnez    v0, rng_fill
    xori    v0, a3, 0x5B
    beqz    v0, rng_fill
    xori    v0, a3, 0x6E
    beqz    v0, rng_fill
    nop
    b       rng_fill
    ori     t2, zero, 10                ; the party's rows
@@aimed:
    jr      ra
    ori     v0, zero, 1

;; BtlCommandItem's call of BtlMenuKey, which opens each frame of the item
;; board: then the preview of the item under the cursor.
rng_item_frame:
    addiu   sp, sp, -0x20
    sw      ra, 0x1C(sp)
    jal     RNG_MENU_KEY
    nop
    sw      v0, 0x14(sp)
    lui     v1, hi(RNG_ITEM_ROW)
    lh      v1, lo(RNG_ITEM_ROW)(v1)
    lui     at, hi(RNG_ITEM_SLOTS)
    sll     v1, v1, 1
    addu    at, at, v1
    lhu     v1, lo(RNG_ITEM_SLOTS)(at)
    lui     at, hi(RNG_ITEM_DEFS)
    andi    v1, v1, 0x1FF               ; the item
    sll     v0, v1, 5
    addu    at, at, v0
    lbu     a3, lo(RNG_ITEM_DEFS) + 0x12(at)    ; the move it makes
    nop
    bnez    a3, @@move
    addiu   v1, v1, -0x1A               ; the nine the command aims itself: 0x1A..0x22
    sltiu   at, v1, 9
    beqz    at, rng_frame_end
    addiu   v1, v1, -5
    sltiu   at, v1, 3                   ; 0x1F..0x21 the enemy side,
    bnez    at, @@side
    move    t2, zero
    ori     t2, zero, 10                ; the rest the party's
@@side:
    jal     rng_fill
    nop
    jal     rng_shown
    nop
    b       rng_frame_end
    nop
@@move:
    jal     rng_show_move
    nop
    b       rng_frame_end
    nop

;; BtlCommandEntry's call of BtlPickUpdate(&row): the frame of the command
;; menu, then on the sword or the gun the preview of the weapon's line, as
;; BtlCommandAttack throws it.
rng_menu_frame:
    addiu   sp, sp, -0x20
    sw      ra, 0x1C(sp)
    jal     RNG_PICK_UPDATE
    nop
    sw      v0, 0x14(sp)
    jal     rng_turn_actor
    nop
    lui     v1, hi(RNG_PICK_ROW)
    lh      v1, lo(RNG_PICK_ROW)(v1)
    nop
    beqz    v1, @@weapon
    lhu     v0, 0x20(a0)                ; equip[0]: the sword
    xori    v1, v1, 3
    bnez    v1, rng_frame_end           ; neither the sword nor the gun
    lhu     v0, 0x22(a0)                ; equip[1]: the gun
    nop
    beqz    v0, rng_frame_end           ; no gun
@@weapon:
    nop                                 ; (the sword's load lands)
    sll     v0, v0, 5
    lui     at, hi(RNG_ITEM_DEFS)
    addu    at, at, v0
    lbu     a1, lo(RNG_ITEM_DEFS) + 0x19(at)    ; area
    lbu     a2, lo(RNG_ITEM_DEFS) + 0x1A(at)    ; swing
    jal     RNG_MARK_AREA
    nop
    jal     rng_shown
    nop
    b       rng_frame_end
    nop

;; BtlPickMoveTarget's whole-party pick calls BtlPartyResetGfx right after
;; BtlSetPartyPickable, and it ends by clearing g_btl_reach: the party's side
;; again after it.
rng_party_reset:
    addiu   sp, sp, -0x18
    sw      ra, 0x14(sp)
    jal     RNG_PARTY_RESET_GFX
    nop
    lw      ra, 0x14(sp)
    ori     t2, zero, 10
    j       rng_fill
    addiu   sp, sp, 0x18

;; a0 = the acting member's record.
rng_turn_actor:
    lui     a0, hi(RNG_ACTOR_TURN)
    lh      a0, lo(RNG_ACTOR_TURN)(a0)
    ori     at, zero, RNG_ACTOR_SIZE
    mult    a0, at
    lui     a0, hi(RNG_ACTORS)
    addiu   a0, a0, lo(RNG_ACTORS)
    mflo    at
    jr      ra
    addu    a0, a0, at
.endarea

.org 0x80098C18
.area 0x80098CF4 - 0x80098C18
;; The overlay's tail: store the POLY_G4 cursor, then one DR_MODE linked last
;; so the GPU meets it first, then the arena.
rng_finish:
    sw      s1, lo(RNG_POLYG4_NEXT)(s0)
    lw      a0, lo(RNG_DRMODE_NEXT)(s0)
    lw      v0, 0(s3)
    lui     a1, 0x0200
    and     v1, v0, t3
    or      v1, v1, a1
    sw      v1, 0(a0)                   ; 2 words, then the entry's list
    lui     v1, 0xE100
    ori     v1, v1, 0x0660              ; draw mode: dither, display area on, blend 3 (B + F/4)
    sw      v1, 4(a0)
    lui     v1, 0xE200
    sw      v1, 8(a0)                   ; no texture window
    and     a1, a0, t3
    srl     v0, v0, 24
    sll     v0, v0, 24
    or      v0, v0, a1
    sw      v0, 0(s3)
    addiu   a0, a0, 12
    j       0x80082E6C                  ; the arena, as after the debug grid
    sw      a0, lo(RNG_DRMODE_NEXT)(s0)

;; g_btl_reach = one whole side: rows t2 .. t2 + 4 of every lane. v0 = 0.
rng_fill:
    lui     t1, hi(RNG_REACH)
    addiu   t1, t1, lo(RNG_REACH)
    move    t3, zero                    ; cell = lane * 15 + row
    ori     t4, zero, 15
@@fill:
    divu    t3, t4
    mfhi    v0                          ; the cell's row
    subu    v0, v0, t2
    sltiu   v0, v0, 5
    subu    v0, zero, v0                ; lit (0xFF) on the side, else 0
    sb      v0, 0(t1)
    addiu   t3, t3, 1
    sltiu   at, t3, 75
    bnez    at, @@fill
    addiu   t1, t1, 1
    jr      ra
    move    v0, zero

rng_hover:
    .byte   0                           ; frames the preview still shows
rng_state:
    .byte   0                           ; 1: a pick is up, 3: a pick of party members
.align 4
.endarea

.org RNG_SPELL_CALL
    jal     rng_board_frame             ; was jal BtlPersonaSpellUpdate (delay slot: a0 = &row)
.org RNG_ITEM_KEY_CALL
    jal     rng_item_frame              ; was jal BtlMenuKey
.org RNG_MENU_CALL
    jal     rng_menu_frame              ; was jal BtlPickUpdate (a0 = &row, set before it)
.org RNG_PICK_CALL_CAST
    jal     rng_wrap_move                    ; was jal BtlPickMoveTarget
.org RNG_PICK_CALL_ITEM
    jal     rng_wrap_move
.org RNG_PICK_CALL_MEMBER
    jal     rng_wrap_member             ; was jal BtlPickTargetMember (delay slot: a0 = the member)
.org RNG_PICK_CALL_PARTY
    jal     rng_wrap_party              ; was jal BtlPickTargetParty
.org RNG_PICK_CALL_ENEMIES
    jal     rng_wrap_enemies            ; was jal BtlPickTargetEnemies
.org RNG_COMMAND_FN
    .word   rng_wrap_attack                  ; the sword's row, was BtlCommandAttack
.org RNG_COMMAND_FN + 3 * 4
    .word   rng_wrap_attack                  ; the gun's row
.org RNG_PARTY_ONE
    jal     rng_party_on                ; was jal BtlSetPartyPickable (one member)
.org RNG_PARTY_SIDE
    jal     rng_party_on                ; (the whole party)
.org RNG_PARTY_RESET_CALL
    jal     rng_party_reset             ; was jal BtlPartyResetGfx
