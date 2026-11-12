;; =============================================================
;; QoL (--qol=western): the Western button scheme for controller TYPE 1 -
;; Cross confirms and Circle cancels (Circle and Cross swapped, Triangle and
;; Square swapped), as in the American release.
;;
;; Every screen of the game reads the pad through one resident function,
;; PadRead (0x80025140: ADV, BTLP, CASINO, DNG, NAME and S2D all call it), so the swap
;; is made there and the game's own logic - menus, battles, the casino, the
;; name entry, every hard-coded button test - keeps its meaning while the
;; physical buttons trade places. Only TYPE 1 is swapped: the saved
;; controller type is read on every poll, so changing it on the controller
;; page takes effect at once, and TYPE 2 stays as it was.
;;
;; PadRead's tail (nor v0,zero,v0; restore ra and sp; return) is rewritten to
;; jump to the swap in a dead resident function. The held word carries
;; controller 1 in its low half and controller 2 in its high half; both are
;; swapped. PSX pad bits: Triangle 0x10, Circle 0x20, Cross 0x40, Square
;; 0x80. A pair of bits i and j is swapped branch-free:
;;   t = ((v >> (j - i)) ^ v) & (1 << i);  v ^= t | (t << (j - i))
;; The controller page's own labels are swapped in western_layout.asm.
;; =============================================================
.org WESTERN_PAD_READ_NOR
    j       western_pad
    nor     v0, zero, v0                ; (retail: the instruction here; ra and sp restore below)

.org WESTERN_PAD_CODE
.area WESTERN_PAD_CODE_END - WESTERN_PAD_CODE
western_pad:
    lw      ra, 0x10(sp)
    lui     t0, (PAD_TYPE_ADDR >> 16) & 0xFFFF
    lbu     t0, (PAD_TYPE_ADDR & 0xFFFF)(t0)
    lui     t2, 0x0020                  ; (load delay) both halves' Circle mask: 0x00200020
    bnez    t0, @@done                  ; TYPE 2: as it was
    ori     t2, t2, 0x0020
    srl     t1, v0, 1                   ; Circle (bit 5) and Cross (bit 6)
    xor     t1, t1, v0
    and     t1, t1, t2
    sll     t3, t1, 1
    or      t1, t1, t3
    xor     v0, v0, t1
    srl     t1, v0, 3                   ; Triangle (bit 4) and Square (bit 7)
    xor     t1, t1, v0
    srl     t2, t2, 1                   ; 0x00100010
    and     t1, t1, t2
    sll     t3, t1, 3
    or      t1, t1, t3
    xor     v0, v0, t1
@@done:
    jr      ra
    addiu   sp, sp, 0x18
.endarea
