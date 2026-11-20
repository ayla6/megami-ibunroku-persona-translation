;; =============================================================
;; Western controls (--mods=western-controls): the Western button scheme for controller TYPE 1 -
;; Cross confirms and Circle cancels (Circle and Cross swapped, Triangle and
;; Square swapped), as in the American release.
;;
;; Ordinary screens read the pad through one resident function,
;; PadRead (0x80025140: ADV, BTLP, DNG, NAME and S2D call it), so the swap
;; is made there and the game's own logic - menus, battles, the casino, the
;; name entry, every hard-coded button test - keeps its meaning while the
;; physical buttons trade places. Casino uses the separate physical-input API
;; below and keeps native button assignments. Only TYPE 1 is swapped: the saved
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

;; Physical-input API: minigames keep their printed button assignments.
;; Read the library's raw pad buffer without applying the TYPE 1 mapping.
western_pad_native:
    addiu   sp, sp, -0x18
    sw      ra, 0x10(sp)
    jal     0x80041428                 ; retail pad library reader
    nop
    lui     v0, 0x8005
    lw      v0, 0x63F0(v0)            ; retail active-low pad buffer
    lw      ra, 0x10(sp)
    addiu   sp, sp, 0x18
    jr      ra
    nor     v0, zero, v0

;; CellsInit builds the same eight 8x12 button half-cells in ADV, DNG and
;; S2D. Their u coordinates are 0,8 (Circle), 16,24 (Cross), 32,40
;; (Triangle), 48,56 (Square). Swap the sampled artwork for TYPE 1.
;; This covers every map using these icons, including the Velvet Room's
;; Persona-list view hint; text and the surrounding artwork stay intact.
;; a0 = high half of this overlay's cell workspace, supplied by the hook.
western_button_cells:
    lui     t0, (PAD_TYPE_ADDR >> 16) & 0xFFFF
    lbu     t0, (PAD_TYPE_ADDR & 0xFFFF)(t0)
    ori     a0, a0, 0x5FEC
    bnez    t0, @@cells_done
    li      t1, 8
@@cell:
    lbu     t0, 0(a0)
    addiu   t1, t1, -1
    xori    t0, t0, 0x10
    sb      t0, 0(a0)
    bnez    t1, @@cell
    addiu   a0, a0, 8
@@cells_done:
    jr      ra
    nop
.endarea
