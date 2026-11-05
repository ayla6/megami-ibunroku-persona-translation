;; =============================================================
;; In-engine FMV subtitles - OPEN.EXE hook and data blob
;;
;; The opening movie (\STR1\MV1C.STR - the Zhuangzi quote cards) is
;; played by OPEN.EXE with its own player loop, not by MOVIE.EXE
;; (references/persona-decomp src/open/movie.c), so the renderer is
;; hooked in here too. As in subs_boot.asm the blob is loaded straight to
;; its home at 0x80160000 (the PS-EXE loader copies t_size bytes to
;; t_addr, so t_size covers the padded gap). Renderer code and data must
;; stay outside the video buffers, which are overwritten during playback.
;; =============================================================

;; --- capture the true stream frame -----------------------------
;; The loop counter (g_open_frame) only counts the frames that reach
;; the decoder: the stream runs in CdlModeRT and drops frames whenever
;; the game falls behind, so the counter lags the picture and subtitles
;; would drift. The player reads the sector header's frame_count at
;; 0x8008940C and throws it away; the free nop after it becomes a jump
;; to the renderer's trampoline, which keeps it (v1 survives: the delay
;; slot only writes v0).
.org 0x80089410
    j     0x80161FC0

;; --- the frame loop's VSync(0) runs the renderer ----------------
;; (after StrSync put the frame in VRAM, before GsSwapDispBuff shows
;; it; the renderer tail-jumps to VSync itself)
.org 0x80088F90
    jal   0x80160008

.org 0x800893BC
    jal   0x80160018

;; --- the blob at its home, and the t_size that makes the loader read it
;; OPEN.EXE has no plate textures: the quote's cards are drawn from the
;; pre-scaled band patches, and the title pack (OPEN.BIN) is loaded at
;; 0x80180000 right before this EXE starts. The blob must therefore end
;; below 0x80180000. Two extra measured zoom levels occupy the space freed
;; by compacting the renderer's ink lookup cache, outside all decoder buffers.
.org 0x80130000
    .incbin "../../build/movie_subs_open_zoom.bin"

.org 0x80160000
SUBS_OBLOB_START:
    .incbin "../../build/movie_subs_open.bin"
SUBS_OBLOB_END:
.org 0x8007F81C
.ifdef QOL_SAVES
    .word qol_o_end - 0x80080000
.else
    .word 0xE0000 + (SUBS_OBLOB_END - SUBS_OBLOB_START)
.endif
