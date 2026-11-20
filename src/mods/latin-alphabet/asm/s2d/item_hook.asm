;; =============================================================
;; S2D.BIN - DrawItemName draws the FULL item name (tools/name_tails.py)
;; Same rule as adv/item_hook.asm: the record's head + the tail bank in
;; the kit's runtime name scratch, and the row draws from there. Dead S2D function.
;; =============================================================

.org S2D_ITEM_NAME_STUB
item_hook_s2d:
    sw      a1, 0x00(sp)            ; dst
    sw      a2, 0x04(sp)            ; base
    la      a0, sf_name_scratch_s2d
    srl     a1, v0, 5               ; v0 = id*32 at the jump
    jal     item_name_copy_s2d
    nop
    lw      a1, 0x00(sp)
    lw      a2, 0x04(sp)
    la      a0, sf_name_scratch_s2d
    li      a3, 10
    j       0x800844E4              ; the row writer's own tail
    nop

.org 0x800844C0
    j       item_hook_s2d
    nop
