;; =============================================================
;; Base game: Select on the title screen plays the staff roll.
;; (credits/open.asm)
;;
;; The title menu's input handler is at 0x80081D80: it loads the press into
;; v1 and tests it against the ordinary confirm bits (0x820 = Circle or
;; Start). Select is not used by the title's choice screen, so the hook adds
;; that one test before retail's:
;;   Select -> g_title_choice = 0xFE (the resident's credits sentinel),
;;             g_card_scan = -1, return through the menu-choice epilogue.
;; Any other press runs retail's own test and rejoins its path unchanged.
;;
;; The press word is the BIOS InitPAD buffer read at 0x800826A0: the port's
;; third byte (Select..Left; Select is its bit 0) is shifted into the high
;; half, so Select is 0x0100 - the same bit the title's card path tests at
;; 0x80081C98, and the layout in which retail's 0x820 means Circle or Start.
;;
;; The key stub and the sentinel dispatch both live in the same unreferenced
;; OPEN.EXE function (CREDITS_KEY_ADDR, 0x8008B53C). OPEN.EXE is the title
;; EXE, so it is mapped while the resident title state reads g_title_choice;
;; credits/slps.asm jumps here only for the sentinel, never for a retail
;; choice.
;; =============================================================
.org 0x80081D88
    j       CREDITS_KEY_ADDR
    nop

.org CREDITS_KEY_ADDR
    andi    v0, v1, 0x100               ; Select (InitPAD byte 2, bit 0)
    bnez    v0, credits_key_yes
    nop
    andi    v0, v1, 0x820               ; retail's confirm bits
    beqz    v0, 0x80082138
    nop
    j       0x80081D94                  ; retail's confirm path
    nop
credits_key_yes:
    lui     at, 0x801F
    ori     v0, zero, CREDITS_SENTINEL
    sb      v0, 0x15B8(at)
    lui     at, 0x800B
    addiu   v0, zero, -1
    sw      v0, 0x359C(at)
    j       0x80082250                  ; the menu-choice epilogue
    nop

;; The resident title switch jumps here for every press (credits/slps.asm):
;;   * Select's sentinel starts END.EXE ending 5 (the credits script) and
;;     returns to the boot/title state afterwards;
;;   * a retail choice runs retail's own bounds test and jumps back to
;;     retail's index shift at 0x80011558, so the five cases execute as
;;     shipped (the resident hook replaced only the test before it).
.org CREDITS_DISPATCH_ADDR
    addiu   v0, v1, -CREDITS_SENTINEL   ; zero only for Select's sentinel
    bnez    v0, credits_normal
    lui     at, 0x801F                  ; (delay) the movie globals' page
    ori     v0, zero, CREDITS_ENDING
    sh      v0, 0x15C2(at)              ; g_movie_id
    addiu   v0, zero, -1
    sw      v0, 0x15C4(at)              ; g_movie_next_state
    ori     v0, zero, 6                 ; GAME_STATE_MOVIE
    sw      v0, 0x68(gp)                ; g_state_next
    j       credits_fallthrough
credits_normal:
    sltiu   v0, v1, 5                   ; retail's bounds test; also the j's delay
    beqz    v0, credits_fallthrough     ; slot, so a retail press enters here
    nop
    j       0x80011558                  ; retail's index shift + table lookup
    nop
credits_fallthrough:
    j       0x800113F0                  ; retail's out-of-range return
    nop
