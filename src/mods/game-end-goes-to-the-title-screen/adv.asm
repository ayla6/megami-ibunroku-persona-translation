;; =============================================================
;; GAME END goes to the title screen (--mods=game-end-goes-to-the-title-screen, on by default): GAME END at an Agastya tree goes
;; straight to the title screen (ADV.BIN).
;;
;; Retail (step 0x8009AD48): the GAME END Yes / No prompt; Yes hides the
;; selector (0x8009ADC4..0x8009ADF8), then opens message 9 ("turn off the
;; power", any button returns to the game, 0x8009ADFC) and waits for a
;; button (0x8009AE44) before the Agastya menu step 0x800BCB3C = 0xFF (back
;; to the game). The suspend save (message 20, 0x8009B790) ends the game by
;; setting the bytes 0x800BC320 and 0x800BCB40 to 1.
;;
;; Here Yes sets those two flags instead of opening message 9, so the event
;; overlay leaves with next mode -1 (ATLUS logo, title) at once: no message,
;; no wait. The jump's delay slot is the message pointer's addiu (sysmsg.py
;; writes its low half), harmless; the exit sits over the message call's
;; window rectangle, and the wait loop stays in place, unreached.
;; =============================================================

.org 0x8009ADFC
    j       adv_gameend_exit        ; was lui a0 (message 9's pointer)

.org 0x8009AE0C
.area 0x8009AE44 - 0x8009AE0C
adv_gameend_exit:
    lui     v1, 0x800C
    ori     t0, zero, 1
    sb      t0, -0x3CE0(v1)         ; 0x800BC320
    sb      t0, -0x34C0(v1)         ; 0x800BCB40
    j       0x8009AEB0              ; menu step = v0
    ori     v0, zero, 0xFF
.endarea
