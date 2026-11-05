;; =============================================================
;; QoL (separate enhancement build): half the random encounter rate in the overworld (S2D.BIN).
;; 0x8009686C runs once per step: no roll during the first 32 steps after a battle
;; (counter 0x800B9C4C), then a battle when rand() % 64 < zone threshold
;; (table 0x80065064: -1, 2, 4, 8). Mean steps between battles =
;; 32 + 64 / threshold = 64 / 48 / 40. Constants only, no new code.
;; =============================================================
.org 0x80096964
    slti    v0, v0, 0x21 ; grace counter caps at 32
.org 0x8009696C
    ori     v0, zero, 0x20
.org 0x80096980
    ori     v0, zero, 0x20 ; roll only once the counter reached 32
.org 0x800969B0
    addiu   v0, a0, 0x3F ; rand() % 64
.org 0x800969BC
    sra     v0, v0, 6
.org 0x800969C4
    sll     v0, v0, 6
