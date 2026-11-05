;; =============================================================
;; BTLP.BIN - story-battle dialogue: byte-pair-encoded strings (tools/btlevt.py)
;;
;; The English story-battle lines need more room than their zone
;; (BTLEVT_ZONE_START..END), so they are stored byte-pair encoded:
;;   FF xx        control code, copied as is (FF F5 / FF EF end the string)
;;   88..E9       a VWF character (ASCII + 0x68; … ＊ ￥ in E7..E9), copied
;;                as is
;;   00 xx        the literal byte xx: a byte outside the character range,
;;                which is where the game's own two-byte glyph form lives
;;                (80|hi,lo - '＞' is 87 26)
;;   01..87,EA..FE  a pair code: expands to the two bytes btlevt_pairs[i]
;;                (which may be pair codes again)
;; The primary window's writer at 0x8007D0B4 and BtlTextOpen's second-window
;; writer at 0x8007D654 share the decoder. Each keeps its own read pointer
;; and unpack buffer, so both windows can remain visible simultaneously.
;; Other strings are stored unchanged.
;; =============================================================

.org 0x8007D0B4
    jal     btl_unpack
    move    a0, s0

.org 0x8007D654
    jal     btl_second_unpack
    nop

.org BTLEVT_UNPACK_ADDR
.area BTLEVT_ZONE_END - BTLEVT_UNPACK_ADDR

;; The second window's flags and BtlWindowStep argument are live here.
btl_second_unpack:
    addiu sp, sp, -32
    sw ra, 28(sp)
    sw a0, 24(sp)
    sw v0, 20(sp)
    sw v1, 16(sp)
    la t2, BTL_SECOND_BUF_ADDR
    la t4, 0x800EBB0C
    jal btl_unpack_window
    move a0, s0
    lw v1, 16(sp)
    lw v0, 20(sp)
    lw a0, 24(sp)
    lw ra, 28(sp)
    addiu sp, sp, 32
    jr ra
    nop

