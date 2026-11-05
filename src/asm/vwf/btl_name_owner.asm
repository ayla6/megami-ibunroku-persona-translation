;; Semantic ownership only: no font/layout policy and no glyph heuristics.
;; a0 = row text pointer; v0 = eligible. a0, t0-t9, s*, sp survive; only
;; a1-a3/v1/HI/LO are scratch (the battle renderers keep t0-t6 live across
;; the bridge call - btl_owned_span honours the same contract). Directory entries: base, span:u16,stride:u16, IDs,
;; IDstride:u16,mask:u16,endbit:u16,bitoff:u16, bitmap, producer-valid byte
;; pointer (zero = not needed). The slot index is the byte offset from base
;; divided by the entry's own stride, and `bitoff` shifts it into the shared
;; ownership bitmap: the Persona bank owns bits 0..2 and skill slot i owns
;; bit 3+i. The static "Cost" label sits in the Persona bank's fourth slot but
;; is outside that range, so it keeps the fixed-width path. `endbit` is the
;; absolute end (bitoff + slots).
;; A row's ownership bit in a producer range answers it; a row with no owned
;; range bit - outside every range, or inside one but unowned - falls through
;; to btl_owned_span (vwf_slps.asm), which owns the translated producers'
;; standalone buffers (the ANALYZE board). Anything else stays fixed-cell.
btl_name_lookup:
    la      a1, btl_name_ranges
@@range:
    lw      a2, 0(a1)
    lhu     a3, 6(a1)
    beqz    a2, @@no
    lhu     v0, 4(a1)
    subu    v1, a0, a2
    sltu    v0, v1, v0
    beqz    v0, @@next
    nop
    beqz    a3, @@no
    nop
    divu    zero, v1, a3
    mfhi    v0
    bnez    v0, @@no
    mflo    v1
    lw      a2, 24(a1)
    nop
    beqz    a2, @@ids
    nop
    lbu     v0, 0(a2)
    nop
    beqz    v0, @@no
    nop
@@ids:
    lw      v0, 8(a1)
    lhu     a3, 12(a1)
    beqz    v0, @@flag
    nop
    multu   v1, a3
    mflo    v1
    addu    v0, v0, v1
    lhu     v1, 0(v0)
    lhu     a3, 14(a1)
    nop
    and     v1, v1, a3
@@flag:
    lhu     a3, 16(a1)                  ; absolute end bit
    lhu     v0, 18(a1)                  ; bit offset within the shared bitmap
    lw      a2, 20(a1)
    addu    v1, v1, v0
    sltu    v0, v1, a3
    beqz    v0, @@no
    srl     v0, v1, 3
    addu    a2, a2, v0
    lbu     a2, 0(a2)
    andi    a3, v1, 7
    srlv    v0, a2, a3
    jr      ra
    andi    v0, v0, 1
@@next:
    b       @@range
    addiu   a1, a1, 28
@@no:
    j       btl_owned_span              ; translated-producer buffer, else zero
    nop
btl_name_lookup_end:
