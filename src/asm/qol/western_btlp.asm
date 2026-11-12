;; =============================================================
;; QoL (--qol=western): the battle Controls page's button icons.
;;
;; The page lists the actions beside an icon each, one icon set per controller
;; type (descriptors: relative x, y, then h/w/v/u of a 16x12 cell of the
;; button atlas). TYPE 1's set shows circle (u 0xA0), cross (0xB0), square
;; (0xD0), triangle (0xC0), then L1 L2 R1 R2. The actions are the game's own
;; (qol/western_pad.asm swaps the buttons that trigger them), so the icons
;; trade places pairwise: confirm shows Cross, cancel Circle, the square action
;; Triangle and the triangle action Square.
;; =============================================================
.org BTLP_CONTROLS_ICONS + 0 * 8 + 4    ; confirm: circle -> cross
    .byte   0xB0
.org BTLP_CONTROLS_ICONS + 1 * 8 + 4    ; cancel: cross -> circle
    .byte   0xA0
.org BTLP_CONTROLS_ICONS + 2 * 8 + 4    ; square action: square -> triangle
    .byte   0xC0
.org BTLP_CONTROLS_ICONS + 3 * 8 + 4    ; triangle action: triangle -> square
    .byte   0xD0

;; =============================================================
;; The corner icon of the choice menus names the cancel key (pressing it pushes
;; the menu aside to read the text). Retail draws a Cross; TYPE 1's cancel is
;; Circle here, so the blob is laid over with the same image redrawn as a Circle
;; (src/assets/western/indicator.png via injection_tools/western_indicator.py).
;; =============================================================
.org BTLP_INDICATOR_ICON
    .incbin "../../build/western_indicator.mes"
