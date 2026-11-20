;; CONTACT offer personality quads only. The private text pointer gates the
;; existing GTE quad path; texture coordinates, palette, OT and frame stay retail.
;; The 32-byte routine below is a retail duplicate of the preceding routine,
;; with no statically reachable entry in active BTLP/SLPS (deadovl audit).
.org 0x800b9f58
.area 32
offer_position:
    li      t4, 0
    j       offer_gate
    sll     v0, s4, 3                 ; retail coordinate for other rows
offer_advance:
    li      t4, 1
    li      t6, 0xff                  ; saved terminator for loop branch
    j       offer_gate
    addiu   s4, s4, 1                 ; retail increment for other rows
.endarea

;; Preserve the displaced stack write. BtlDrawGlyphs saved ra on entry.
.org 0x80078574
    jal     offer_position
    sw      zero, 0x28(sp)

;; Preserve the linked-list writes and give the following load one instruction
;; of delay before its branch. Both end-of-string and loop targets stay retail.
.org 0x800788b8
    jal     offer_advance
    sw      v0, -0x7c58(at)
    and     v1, v1, a3
    or      v1, v1, a0
    lbu     v0, 0(s1)
    sw      v1, 0(a1)
    bne     v0, t6, 0x80078564
    nop

;; The eight retail glyph loads each turned the byte at 0(s1) straight into a
;; texture U/V; route them through the proportional selector, which reads the
;; row's art mode from `at` (set by the position phase of the gate). The load
;; moves into the call's delay slot, so each site keeps its exact retail
;; footprint: a0 sites call the selector directly, v0 sites need the answer in
;; v0 and use the wrapper in vwf/vwf_offer_art.asm.
.org 0x80078608
    jal     btl_sf_art_code
    lbu     a0, 0(s1)
.org 0x8007863c
    jal     offer_art_v
    lbu     v0, 0(s1)
.org 0x80078670
    jal     btl_sf_art_code
    lbu     a0, 0(s1)
.org 0x800786a8
    jal     offer_art_v
    lbu     v0, 0(s1)
.org 0x800786dc
    jal     btl_sf_art_code
    lbu     a0, 0(s1)
.org 0x80078710
    jal     offer_art_v
    lbu     v0, 0(s1)
.org 0x80078748
    jal     btl_sf_art_code
    lbu     a0, 0(s1)
.org 0x80078780
    jal     offer_art_v
    lbu     v0, 0(s1)
