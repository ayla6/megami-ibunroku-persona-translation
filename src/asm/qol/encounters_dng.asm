;; =============================================================
;; QoL (separate enhancement build): half the random encounter rate in the 3D dungeons (DNG.BIN).
;; 0x8007099C runs once per step on a cell with encounter level 1..3: no roll while
;; the cooldown byte (player struct +0x15B0, set to 14 after a battle) counts down,
;; then a battle when rand() % divisor == 0 (table 0x80099ED0: -, 16, 8, 4).
;; Mean steps between battles = 14 + divisor = 30 / 22 / 18. Constants only, no new code.
;; =============================================================
.org 0x80070A8C
    ori     v0, zero, 14 ; cooldown after a fixed-formation cell battle
.org 0x80070B50
    ori     v0, zero, 14 ; cooldown after a random battle
.org 0x80099ED0
    .halfword 0, 16, 8, 4 ; per-step chance 1 / divisor
