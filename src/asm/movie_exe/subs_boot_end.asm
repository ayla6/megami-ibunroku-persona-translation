;; =============================================================
;; In-engine FMV subtitles - END.EXE hooks and data blob (Rev 0)
;;
;; The endings play their movies (the hospital and graduation poems,
;; MV1B's speech, ...) with END.EXE's own copy of the streaming player,
;; EndPlayMovie, not MOVIE.EXE. The same renderer runs here as a third
;; driver (subs_code.asm entry_end / poll_end / trueframe_end).
;;
;; END.EXE's buffers and library work areas end near 0x80114700 (below the
;; renderer's lookups at 0x80128000), but its image, VAB and SEQ
;; staging (0x80140000, 0x80180000, 0x801C0000, 0x801D0000) overlap the
;; renderer's home and are refilled for every page and song. So the blob
;; (renderer code + the entries of the movies END.EXE's scripts play,
;; build/movie_subs_end.bin) rides after the executable's image in
;; END.EXE's file and is read to 0x80160000 when a movie starts: EndPlayMovie's CdSearchFile
;; for the movie goes through end_subs_load first. Sound is stopped by
;; then and every staging area is reloaded after the movie (the scripts
;; reopen their song with opcode 0xB), so nothing live is overwritten.
;; The read waits on g_cd_busy like every END.EXE load and retries until
;; it succeeds, so the hooks below only ever run a loaded renderer.
;;
;; The loader sits in LoadFileToAddrAsync (0x80082CE4..+0xA0), which nothing
;; in END.EXE calls (end_exe/roll.asm uses the rest of that dead pair).
;; =============================================================
END_CD_SEARCH_FILE  equ 0x8008A598
END_CD_INT_TO_POS   equ 0x80088AC0
END_CD_POS_TO_INT   equ 0x80088BC4
END_CD_READ_TO_ADDR equ 0x80082EF8      ; CdReadFileToAddr(pos, sectors, dest)
END_SUBS_CAVE       equ 0x80082CE4
END_SUBS_CAVE_END   equ 0x80082CE4 + 0xA0   ; end_exe/roll.asm's copy stub follows
END_SUBS_FILE_AT    equ 0x2E000         ; file offset: right after the retail image
END_SUBS_HOME       equ 0x80160000

;; --- the true stream frame (as subs_boot.asm: 0x80082B08 loads it into
;; v1 and the next two instructions clobber it) -------------------------
.org 0x80082B0C
    j     0x80161FA0                    ; trueframe_end
    nop

;; --- the frame loop's PadRead(1) runs the renderer (delay slot keeps a0 = 1)
.org 0x8008285C
    jal   0x80160020                    ; frame_entry_end

;; --- an idle CD poll may composite a finished frame early
.org 0x80082ACC
    jal   0x80160028                    ; poll_entry_end

;; --- the movie's file lookup first brings the renderer in
.org 0x80082790
    jal   end_subs_load                 ; delay slot keeps a1 = the name

.org END_SUBS_CAVE
.area END_SUBS_CAVE_END - END_SUBS_CAVE
;; a0 = &file, a1 = the movie's name: CdSearchFile's own arguments, passed on.
end_subs_load:
    addiu sp, sp, -0x40
    sw    ra, 0x3C(sp)
    sw    a0, 0x38(sp)
    sw    a1, 0x34(sp)
@@find:
    addiu a0, sp, 0x10                  ; CdlFILE, 24 bytes
    lui   a1, hi(end_subs_exe)
    jal   END_CD_SEARCH_FILE
    addiu a1, a1, lo(end_subs_exe)
    beqz  v0, @@find
    nop
    jal   END_CD_POS_TO_INT
    addiu a0, sp, 0x10                  ; file.pos
    addiu a0, v0, END_SUBS_FILE_AT / 0x800
    jal   END_CD_INT_TO_POS
    addiu a1, sp, 0x28
    addiu a0, sp, 0x28
    li    a1, (END_SUBS_BLOB_END - END_SUBS_BLOB_START + 0x7FF) / 0x800
    jal   END_CD_READ_TO_ADDR
    lui   a2, hi(END_SUBS_HOME)
    lw    a0, 0x38(sp)
    lw    a1, 0x34(sp)
    lw    ra, 0x3C(sp)
    j     END_CD_SEARCH_FILE
    addiu sp, sp, 0x40
end_subs_exe:
    .asciiz "\\EXE\\END.EXE;1"
.endarea

;; --- the blob, after the image. t_size (set by end_exe/roll.asm, whose
;; data follows) covers the whole file, so the PS-EXE loader also copies the
;; blob to 0x800AD800.. at start: that is inside the VLC buffers
;; (0x800AD340..0x800FD340), which only EndPlayMovie uses and fills before it
;; reads them. The renderer runs from the copy read to 0x80160000, never from
;; this one.
.org END_EXE_ADDR + END_SUBS_FILE_AT
END_SUBS_BLOB_START:
    .incbin "../../build/movie_subs_end.bin"
END_SUBS_BLOB_END:
