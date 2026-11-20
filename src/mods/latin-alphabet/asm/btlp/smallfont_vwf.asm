;; Battle object-text bridge to the small-font VWF metrics. Every row is laid
;; out proportionally. A producer's name row (skill, Persona and complete item
;; names, the ANALYZE board) samples the separate proportional cells with
;; their metrics; every other row - board labels, character names, rows no
;; producer owns - is the original font: its retail cells with the original
;; face's advances, numbers and every non-text cell at the retail 8 px
;; (btl_row_face). The pen/mode word belongs to each renderer invocation, so
;; rows cannot switch modes halfway through a draw; the original font's pen
;; is negative (bit 31), which the art selector reads as "the retail cell"
;; and the renderers drop with the rest of the high half when they store x.
;; No glyph count, OT, packet size or animation is changed.
.include "../../../../build/btl_text_centres.asm"
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

;; Party marker names draw in the original font and are centred on their
;; drawn width (btl_marker_x, btlp/orig_face.asm), where retail centred
;; 12 - n * 4 cells; the room left holds the flat renderer's art adapter.
;; btl_marker_name_tail restores the registers the retail continuation reads.
.org 0x800AA0F8
.area 0x800AA150 - 0x800AA0F8
    jal     btl_marker_x                ; v0 = the name's x
    lw      a0, 4(s7)                   ; (delay) the marker's name
    ori     t3, zero, 0xFF
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
    lhu a1, 0(s5)                       ; retail's at 0x800892C4 (btlp/text_slot_bound.asm takes that slot)

.org BTLP_SF_WIDTH_ADDR
.area BTLP_SF_CODE_ADDR - BTLP_SF_WIDTH_ADDR
    ;; Text cells keep the proportional metric; every other cell carries the
    ;; retail 8 px metric (0x08), the sentinel btl_sf_art_code leaves on the
    ;; original cell. Built by smallfont_vwf.py from btl_text_bits.bin.
    .incbin "../../../../build/btl_sf_width.bin"
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
 ; First glyph latches the row's face and pen (btl_row_face).
 sw ra,4(t9) ; second word of the bridge's existing extra stack area
 lw a0,4(t7)
 jal btl_row_face
 nop
 lw ra,4(t9)
 sw v0,0(t9)
btl_sf_read_state:
 lw a0,0(t9)
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
