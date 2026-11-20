;; =============================================================
;; BTLP.BIN - typed names and demon names in battle text (FFF9 etc.)
;;
;; 0x8007A86C(a0 = text buffer, a1 = stored name, a2 = max chars) copies a
;; stored small-font name (typed names, demon names) into a text buffer:
;; the name entry stores typed lowercase as the LOW byte of the full-width
;; glyph (ａ = 0x723 -> 0x23). The copy body lives at BTLP_NAME_COPY_ADDR
;; (unreferenced function space, tools/deadovl.py) and maps:
;;   name_sym pairs     -> the VWF byte itself (narrow space, . ' -)
;;   lowercase codes    -> 0x87 prefix (vwf_name_lc != 0), i.e. back to the
;;                         full-width glyph, which vwf_name_map turns into narrow English
;;   >= 0x80            -> 0x80 prefix (A-Z ... via vwf_name_map)
;; Clobbers v0, v1, a0, a1, a2, t0, t1, at; all callers return right after.
;; =============================================================
.org 0x8007A86C
.area 0x8007A8D4 - 0x8007A86C
.if SF_VWF
    j       btl_name_copy
.else
    j       btl_name_encode
.endif
    nop
.endarea

.org BTLP_NAME_COPY_ADDR
.area BTLP_NAME_COPY_SIZE
.if SF_VWF == 0
btl_name_copy:
.endif
btl_name_encode:
    lbu     v1, 0(a1)
    li      v0, 0xFF
    beq     v1, v0, btl_name_encode_end
    addiu   a1, a1, 1
    blez    a2, btl_name_encode_end     ; a2 = characters left
    addiu   a2, a2, -1
.if SF_VWF
    j       btl_compact_lookup
    nop
.else
    la      t0, @@sym
@@sym_loop:
    lbu     t1, 1(t0)
    lbu     v0, 0(t0)
    beqz    t1, btl_name_encode_raw
    addiu   t0, t0, 2
    bne     v0, v1, @@sym_loop
    nop
    b       btl_name_encode_single
    move    v1, t1
.endif
btl_name_encode_raw:
    andi    v0, v1, 0x80
    bnez    v0, @@prefix                ; >= 0x80: prefix 0x80
    li      t0, 0x80
    addiu   t0, v1, -0x23
    sltiu   v0, t0, 35
    beqz    v0, btl_name_encode_single
    lui     at, hi(vwf_name_lc - 0x23)
    addu    at, at, v1
    lbu     v0, lo(vwf_name_lc - 0x23)(at)
    nop
    beqz    v0, btl_name_encode_single  ; not a lowercase code: single byte
    li      t0, 0x87
@@prefix:
    sb      t0, 0(a0)
    addiu   a0, a0, 1
btl_name_encode_single:
    sb      v1, 0(a0)
    b       btl_name_encode
    addiu   a0, a0, 1
btl_name_encode_end:                    ; v0 = 0xFF on both paths
    jr      ra
    sb      v0, 0(a0)
.if SF_VWF == 0
@@sym:
    .byte   0x00, ' ' + 0x68
    .byte   0x47, '.' + 0x68
    .byte   0x51, 0x27 + 0x68
    .byte   0xCC, '-' + 0x68
    .byte   0, 0
.endif
.endarea
