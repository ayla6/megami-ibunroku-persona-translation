;; CasinoReadPad's sole resident PadRead call, Rev 0. Minigame button
;; assignments are physical controls, so use the unremapped input API.
.org 0x800668E4
    jal western_pad_native
