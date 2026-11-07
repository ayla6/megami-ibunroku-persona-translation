;; =============================================================
;; Base game: the resident title switch routes the credits sentinel.
;; (credits/slps.asm)
;;
;; The resident title state reads g_title_choice and indexes retail's
;; five-entry switch at 0x80011558. OPEN.EXE's title hook writes 0xFE for
;; Select (credits/open.asm). This hook runs before the switch:
;;
;;   * every press jumps to the dispatch in OPEN.EXE (credits/open.asm),
;;     which is mapped while the title state runs;
;;   * the dispatch handles 0xFE there and, for a retail choice, does
;;     retail's own bounds test and jumps back to 0x80011558.
;;
;; Only the bounds test (0x80011550..0x80011554) is replaced. Retail's
;; index shift (sll v0,v1,2), its lui at,0x8001 and the table lookup at
;; 0x80011558..0x80011574 stay exactly as shipped, so a retail choice
;; executes the same instructions in the same order as before.
;; =============================================================
.org 0x80011550
    j       CREDITS_DISPATCH_ADDR
    nop
