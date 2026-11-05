;; Held-START field title. The field's original uploader treats its 20-byte
;; source as ten 16-bit glyph IDs; translated long names can instead be VWF
;; script bytes. Match that exact field against the generated title table and
;; render its complete PSP wording into the same 160x16 VRAM strip. Unknown
;; fields replay the original entry and stay retail.
.if DNG_FIELD_TITLE_WIDTH != 160
    .error "field_title: the fixed 80-byte row stride requires ten 16px cells"
.endif

.org DNG_FIELD_TITLE_ENTRY
    j       dng_field_title_hook
    nop

.org DNG_FIELD_TITLE_ADDR
dng_field_title_hook:
    addiu   sp, sp, -0x40
    sw      ra, 0x3C(sp)
    sw      s0, 0x38(sp)
    sw      s1, 0x34(sp)
    sw      s2, 0x30(sp)
    sw      s3, 0x2C(sp)
    sw      s4, 0x28(sp)
    sw      s5, 0x24(sp)
    sw      s6, 0x20(sp)
    sw      s7, 0x1C(sp)
    lui     t0, 0x800A
    lw      s0, 0x06C0(t0)             ; current floor's 20-byte name field
    la      t0, dng_title_idx
    li      t1, dng_title_count
@@scan:
    beqz    t1, @@fallback
    nop
    move    t2, s0
    move    t3, t0
    li      t4, 20
@@compare:
    lbu     t5, 0(t2)
    lbu     t6, 0(t3)
    addiu   t2, t2, 1
    addiu   t3, t3, 1
    bne     t5, t6, @@next
    addiu   t4, t4, -1
    bnez    t4, @@compare
    nop
    lbu     s3, 0(t3)                  ; full title advance in pixels
    lhu     t5, 2(t3)                  ; blob offset
    la      s1, dng_title_blob
    addu    s1, s1, t5
    sltiu   t5, s3, DNG_FIELD_TITLE_WIDTH + 1
    beqz    t5, @@fallback             ; corrupt or impossible row: retail
    nop
    li      t5, DNG_FIELD_TITLE_WIDTH
    subu    t5, t5, s3
    srl     s2, t5, 1                  ; center the complete title
    sw      s2, 0x18(sp)
    la      s7, dng_field_title_pixels
    move    t0, s7
    addiu   t1, t0, 1280
@@clear:
    sw      zero, 0(t0)
    addiu   t0, t0, 4
    bne     t0, t1, @@clear
    nop
@@character:
    lbu     t0, 0(s1)
    addiu   s1, s1, 1
    li      t1, 0xFF
    beq     t0, t1, @@finished
    addiu   t0, t0, -VWF_FIRST_BYTE   ; byte -> shared VWF index
    sltiu   t1, t0, VWF_GLYPHS
    beqz    t1, @@fallback
    nop
    la      t1, vwf_font_width
    addu    t1, t1, t0
    lbu     s6, 0(t1)
    la      t1, vwf_font_index
    sll     t0, t0, 1
    addu    t1, t1, t0
    lhu     t0, 0(t1)
    lui     s4, 0x801E                  ; FONT.BIN; index is a byte offset
    addu    s4, s4, t0
    beqz    s6, @@fallback
    addu    t1, s2, s6
    sltiu   t1, t1, DNG_FIELD_TITLE_WIDTH + 1
    beqz    t1, @@fallback
    move    s5, zero
@@row:
    lbu     t0, 0(s4)                  ; narrow glyph: 16 rows, MSB left
    addiu   s4, s4, 1
    li      t1, 0x80
    move    t2, zero
