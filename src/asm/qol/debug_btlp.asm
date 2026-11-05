;; =============================================================
;; QoL (separate enhancement build): the battle debug menu (BTLP.BIN).
;;
;; The retail cheat is BtlCheatWatch (references/persona-decomp
;; src/btlp/cheat.c): it compares the party leader's eight-byte
;; battle name against a fixed kana string and only then watches the
;; second pad for a ten-press sequence; the sequence flips
;; g_btl_debug_hud, and BtlOrdersMenu then opens BtlDebugMenu
;; (src/btlp/debugmenu.c) instead of the orders menu while Cancel is
;; held.
;;
;; The name it wants is しんけたがるべよ, eight glyph codes
;; 0C 2E 09 10 2F 29 41 26. The translation build's name entry is
;; ABC-only (name/abc_only.asm), so that name cannot be typed: the
;; gate would make the debug menu unreachable on every translated
;; disc. This patch drops the gate, leaving the button sequence as the
;; only key - which is what makes it a separate QoL patch rather than
;; part of the translation.
;;
;; Addresses are this project's first-pressing BTLP.BIN (data/psx),
;; not the decomp's: the name loop is 0x8008F06C-0x8008F094, a
;; mismatch jumps to 0x8008F098 with a2 = 0, and 0x8008F098 is the
;; gate itself (beqz a2, 0x8008F134). Nop it and a2 no longer matters;
;; the pad table at 0x800CF100 and its step counter are untouched.
;;
;; In battle, on controller 2: Up Up Down Down Left Right Left Right
;; Cross Circle (fresh presses, any wrong press restarts the count).
;; Then hold Cancel in the command phase for the debug page - Cross on
;; the default control scheme, or whatever Config binds Cancel to.
;; =============================================================
.org 0x8008F098
    nop                                 ; was beqz a2, 0x8008F134 - the name gate
