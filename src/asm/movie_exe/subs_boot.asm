;; =============================================================
;; In-engine FMV subtitles - MOVIE.EXE hook and data blob (Rev 0)
;;
;; The blob (renderer code + glyph atlas + subtitle text, built by
;; src/injection_tools/fmv_subgen.py) is loaded straight to its home at
;; 0x80160000 by the PS-EXE loader, which copies t_size bytes of the file
;; to t_addr - so the header's t_size covers the gap and the file is
;; padded with zeros in between. Keep renderer code and data outside the
;; decoder buffers, which are overwritten during playback.
;; 0x80160000..0x80180000 is the one window the movie player, the buffers
;; and the resident's staging areas never touch (see
;; docs/research/fmv-subs-in-engine.md).
;; =============================================================

;; --- capture the true stream frame -----------------------------
;; Same as subs_boot_open.asm: g_movie_frame counts only the frames the
;; decoder receives (CdlModeRT drops the rest), while the sector header
;; carries the real index. 0x800813B0 loads it into v1 and the next two
;; instructions clobber it, so both are replaced and re-issued by the
;; renderer's trampoline (which saves v1 first).
.org 0x800813B4
    j     0x80161FE0
    nop

;; --- the frame loop's PadRead(1) runs the renderer --------------
;; (the renderer tail-jumps to PadRead itself; the delay slot at
;; 0x80080FC0 still sets a0 = 1 and stays untouched)
.org 0x80080FBC
    jal   0x80160000

;; Opportunistically composite a finished frame during an empty CD poll.
;; The wrapper always calls the original StGetNext first.
.org 0x80081374
    jal   0x80160010

;; --- the blob at its home, and the t_size that makes the loader read it
.org 0x80160000
SUBS_BLOB_START:
    .incbin "../../build/movie_subs.bin"
SUBS_BLOB_END:
.org 0x8007F81C
    .word 0xE0000 + (SUBS_BLOB_END - SUBS_BLOB_START)
