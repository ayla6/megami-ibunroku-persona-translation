;; =============================================================
;; Optional direct Agastya entry (--mods=skip-the-agastya-tree-menu): ADV.BIN.
;;
;; Opening an Agastya tree runs the card checks and the save list (with
;; --mods=unified-save-menu its combined list, mods/unified-save-menu/adv.asm) at once, before the facility's fade-in, without
;; the SAVE / GAME END selector or an extra Accept. Cancel from the list
;; and failed initial card/format checks close the facility. Without this
;; patch the retail selector stays: SAVE enters the same combined list and
;; cancel returns to the selector, and GAME END returns to the title
;; screen with --mods=game-end-goes-to-the-title-screen (mods/game-end-goes-to-the-title-screen/adv.asm). Without --mods=unified-save-menu it opens the retail flow
;; the same way (card choice with two cards, then the slot list).
;;
;; The adapters live in the retired selector's sprite setup
;; (MOD_AGASTYA_RETIRED_SELECTOR_*, mods/skip-the-agastya-tree-menu/agastya.inc).
;; =============================================================
.include "../../skip-the-agastya-tree-menu/agastya.inc"

;; FacilityOpen initializes Agastya BEFORE its shared fade-in. Prepare the
;; whole list there, not on the first dispatcher tick after the fade.
.org 0x8009A370
    jal     mod_prepare_menu

;; Initial card warnings/format choices may now run while the facility is
;; black. Make those interactive prompts visible before waiting for input.
.org 0x8009AB20
    jal     mod_initial_message
.org 0x8009ACAC
    jal     mod_initial_message
.org 0x8009ACC4
    jal     mod_initial_format

;; Agastya is a save facility, not a SAVE / GAME END selector. Keep
;; the badge initialization, then enter the normal card-check/scan path
;; in this same dispatcher tick, without consuming an Accept button.
.org 0x8009A720
    j       0x8009A820             ; SaveScreenOpen's normal epilogue
    nop
.org 0x8009A5D8
    j       0x8009A5E0             ; newly initialized step 1 runs immediately
    nop
.org 0x8009A860
    j       mod_top_entry          ; after SaveTopStep's callee-save prologue
    nop

;; There is no parent selector to return to. Cancel from the list and
;; failed initial card/format checks close the facility (STEP_DONE=FF).
.org 0x8009B4FC
    j       0x8009B54C
    ori     v0, zero, 0xFF
.org 0x8009AB28
    j       0x8009AD20             ; both cards absent: show the error once
    ori     v0, zero, 0xFF
.org 0x8009ACB4
    j       0x8009AD20             ; card error/removal or declined formatting
    ori     v0, zero, 0xFF

;; Retired SAVE / GAME END sprite setup supplies bounded adapter space.
.org MOD_AGASTYA_RETIRED_SELECTOR_START
    .area MOD_AGASTYA_RETIRED_SELECTOR_END - MOD_AGASTYA_RETIRED_SELECTOR_START
mod_prepare_menu:
    addiu   sp, sp, -0x18
    sw      ra, 0x14(sp)
    la      t0, mod_top_fresh
    ori     t1, zero, 1
    sb      t1, 0(t0)              ; the facility's first top step: enter the list
    jal     0x8009A580             ; initialize + scan + list before the fade
    nop
    ;; Slot blackout and BG-layer brightness are independent. The blocking
    ;; fade terminates from BG layer 0, NOT from the slot fade level. Reset
    ;; both after preparation or a bright inherited BG ends it in one frame.
    ;; An initial warning/format prompt has already faded up: do not black
    ;; out an interactive screen a second time after it returns.
    la      t0, 0x800DC00C
    lbu     t0, 0(t0)
    nop
    bnez    t0, mod_prepare_done
    nop
    move    a0, zero
    jal     0x8008BDBC             ; FadeSpritesStep(0, 0): six BG RGB triplets
    move    a1, zero
    jal     mod_card_ready         ; blackout + hidden frames after all card activity
    nop
mod_prepare_done:
    lw      ra, 0x14(sp)
    nop                             ; return to the unchanged retail fade setup
    jr      ra
    addiu   sp, sp, 0x18

    .endarea

;; The selector's own input code (SaveTopStep after its prologue, up to the
;; card checks): mod_top_entry jumps past it, so it is dead.
.org MOD_AGASTYA_RETIRED_TOPSEL_START
    .area MOD_AGASTYA_RETIRED_TOPSEL_END - MOD_AGASTYA_RETIRED_TOPSEL_START
mod_initial_message:
    la      t0, 0x8009C1A8         ; SaveMessage(n, keep)
    b       mod_initial_visible
    nop
mod_initial_format:
    la      t0, 0x8009B9D4         ; SaveOfferFormat(keep)
mod_initial_visible:
    addiu   sp, sp, -0x28
    sw      ra, 0x24(sp)
    sw      t0, 0x20(sp)
    sw      a0, 0x1C(sp)
    sw      a1, 0x18(sp)
    la      t0, 0x800DC00C
    lbu     t0, 0(t0)
    nop
    bnez    t0, mod_initial_fade
    nop
    move    a0, zero
    jal     0x8008BDBC
    move    a1, zero
    jal     mod_card_ready
    nop
mod_initial_fade:
    ori     a0, zero, 4              ; same step as the retail facility fade
    jal     0x8008BCAC             ; FadeUpBlocking, only on initial prompts
    ori     a1, zero, 0x80
    lw      t9, 0x20(sp)
    lw      a0, 0x1C(sp)
    lw      a1, 0x18(sp)
    lw      ra, 0x24(sp)
    addiu   sp, sp, 0x28
    jr      t9
    nop
;; Finish card preparation before the visible ramp. DuckStation continues
;; its automatic card fast-forward for 30 frames after the last access.
;; Render those frames black; on hardware this is a fixed half-second phase.
;; SaveTopStep runs once when the facility opens. It is entered again only
;; by a cancel (the slot list with one card, the card-choice screen with two
;; when --mods=unified-save-menu is off): there is no selector to return to, so that
;; closes the facility, like a cancel from the list (0x8009B4FC).
mod_top_entry:
    la      t0, mod_top_fresh
    lbu     t1, 0(t0)
    nop
    beqz    t1, mod_top_close
    nop
    j       0x8009AAD0             ; the card checks and the list
    sb      zero, 0(t0)
mod_top_close:
    j       0x8009AD20             ; SaveTopStep's step store and epilogue
    ori     v0, zero, 0xFF         ; STEP_DONE
mod_card_ready:
    addiu   sp, sp, -0x18
    sw      ra, 0x14(sp)
    jal     0x80066034             ; FadeBlackout: sprite RGB + slot fade level
    nop
    lw      ra, 0x14(sp)
    ori     a0, zero, MOD_CARD_READY_FRAMES
    j       0x8008BC04             ; RenderFrames: no menu dispatch or card reads
    addiu   sp, sp, 0x18
mod_top_fresh:
    .byte   0
    .align  4
    .endarea
