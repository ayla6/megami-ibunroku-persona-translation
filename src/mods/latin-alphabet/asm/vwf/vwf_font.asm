;; =============================================================
;; FONT.BIN - English VWF glyphs written into unused glyph slots
;; (filler/blank glyphs no text uses; placement by make_vwf_font.py). One
;; edition per disc: FONT_SMALL (build.py --mods='english-translation(font=small)') picks the small face.
;; =============================================================

.ifdef FONT_SMALL
.include "../../latin-alphabet/assets/fonts/vwf_glyphs_small.asm"
.else
.include "../../latin-alphabet/assets/fonts/vwf_glyphs_large.asm"
.endif
