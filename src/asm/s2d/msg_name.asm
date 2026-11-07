;; =============================================================
;; S2D.BIN - MsgStep cases 9-12 print the full inserted name
;; (stubs: vwf/sf_msg_name.asm, placed in s2d/smallfont.asm)
;;
;; 9 item    0x80066AC8  j to the case's own tail; v0 still holds the id
;; 10 skill  0x80066AEC  the base load becomes the jump; a0 still holds the id
;; 11 demon  0x80066B1C  same
;; 12 Persona 0x80066B40 same, with the id in v1
;;
;; S2D links the same script VM as ADV and DNG. Its inserts resolved the
;; ten-glyph record head with left = 10, so every English name longer than
;; the head was cut in the overworld/system message boxes as well.
;; =============================================================
sf_msg_name_patches sf_msg_item_s2d, sf_msg_skill_s2d, sf_msg_demon_s2d, \
                    sf_msg_persona_s2d, \
                    0x80066AC8, 0x80066AEC, 0x80066B1C, 0x80066B40
