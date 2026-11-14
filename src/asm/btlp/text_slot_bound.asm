;; =============================================================
;; BTLP.BIN - the battle's object drawers stop at the end of their run.
;;
;; Every cell an object draws takes one slot from a typed run of the
;; per-frame primitive pool (addresses.inc, "BTLP's per-frame primitive
;; pool"): flat text (0x80088E80) a SPRT from 0x70..0x2398 of the frame;
;; rotated text (0x800891B0, boards opening and closing) and the two other
;; object drawers at 0x80088AF4 and 0x80089A2C a POLY_FT4 from
;; 0x2498..0x6AE8. 450 of each. Retail never checks: a frame with more cells
;; writes them over the next runs, whose slots keep their own headers - for
;; the rest of the battle, since the runs are tagged once - and draws
;; screen-wide quads or leaves the GPU's list DMA in a loop. The longer
;; English board text is what fills the POLY_FT4 run while a board animates
;; during a turn, and whichever drawer comes last overruns it. Here a cell
;; that finds its run full ends its object instead (the cells already taken
;; stay drawn).
;;
;; Each check sits where its drawer sets the slot's semi-transparency bit
;; from the object (attr bit 0 -> code bit 1): retail loads the cursor twice
;; for that, 18 instructions, written here once. The flat and rotated text
;; renderers do that before touching the slot. The two other drawers write
;; corners or texture coordinates into the slot first, so every POLY_FT4 user
;; stops one slot early: the cursor never passes slot 449, and a cell that
;; finds it has written only into that slot, a POLY_FT4 that is never linked.
;;
;; The arena and floor mesh reuse the POLY_FT4 cursor at 0x76A8 and 0xA588
;; after the objects (decomp objects.c), so the POLY_FT4 checks stop only in
;; the band an overrun reaches first, up to 0x76A8.
;; =============================================================

;; v1 = the POLY_FT4 cursor; to `exit` when it lies in [band, 0x76A8) of this
;; frame (g_btl_prim_pool + g_btl_frame * 0xE660), else set the slot's
;; semi-transparency from the object's attr. 19 instructions.
.macro ft4_bound, attr, band, exit
    lui     v1, 0x800F
    lw      v1, -0x13C4(v1)             ; g_btl_polyft4_next
    lui     at, 0x800D
    lw      v0, -0xF68(at)              ; g_btl_prim_pool
    lbu     at, -0xF08(at)              ; g_btl_frame
    subu    v0, v1, v0
    negu    at, at
    andi    at, at, 0xE660              ; frame 1: one frame further
    subu    v0, v0, at
    addiu   v0, v0, -(band)
    sltiu   v0, v0, 0x76A8 - (band)
    bnez    v0, exit                    ; past the run: end the object
    lw      v0, 0(attr)                 ; (delay) the object's attr
    lbu     at, 7(v1)
    andi    v0, v0, 1
    andi    at, at, 0xFD
    sll     v0, v0, 1
    or      v0, at, v0
    sb      v0, 7(v1)                   ; semi-transparent as the object
.endmacro

;; Flat text: s0 = this frame's last OT entry (frame + 0xE65C), so the SPRT
;; run ends at s0 - 0xE65C + 0x2398. The object still links its DR_MODE
;; (0x80089120).
.org 0x80088F24
.area 0x80088F6C - 0x80088F24
    lui     v1, 0x800F
    lw      v1, -0x13CC(v1)             ; g_btl_sprt_next
    addiu   at, s0, 0x2398 - 0xE65C
    sltu    at, v1, at
    beqz    at, 0x80089120              ; the run is full: end the object
    lw      v0, 0(t1)                   ; (delay) the object's attr
    lbu     at, 7(v1)
    andi    v0, v0, 1
    andi    at, at, 0xFD
    sll     v0, v0, 1
    or      v0, at, v0
    sb      v0, 7(v1)                   ; semi-transparent as the object
    .fill   0x80088F6C - ., 0           ; the rest of retail's two loads
.endarea

;; Rotated text. The 19th instruction comes from the next one: smallfont_vwf.asm
;; moves its lhu into the delay slot of its jump (btl_sf_rot_entry does not
;; read a1 before its third instruction).
.org 0x8008927C
.area 0x800892C8 - 0x8008927C
    ft4_bound s2, 0x6AE8 - 0x28, 0x800895A4
.endarea

;; The drawer at 0x80088AF4 (RotTransPers4 has written the corners). The
;; retail reload of the cursor after the block is v1 already.
.org 0x80088C34
.area 0x80088C84 - 0x80088C34
    ft4_bound s1, 0x6AE8 - 0x28, 0x80088E58
    .fill   0x80088C84 - ., 0
.endarea

;; The drawer at 0x80089A2C (the texture coordinates are written).
.org 0x80089DB4
.area 0x80089E04 - 0x80089DB4
    ft4_bound s2, 0x6AE8 - 0x28, 0x80089FC4
    .fill   0x80089E04 - ., 0
.endarea
