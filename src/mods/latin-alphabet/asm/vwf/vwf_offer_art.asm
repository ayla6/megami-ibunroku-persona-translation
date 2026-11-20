;; =============================================================
;; CONTACT panel quad text samples the proportional atlas
;;
;; The offer panel's text is drawn by BtlDrawGlyphs (0x800784D8). Each glyph's
;; four U/V corners come from eight inlined loads of the byte at 0(s1), which
;; therefore sample the retail 8x12 fixed-cell atlas. The pen hooks
;; (offer_position / offer_advance) already position the gated rows with
;; proportional advances, so those quads must sample the proportional atlas:
;; a VWF pen row never renders fixed-cell artwork.
;;
;; The gate knows, per row, whether the row is VWF-positioned, and records it
;; in `at` during the position phase only: 0 for the private personality bank
;; and the offer-name scratch, -1 for every other row. `at` survives the whole
;; glyph loop. BtlDrawGlyphs reads no `at` between the position hook and the
;; eight loads, RotTransPers4 (0x80029E0C) writes no general register below t0,
;; and btl_sf_art_code leaves `at` in {0,1} along its remapping paths and
;; unchanged on its skip path - so a gated row stays gated for all eight loads.
;; The advance phase must leave `at` alone: the retail `sw v0,-0x7c58(at)` in
;; the advance hook's delay slot still stores through the address that
;; BtlDrawGlyphs loads there.
;;
;; The a0 sites call btl_sf_art_code directly. The v0 sites need the answer in
;; v0, so they go through the six-instruction wrapper below - the last 24 bytes
;; of the negotiation unpacker's dead function.
;; =============================================================

;; v0 = glyph byte -> v0 = its proportional atlas cell (-1 in `at`: raw).
;; v1 carries this call's return address across the selector; the site's own
;; delay slot has already loaded the code into v0.
.org 0x800ABD98
.area 24
offer_art_v:
    move    v1, ra
    jal     btl_sf_art_code
    move    a0, v0                      ; delay: the code into the selector's argument
    move    v0, a0
    jr      v1
    nop
.endarea
