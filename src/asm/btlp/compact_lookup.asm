;; The resident name-insert map is the same small-font to ASCII mapping.
;; Use its packed pages instead of carrying a second 215-byte direct table.
;; The retail name-copy body is unreachable after its entry jumps to the
;; replacement at 0x8007A86C. Its remaining 96 bytes hold this lookup.
.org 0x8007A874
.area 88
btl_compact_lookup:
    sltiu   t0, v1, VWF_SMALL_MAP_LEN
    beqz    t0, btl_compact_raw
    srl     t1, v1, 3
    la      t0, vwf_small_pages
    addu    t1, t1, t0
    lbu     t1, 0(t1)
    andi    v0, v1, 7
    beqz    t1, btl_compact_raw
    addiu   t1, t1, vwf_small_map - vwf_small_pages - 1
    addu    t1, t1, t0
    addu    t1, t1, v0
    lbu     t0, 0(t1)
    nop
    beqz    t0, btl_compact_raw
    nop
    j       btl_name_encode_single
    addiu   v1, t0, VWF_CHAR_BIAS
btl_compact_raw:
    j       btl_name_encode_raw
    nop
.endarea
