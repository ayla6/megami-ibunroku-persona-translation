;; CardSave is called only by ADV's save screen. Its summary stamp lives
;; in that overlay's retired code, not CD-system globals at 0x80055C10.
.include "qol/saves.inc"
.org 0x8001427C
    j       qol_stamp
    nop
