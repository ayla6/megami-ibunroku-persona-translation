;; Rev0 item-name producer generation. No glyph counts or source wording change.
.org 0x800ACF0C
    j btl_item_owner_begin
    addiu sp,sp,-0x30
.org 0x800AD110
    j btl_item_owner_commit
    lw ra,0x2C(sp)
;; This second producer puts skill names in the same retail buffer.
.org 0x800AD41C
    j btl_item_owner_clear
    lui t4,hi(BTLP_ITEM_FULL_ADDR)