@@bit:
    and     t3, t0, t1
    beqz    t3, @@bit_next
    addu    t4, s2, t2                ; pen + bit position
    sltiu   t3, t4, DNG_FIELD_TITLE_WIDTH
    beqz    t3, @@fallback            ; never truncate a visible ink pixel
    sll     t5, s5, 6                 ; row*80 = row*64 + row*16
    sll     t6, s5, 4
    addu    t5, t5, t6
    srl     t6, t4, 1
    addu    t5, t5, t6
    addu    t5, s7, t5
    andi    t6, t4, 1
    sll     t6, t6, 2
    li      t7, 1                      ; ink palette index
    sllv    t7, t7, t6
    lbu     t8, 0(t5)
    nop
    or      t8, t8, t7
    sb      t8, 0(t5)
    sltiu   t3, s5, 15
    beqz    t3, @@bit_next
    addiu   t4, t4, 1
    sltiu   t3, t4, DNG_FIELD_TITLE_WIDTH
    beqz    t3, @@bit_next
    sll     t5, s5, 6
    sll     t6, s5, 4
    addu    t5, t5, t6
    addiu   t5, t5, 80                ; next row; shadow is +1,+1
    srl     t6, t4, 1
    addu    t5, t5, t6
    addu    t5, s7, t5
    andi    t6, t4, 1
    sll     t6, t6, 2
    li      t7, 2                      ; retail shadow palette index
    sllv    t7, t7, t6
    lbu     t8, 0(t5)
    nop
    or      t8, t8, t7
    sb      t8, 0(t5)
@@bit_next:
    srl     t1, t1, 1
    addiu   t2, t2, 1
    sltiu   t3, t2, 8
    bnez    t3, @@bit
    nop
    addiu   s5, s5, 1
    sltiu   t3, s5, 16
    bnez    t3, @@row
    nop
    b       @@character
    addu    s2, s2, s6
@@finished:
    lbu     t0, 0(s1)
    li      t1, 1
    bne     t0, t1, @@fallback
    nop
    lw      t0, 0x18(sp)
    nop
    addu    t0, t0, s3
    bne     t0, s2, @@fallback         ; metadata and script must agree
    nop
    li      t0, 320
    sh      t0, 0x10(sp)
    li      t0, 72
    sh      t0, 0x12(sp)
    li      t0, 40                     ; VRAM units are 16-bit words
    sh      t0, 0x14(sp)
    li      t0, 16
    sh      t0, 0x16(sp)
    addiu   a0, sp, 0x10
    jal     0x8002B810                 ; LoadImage(rect, pixels)
    move    a1, s7
    jal     0x8002B5E8                 ; keep DMA source stable until done
    move    a0, zero
    lw      ra, 0x3C(sp)
    lw      s0, 0x38(sp)
    lw      s1, 0x34(sp)
    lw      s2, 0x30(sp)
    lw      s3, 0x2C(sp)
    lw      s4, 0x28(sp)
    lw      s5, 0x24(sp)
    lw      s6, 0x20(sp)
    lw      s7, 0x1C(sp)
    jr      ra
    addiu   sp, sp, 0x40
@@next:
    addiu   t0, t0, 24
    addiu   t1, t1, -1
    b       @@scan
    nop
@@fallback:
    lw      ra, 0x3C(sp)
    lw      s0, 0x38(sp)
    lw      s1, 0x34(sp)
    lw      s2, 0x30(sp)
    lw      s3, 0x2C(sp)
    lw      s4, 0x28(sp)
    lw      s5, 0x24(sp)
    lw      s6, 0x20(sp)
    lw      s7, 0x1C(sp)
    addiu   sp, sp, 0x40
    addiu   sp, sp, -0x28              ; replay the two stolen retail words
    j       0x8006E708
    sw      s0, 0x18(sp)
.align 4
dng_field_title_pixels:
    .fill 1280, 0                     ; 160 x 16, 4bpp, row-major
dng_field_title_end:
.if DNG_FIELD_TITLE_ADDR < DNG_SPILL_LIMIT
    .error "field_title: renderer overlaps dungeon spill window"
.endif
.if DNG_FIELD_TITLE_LIMIT != DNG_TITLE_TABLE_ADDR
    .error "field_title: upper boundary must meet the title table"
.endif
.if dng_field_title_end > DNG_FIELD_TITLE_LIMIT
    .error "field_title: renderer and scratch overrun their owned window"
.endif
