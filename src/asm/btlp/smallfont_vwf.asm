;; Battle object-text bridge to the existing small-font VWF metrics.
;; Only rows owned by a producer range or a translated-producer span (skill,
;; Persona and complete item names, plus the ANALYZE board's translated rows)
;; are proportional; every other row retains the retail 8px path. A pen/mode word belongs to each renderer
;; invocation, so rows cannot switch modes halfway through a draw.
;; No glyph count, OT, packet size or animation is changed. Owned VWF rows
;; sample separate proportional cells; fixed rows sample original artwork.
.include "../../build/btl_text_centres.asm"
.if BTLP_SF_WIDTH_ADDR != 0x800F8960 || BTLP_SF_CODE_ADDR != BTLP_SF_WIDTH_ADDR + 0x100 || BTLP_SF_END_ADDR != 0x800F8BC4
    .error "battle VWF must fit after the optional reward code in the last loaded sector"
.endif

;; One extra eight-byte stack area per renderer: pen state is above all retail
;; locals and call arguments, including RotTransPers4's output scratch.
.org 0x80088E80
    addiu sp,sp,-0x38
.org 0x800891A4
    addiu sp,sp,0x38
.org 0x800891B0
    addiu sp,sp,-0x70
.org 0x800895C8
    addiu sp,sp,0x70
.org 0x80088F84
    j btl_sf_flat_entry
    nop

;; Party marker names retain retail x = 12 - n * 4 and 8-px pitch. The
;; bounded count loop leaves room for the flat renderer's art adapter;
;; btl_marker_name_tail restores the registers the retail continuation reads.
.org 0x800AA0F8
.area 0x800AA150 - 0x800AA0F8
    lw      a0, 4(s7)                   ; party marker names retain retail pitch
    ori     t3, zero, 0xFF
    ori     v0, zero, 12
    addiu   t4, a0, 8                   ; NAME_CELLS bound
@@width:
    lbu     t2, 0(a0)
    addiu   a0, a0, 1
    beq     t2, t3, @@centred
    nop
    bne     a0, t4, @@width
    addiu   v0, v0, -4
@@centred:
    ori     t0, zero, 0x10
    ori     v1, zero, 0x20
    j       btl_marker_name_tail
    move    a2, zero
btl_sf_flat_art:
    lw      at, 0x30(sp)                ; row's latched mode
    sw      ra, 0x34(sp)
    jal     btl_sf_art_code
    lbu     a0, 0(a3)
    lw      ra, 0x34(sp)
    sw      a0, 0x34(sp)                ; V calculation reads the same mapped cell
    j       0x80088FB0
    nop
.endarea
.org 0x80088FA8
    j       btl_sf_flat_art
    nop
.org 0x80088FDC
    lw      v1, 0x34(sp)
.org 0x80089370
    j       btl_sf_rot_art
    ori     v0, v0, 0x1085             ; displaced divide constant
.org 0x800892C8
    j btl_sf_rot_entry
    nop

.org BTLP_SF_WIDTH_ADDR
.area BTLP_SF_CODE_ADDR - BTLP_SF_WIDTH_ADDR
    ;; Text cells keep the proportional metric; every other cell carries the
    ;; retail 8 px metric (0x08), the sentinel btl_sf_art_code leaves on the
    ;; original cell. Built by smallfont_vwf.py from btl_text_bits.bin.
    .incbin "../../build/btl_sf_width.bin"
.endarea
.org BTLP_SF_CODE_ADDR
.area BTLP_SF_END_ADDR - BTLP_SF_CODE_ADDR
btl_sf_flat_entry:
 addiu sp,sp,-32
 sw t7,0(sp)
 sw t8,4(sp)
 sw t9,8(sp)
 move t7,t3
 move t8,t0
 j btl_sf_common
 addiu t9,sp,0x50 ; original flat frame +0x30
btl_sf_rot_entry:
 addiu sp,sp,-32
 sw t7,0(sp)
 sw t8,4(sp)
 sw t9,8(sp)
 move t7,s5
 move t8,s3
 addiu t9,sp,0x88 ; original transformed frame +0x68
btl_sf_common:
 sw a0,12(sp)
 sw a1,16(sp)
 sw a2,20(sp)
 sw a3,24(sp)
 sw v0,28(sp)
 bnez t8,btl_sf_read_state
 nop
 ; First glyph latches only current producer-owned semantic name rows.
 sw ra,4(t9) ; second word of the bridge's existing extra stack area
 lw a0,4(t7)
 jal btl_name_lookup
 nop
 lw ra,4(t9)
 bnez v0,btl_sf_eligible
 nop
btl_sf_not_vwf:
 addiu a0,zero,-1
 b btl_sf_set_state
 nop
btl_sf_eligible:
 move a0,zero
btl_sf_set_state:
 sw a0,0(t9)
btl_sf_read_state:
 lw a0,0(t9)
 nop
 bltz a0,btl_sf_fallback
 nop
 ; Renderer uses the current live btl_sf_glyph for its UV; use that same byte here.
 addiu a1,sp,0x50
 beq t9,a1,btl_sf_flat_ptr
 nop
 move a1,s4
 b btl_sf_glyph
 nop
btl_sf_flat_ptr:
 lw a1,24(sp) ; saved a3 = current btl_sf_glyph pointer
 nop
btl_sf_glyph:
 lbu a1,0(a1)
 j btl_sf_metric ; a1 = the glyph's width byte (btlp/offer_name.asm)
 nop
btl_sf_metric_back:
 sf_glyph_layout a1, a0, a2, v1, a1
 addu a0,a0,a1
 sw a0,0(t9)
 b btl_sf_done
 nop
btl_sf_fallback:
 sll v1,t8,3
btl_sf_done:
 lw a0,12(sp)
 lw a1,16(sp)
 lw a2,20(sp)
 lw a3,24(sp)
 lw v0,28(sp)
 lw t7,0(sp)
 addiu t8,sp,0x50
 beq t9,t8,btl_sf_flat_return
 lw t9,8(sp)
 lw t8,4(sp)
 addu a1,a1,v1
 j 0x800892d0
 addiu sp,sp,32
btl_sf_flat_return:
 lw t8,4(sp)
 addu v0,v0,v1
 j 0x80088f8c
 addiu sp,sp,32
btl_item_owner_commit:
 ori v0,zero,1
 la at,btl_item_owner
 sb v0,0(at)
 j 0x800AD118
 lw s6,0x28(sp)
;; The rest of the retail state the replaced count loop left (0x800AA0F8).
btl_marker_name_tail:
 move a0,zero
 addiu a1,s3,4
 lui a3,0x8006
 addiu a3,a3,-0x2928
 j 0x800AA150
 ori t1,zero,8
.endarea