;; a0 = string -> stores the (unpacked) read pointer, returns v0 = 1 (the caller's v0)
;; clobbers a0, v1, t0-t7, at
btlevt_buf equ BTLEVT_BUF_ADDR    ; resident (main.asm's spill bank): the zone
                                  ; has no room for a whole message's worth

btl_unpack:
    la      t2, btlevt_buf
    la      t4, 0x800EB898
btl_unpack_window:
    addiu   sp, sp, -40
    sw      t2, 36(sp)                  ; each window owns its unpacked text
    la      t0, btlevt_pairs
    sw      t0, 32(sp)                  ; pair table of this string (the negotiation strings have their own: btl_neg)
    la      t0, BTLEVT_ZONE_START
    sltu    t1, a0, t0
    bnez    t1, btl_unpack_neg                   ; below the story-battle zone: maybe a packed negotiation string
    la      t0, BTLEVT_ZONE_END
    sltu    t1, a0, t0
    beqz    t1, btl_unpack_store
    nop
btl_unpack_go:
    lhu     v0, 0(a0)                   ; a slot that holds only 'FF 00 hi lo'
    li      t1, BTLEVT_MARK             ; NAMES its text: the wording lives in
    beq     v0, t1, btl_unpack_chain    ; the resident spill bank (btlp.py),
    nop                                 ; where nothing counts its bytes
btl_unpack_decode:
    lw      t2, 36(sp)                  ; t2 = this window's destination
    addiu   t6, sp, 28                  ; t6 = empty-stack mark (byte stack grows down inside our frame)
@@next:
    lbu     v0, 0(a0)
    addiu   a0, a0, 1
    li      t1, 0xFF
    bne     v0, t1, @@symbol
    nop
    lbu     v1, 0(a0)                   ; control code FF xx
    addiu   a0, a0, 1
    sb      v0, 0(t2)
    sb      v1, 1(t2)
    addiu   t2, t2, 2
    li      t1, 0xF5
    beq     v1, t1, @@done
    li      t1, 0xEF
    beq     v1, t1, @@done
    nop
    b       @@next
    nop
@@symbol:
    move    t5, t6
    beqz    v0, @@escaped               ; 00 xx: the literal byte xx
    nop
    sb      v0, 0(t5)                   ; push the symbol
    addiu   t5, t5, -1
    b       @@expand
    nop
@@escaped:
    lbu     v0, 0(a0)                   ; the escaped byte (the game's
    addiu   a0, a0, 1                   ; two-byte glyph form lives here)
    b       @@literal
    nop
@@expand:
    beq     t5, t6, @@next              ; stack empty
    nop
    addiu   t5, t5, 1
    lbu     v0, 0(t5)                   ; pop
    nop
    beqz    v0, @@escape                ; 00: the next pop is a literal
    nop
    sltiu   t1, v0, 0x88
    bnez    t1, @@low                   ; 01..87: pair code
    sltiu   t1, v0, 0xEA
    bnez    t1, @@literal               ; 88..E9: character (the VWF font
    nop                                 ; carries …, ＊ and ￥ in E7..E9)
    b       @@pair                      ; EA..FE: pair code
    addiu   v1, v0, 0x87 - 0xEA
@@escape:
    addiu   t5, t5, 1
    lbu     v0, 0(t5)                   ; the escaped byte, verbatim
    nop                                 ; (falls into the literal store)
@@low:
    addiu   v1, v0, -1
@@pair:
    sll     v1, v1, 1
    lw      t7, 32(sp)                  ; pair table
    nop
    addu    t7, t7, v1
    lbu     t1, 1(t7)                   ; right
    lbu     v1, 0(t7)                   ; left
    sb      t1, 0(t5)                   ; push right, then left (popped first)
    addiu   t5, t5, -1
    sb      v1, 0(t5)
    b       @@expand
    addiu   t5, t5, -1
@@literal:
    sb      v0, 0(t2)
    b       @@expand
    addiu   t2, t2, 1
@@done:
    lw      a0, 36(sp)
btl_unpack_store:
    nop                                ; load delay for the unpacked pointer
    sw      a0, 0(t4)                  ; selected window's text read pointer
    addiu   sp, sp, 40
    jr      ra
    li      v0, 1
btl_unpack_chain:
    lhu     t0, 2(a0)                   ; the address, halves in reading order
    lhu     v0, 4(a0)                   ; (lhu: a slot is 2-aligned, not 4)
    sll     t0, t0, 16
    b       btl_unpack_go               ; unpack the real string from there
    or      a0, t0, v0

btl_unpack_neg:
    ;; Directly relocated story strings live in the four resident spill
    ;; fragments. They use the story dictionary, not the negotiation one.
    ;; Marker-indirected strings already reach btl_unpack_go above; this
    ;; covers pointers rewritten directly to the same owned fragments.
    la      t0, btl_story_spills
@@spill_range:
    lw      t1, 0(t0)
    lw      t2, 4(t0)
    addiu   t0, t0, 8
    beqz    t1, @@negotiation
    sltu    t3, a0, t1
    bnez    t3, @@spill_range
    sltu    t3, a0, t2
    bnez    t3, btl_unpack_go
    nop
    b       @@spill_range
    nop
@@negotiation:
    j       btl_neg                     ; negotiation's own marker and pair table
    nop
.align 4
btl_story_spills:
    .word BTLEVT_SPILL_ADDR, BTLEVT_SPILL_END
    .word BTLEVT_SPILL2_ADDR, BTLEVT_SPILL2_END
    .word BTLEVT_SPILL3_ADDR, BTLEVT_SPILL3_END
    .word BTLEVT_SPILL4_ADDR, BTLEVT_SPILL4_END
    .word 0, 0

btl_unpack_code_end:
btlevt_pairs:
.include "../../build/btlevt_pairs.asm"       ; generated by src/injection_tools/btlevt.py
btlevt_pairs_end:
.endarea
