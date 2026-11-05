;; =============================================================
;; SLPS_005.00 - the small-font VWF kit's sorter stubs.
;;
;; The two libgs background sorters' six-word prologues are replaced by a
;; jump into the kit's gate, which lives in FONT.BIN (vwf/sf_font.asm -
;; the only never-wiped resident bytes the project has; SLPS's appended
;; space is BSS the game clears at boot and BIOS territory the loader may
;; not touch, so NOTHING of the kit lives here any more). t4 carries the
;; guard magic the gate checks against the registered entry's own guard
;; word; the FONT.BIN cells pre-name the retail replays, so until an
;; overlay's recorder registers, every sorter call behaves byte-exact
;; retail.
;; =============================================================
.psx
;; addresses.inc and smallfont_defs.asm are already included by main.asm;
;; armips symbols are global and duplicates are errors.

.if SF_VWF
.org GSORT_BG_ADDR
    lui     t0, (SF_FONT_CELL_BG >> 16) & 0xFFFF
    lw      t0, (SF_FONT_CELL_BG & 0xFFFF)(t0)
    j       SF_FONT_GATE_BG
    ori     t4, zero, SF_REG_MAGIC          ; jump delay also separates the pointer load
    nop

.org GSORT_FASTBG_ADDR
    lui     t0, (SF_FONT_CELL_FAST >> 16) & 0xFFFF
    lw      t0, (SF_FONT_CELL_FAST & 0xFFFF)(t0)
    j       SF_FONT_GATE_FAST
    ori     t4, zero, SF_REG_MAGIC
    nop
.endif
