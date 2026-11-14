;; A stat label too wide for its three retail art cells in the original font
;; (menu_gfx.py: MATK, MDEF) is drawn as a text row instead. Each retail
;; call keeps its destination, puts the label's index in a2 and calls this;
;; the row is the glossary wording in small-font codes
;; (build/stat_label_strings.asm: 8 bytes per label, the cell count in the
;; last byte) at text base 0 like the page's other text rows, so the kit
;; draws it in the original font from the retail cells on.
.macro stat_label_text, strings, writer
    sll     t0, a2, 3                   ; 8 bytes per label
    la      a0, strings
    addu    a0, a0, t0
    lbu     a3, 7(a0)                   ; the label's cells
    move    a2, zero                    ; (load delay) text base 0
    j       writer                      ; this overlay's TileMapWriteRow (the kit's hook)
    nop
.endmacro
