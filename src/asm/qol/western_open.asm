;; =============================================================
;; QoL (--qol=western): the title and its load list (OPEN.EXE).
;;
;; The title has its own pad poll and tests its buttons in place, so the
;; masks it tests are swapped here instead of the pad word (qol/western_pad.asm
;; covers every screen that reads PadRead). It runs before a save is loaded,
;; so it follows no controller type. `pressed` is the word at 0xC(gp); the
;; andi immediates below are the retail Circle/Cross/Square tests:
;;   0x20 Circle <-> 0x40 Cross, 0x10 Triangle <-> 0x80 Square,
;;   0x820 (Start or Circle) -> 0x840 (Start or Cross).
;; =============================================================
.org 0x80081D88                          ; retail andi 0x820
    .halfword 0x840
.org 0x80082140                          ; retail andi 0x40
    .halfword 0x20
.org 0x8008313C                          ; retail andi 0x40
    .halfword 0x20
.org 0x80083170                          ; retail andi 0x80
    .halfword 0x10
.org 0x800831A4                          ; retail andi 0x820
    .halfword 0x840
.org 0x80083768                          ; retail andi 0x40
    .halfword 0x20
.org 0x800837C4                          ; retail andi 0x80
    .halfword 0x10
.org 0x800837F8                          ; retail andi 0x820
    .halfword 0x840
.org 0x80083BD0                          ; retail andi 0x40
    .halfword 0x20
.org 0x80083C7C                          ; retail andi 0x80
    .halfword 0x10
.org 0x80083CB0                          ; retail andi 0x820
    .halfword 0x840
