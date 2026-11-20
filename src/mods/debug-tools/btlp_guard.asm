;; =============================================================
;; Debug tools (--mods=debug-tools): the battle checks its primitive pool every frame and
;; stops on the first frame it finds broken (BTLP.BIN).
;;
;; BtlInitObjects tags six typed runs in both halves of the per-frame pool
;; once per battle (addresses.inc, "BTLP's per-frame primitive pool"); every
;; user takes slots by advancing a run's cursor and rewrites only colours and
;; corners. A slot whose length or command byte is not its run's, or a cursor
;; past its run's end, means something wrote where it must not - the kind of
;; damage that otherwise shows frames or battles later as stray polygons or a
;; GPU that never finishes (docs/MEMORY_AUDIT.md, "Borrowed primitive
;; slots"). On the first such frame the guard records what it found at
;; dbg_guard_info, paints a red 16x16 square at the top left of both frame
;; buffers and spins there, with the pool as the frame left it, for gdb:
;;   dbg_guard_info + 0   1 = a slot's header, 2 = a cursor
;;                  + 4   the slot's address / the cursor variable's address
;;                  + 8   the run's start offset / the cursor's value
;;                  + 12  frames checked (counts up while all is well)
;;
;; It runs from BtlDrawDebugHud (0x8008EA70), which BtlDrawFrame calls first
;; every frame. Only the cheat key debug_btlp.asm retires could raise
;; g_btl_debug_hud (decomp cheat.c), so the function's live part is its
;; flag-off path - the max-damage key cleared and the four HUD objects hidden
;; - which stays as retail up to 0x8008EBD0. What follows only fills the
;; hidden HUD's counters and is replaced; the retail epilogue (0x8008EF44)
;; returns. The SPRT, TILE, F4, G4 and LINE_G2 cursors keep the previous
;; frame's end, which must not be past their run's; the POLY_FT4 cursor ends
;; in the arena / floor mesh area and is left to the headers. The cursors are
;; checked from a battle's second frame (the first draw sets the DR_MODE one),
;; and closing frames are not checked.
;; =============================================================
.org 0x8008EBD0
.area 0x8008EF44 - 0x8008EBD0
    lui     t0, 0x800D
    lbu     v0, -0xF8C(t0)              ; g_btl_closing
    lw      t0, -0xF68(t0)              ; g_btl_prim_pool
    bnez    v0, @@done
    move    t9, zero                    ; the half
@@half:
    la      t1, dbg_guard_runs
@@run:
    lhu     t2, 0(t1)                   ; run start (0: the table's end)
    lhu     t3, 2(t1)                   ; slots
    beqz    t2, @@next_half
    lbu     t4, 4(t1)                   ; stride
    lbu     t5, 5(t1)                   ; length byte
    lbu     t6, 6(t1)                   ; command mask
    lbu     t7, 7(t1)                   ; command
    addu    t8, t0, t2
@@slot:
    lbu     v0, 3(t8)
    lbu     v1, 7(t8)
    bne     v0, t5, @@bad_slot
    and     v1, v1, t6
    bne     v1, t7, @@bad_slot
    addiu   t3, t3, -1
    bnez    t3, @@slot
    addu    t8, t8, t4
    b       @@run
    addiu   t1, t1, 8
@@next_half:
    bnez    t9, @@cursors
    ori     at, zero, 0xE660
    addu    t0, t0, at
    b       @@half
    ori     t9, zero, 1

@@cursors:
    la      t1, dbg_guard_info
    lw      v0, 12(t1)
    lui     t0, 0x800D
    beqz    v0, @@ok                    ; the battle's first frame: the DR_MODE
    lw      t0, -0xF68(t0)              ; cursor is set by the first draw
    la      t1, dbg_guard_cursors
@@cursor:
    lw      t2, 0(t1)                   ; the cursor variable (0: the table's end)
    lw      t4, 4(t1)                   ; its run's end in the frame
    beqz    t2, @@ok
    nop
    lw      t5, 0(t2)
    nop
    subu    t3, t5, t0                  ; offset in the pool
    ori     at, zero, 0xE660            ; (sltiu would sign-extend it)
    sltu    v0, t3, at
    bnez    v0, @@in_half
    nop
    subu    t3, t3, at                  ; the second half
@@in_half:
    sltu    at, t4, t3
    bnez    at, @@bad_cursor
    nop
    b       @@cursor
    addiu   t1, t1, 8

@@ok:
    la      t1, dbg_guard_info
    lw      v0, 12(t1)
    nop
    addiu   v0, v0, 1
    sw      v0, 12(t1)                  ; frames checked
@@done:
    j       0x8008EF44                  ; retail's epilogue
    nop

@@bad_slot:
    ori     v0, zero, 1
    move    v1, t8                      ; the slot
    b       @@stop
    move    a1, t2                      ; its run's start
@@bad_cursor:
    ori     v0, zero, 2
    move    v1, t2                      ; the cursor variable
    move    a1, t5                      ; its value
@@stop:
    la      t1, dbg_guard_info
    sw      v0, 0(t1)
    sw      v1, 4(t1)
    sw      a1, 8(t1)
    jal     0x8002B5E8                  ; DrawSync(0): the GPU takes no list now
    move    a0, zero
    lui     t0, 0x1F80
    li      t1, 0x020000FF              ; GP0 fill, red
    li      t2, 0x00100010              ; 16 x 16
    move    t3, zero                    ; y 0, then y 240
@@fill:
    lw      v0, 0x1814(t0)              ; GPUSTAT
    lui     at, 0x0400                  ; ready for a command
    and     v0, v0, at
    beqz    v0, @@fill
    nop
    sw      t1, 0x1810(t0)
    sw      t3, 0x1810(t0)
    sw      t2, 0x1810(t0)
    lui     at, 240
    bne     t3, at, @@fill
    move    t3, at
@@spin:
    b       @@spin                      ; the broken frame stays for gdb
    nop

.align 4
dbg_guard_info:
    .word   0, 0, 0, 0
;; start, slots / stride, length byte, command mask, command
dbg_guard_runs:
    .halfword 0x0070, 450   ; SPRT
    .byte   0x14, 4, 0xFC, 0x64
    .halfword 0x2398, 16   ; TILE
    .byte   0x10, 3, 0xFC, 0x60
    .halfword 0x2498, 450   ; POLY_FT4
    .byte   0x28, 9, 0xFC, 0x2C
    .halfword 0x6AE8, 16   ; POLY_F4
    .byte   0x18, 5, 0xFC, 0x28
    .halfword 0x6C68, 64   ; POLY_G4
    .byte   0x24, 8, 0xFC, 0x38
    .halfword 0x7568, 16   ; LINE_G2
    .byte   0x14, 4, 0xFC, 0x50
    .halfword 0, 0
    .byte   0, 0, 0, 0
;; cursor variable, its run's end
dbg_guard_cursors:
    .word   0x800EEC34, 0x2398          ; g_btl_sprt_next
    .word   0x800EEC38, 0x2498          ; g_btl_tile_next
    .word   0x800EEC40, 0x6C68          ; g_btl_polyf4_next
    .word   0x800EEC44, 0x7568          ; g_btl_polyg4_next
    .word   0x800EEC48, 0x76A8          ; g_btl_lineg2_next
    .word   0x800EEC4C, 0xD6C0          ; g_btl_drmode_next: the ordering table follows
    .word   0, 0
.endarea
