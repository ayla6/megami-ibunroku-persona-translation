;; =============================================================
;; ADV.BIN - MsgStep cases 9-12 print the full inserted name
;; (stubs: vwf/sf_msg_name.asm, placed in adv/smallfont.asm)
;;
;; 9 item    0x80067158  j to the case's own tail; v0 still holds the id
;; 10 skill  0x8006717C  the base load becomes the jump; a0 still holds the id
;; 11 demon  0x800671AC  same
;; 12 Persona 0x800671D0 same, with the id in v1
;; =============================================================
sf_msg_name_patches sf_msg_item_adv, sf_msg_skill_adv, sf_msg_demon_adv, \
                    sf_msg_persona_adv, \
                    0x80067158, 0x8006717C, 0x800671AC, 0x800671D0
