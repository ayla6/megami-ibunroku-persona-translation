;; =============================================================
;; QoL (separate enhancement build): Upper Right movement in the 2D rooms.
;;
;; The isometric room view has four walking directions, each a diagonal on
;; screen. AdvFieldRun maps the d-pad to them: in the retail scheme Up walks
;; to the upper left, Right to the upper right, Down to the lower right and
;; Left to the lower left. This patch keeps the same four screen directions
;; but starts the clockwise order at the upper right instead: Up walks to the
;; upper right, Right to the lower right, Down to the lower left and Left to
;; the upper left. That is the PSP's "Upper Right" setting; there is no
;; setting row on this disc, so this patch is the choice.
;;
;; Only the four direction constants change. The branch order (and so which
;; button wins when two are held) stays retail: Up, Down, Left, Right.
;; AdvFieldRun's entry already loads $at with the walk-direction address, so
;; the Up case reuses it and only needs the value 3 stored.
;; =============================================================
.definelabel adv_upright_enter,  0x8007EB1C    ; AdvFieldRun
.definelabel adv_upright_up,     0x8007EB54    ; up:    ori v0, zero, 3
.definelabel adv_upright_up_store, 0x8007EB58  ;        sh v0, g_adv_walk_dir(at)
.definelabel adv_upright_down,   0x8007EB68    ; down:  ori v0, zero, 2
.definelabel adv_upright_left,   0x8007EB84    ; left:  ori v0, zero, 0
.definelabel adv_upright_right,  0x8007EBA0    ; right: ori v0, zero, 1

.org adv_upright_up
    ori     v0, zero, 3
.org adv_upright_up_store
    sh      v0, -0x3B90(at)                     ; g_adv_walk_dir = 0x800BC470
.org adv_upright_down
    ori     v0, zero, 2
.org adv_upright_left
    ori     v0, zero, 0
.org adv_upright_right
    ori     v0, zero, 1
