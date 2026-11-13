;; =============================================================
;; QoL (--qol=debug): the endings from the title menu (OPEN.EXE).
;;
;; Every ending (epilogue pages, staff roll) is END.EXE running one of
;; its five real scripts; the resident starts it from GAME_STATE_MOVIE
;; when g_movie_id is 0x30..0x34 (decomp src/main/main.c). On the title
;; menu a fresh press of
;;   L1 = ending 0   L2 = ending 1   R1 = ending 2   R2 = ending 3
;;   Select = ending 4
;; puts the resident there: g_movie_id = 0x30 + n, g_movie_next_state =
;; -1 (boot and title when the script returns), and the resident's own
;; g_state_next (0x68 off the resident's gp, 0x80055BF4: OPEN.EXE has
;; its own gp) = GAME_STATE_MOVIE. The title then leaves through the
;; retail menu-choice tail with the choice 0xFE, which no case of the
;; resident's title switch takes, so g_state_next stays on the movie.
;;
;; The hook enters at the load of the pressed word (0xC(gp)), one
;; instruction before the confirm test, so any other press runs the
;; retail test (or western_open.asm's swapped one) unchanged. Only v0
;; and at are written: v0 is the test's own result register.
;; The code sits in PRIM_OBJ_7A4 (0x8008B53C..0x8008B5C0), a libgpu
;; function nothing in OPEN.EXE calls.
;; =============================================================

.org 0x80081D80
    j       dbg_end_title
    lw      v1, 0xC(gp)                 ; retail: the pressed buttons

.org DBG_END_HOOK
.area DBG_END_HOOK_END - DBG_END_HOOK
dbg_end_title:
    nop
    andi    v0, v1, 0x4                 ; L1
    bnez    v0, @@start
    ori     v0, zero, 0x30
    andi    v0, v1, 0x1                 ; L2
    bnez    v0, @@start
    ori     v0, zero, 0x31
    andi    v0, v1, 0x8                 ; R1
    bnez    v0, @@start
    ori     v0, zero, 0x32
    andi    v0, v1, 0x2                 ; R2
    bnez    v0, @@start
    ori     v0, zero, 0x33
    andi    v0, v1, 0x100               ; Select
    bnez    v0, @@start
    ori     v0, zero, 0x34
    j       0x80081D88                  ; retail's confirm test
    nop
@@start:
    lui     at, hi(DBG_END_MOVIE_ID)
    sh      v0, lo(DBG_END_MOVIE_ID)(at)
    addiu   v0, zero, -1
    sw      v0, lo(DBG_END_MOVIE_NEXT)(at)
    ori     v0, zero, DBG_END_STATE_MOVIE
    lui     at, hi(DBG_END_STATE_NEXT)
    sw      v0, lo(DBG_END_STATE_NEXT)(at)
    j       0x8008223C                  ; store the choice, card scan -1, return
    ori     v0, zero, 0xFE              ; the choice: no title case takes it
.endarea
