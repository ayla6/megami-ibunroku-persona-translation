;; =============================================================
;; ADV.BIN - DrawItemName draws the FULL item name (tools/name_tails.py)
;;
;; DrawItemName (ADV 0x80090164) tail-jumps here from 0x8009018C: the name is
;; built in the kit's runtime name scratch (head + tail bank, item_name_copy_adv) and the
;; row draws from there - the smallfont engine walks that string to its
;; own FF; the row count bounds only the logical map and fallback write.
;; VWF placement follows the map's actual geometry. Dead ADV function (tools/deadovl.py).
;; =============================================================

;; DrawItemName's name path: j here (its frame: 0x18, 0x00..0x0C free)
.org ADV_ITEM_NAME_STUB
item_hook_adv:
    sw      a1, 0x00(sp)            ; dst
    sw      a2, 0x04(sp)            ; base
    la      a0, sf_name_scratch_adv
    srl     a1, v0, 5               ; v0 = id*32 at the jump
    jal     item_name_copy_adv
    nop
    lw      a1, 0x00(sp)
    lw      a2, 0x04(sp)
    la      a0, sf_name_scratch_adv
    li      a3, 10
    j       0x800901B0              ; the row writer's own tail
    nop

.org 0x8009018C
    j       item_hook_adv
    nop
