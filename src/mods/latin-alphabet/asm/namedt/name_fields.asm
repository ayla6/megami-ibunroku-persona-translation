;; =============================================================
;; NAMEDT.BIN - the family and given name rules take the
;; nickname's eight cells
;;
;; The three name fields are BACKGROUND art, not sprites: g_bg_list is
;; built from entry 3 (16x16 cell definitions over the shared 256x256
;; entry-12 atlas) and entry 4 (a 19x6 cell map), and its rows 2/3/4 are
;; the family/given/nickname rows. The rule under each field is two rows
;; of atlas pixels, palette index 0xE4, at rows 7-8 of that field's
;; 16 px strip:
;;
;;   family  strip v=176 -> rule rows 183,184
;;   given   strip v=192 -> rule rows 199,200
;;   nickname strip v=208 -> rule rows 215,216
;;
;; The nickname rule already runs to atlas u=127 (map column 17 draws
;; cell 48, whose left half carries the closing 8 px), which is eight
;; text cells. The family and given rules stop at u=95 (cell 26's left
;; half), five text cells. long_names.asm widens all three fields to
;; eight cells, so the two short strips take the nickname's run: atlas
;; u 96..127 on their rule rows becomes 0xE4.
;;
;; Only map cells 27/28/37/38 read that atlas region, and only in this
;; background (the keyboard, frame and list packs use other cells), so
;; the rest of each cell keeps its own panel texture and only the rule
;; grows.
;; =============================================================

.macro field_rule, v
.org NAMEDT_ADDR + 0x3350 + v * 256 + 96
    .fill 32, 0xE4
.endmacro

field_rule 183                          ; family rule, upper row
field_rule 184                          ; family rule, lower row
field_rule 199                          ; given rule, upper row
field_rule 200                          ; given rule, lower row
