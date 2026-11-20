;; =============================================================
;; NAME.BIN - the hero's family and given names are 8 characters
;;
;; Retail has eight cells per field but only uses the first five of the
;; family / given fields: the writer stops at five, NameEntryComplete stops
;; the "did you type something?" scan at five, the caret stops at
;; g_name_len = 5, and the two preview sprites are five cells wide. The
;; nickname field is already eight.
;;
;; The save area already has the room - the two slots are 10 bytes each -
;; so no save format grows. New names are written COMPACT: one VWF byte per
;; character (ASCII + 0x68, glyph 0 -> the font's 8 px blank 0x88), then
;; FF 01. Eight characters fill the slot exactly (8 + FF 01 = 10 bytes).
;;
;; A save made before this patch holds five two-byte glyphs = exactly ten
;; bytes with no terminator; a shorter legacy name is FF 01-terminated. So
;; the readers tell the forms apart by the first byte (compact bytes are
;; 0x88 and up, a legacy lead is 0x00 or 0x80-0x87) and count up to FF: the
;; compact count is the FF position, a legacy slot keeps retail's five. The
;; dialogue interpreters stop at FF anyway, so a short compact name prints
;; its own length and no more.
;;
;; The name entry is ABC-only (name/abc_only.asm), so every typed glyph is
;; a full-width Latin letter / digit / symbol the vwf_name_map tables know:
;; the writer runs each cell through vwf_name_map, exactly like the rest of
;; the port, and glyph 0 (the full-width space) becomes 8 px.
;;
;; The preview texture is re-laid out with the fields: at u = g_name_x * 4
;; a field occupies 8 cells = 0x80 texels, so family starts at u = 0x00 and
;; given at u = 0x80. (The old 0x60/0xB0 pair ran past the 8-bit GsSPRITE.u
;; limit once widened.) The family field now overwrites the init-only label
;; glyph upload at (0x200, 0); sprites 23-25 point at the NAMEDT atlas
;; (name_gfx.py), so nothing reads that area any more.
;; =============================================================

;; --- geometry: 8 cells per field, two 8-cell preview strips ---
;; g_name_x: u/4 of each field's first cell (page word x = 0x200 + value)
.org NAME_ADDR + 0x3F18
    .byte 0x00, 0x20, 0x00              ; family u=0x00, given u=0x80, nickname u=0x00
.org NAME_ADDR + 0x3F20
    .byte 8, 8, 8                       ; g_name_len: all three fields use 8 cells

;; Sprites 46 (family) and 47 (given): 8 cells wide, at the new u origins.
.org NAME_ADDR + 0x3F28 + 20 * 46 + 8
    .byte 0x80                          ; w = 8 * 16 px
.org NAME_ADDR + 0x3F28 + 20 * 46 + 0xB
    .byte 0x00                          ; u = g_name_x[0] * 4
.org NAME_ADDR + 0x3F28 + 20 * 47 + 8
    .byte 0x80                          ; w = 8 * 16 px
.org NAME_ADDR + 0x3F28 + 20 * 47 + 0xB
    .byte 0x80                          ; u = g_name_x[1] * 4

;; The init label upload (init.c) expanded three Japanese field labels into
;; tpage 8 at (0x200, 0), then uploaded the strip; the port draws those
;; labels from the NAMEDT atlas instead (name_gfx.py), so the glyphs are
;; dead. The strip is exactly where the eight-cell family preview now
;; starts, so expand the blank glyph 0 six times instead: the first frame
;; must not show the old label glyphs behind the empty family field.
.org NAME_ADDR + 0x3168                 ; 0x8006752C: lhu a0, 0(s0)
    move    a0, zero

;; --- NameEntryComplete: the first two fields are used all eight cells ---
;; entry.c scans NAME_SHORT cells for a non-zero cell and compares i with
;; NAME_SHORT. Both the cap (ori) and the loop bound (slti) are eight now;
;; the nickname's NAME_CELLS loop is already eight.
.org NAME_ADDR + 0x1EFC                 ; 0x800662C0: family, early "found" cap
    ori     v0, zero, 8
.org NAME_ADDR + 0x1F04                 ; 0x800662C8: family loop bound
    slti    v0, v1, 8
.org NAME_ADDR + 0x1F10                 ; 0x800662D4: family, all-zero cap
    ori     v0, zero, 8
.org NAME_ADDR + 0x1F30                 ; 0x800662F4: given, early "found" cap
    ori     v0, zero, 8
.org NAME_ADDR + 0x1F38                 ; 0x800662FC: given loop bound
    slti    v0, v1, 8
.org NAME_ADDR + 0x1F44                 ; 0x80066308: given, all-zero cap
    ori     v0, zero, 8

;; --- the save writer: compact VWF bytes instead of two-byte glyphs ---
;; screen.c (JP) writes field 0 into SAVE_NAME0 and field 1 into SAVE_NAME1:
;; scan back from cell 4 for the last non-zero cell, copy the glyphs
;; (two bytes for a >= 0x80 code), then FF 01 when the field is shorter than
;; five. Both blocks are replaced by a call to name_save_compact, which
;; reads all eight cells and writes the compact form; the nickname block at
;; 0x80064788 (still the retail small-font writer) follows with s0 = 0.
;;
;; No branch or jump outside these blocks targets them (checked: every
;; target inside the span is from the span itself), so overwriting the whole
;; 0x80064614..0x80064788 run is safe. The two small calls plus
;; name_save_compact fit in that run, so no other code home is needed.
.org NAME_ADDR + 0x250                  ; 0x80064614
.area 0x174                             ; ends at the nickname writer, 0x80064788
    li      a0, NAME_SAVE_FAMILY_ADDR
    li      a1, NAME_FAMILY_TEXT_ADDR
    jal     name_save_compact
    li      a2, 8
    li      a0, NAME_SAVE_GIVEN_ADDR
    li      a1, NAME_GIVEN_TEXT_ADDR
    jal     name_save_compact
    li      a2, 8
    j       0x80064788                  ; the nickname block, s0 = its loop index
    move    s0, zero

;; --- name_save_compact(dst, cells, max) ---
;; dst = the 10-byte save slot, cells = g_name_text field (u16), max = 8.
;; Zeroes the slot, finds the field's length (last non-zero cell + 1), writes
;; one VWF byte per cell:
;;   0          -> 0x88 (the font's 8 px blank; vwf_name_map keeps glyph 0
;;                at 16 px for Japanese layouts, but a typed Latin name has
;;                no full-width spaces),
;;   otherwise  -> vwf_name_map(cell | 0x8000); an unmapped glyph (>= 0x100)
;;                becomes '?' (0xA7) rather than a two-byte lead byte,
;; then FF 01 at [len]. The one case with no FF is a legacy five-glyph slot,
;; which this writer never produces.
name_save_compact:
    addiu   sp, sp, -0x20
    sw      ra, 0x1C(sp)
    sw      s0, 0x18(sp)
    sw      s1, 0x14(sp)
    sw      s2, 0x10(sp)
    sw      s3, 0x0C(sp)
    sw      s4, 0x08(sp)
    move    s0, a0                      ; dst
    move    s1, a1                      ; cells
    move    s2, a2                      ; max
    ;; zero the ten bytes (the FF 01 terminator overwrites two of them)
    move    t0, s0
    li      t1, 10
@@zero:
    sb      zero, 0(t0)
    addiu   t0, t0, 1
    addiu   t1, t1, -1
    bnez    t1, @@zero
    nop
    ;; len = index of the last non-zero cell + 1 (0 if the field is empty)
    move    s3, zero
    move    t0, s2
@@scan:
    beqz    t0, @@scan_done
    nop
    addiu   t0, t0, -1
    sll     t1, t0, 1
    addu    t1, s1, t1
    lhu     t2, 0(t1)
    nop
    bnez    t2, @@scan_found
    nop
    b       @@scan
    nop
@@scan_found:
    addiu   s3, t0, 1
@@scan_done:
    ;; one compact byte per cell
    move    s4, zero
@@glyph:
    beq     s4, s3, @@term
    nop
    sll     t1, s4, 1
    addu    t1, s1, t1
    lhu     a0, 0(t1)
    nop
    bnez    a0, @@not_space
    nop
    li      t2, 0x88                    ; glyph 0 = the 8 px blank
    b       @@store
    nop
@@not_space:
    ori     a0, a0, 0x8000              ; vwf_name_map's two-byte glyph form
    jal     vwf_name_map
    nop
    move    t2, v0
    li      t4, 0x100
    sltu    t5, t2, t4                  ; a VWF byte is < 0x100
    bnez    t5, @@store
    nop
    li      t2, 0xA7                    ; '?' (ASCII + VWF_CHAR_BIAS)
@@store:
    addu    t1, s0, s4
    sb      t2, 0(t1)
    addiu   s4, s4, 1
    b       @@glyph
    nop
@@term:
    addu    t1, s0, s3
    li      t2, 0xFF
    sb      t2, 0(t1)
    addiu   t1, t1, 1
    li      t2, 1
    sb      t2, 0(t1)
    lw      ra, 0x1C(sp)
    lw      s0, 0x18(sp)
    lw      s1, 0x14(sp)
    lw      s2, 0x10(sp)
    lw      s3, 0x0C(sp)
    lw      s4, 0x08(sp)
    jr      ra
    addiu   sp, sp, 0x20
.endarea
