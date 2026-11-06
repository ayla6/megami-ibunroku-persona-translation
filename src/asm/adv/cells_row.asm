;; =============================================================
;; ADV CellsWriteRow, rewritten in place: sprite-cell rows that also
;; carry each glyph's advance (adv/bar.asm + vwf/sf_bar hook).
;;
;; Retail writes u, v, flag and tpage per cell and leaves the cell's +3
;; byte (the cba high byte) untouched - and the slot renderer never reads
;; it, so it is free to hold the glyph's PEN ADVANCE. This copy stores
;; widths[code] & 0xF there, from the overlay's own small-font advance
;; table (sf_widths_adv, the same table the tile-path recorder uses).
;; Cells that the table gives a zero advance keep it: the bar's advance
;; hook only trusts non-zero bytes, and every printed glyph is 1..15 px.
;;
;; Everything else is byte-for-byte retail semantics: the 16-bit count
;; guard, the 0xFF terminator, u/v/flag/tpage values, and the caller
;; contract (a0-a3, v0-v1, t0-t9, at clobbered - a2 only re-read, never
;; written, so callers can chain row writes without re-setting it;
;; s-registers and ra kept). Nothing reads +3 unless a cel entry carries
;; the SF_BAR_MARK pad, so rows without the mark render exactly as
;; retail. The /31 is the multiply-shift reciprocal (code * 265 >> 13,
;; exact for every code 0..255), replacing retail's 0x08421085 trick.
;;
;; BIT 7 OF THE PAGE ARGUMENT selects the VWF Latin face: each glyph's
;; retail u/v is passed through the overlay's sf_variant_uv selector (the
;; same table the renderer routes its cells through) while the advance
;; still comes from sf_widths_adv. The low 7 bits remain the retail page.
;; The writer has no text tier, so it enters the selector's v1 entry,
;; which pins the regular face. Without the bit the writer is
;; byte-for-byte retail, so every other CellsWriteRow caller keeps the
;; fixed-cell atlas. The selector call is the only reason for the 8-byte
;; frame: ra is preserved across it and nothing else is spilled.
;; =============================================================
.psx
.org ADV_CELLS_ROW
.area 0xC0

cells_row:
    andi    v0, a3, 0xFFFF
    beqz    v0, @@ret0              ; the retail count-0 guard (no frame)
    move    t0, a0                  ; (delay) the cell cursor
    addiu   sp, sp, -8              ; the selector call needs the caller's ra
    sw      ra, 0(sp)
    move    t9, a1                  ; the source cursor (a1 carries u/v)
    ori     t4, zero, 0xFF          ; the terminator
    ori     t5, zero, 265           ; the /31 reciprocal
    ori     t3, zero, 0x3C0         ; flag (the CLUT x the renderer reads)
    andi    t2, a2, 0x7F
    addiu   t2, t2, 0x1A0           ; tpage (the CLUT y the renderer reads)
    la      t8, sf_widths_adv       ; this overlay's advance table

@@row:
    lbu     v1, 0(t9)               ; the glyph code
    addiu   t9, t9, 1
    beq     v1, t4, @@ret           ; 0xFF ends the row (retail)
    addiu   a3, a3, -1              ; (delay)
    multu   v1, t5
    mflo    v0
    srl     v0, v0, 13              ; v0 = code / 31
    sll     t6, v0, 5
    subu    t6, t6, v0              ; q * 31
    subu    a0, v1, t6              ; code % 31
    sll     a0, a0, 3               ; u (a0/a1 are the selector's own in/out pair)
    sll     a1, v0, 1
    addu    a1, a1, v0
    sll     a1, a1, 2               ; v = q * 12
    addu    t1, t8, v1              ; the glyph's advance entry
    andi    t6, a2, 0x80            ; bit 7 of the page: the VWF Latin face
    beqz    t6, @@uv                ; retail face: keep the atlas u/v
    move    v0, v1                  ; (delay) the selector's code
    jal     sf_variant_uv_v1_adv    ; retail code -> the regular Latin cell
    nop
@@uv:
    sb      a0, 0(t0)
    sb      a1, 1(t0)
    lbu     v0, 0(t1)
    sh      t3, 4(t0)               ; (lbu load delay: the flag doesn't read v0)
    andi    v0, v0, 0xF             ; the glyph's pen advance
    sb      v0, 3(t0)               ; +3: the bar's advance hook reads it
    sh      t2, 6(t0)
    addiu   t0, t0, 8
    bnez    a3, @@row
    nop                             ; (delay)

@@ret:
    lw      ra, 0(sp)
    addiu   sp, sp, 8
@@ret0:
    jr      ra
    nop
cells_row_end:
.fill ADV_CELLS_ROW + 0xC0 - cells_row_end

.endarea
