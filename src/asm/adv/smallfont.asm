;; ADV small-font kit: a packed, overlay-owned extension below the CD load ceiling.
.if SF_VWF
.include "../../build/smallfont_fixed_adv.asm"
.org ADV_SF_HOOK_ADDR
    la      t0, sf_cfg_adv
    j       sf_record_adv
    nop
.endif

.org ADV_SF_DATA_ADDR
.if SF_VWF
sf_state_adv:
    .fill SF_ST_END, 0
sf_widths_adv:
    .incbin "../../build/sf_field_width.bin"
sf_pool_adv:
    .incbin "../../build/affinity_pool.bin"
sf_data_end_adv:
.endif

.align 4
    .include "../../build/name_tails_adv.asm"
    .include "../../build/item_names_adv.asm"
sf_item_end_adv:

.if SF_VWF
.align 4
sf_cfg_adv:
    .word SF_ENG_MAGIC, ADV_SF_MAP_BASE, sf_table_adv, 0
    .word ADV_SF_BUFS_ADDR, sf_widths_adv, sf_pool_adv, ADV_SF_HOOK_ADDR + 0x0C
    .word SF_REG_MAGIC
    .include "../../build/smallfont_hook_adv.asm"
    .include "../../build/smallfont_rec_adv.asm"
    .include "../../build/smallfont_helpers_adv.asm"
.align 4
sf_table_adv:
    .fill SF_TABLE_SIZE, 0
sf_table_end_adv:
.endif

.align 4
sf_name_scratch_adv:
    .fill SF_NAME_BYTES, 0
sf_extension_end_adv:
.if sf_extension_end_adv > ADV_SF_EXTENSION_END
    .error "smallfont: packed ADV extension exceeds the sector-safe overlay ceiling"
.endif
.if ADV_SF_BUFS_ADDR + SF_BUFS * SF_BUF_SIZE > ADV_SF_BUFS_LIMIT
    .error "smallfont: ADV packet buffers reach the retail font/map area"
.endif
.if SF_VWF
.org ADV_SF_CENTER_ADDR
    .include "../../build/smallfont_center_adv.asm"
.if sf_center_end_adv > ADV_SF_CENTER_END
    .error "smallfont: ADV centering helper exceeds its dead run"
.endif
.endif
