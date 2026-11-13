;; =============================================================
;; The staff roll's added pages (END.EXE): the PSP-US U.S. localization
;; staff, shown after the retail roll's last page in every ending that has
;; the roll, before the "Presented By" card.
;;
;; src/injection_tools/endtext.py appends the pages to END.BIN (copies of the
;; roll's last page's slot, redrawn) and writes build/end_roll.asm: a copy of
;; g_end_sectors with the new pages' entries, and each roll script with four
;; steps per page inserted before opcode 8 0x48 (load to the text layer,
;; wait, fade in, hold, fade out - every retail roll page's rhythm). Script
;; 0 has no roll and keeps its retail copy.
;;
;; Both tables are full in place, so the data rides at the end of END.EXE's
;; file (after the subtitle blob; t_size covers it, so the PS-EXE loader puts
;; it in the VLC buffers) and the first call of main copies it to
;; END_ROLL_HOME (0x80120000): free RAM above END.EXE's buffers and its
;; libraries' work areas (the highest address its code names is 0x801146D0,
;; and main's SsInit clears that range after this copy), below the subtitle
;; renderer's lookups at 0x80128000. Every reader then points there: the image
;; loads (EndLoadImage), the song loads (opcode 0xB), main's frame-sheet
;; load, g_end_scripts[1..4] and main's flag-picked pages in scripts 1 and 3
;; (their offsets precede the insertion).
;; =============================================================
END_ROLL_STUB     equ 0x80082CE4 + 0xA0  ; LoadFileToAddr: nothing calls it
END_ROLL_STUB_END equ 0x80082E38
END_RESET_CALLBACK equ 0x80083024        ; main's first call

.org END_SUBS_BLOB_END
.align 4
.include "../../build/end_roll.asm"
.if END_ROLL_SCRIPT1_CUT <= 0x3C || END_ROLL_SCRIPT3_CUT <= 3
    .error "end roll: the inserted pages precede a flag-picked script word"
.endif
.org 0x8007F81C
    .word end_roll_data_end - 0x80080000

.org 0x80080D04
    jal   end_roll_copy                 ; delay slot keeps sw s0

.org END_ROLL_STUB
.area END_ROLL_STUB_END - END_ROLL_STUB
end_roll_copy:
    lui   t0, hi(end_roll_data)
    addiu t0, t0, lo(end_roll_data)
    lui   t1, hi(END_ROLL_HOME)
    addiu t1, t1, lo(END_ROLL_HOME)
    li    t2, END_ROLL_SIZE / 4
@@copy:
    lw    t3, 0(t0)
    addiu t0, t0, 4
    addiu t2, t2, -1
    sw    t3, 0(t1)
    bnez  t2, @@copy
    addiu t1, t1, 4
    j     END_RESET_CALLBACK
    nop
.endarea

;; --- g_end_scripts: the roll's four scripts ---
.org 0x80099FF8
    .word END_ROLL_SCRIPT1, END_ROLL_SCRIPT2, END_ROLL_SCRIPT3, END_ROLL_SCRIPT4

;; --- g_end_sectors readers ---
.org 0x80081534                         ; opcode 0xB: the song's three entries
    lui   t0, hi(END_ROLL_TABLE)
    addiu t0, t0, lo(END_ROLL_TABLE)
.org 0x8008156C
    lui   t0, hi(END_ROLL_TABLE)
    addiu t0, t0, lo(END_ROLL_TABLE)
.org 0x800815DC
    lui   t0, hi(END_ROLL_TABLE)
    addiu t0, t0, lo(END_ROLL_TABLE)
.org 0x8008214C                         ; EndLoadImage
    lui   at, hi(END_ROLL_TABLE)
    addiu at, at, lo(END_ROLL_TABLE)
.org 0x8008217C
    lui   at, hi(END_ROLL_TABLE + 2)
    addiu at, at, lo(END_ROLL_TABLE + 2)
.org 0x8008218C
    lui   at, hi(END_ROLL_TABLE)
    addiu at, at, lo(END_ROLL_TABLE)
.org 0x80080DEC                         ; main: the frame sheet's entries
    lui   s0, hi(END_ROLL_TABLE + 2 * 0x45)
    addiu s0, s0, lo(END_ROLL_TABLE + 2 * 0x45)
.org 0x80080E20
    lui   v0, hi(END_ROLL_TABLE + 2 * 0x46)
    lhu   v0, lo(END_ROLL_TABLE + 2 * 0x46)(v0)

;; --- main's flag-picked pages ---
.org 0x80080F28
    lui   at, hi(END_ROLL_SCRIPT1 + 2 * 0x36)
    sh    a0, lo(END_ROLL_SCRIPT1 + 2 * 0x36)(at)
.org 0x80080F30
    lui   at, hi(END_ROLL_SCRIPT1 + 2 * 0x3C)
    sh    a1, lo(END_ROLL_SCRIPT1 + 2 * 0x3C)(at)
.org 0x80080F80
    lui   at, hi(END_ROLL_SCRIPT3 + 2 * 3)
    sh    a0, lo(END_ROLL_SCRIPT3 + 2 * 3)(at)
