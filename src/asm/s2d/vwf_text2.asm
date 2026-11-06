;; =============================================================
;; S2D.BIN - VWF for the overworld dialogue box (second text interpreter, 0x8009B2F4)
;;
;; The overworld party comments / door texts are NOT printed by the interpreter that vwf_hooks.asm patches (0x80066F9C...),
;; but by the generic "text object" interpreter 0x8009B2F4 (also used for the arrival banner and the area labels). Its objects
;; are a grid of 16x16 cells (+0x1D8 columns, +0x1DA rows), one 8-byte sprite record per cell at +0x1C, cell pixels
;; uploaded through the queue function 0x80098EC8 to VRAM (+0x1C4,+0x1C6) + cell. The dialogue box is the 15x3 object.
;;
;; Patches:
;;   * glyph decoder 0x8009AE50: only 80-87 are lead bytes of two-byte glyphs (result | 0x8000, like the other overlays),
;;     so 88-E6 pass as single bytes = English VWF characters.
;;   * the glyph function 0x8009AF6C (one call site, 0x8009BA0C) is replaced by s2d_txt_put: 15x3 objects go through the
;;     shared engine (vwf_dialog_emit with a private config); 8x1 area labels and the 15x1 arrival banner go through a
;;     dedicated 1-row VWF path (greedy pen, CLIP on overflow - no wrap / no rewind).
;;     A 1-row object draws only inside its own cols*16 px VRAM strip (labels 8 cells = 128 px, the banner
;;     15 cells = 240 px); glyphs past that limit are skipped, so text can never overwrite the next strip.
;;   * s2d_txt_activate (engine callback): uploads the composed cell and creates / reuses the cell's sprite record.
;;   * the message window's background plate (the banner band, func_800937FC): s2d_plate_w
;;     supplies the pen extent s2d_txt_put keeps per object, plus 8px margin either side,
;;     so the plate hugs the text actually laid into the window.
;; The engine's pos = object +0x12 (state = object + 8); the interpreter's own scroll / page logic is unchanged.
;; Colours of this box: main 1, shadow 2 at (+1,+1) (set in vwf_dlg_state for the duration of the call).
;; Code and config live behind the English boxes in the extension of S2D.BIN (tools/s2dscript.py SPILL).
;; =============================================================

