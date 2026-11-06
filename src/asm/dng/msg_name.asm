;; =============================================================
;; DNG.BIN - MsgStep cases 9-12 print the full inserted name
;; (stubs: vwf/sf_msg_name.asm, placed in dng/smallfont.asm)
;;
;; 9 item    0x80076F14  j to the case's own tail; v0 still holds the id
;; 10 skill  0x80076F38  the base load becomes the jump; a0 still holds the id
;; 11 demon  0x80076F68  same
;; 12 Persona 0x80076F8C same, with the id in v1
;; =============================================================
sf_msg_name_patches sf_msg_item_dng, sf_msg_skill_dng, sf_msg_demon_dng, \
                    sf_msg_persona_dng, \
                    0x80076F14, 0x80076F38, 0x80076F68, 0x80076F8C
