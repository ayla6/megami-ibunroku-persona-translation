;; =============================================================
;; DNG.BIN - map title shows the full PSP-US name (VWF, hugging strip)
;;
;; MapDrawName (0x80096D2C) copies 10 byte-pairs from the map pack's
;; name field into g_map_name_cells and BgMapInit hands them to the
;; message interpreter as a script - the SAME interpreter the DNG VWF
;; hooks already cover (single sltiu-0x80 classify in the overlay).
;; The 10-cell field only fits 10 characters, so 117/119 PSP names
;; never rendered ("10 cells is too small").
;;
;; Hook: the first word of MapDrawName jumps here. The glue matches the
;; pack field's 20 JA bytes against the generated table
;; (build/dng_titles.asm, from translation/generated/D0x/DxM.tsv - full
;; PSP names, VWF-encoded); on a hit it writes the full name + FF01 into
;; the cells and lays a strip hugging the text, centered at the strip
;; center.
;; On a miss it resumes the original body - Japanese rows render exactly
;; as retail (same 10-pair path, same fixed strip).
;; The strip hugs like the S2D banner plate: x = 0xAA - width/2.
;;
;; The hook sits at DNG_TITLE_HOOK_ADDR and the table lives in front of
;; it, at DNG_TITLE_TABLE_ADDR..DNG_TITLE_HOOK_ADDR (both in
;; src/asm/common/addresses.inc) - the table's budget is that room, and it
;; grows with every floor name the PSP-US wording is found for.
;; =============================================================

DNG_TITLE_CELLS         equ 0x800A0730          ; g_map_name_cells
DNG_TITLE_BGMAP_INIT    equ 0x800765c4          ; BgMapInit
DNG_TITLE_STRIP_CX      equ 0xAA                ; strip center (0x5A + 0xA0/2)

.org 0x80096D2C                             ; MapDrawName: addiu sp,sp,-0x20
    j       dng_title_hook
    nop

.org DNG_TITLE_HOOK_ADDR
dng_title_hook:
    addiu   sp, sp, -0x20               ; stolen prologue
    sw      ra, 0x18(sp)
    ;; entry pointer, same math as the original head
    lui     $v1, 0x801D
    ori     $v1, $v1, 0xD000
    sll     $v0, $a0, 0x10
    sra     $v0, $v0, 0xE                ; map * 4
    lui     $at, 0x801E
    addu    $at, $v0, $at
    lw      $v0, -0x2FF8($at)            ; entry offset in the pack
    addu    $v0, $v0, $v1                ; abs JA field (20 bytes)
    la      $t0, dng_title_idx
    li      $t1, dng_title_count
@@scan:
    beqz    $t1, @@miss
    nop
    move    $t4, $v0
    li      $t8, 20
@@cmp:
    lbu     $t2, 0($t0)
    lbu     $t3, 0($t4)
    bne     $t2, $t3, @@next
    addiu   $t0, $t0, 1
    addiu   $t4, $t4, 1
    addiu   $t8, $t8, -1
    bnez    $t8, @@cmp
    nop
    ;; full 20-byte hit ($t0 now at row+20 = width byte)
    j       @@hit
    nop
@@next:
    li      $t9, 21
    subu    $t9, $t9, $t8               ; bytes advanced this row: the
    subu    $t0, $t0, $t9               ; loop steps plus the delay slot
    addiu   $t0, $t0, 24                ; next row
    addiu   $t1, $t1, -1
    j       @@scan
    nop
@@miss:
    ;; resume the original body WITH THE FRAME STILL ALLOCATED: the
    ;; body saves s1/ra/s0 into its own frame and its epilogue pops
    ;; it. Restoring sp here would make the body overwrite the caller's stack.
    j       0x80096D30
    nop
@@hit:
    ;; the retail ritual also bzeroes the script work area before the
    ;; copy (MapDrawName head: 0x800412FC = BIOS bzero(cells, 0x22)).
    ;; Do it here too: stale bytes behind the terminator are scratch
    ;; the map-message system reuses.
    lui     $a0, 0x800A
    addiu   $a0, $a0, 0x730
    ori     $a1, $zero, 0x22
    jal     0x800412FC                  ; bzero(cells, 0x22)
    nop
    lbu     $t6, 0($t0)                 ; strip width px
    lhu     $t5, 2($t0)                 ; blob offset
    la      $t4, dng_title_blob
    addu    $t5, $t5, $t4
    lui     $t7, 0x800A
    addiu   $t7, $t7, 0x730             ; cells
@@copy:
    lbu     $t4, 0($t5)
    sb      $t4, 0($t7)
    addiu   $t5, $t5, 1
    addiu   $t7, $t7, 1
    xori    $t4, $t4, 0xFF
    bnez    $t4, @@copy
    nop
    lbu     $t4, 0($t5)                 ; the 0x01 of FF01
    sb      $t4, 0($t7)
    sw      $t6, 0x10(sp)               ; stash width across the call
    lui     $a0, 0x800A
    addiu   $a0, $a0, 0x730
    jal     DNG_TITLE_BGMAP_INIT
    move    $a1, $zero
    lw      $t6, 0x10(sp)
    li      $v0, DNG_TITLE_STRIP_CX
    srl     $v1, $t6, 1
    subu    $v0, $v0, $v1               ; x = center - width/2
    lui     $at, 0x800A
    sh      $v0, -0x3E28($at)
    li      $v0, 0x12
    lui     $at, 0x800A
    sh      $v0, -0x3E26($at)
    lui     $at, 0x800A
    sh      $t6, -0x3E24($at)           ; w = text width
    lui     $v0, 0x800A
    lw      $v0, 0xCCC($v0)
    ori     $v1, $zero, 0x10
    lui     $at, 0x800A
    sh      $v1, -0x3E22($at)
    ori     $v0, $v0, 0x10
    lui     $at, 0x800A
    sw      $v0, 0xCCC($at)
    lw      $ra, 0x18(sp)
    addiu   sp, sp, 0x20
    jr      $ra
    nop