S2D_TXT_PUT_ORIG        equ 0x8009AF6C
S2D_TXT_UPLOAD          equ 0x80098EC8          ; (src, x, y, w, stack+0x10 = h): queue a LoadImage
S2D_TXT_ATTR            equ 0x8002DF60          ; (a0, a1) -> sprite attribute halfword
S2D_MSG_STEPS           equ 0x800B1604          ; script steps the message window took before it stopped
                                                ; (decomp D_800B0EE4; retail's plate width factor)
S2DT_STRUCT             equ 0x10                ; config: text object (@@vwf path)
S2DT_COUNT              equ 0x14                ; config: queued entry count
S2DT_ENTRY              equ 0x18                ; config: queue entry {u32 src; u16 x, y, w, h}
S2DT_NEXT               equ 0x24                ; config: round-robin pen-table victim (word)
S2DT_NPENS              equ 24                  ; per-object (pen, cleared cells):
S2DT_PENS               equ 0x28                ; banner, labels and proximity
                                                ; resumes interleave freely; a
                                                ; shared pen would restart every
                                                ; other call, and every draw would
                                                ; wipe the previous glyph's cell
SPACE_ADVANCE           equ 4                   ; blank advance (font/vwf_width.bin[0])

;; --- decoder: 80-87 = two-byte glyph (flagged 0x8000), everything else single ---
.org 0x8009AE58
    addiu   v0, v0, -0x80
    sltiu   v0, v0, 8
    bnez    v0, 0x8009AE70
.org 0x8009AE70
    lbu     v0, 0(a0)
    addiu   a0, a0, 1
    lbu     v1, 0(a0)
    ori     v0, v0, 0x80
.org 0x8009BA0C
    jal     s2d_txt_put

;; --- name inserts: the text object keeps the slot's real length, not 5 ---
;; S2dCopyChars (0x8009AEE0) copies the hero's family / given slot into the
;; text object's cell array. Its fixed cap of five cut every compact name
;; (8 VWF bytes + FF 01) short and is still right for an older save (five
;; retail glyphs = exactly ten bytes, no terminator). Ask the slot: FF in
;; it -> 8, absent -> 5. The call's delay slot is retail's
;; `ori s2,zero,0xff` at 0x8009AF10.
.org 0x8009AF0C
    jal     s2d_name_cap

;; --- the window's background plate hugs the VWF text ---
;; func_800937FC (the message window's per-frame draw) uses the text's
;; real extent: a2 = plate width in pixels, including 8px margin per side.
;; The quad corners are -8 / width-8 and -12 / 12 in window space.
.org 0x80093FD4
    move    a0, s1                      ; s1 = the text object (set by the draw)
    jal     s2d_plate_w                 ; v0 = plate width in px
    addiu   a3, sp, 0x28                ; (delay slot: unchanged)
    sw      zero, 0x98(sp)              ; unchanged
    move    a2, v0
.org 0x80094034
    nop                                 ; a2 is already in px

.org S2D_GLUE_ADDR
.area S2D_GLUE_SIZE

s2d_txt_put:
    lh      t0, 0x1D8(a0)               ; cols
    li      t1, 15
    bne     t0, t1, @@row1              ; 8x1 area label
    lh      t0, 0x1DA(a0)               ; rows
    li      t1, 3
    bne     t0, t1, @@row1              ; 15x1 arrival banner
    nop
    j       @@vwf                       ; 15x3 dialogue: shared engine
    nop
@@row1:                                 ; 1-row VWF: greedy pen, CLIP on
    addiu   sp, sp, -0x38               ; overflow (no wrap, no rewind:
    sw      ra, 0x34(sp)                ; cannot hang - the reverted
    sw      s0, 0x30(sp)                ; attempt routed these through
    sw      s1, 0x2C(sp)                ; the wrapping engine)
    sw      s2, 0x28(sp)                ; (s1-s3: interpreter holds the
    sw      s3, 0x24(sp)                ; text object in s1 across the
    sw      s4, 0x20(sp)                ; glyph call - the original putter
    sw      s5, 0x1C(sp)                ; saved s0-s3, so must we)
    move    s4, a0                      ; s4 = text object (draw keeps s4)
    la      t0, vwf_dlg_state
    li      t1, 1
    sb      t1, 8(t0)                   ; main colour: the map/banner CLUT
    li      t1, 2                       ; has ink in slot 1, dark in slot 2
    sb      t1, 9(t0)                   ; (same swap as the DNG script box;
    li      t1, 1                       ; 2/1 renders inverted, proven live)
    sb      t1, 10(t0)                  ; shadow offset x
    la      s5, s2d_txt_cfg
    sw      s4, S2DT_STRUCT(s5)           ; activate + upload read the object here
    sw      zero, S2DT_COUNT(s5)
    la      t0, vwf_dlg_state
    lh      t1, DLG_INIT(t0)
    nop
    sw      t1, 0x14(sp)                  ; stash the engine's cleared-cell mark
    la      t0, s2d_txt_cfg + S2DT_PENS
    li      t1, S2DT_NPENS
@@find:
    lw      t2, 0(t0)
    nop
    beq     t2, s4, @@hit
    nop
    beqz    t2, @@claim
    nop
    addiu   t0, t0, 8
    addiu   t1, t1, -1
    bnez    t1, @@find
    nop
    lw      t2, S2DT_NEXT(s5)             ; table full: evict round-robin
    nop
    addiu   t3, t2, 1
    slti    t4, t3, S2DT_NPENS
    bnez    t4, @@evok
    nop
    move    t3, zero
@@evok:
    sw      t3, S2DT_NEXT(s5)
    sll     t2, t2, 3                     ; *8 bytes per slot
    la      t3, s2d_txt_cfg + S2DT_PENS
    addu    t0, t3, t2
@@claim:
    sw      s4, 0(t0)                     ; pen and cleared cells restart
    sh      zero, 4(t0)                   ; with a new (or evicted) object
    li      t1, -1
    sh      t1, 6(t0)
    sw      t0, 0x10(sp)                  ; stash slot (draw clobbers t-regs)
    move    s2, zero                      ; pen 0
    la      t2, vwf_dlg_state
    j       @@pen
    sh      t1, DLG_INIT(t2)              ; fresh object: clear touched cells
@@hit:
    lh      t2, 0x12(s4)
    nop
    bnez    t2, @@cont                    ; pos != 0: same text continues
    nop
    sh      zero, 4(t0)                   ; pos == 0: restarted text
    li      t1, -1
    sh      t1, 6(t0)
    sw      t0, 0x10(sp)
    move    s2, zero
    la      t2, vwf_dlg_state
    j       @@pen
    sh      t1, DLG_INIT(t2)
@@cont:
    lhu     s2, 4(t0)                     ; pen persists per object
    lhu     t1, 6(t0)                     ; cleared cells persist with it
    la      t2, vwf_dlg_state             ; (otherwise each draw would wipe
    sh      t1, DLG_INIT(t2)              ; the previous glyph's cell)
    sw      t0, 0x10(sp)
@@pen:
    andi    t2, a1, 0x8000              ; glyph decode, mirrors vwf_dialog_emit
    bnez    t2, @@wide
    andi    s1, a1, 0x7FF
    andi    t2, a1, 0xFFFF
    sltiu   t3, t2, 0x80
    bnez    t3, @@wide                  ; original single-byte glyph
    addiu   t1, t2, -0x88               ; VWF index (delay slot)
    sltiu   t3, t1, VWF_GLYPHS
    beqz    t3, @@nud                   ; stray byte (80-87 lead arriving
    nop                                 ; singly, E7+ gap): nudge, no draw
    beq     t1, zero, @@space           ; 0x88 = space
    nop
    j       @@narrow
    nop
@@nud:
    li      s3, 4
    j       @@skip
    nop
@@space:
    li      s3, SPACE_ADVANCE
    j       @@skip
    nop
@@narrow:
    la      t3, vwf_font_width
    addu    t3, t3, t1
    lbu     s3, 0(t3)                   ; advance
    la      t3, vwf_font_index
    sll     t1, t1, 1
    addu    t3, t3, t1
    lhu     t1, 0(t3)
    lui     a0, 0x801E                  ; FONT_GLYPHS_ADDR: rows 1-14 packed
    addu    a0, a0, t1
    li      a1, 0
    j       @@limit
    nop
@@wide:
    sll     s1, s1, 5
    lui     a0, 0x801E
    addu    a0, a0, s1
    li      s3, 16
    li      a1, 1
@@limit:
    lh      t5, 0x1D8(s4)               ; the object's own width: its VRAM
    nop                                 ; (load delay)
    sll     t5, t5, 4                   ; strip is exactly cols 16-px cells, so
                                        ; a glyph past it would land in the
                                        ; neighbouring strip (a label's is
                                        ; 8 cells, the banner's 15)
    addu    t7, s2, s3
    sltu    t7, t5, t7                  ; LIMIT < pen+adv: clipped
    bnez    t7, @@skip
    nop
    jal     vwf_dialog_draw
    move    s0, zero                    ; line 0 (delay slot)
@@skip:
    lh      t8, 0x1D8(s4)               ; pos tracks the pen's cell (retail
    lh      t9, 0x1DA(s4)               ; counted cells, not glyphs - plates
    addu    s2, s2, s3                  ; and the grid-full latch read cells;
    lw      t0, 0x10(sp)                ; counting glyphs would oversize both
    nop                                 ; and trip the latch at pos == grid,
    sh      s2, 4(t0)                   ; locking out further script reads)
    la      t2, vwf_dlg_state
    lh      t2, DLG_INIT(t2)
    nop
    sh      t2, 6(t0)                   ; persist pen + cleared cells per object
    srl     t7, s2, 4                   ; cell of pen, 1-based (0 stays fresh-only
    addiu   t7, t7, 1                   ; so the pen-table restart check keeps working)
    mult    t8, t9                      ; grid cells; VWF pixels need no cells
    nop                                 ; (mult + load latency)
    nop
    mflo    t8
    addiu   t8, t8, -1                  ; cap at grid-1 (never latches)
    slt     t6, t8, t7                  ; cell beyond cap?
    beqz    t6, @@storepos
    nop
    move    t7, t8
@@storepos:
    sh      t7, 0x12(s4)
@@posdone:
    la      t0, vwf_dlg_state
    li      t1, 1
    sb      t1, 8(t0)
    li      t1, 2
    sb      t1, 9(t0)
    li      t1, 2
    sb      t1, 10(t0)
    lw      ra, 0x34(sp)
    lw      t0, 0x14(sp)                  ; stashed engine cleared-cell mark
    lw      s0, 0x30(sp)
    la      t2, vwf_dlg_state
    sh      t0, DLG_INIT(t2)              ; the dialogue engine must not see ours
    lw      s1, 0x2C(sp)
    lw      s2, 0x28(sp)
    lw      s3, 0x24(sp)
    lw      s4, 0x20(sp)
    lw      s5, 0x1C(sp)
    jr      ra
    addiu   sp, sp, 0x38
@@vwf:
    addiu   sp, sp, -0x30
    sw      ra, 0x2C(sp)
    sw      s0, 0x28(sp)
    sw      s1, 0x24(sp)
    sw      s2, 0x20(sp)
    move    s0, a0                      ; s0 = text object
    sw      a1, 0x1C(sp)
    la      t0, s2d_txt_cfg
    addiu   t1, a0, 8
    sw      t1, 0(t0)                   ; engine state = object + 8 (pos at +0xA = object +0x12)
    sw      a0, S2DT_STRUCT(t0)
    sw      zero, S2DT_COUNT(t0)
    lhu     t2, 2(a0)
    nop                                 ; load delay
    andi    s1, t2, 0x100               ; s1 = 1-flag: glyph comes from the name buffer (pointer +8), else script (+0xC)
    bnez    s1, @@buf
    lw      s2, 0xC(a0)                 ; s2 = read pointer after the glyph
    j       @@go
    nop
@@buf:
    lw      s2, 8(a0)
@@go:
    la      t0, vwf_dlg_state
    li      t1, 1
    sb      t1, 8(t0)                   ; main colour
    li      t1, 2
    sb      t1, 9(t0)                   ; shadow colour
    li      t1, 1
    sb      t1, 10(t0)                  ; shadow offset x
    la      a0, s2d_txt_cfg
    li      a1, 0
    jal     vwf_dialog_emit
    lw      a2, 0x1C(sp)
    la      t0, vwf_dlg_state
    li      t1, 2
    sb      t1, 8(t0)
    li      t1, 1
    sb      t1, 9(t0)
    li      t1, 2
    sb      t1, 10(t0)
    beqz    s1, @@script
    nop
    lw      t0, 8(s0)                   ; name buffer: rewound = the engine handed the glyph back
    nop
    beq     t0, s2, @@ret
    nop
    addiu   t0, t0, -2
    j       @@ret
    sw      t0, 8(s0)
@@script:
    sw      s2, 0xC(s0)
@@ret:
    lw      ra, 0x2C(sp)
    lw      s0, 0x28(sp)
    lw      s1, 0x24(sp)
    lw      s2, 0x20(sp)
    jr      ra
    addiu   sp, sp, 0x30
@@orig:
    andi    a1, a1, 0x7FFF              ; flagged two-byte glyph -> original glyph index
    j       S2D_TXT_PUT_ORIG
    nop

;; s2d_txt_activate(a0 = cell P): upload the composed cell, make sure cell P has a sprite record
s2d_txt_activate:
    addiu   sp, sp, -0x38
    sw      ra, 0x34(sp)
    sw      s0, 0x30(sp)
    sw      s1, 0x2C(sp)
    sw      s2, 0x28(sp)
    sw      s3, 0x24(sp)
    move    s3, a0                      ; P
    la      s0, s2d_txt_cfg
    lw      s1, S2DT_STRUCT(s0)         ; text object
    li      t0, 15
    divu    s3, t0
    mflo    t1                          ; row
    mfhi    t2                          ; col
    lw      a0, S2DT_ENTRY(s0)          ; src: ring cell queued by the engine
    lh      t3, 0x1C4(s1)
    sll     t4, t2, 2
    addu    a1, t3, t4                  ; x (16-bit units)
    lh      t3, 0x1C6(s1)
    sll     t4, t1, 4
    addu    a2, t3, t4                  ; y
    li      a3, 4
    li      t3, 16
    jal     S2D_TXT_UPLOAD
    sw      t3, 0x10(sp)
    sw      zero, S2DT_COUNT(s0)
    li      t0, 15
    divu    s3, t0
    mflo    t1
    mfhi    t2
    lhu     t8, 0x1DA(s1)               ; 1-row objects: the text continues
    li      t9, 1                       ; past the grid - the screen column
    bne     t8, t9, @@scr1              ; is linear (P), the row stays 0
    nop
    move    t2, s3
    move    t1, zero
@@scr1:
    sll     t5, t2, 4                   ; x px
    sll     t6, t1, 4                   ; y px
    lhu     t7, 6(s1)                   ; sprite count
    move    t8, zero
    addiu   t9, s1, 0x1C
@@find:
    beq     t8, t7, @@append
    nop
    lh      t3, 4(t9)
    lh      t4, 6(t9)
    bne     t3, t5, @@next
    nop
    beq     t4, t6, @@done              ; the cell already has its record
    nop
@@next:
    addiu   t8, t8, 1
    j       @@find
    addiu   t9, t9, 8
@@append:
    sh      t5, 4(t9)
    sh      t6, 6(t9)
    lh      t3, 0x1C4(s1)
    lh      t4, 0x1C6(s1)
    andi    t3, t3, 63
    andi    t4, t4, 0xFF
    sll     t3, t3, 2
    addu    t3, t3, t5
    sb      t3, 0(t9)                   ; u
    addu    t4, t4, t6
    sb      t4, 1(t9)                   ; v
    sw      t9, 0x20(sp)
    lh      a0, 0x1C8(s1)
    lh      a1, 0x1CA(s1)
    lh      t0, 0x10(s1)
    nop                                 ; load delay
    addu    a1, a1, t0
    jal     S2D_TXT_ATTR
    nop
    lw      t9, 0x20(sp)
    lhu     t0, 6(s1)
    sh      v0, 2(t9)
    addiu   t0, t0, 1
    sh      t0, 6(s1)
@@done:
    lw      ra, 0x34(sp)
    lw      s0, 0x30(sp)
    lw      s1, 0x2C(sp)
    lw      s2, 0x28(sp)
    lw      s3, 0x24(sp)
    jr      ra
    addiu   sp, sp, 0x38

;; s2d_plate_w(a0 = text object) -> v0 = the window plate's width in px.
;; Retail: (steps+1)*16 - the entry's byte length in 16px cells plus the
;; 8px margin the plate keeps either side (its corners are -8 .. width-8).
;; The real extent of the text is the pen s2d_txt_put keeps per object, so
;; a 1-row window (banner, labels: the only ones s2d_txt_put lays, see its
;; routing) gets pen+16; anything else (the 15x3 dialogue window runs the
;; shared engine and keeps no pen) falls back to the retail formula.
;; Called from the plate draw with only t-regs and v0 touched.
s2d_plate_w:
    lhu     t0, 0x1DA(a0)               ; rows
    li      t1, 1
    bne     t0, t1, @@retail
    nop
    la      t0, s2d_txt_cfg + S2DT_PENS
    li      t1, S2DT_NPENS
@@f:
    lw      t2, 0(t0)
    nop
    beq     t2, a0, @@hit
    nop
    addiu   t0, t0, 8
    addiu   t1, t1, -1
    bnez    t1, @@f
    nop
@@retail:
    la      t2, S2D_MSG_STEPS
    lw      t2, 0(t2)
    nop
    addiu   t2, t2, 1
    sll     v0, t2, 4                   ; (steps+1)*16, as retail
    jr      ra
    nop
@@hit:
    lhu     v0, 4(t0)                   ; the pen = the text's pixel width
    jr      ra
    addiu   v0, v0, 16                  ; + the 8px margin either side

;; S2dCopyChars cap: a0 = a 10-byte name slot; sets s3 (the caller's loop
;; cap) to 8 when the slot is FF-terminated, else 5. Preserves a0 and every
;; register the caller keeps live (s0-s2); writes s3 and clobbers t0-t3 only.
s2d_name_cap:
    move    t0, a0
    li      t1, 10
    li      t3, 0xff
@@scan:
    lbu     t2, 0(t0)
    nop
    beq     t2, t3, @@compact
    addiu   t0, t0, 1
    addiu   t1, t1, -1
    bnez    t1, @@scan
    nop
    li      s3, 5
    jr      ra
    nop
@@compact:
    li      s3, 8
    jr      ra
    nop

.align 4
s2d_txt_cfg:                            ; engine config (vwf_dialog.asm): state, activate, upload count*, upload queue*
    .word 0, s2d_txt_activate, s2d_txt_cfg + S2DT_COUNT, s2d_txt_cfg + S2DT_ENTRY
    .word 0                             ; S2DT_STRUCT
    .word 0                             ; S2DT_COUNT
    .fill 12, 0                         ; S2DT_ENTRY
    .word 0                             ; S2DT_NEXT (pen-table victim)
    .fill S2DT_NPENS * 8, 0             ; S2DT_PENS: (obj, pen, cleared cells)
.endarea

;; Keep the established S2D extension boundary; the shared compositor ring
;; is resident runtime scratch, not S2D memory reused by other overlays.
.org 0x800BC170
s2d_glue_end:
