;; =============================================================
;; In-engine FMV subtitles - renderer (Rev 0 MOVIE.EXE)
;;
;; Assembled at 0x80160000 by a separate armips pass (build.py), packed
;; behind the data blob and copied to 0x80160000 at startup (no copy
;; stub: the PS-EXE t_size trick lands it there). Called from
;; MoviePlay's frame loop instead of PadRead(1) - tail-jumps to
;; PadRead afterwards, so the loop is unchanged.
;;
;; Per active entry:
;;   - one band (the rows/cols that get painted) is StoreImage'd into
;;     scratch, blended by the CPU, LoadImage'd back - GPU primitives
;;     cannot produce correct 24bpp colors.
;;   - entries over the live frame (speech subtitles) just blend their
;;     text in; entries over burned-in text first paint a PATCH: the
;;     picture's own pixels where the original text sits (measured
;;     offline from the movie's clean frame, so the baked-in text is
;;     painted over with its own background), scaled by the measured
;;     fade. The English text then draws over it as one thing:
;;       intro (additive ink): out = bg + ink*eff
;;       poems/speech (paste): out = bg + (ink-bg)*eff
;;     The quote's text fades with the picture scale, exactly as the
;;     original's black-card layer did.
;;   - StoreImage/LoadImage are asynchronous GPU DMA: every StoreImage
;;     is followed by DrawSync before the band is read on the CPU.
;; =============================================================

.psx
.include "common/addresses.inc"
.create MOVIE_SUBS_CODE_OUTPUT, MOVIE_SUBS_CODE_ADDR

;; ---- shared with fmv_subgen.py ----
DATA_BASE   equ 0x80162000
SCRATCH     equ 0x80140640          ; band: band_rows*band_w*3 bytes
INK_TAB     equ 0x80128000          ; eight 1024-expression lookups, 4 KB each
INK_META    equ 0x8013FF00          ; 8 x {program, alpha, mode, spans}

;; ---- blend scratch, above the band's origin. The pixel loops never
;;      multiply: everything they need is a byte lookup here. ----
T_TAB       equ 0x80140000          ; reserved together with the patch LUT
ROW_TAB     equ 0x80140100          ; per line: glyph cell row -> band row
                                    ; base (24 x 4 bytes)
SPAL        equ 0x80140200          ; patch palette scaled for this frame,
                                    ; 256 x 4 bytes (R,G,B,-)
LUT32       equ 0x80140000          ; patch: 8-bit channel -> scaled (256 B).
                                    ; Text selects its ramp from H_TAB.

;; ---- data header fields (at DATA_BASE) ----
H_MAGIC     equ 0x80162000
H_ADV       equ 0x8016200C          ; -> advance table (1 byte per glyph)
H_SPANS     equ 0x80162010          ; -> glyph span data
H_PTRS      equ 0x80162014          ; -> span pointer per glyph
H_LISTS     equ 0x80162018          ; per-movie entry list pointers
H_CLAMP     equ 0x801620B4          ; -> 512 B: v -> min(v,255) (after the
                                    ; 39 per-movie list pointers at 0x80162018)
H_TAB       equ 0x801620B8          ; -> 64K paste table: T[eff*256+v] =
                                    ; v*eff>>8 (row shared by ink and bg)
GLYPH_FIRST equ 0x20                ; atlas glyphs 0x20..0x7E

;; ---- Rev 0 MOVIE.EXE addresses ----
G_MOVIE_NO    equ 0x800A92A0        ; gp+4
G_MOVIE_FRAME equ 0x800A92B4        ; gp+0x18
DEC_RECT_ID   equ 0x800FF8E4        ; g_dec + 0x20
PAD_READ      equ 0x8008A910
;; ---- Rev 0 OPEN.EXE addresses (plays the opening movie MV1C) ----
G_OPEN_FRAME  equ 0x800B3574
OPEN_RECT_ID  equ 0x801146E0        ; its g_dec + 0x20
VSYNC         equ 0x80093708
OPEN_STORE    equ 0x8008AAC0
OPEN_LOAD     equ 0x8008AA5C
OPEN_DSYNC    equ 0x8008A834
;; ---- libgpu (both binaries link their own copies) ----
STORE_IMAGE   equ 0x80082784        ; MOVIE.EXE's; OPEN.EXE's is OPEN_STORE
LOAD_IMAGE    equ 0x80082720
DRAW_SYNC     equ 0x800824F8
MAGIC         equ 0x34534D46        ; 'FMS4'

;; entry record (32 bytes + 8 per line), written by fmv_subgen.py:
;;   +0  u16 start_frame (0-based stream frame, inclusive; 0xFFFF = end)
;;   +2  u16 end_frame (inclusive)
;;   +4  u8  nlines
;;   +5  u8  flags: 1 = patch composite, 2 = additive ink, 8 = the patch
;;        repaints the whole band (no store pass needed)
;;   +6  u8  band_y0 / +7 u8 band_rows
;;   +8  u32 patch_ptr (0 = live frame, no patch)
;;   +12 u32 scale_ptr (u16 per frame, 8.8 fixed, 256 = straight copy; 0 = 256)
;;   +16 u32 alpha_ptr (u8 per frame per line, line tables back to back;
;;        0 = fade_shift ramp)
;;   +20 u8  fade_shift (ramp of 2**shift frames when alpha_ptr is 0)
;;   +22 u16 band_x0 / +24 u16 band_w (columns; both multiples of 4)
;;   +32 nlines x { u32 text_addr, u8 x, u8 y_top, u8 alpha_idx, u8 0 }
;; patch blob: 256 x RGB (8 bits per channel), then rows of
;;   u8 y, u8 nruns, nruns x (u16 x0, u16 len, len x u8 palette index),
;;   with indices word-aligned and padded to a whole word per run.
;;   0xFF ends the blob; zoom-level terminators are also padded to a word.

;; per-driver context, written by the entry stubs. The GPU helpers live at
;; different addresses in each binary (each links its own libgpu), so the
;; shared renderer calls them through here.
S_FRAME     equ 0x80161F00          ; 0-based video frame index
S_NO        equ 0x80161F04          ; movie number to look up
S_BUFY      equ 0x80161F08          ; vram y of the frame just completed
S_TAILFN    equ 0x80161F0C          ; where to hand control back to
S_TAILARG   equ 0x80161F10          ; its a0
S_STORE     equ 0x80161F18          ; this binary's StoreImage
S_LOAD      equ 0x80161F1C          ; ...LoadImage
S_DSYNC     equ 0x80161F20          ; ...DrawSync
S_SCALE     equ 0x80161F24          ; the fade measured from the live frame
S_STRIDE    equ 0x80161F28          ; band row pitch in bytes (band_w*3)
S_XOFF      equ 0x80161F2C          ; row base offset: -band_x0*3
S_BANDY0    equ 0x80161F30
S_BANDROWS  equ 0x80161F34
S_BANDX0    equ 0x80161F38
S_BANDW     equ 0x80161F3C
;; the true stream frame index, captured from the sector header (see the
;; trampolines at the end): the CD stream drops frames whenever the game
;; falls behind (CdlModeRT), so g_movie_frame counts only the survivors
;; and lags the picture. S_TRUE is the frame whose VLC is being decoded
;; (the next one after a successful poll); the poll wrapper latches S_DISP
;; before that next header can replace the current frame index. The decoder still runs a few frames ahead of
;; what the screen shows, so the picture's fade is measured from the live
;; frame (see frame_entry's strip probe) instead of trusting this index.
S_TRUE      equ 0x80161F40
S_DISP      equ 0x80161F44
S_PLATE     equ 0x80161F48          ; vram already holds this frame's plate
;; the composite cache. What lands in the band is a pure function of the
;; entry, the picture's scale and the per-line text alpha: the plate is a
;; static texture and the text is redrawn at the same levels. So the
;; composited band is uploaded once and kept in vram at (CACHE_X, CACHE_Y);
;; every later frame with the same state is a single vram->vram copy, and
;; the cpu does nothing at all. Only the short fade ramps still pay for a
;; store, a blend and a texture upload.
S_CACHEABLE equ 0x80161F4C          ; this frame's band is cacheable
S_CACHED    equ 0x80161F50          ; ... and the cache already holds it
S_CACHE_E   equ 0x80161F54          ; entry the cache was built for
S_CACHE_S   equ 0x80161F58          ; its picture scale
S_CACHE_N   equ 0x80161F5C          ; its line count
S_CACHE_L   equ 0x80161F60          ; its zoom level (0 = no zoom)
S_CACHE_P   equ 0x80161F64          ; its pan in pixels (0 = zoomed patch)
S_CACHE_A   equ 0x80161F68          ; its 8 alpha levels
S_CUR_L     equ 0x80161F70          ; this frame's zoom level
S_CUR_P     equ 0x80161F74          ; this frame's pan in pixels
S_CUR_A     equ 0x80161F78          ; this frame's 8 alpha levels
S_CUR_E     equ 0x80161F80          ; entry the held values below belong to
S_HOLD      equ 0x80161F84          ; 1 = this entry held values last frame
S_SCALE_H   equ 0x80161F88          ; the held scale (S_SCALE is zeroed per frame)
S_HEADROOM  equ 0x80161F8C          ; 255 - maximum scaled patch channel
S_EARLY     equ 0x80161F90          ; render-only call from an idle CD poll
S_RENDERED  equ 0x80161F94          ; current decoded frame already composited

;; ---- the GPU: the plate is a texture, the fade is texture modulation ----
;; A textured gouraud quad with all four vertices the same colour computes
;; TEX x colour / 128 - an exact per-frame fade, done by the GPU while the
;; CPU does nothing. The whole band rectangle is painted, so the burned
;; text's compression halo goes with it.
PLATE_X     equ 480                 ; the plate on its own (patch_pass's
PLATE_Y     equ 0                   ; output, before the text): a frame that
                                    ; only moves the text alphas stores it
                                    ; back instead of repainting it
GP0         equ 0x1F801810
GP0STAT     equ 0x1F801814          ; port+1: polled for FIFO room
TEX_X       equ 512                 ; texture page x (a multiple of 64)
TEX_Y       equ 0
CACHE_X     equ 512                 ; the composited band (plain rectangle)
CACHE_Y     equ 256
CLUT_X      equ 768                 ; its 256-entry palette
CLUT_Y      equ 0
TEX_TPAGE   equ ((TEX_X / 64) | ((TEX_Y / 256) << 4) | (1 << 7))
TEX_CLUT    equ ((CLUT_X / 16) | (CLUT_Y << 6))

;; ---------------------------------------------------------------
;; frame_entry (0x80160000): MOVIE.EXE - hook replaces PadRead(1)
;; frame_entry_open (0x80160008): OPEN.EXE - hook replaces VSync(0)
;; Both hooks land on a fixed two-instruction jump stub (these can
;; never outgrow their slots - armips .org would silently rewind and
;; overwrite an overflow). The real entries follow.
;; ---------------------------------------------------------------
.org 0x80160000
frame_entry:
    j     entry_movie
    nop

.org 0x80160008
frame_entry_open:
    j     entry_open
    nop

.org 0x80160010
poll_entry_movie:
    j     poll_movie
    nop

.org 0x80160018
poll_entry_open:
    j     poll_open
    nop

entry_movie:
    lw    t0, S_DISP                ; the frame on screen (true stream index)
    nop
    sw    t0, S_FRAME
    lbu   t0, G_MOVIE_NO
    sw    t0, S_NO
    lw    t0, DEC_RECT_ID
    li    t1, 0                     ; rect[1-rect_id]: y = rect_id ? 0 : 240
    bnez  t0, movie_y
    nop
    li    t1, 240
movie_y:
    sw    t1, S_BUFY
    li    t0, PAD_READ
    sw    t0, S_TAILFN
    li    t0, 1
    sw    t0, S_TAILARG
    li    t0, STORE_IMAGE
    sw    t0, S_STORE
    li    t0, LOAD_IMAGE
    sw    t0, S_LOAD
    li    t0, DRAW_SYNC
    sw    t0, S_DSYNC
    j     driver_common
    nop

entry_open:
    lw    t0, S_DISP                ; the frame on screen (true stream index)
    nop
    sw    t0, S_FRAME
    li    t0, 0x1C                  ; the opening movie is the only one here
    sw    t0, S_NO
    lw    t0, OPEN_RECT_ID
    li    t1, 0
    bnez  t0, open_y
    nop
    li    t1, 240
open_y:
    sw    t1, S_BUFY
    li    t0, VSYNC
    sw    t0, S_TAILFN
    sw    zero, S_TAILARG
    li    t0, OPEN_STORE
    sw    t0, S_STORE
    li    t0, OPEN_LOAD
    sw    t0, S_LOAD
    li    t0, OPEN_DSYNC
    sw    t0, S_DSYNC
    j     driver_common
    nop

driver_common:
    lw    t0, S_EARLY
    nop
    beqz  t0, common
    nop
    li    t0, early_return
    sw    t0, S_TAILFN
    sw    zero, S_TAILARG

common:
    addiu sp, sp, -0x20
    sw    s6, 0x18(sp)
    sw    ra, 0x14(sp)
    sw    s0, 0x10(sp)
    sw    s1, 0x0C(sp)
    sw    s2, 0x08(sp)
    sw    s3, 0x04(sp)
    sw    s4, 0x00(sp)

    ;; An idle CD poll may have drawn this completed frame already. The
    ;; regular hook must still publish the next frame and call PadRead/VSync,
    ;; but must not blend or upload the subtitles twice.
    lw    t0, S_RENDERED
    lw    t1, S_EARLY
    beqz  t0, common_draw
    nop
    bnez  t1, common_draw
    nop
    sw    zero, S_RENDERED
    b     out
    nop
common_draw:

    ;; data copied yet? (foreign builds / stale RAM skip silently)
    lw    t1, H_MAGIC
    li    t0, MAGIC
    bne   t0, t1, out
    nop

    lw    s2, S_FRAME
    nop
    bltz  s2, out
    nop

    ;; entry list of this movie
    lw    t0, S_NO
    nop
    sll   t0, t0, 2
    li    t1, H_LISTS
    addu  t1, t1, t0
    lw    s0, 0(t1)
    nop
    beqz  s0, out
    nop

find:
    lhu   t0, 0(s0)
    nop
    li    t1, 0xFFFF
    beq   t0, t1, out
    nop
    sltu  t1, s2, t0            ; frame < start: sorted, nothing active yet
    bnez  t1, out
    nop
    lhu   t1, 2(s0)             ; end is inclusive
    nop
    sltu  t2, t1, s2            ; end < frame: this entry is over
    beqz  t2, active
    nop
    lbu   t3, 4(s0)             ; skip 32 + 8*nlines
    nop
    sll   t3, t3, 3
    addiu t3, t3, 32
    addu  s0, s0, t3
    b     find
    nop

active:
    sw    zero, S_SCALE         ; only the strip probe below may set this
    ;; A new entry starts with nothing held; inside one entry the fade
    ;; values below may stay at their previous frame's value.
    lw    t0, S_CUR_E
    nop
    beq   t0, s0, ar_hold
    nop
    sw    s0, S_CUR_E
    sw    zero, S_HOLD
    jal   ink_reset
    nop
    b     ar_held
    nop
ar_hold:
    li    t0, 1
    sw    t0, S_HOLD
ar_held:
    ;; ---- the band's geometry: rows band_y0..+band_rows, cols band_x0..+w
    lbu   t0, 6(s0)
    lbu   t1, 7(s0)
    lhu   t2, 22(s0)
    lhu   t3, 26(s0)
    sw    t0, S_BANDY0
    sw    t1, S_BANDROWS
    sw    t2, S_BANDX0
    sw    t3, S_BANDW
    sll   t4, t3, 1
    addu  t4, t4, t3            ; stride = band_w*3
    sw    t4, S_STRIDE
    sll   t4, t2, 1
    addu  t4, t4, t2
    subu  t4, zero, t4
    sw    t4, S_XOFF            ; row base = SCRATCH + row*stride - band_x0*3

    ;; ---- this frame's patch geometry: zoom level and pan ----
    ;; both land in the band, so both are part of what the cache key below
    ;; has to carry. A zoomed patch holds one pre-scaled copy of the band
    ;; per level and this frame takes one; a flat one drifts under the
    ;; burned text by the measured pan. Computed once here; patch_pass
    ;; reads the two words instead of walking the tables again.
    lbu   t0, 5(s0)             ; flags
    nop
    andi  t1, t0, 0x10          ; F_ZOOM
    beqz  t1, ag_pan
    nop
    lw    t1, 28(s0)            ; level table, one u8 per frame
    lhu   t2, 0(s0)             ; f0
    nop
    subu  t2, s2, t2
    addu  t1, t1, t2
    lbu   t1, 0(t1)             ; this frame's level
    nop
az_take:
    sw    t1, S_CUR_L
    sw    zero, S_CUR_P         ; the drift is baked into the levels
    b     ag_lines
    nop
ag_pan:
    sw    zero, S_CUR_L
    ;; pan = (pan0*32 + slope*clamp(frame-f0, lo, hi) + 128) >> 8 (pixels);
    ;; it is only measured where the picture is visible, so it is held at
    ;; the window's ends instead of running off into the black
    lbu   t0, 21(s0)            ; pan at f0, 1/8 px (s8)
    nop
    sll   t0, t0, 24
    sra   t0, t0, 24
    sll   t0, t0, 5             ; -> 1/256 px
    lbu   t1, 31(s0)            ; slope, 1/256 px per frame (s8)
    nop
    sll   t1, t1, 24
    sra   t1, t1, 24
    lhu   t2, 0(s0)             ; f0
    nop
    subu  t2, s2, t2            ; frames since f0
    lbu   t3, 24(s0)            ; lo
    lbu   t4, 25(s0)            ; hi
    nop
    sltu  t5, t2, t3
    beqz  t5, ag_panlo
    nop
    move  t2, t3
ag_panlo:
    sltu  t5, t4, t2
    beqz  t5, ag_panhi
    nop
    move  t2, t4
ag_panhi:
    mult  t1, t2
    nop
    mflo  t1
    addu  t0, t0, t1
    addiu t0, t0, 128           ; nearest pixel
    sra   t0, t0, 8             ; pan in pixels
    sw    t0, S_CUR_P
ag_lines:
    ;; every entry's lines get their (held) alpha here: the cache key and
    ;; draw_line read the same bytes
    jal   sig_fill
    nop
ag_done:

    ;; ---- the picture's scale for this frame ----
    ;; scale 0 means the picture is black there (a black quote card) - the
    ;; quad then simply paints black, and needs no texture at all.
    lw    t0, 12(s0)            ; scale_ptr (0 = live frame, nothing to paint)
    nop
    sw    zero, S_CACHED        ; patched below when the cache is valid
    sw    zero, S_CACHEABLE
    beqz  t0, band_store
    li    s3, 256
    lhu   t1, 0(s0)             ; f0
    nop
    subu  t1, s2, t1            ; frame - f0
    sll   t1, t1, 1
    addu  t0, t0, t1
    lhu   s3, 0(t0)             ; the picture's scale (8.8 fixed)
    nop

    ;; ---- the fade measured from the live frame ----
    ;; A strip of rows just outside the band is text-free and carries the
    ;; same fade as the band, so scale = live_mean / plate_mean, exactly
    ;; what the screen shows. The CD makes the decoder run a few frames
    ;; ahead of the picture, and a plate scaled by the stream index's fade
    ;; then stands out as a rectangle around the text.
    lw    t1, 8(s0)             ; patch (0 = no picture)
    nop
    beqz  t1, ls_done
    nop
    lbu   t2, 768(t1)           ; strip y (0xFF = none)
    nop
    li    t3, 0xFF
    beq   t2, t3, ls_done
    nop
    lbu   t3, 769(t1)           ; strip rows
    nop
    beqz  t3, ls_done
    nop
    ;; StoreImage(band_x0*3/2, bufy+strip_y, band_w*3/2, rows) -> SCRATCH
    addiu sp, sp, -0x10
    lw    t4, S_BANDX0
    lw    t5, S_BANDW
    sll   t6, t4, 1
    addu  t6, t6, t4
    srl   t6, t6, 1
    sh    t6, 0(sp)
    lw    t6, S_BUFY
    nop
    addu  t6, t6, t2
    sh    t6, 2(sp)
    sll   t6, t5, 1
    addu  t6, t6, t5
    srl   t6, t6, 1
    sh    t6, 4(sp)
    sh    t3, 6(sp)
    move  a0, sp
    li    a1, SCRATCH
    lw    t0, S_STORE
    nop
    jalr  t0
    nop
    addiu sp, sp, 0x10
    move  a0, zero
    lw    t0, S_DSYNC
    nop
    jalr  t0
    nop
    ;; the strip's mean, then the scaled ratio to the plate's own mean
    lw    t2, 8(s0)
    nop
    lbu   t3, 769(t2)
    lw    t4, S_BANDW
    nop
    sll   t5, t4, 1
    addu  t4, t5, t4            ; band_w*3
    mult  t4, t3
    mflo  t4                    ; bytes in the strip
    move  s4, t4
    li    t0, SCRATCH
    jal   sum_bytes
    nop
    sll   t5, t5, 4             ; sum * 16 / bytes = mean*16
    divu  t5, s4
    nop
    mflo  t5
    lw    t2, 8(s0)
    nop
    lhu   t3, 770(t2)           ; plate mean*16
    nop
    beqz  t3, ls_done
    nop
    sll   t5, t5, 8             ; live_mean*16 * 256 / plate_mean*16
    divu  t5, t3
    nop
    mflo  s3
    ;; the plate is baked at the entry's plateau level, so divide it back out
    lw    t2, 8(s0)
    nop
    lhu   t3, 772(t2)           ; plateau level * 256
    nop
    beqz  t3, ls_store
    nop
    sll   s3, s3, 8
    divu  s3, t3
    nop
    mflo  s3
    ;; no cap at 256: the plate can be baked below the entry's brightest
    ;; frame (the poems hold at half and bloom to full at the end), and the
    ;; LUT saturates, so a scale past 1.0 is the brightening the live frame
    ;; itself has
ls_store:
    ;; Hold the scale at its previous frame's value only while it is not
    ;; moving: 0..2/256 is the probe's own noise on a still picture. A fade
    ;; step is bigger than that (the quote's moon ramp moves ~8/256 per
    ;; frame), and holding through it leaves the plate visibly darker than
    ;; the live frame - up to two frames behind, ~11% on the opening quote.
    ;; The composite is rebuilt on every fade frame as a result; the cache
    ;; still hits on the plateau, where the probe is steady.
    lw    t0, S_HOLD
    nop
    beqz  t0, ls_take
    nop
    lw    t3, S_SCALE_H         ; the held value (S_SCALE is zeroed each
    nop                         ; frame before the probe may set it)
    subu  t5, s3, t3
    sra   t6, t5, 31
    xor   t5, t5, t6
    subu  t5, t5, t6            ; |new - held|
    sltiu t5, t5, 3
    beqz  t5, ls_take
    nop
    move  s3, t3                ; hold
ls_take:
    sw    s3, S_SCALE
    sw    s3, S_SCALE_H
ls_done:
    ;; park the scale the plate is painted at: the flow below reuses s3
    ;; (the text loop counts lines in it), and the cache key has to carry
    ;; the exact value well after that
    sw    s3, S_SCALE
    ;; A black card paints nothing from the patch, so neither the zoom
    ;; level nor the pan can reach the band: keeping them out of the key
    ;; lets a zooming black card (the opening quote's first 120 frames)
    ;; hit the cache instead of rebuilding every frame as the level table
    ;; walks along.
    beqz  s3, ak_zero
    nop
    b     ak_keep
    nop
ak_zero:
    sw    zero, S_CUR_L
    sw    zero, S_CUR_P
ak_keep:

    ;; ---- is this frame's band identical to the cached composite? ----
    ;; What lands in the band is a pure function of this frame's state -
    ;; the entry, the picture's scale, the zoom level and pan, and every
    ;; line's alpha - so the composited band is kept in vram at
    ;; (CACHE_X, CACHE_Y) and every later frame in the same state is one
    ;; vram->vram copy, with the cpu doing nothing at all. Only entries
    ;; whose whole band is ours qualify: a live frame's own pixels change
    ;; under us and are never cached. (The measured scale is not forced to
    ;; 256 here - the plate is painted at whatever the frame shows, and the
    ;; key carries it. It holds still through the plateau frames, which is
    ;; what makes the cache hit at all.)
    lbu   t0, 4(s0)             ; nlines
    nop
    sltiu t1, t0, 9
    beqz  t1, cache_checked
    nop
    lbu   t0, 5(s0)             ; flags
    nop
    andi  t0, t0, 8             ; F_FULL: the patch repaints the whole band
    bnez  t0, cache_state
    nop
    beqz  s3, cache_state       ; scale 0: the quad painted the frame black
    nop
    b     cache_checked         ; a live frame: never cacheable
    nop
cache_state:
    li    t0, 1
    sw    t0, S_CACHEABLE
    jal   sig_match
    nop
    sw    v0, S_CACHED
    bnez  v0, cache_checked
    nop
    ;; Miss: this frame composites the band and `done` publishes the new
    ;; cache key. The plate itself only changes with the entry, the scale,
    ;; the zoom level or the pan - so when only the text alphas moved the
    ;; plate is still sitting in vram and comes back with one store
    ;; instead of being repainted from the palette (the fades are those
    ;; frames). A plate change invalidates it.
    jal   sig_plate
    nop
    lw    t0, S_PLATE
    nop
    and   t0, t0, v0
    sw    t0, S_PLATE

cache_checked:
    ;; ---- the plate as a GPU quad: plate x fade, whole rectangle ----
    jal   patch_quad
    nop
    move  a0, zero                  ; wait for the GPU before reading the band
    lw    t0, S_DSYNC
    nop
    jalr  t0
    nop

    ;; the composite already in vram *is* this frame's band: copy it over
    lw    t0, S_CACHED
    nop
    beqz  t0, band_store
    nop
    jal   cache_blit
    nop
    b     out
    nop

band_store:
    ;; The band is filled from scratch whenever all of it is painted
    ;; anyway: a full-band patch rewrites every byte of it, and a black
    ;; card is black everywhere (the quad above painted the frame black),
    ;; so reading the band back from vram first would only be thrown away
    ;; again. clear_band ends in the text loop, not here.
    beqz  s3, clear_band
    nop
    lbu   t0, 5(s0)             ; flags
    nop
    andi  t0, t0, 8             ; F_FULL
    beqz  t0, band_read
    nop
    lw    t0, 8(s0)             ; patch_ptr
    nop
    beqz  t0, band_read
    nop
    lw    t0, S_PLATE           ; this state's plate is in vram already
    nop
    bnez  t0, plate_store
    nop
    b     band_patch            ; paint it from the palette
    nop

band_read:
    ;; ---- StoreImage the band (vram -> scratch), then wait for it ----
    addiu sp, sp, -0x10
    lw    t2, S_BANDX0
    lw    t3, S_BANDW
    lw    t0, S_BANDY0
    lw    t1, S_BANDROWS
    sll   t4, t2, 1
    addu  t4, t4, t2
    srl   t4, t4, 1
    sh    t4, 0(sp)             ; vram x (halfwords) = band_x0*3/2
    lw    t4, S_BUFY
    nop
    addu  t4, t4, t0
    sh    t4, 2(sp)             ; vram y = frame_y + band_y0
    sll   t4, t3, 1
    addu  t4, t4, t3
    srl   t4, t4, 1
    sh    t4, 4(sp)             ; w (halfwords) = band_w*3/2
    sh    t1, 6(sp)             ; h = band_rows
    move  a0, sp
    li    a1, SCRATCH
    lw    t0, S_STORE
    nop
    jalr  t0
    nop
    move  a0, zero
    lw    t0, S_DSYNC
    nop
    jalr  t0
    nop
    addiu sp, sp, 0x10

band_patch:
    ;; the burned-in text's pixels are repainted from the patch at this
    ;; frame's fade, so the picture under our text is the picture the game
    ;; is showing, at whatever fade it is showing it. (A black card needs
    ;; nothing: the full-screen quad already covered the band.)
    beqz  s3, text
    nop
    lw    t0, 8(s0)             ; patch_ptr (0 = a live frame, no picture)
    nop
    beqz  t0, text
    nop
    move  a0, t0
    jal   patch_pass
    nop
    ;; Keep the plate on its own in vram only where the text alphas are
    ;; moving under it (the fades) - those frames rebuild from the stored
    ;; plate instead of the palette. A frame whose plate itself changed
    ;; (the ramps) repaints it again next frame and never stores it back.
    jal   sig_plate
    nop
    beqz  v0, bp_done
    nop
    jal   plate_upload
    nop
    li    t0, 1
    sw    t0, S_PLATE
bp_done:
    b     text
    nop

sig_fill:
    ;; S_CUR_A[i] = the alpha level line i is drawn with this frame - the
    ;; same expression draw_line uses, so the cache key cannot drift.
    ;; Every stream frame takes its exact alpha; cache reuse never throttles
    ;; a fade by holding an older level.
    addiu sp, sp, -0x08
    sw    ra, 0x04(sp)
    lbu   t8, 4(s0)             ; nlines
    addiu t7, s0, 32            ; line cursor
    li    t6, S_CUR_A
sf_line:
    beqz  t8, sf_done
    nop
    lbu   t0, 6(t7)             ; alpha_idx
    lw    t1, 16(s0)            ; alpha_ptr (0 = a computed ramp)
    nop
    beqz  t1, sf_ramp
    nop
    lhu   t2, 0(s0)             ; f0
    lhu   t3, 2(s0)             ; f1
    nop
    subu  t4, t3, t2
    addiu t4, t4, 1             ; N = f1-f0+1
    mult  t0, t4
    nop
    nop
    mflo  t0                    ; alpha_idx*N
    addu  t0, t0, s2
    subu  t0, t0, t2            ; + (frame-f0)
    addu  t1, t1, t0
    lbu   t0, 0(t1)
    b     sf_store
    nop
sf_ramp:
    ;; min(frame-f0+1, f1-frame+1, 2**shift) << (8-shift)
    lhu   t1, 0(s0)             ; f0
    lhu   t2, 2(s0)             ; f1
    nop
    subu  t3, s2, t1
    addiu t3, t3, 1
    subu  t4, t2, s2
    addiu t4, t4, 1
    ;; the min() clamps: the move may not sit in a branch delay slot (it
    ;; runs whether or not the branch is taken, and the min then always
    ;; takes the second operand - the fade became a constant full alpha)
    sltu  t5, t4, t3
    beqz  t5, sf_a
    nop
    move  t3, t4
sf_a:
    lbu   t5, 20(s0)            ; shift
    li    t4, 1
    nop
    sllv  t4, t4, t5            ; 2**shift
    sltu  t0, t4, t3
    beqz  t0, sf_b
    nop
    move  t3, t4
sf_b:
    li    t4, 8
    subu  t4, t4, t5
    sllv  t0, t3, t4
sf_store:
    ;; A level is a byte and 255 is opaque; the computed ramp's plateau is
    ;; 256 = 1.0 in 8.8, which a byte store would truncate to 0 - the line
    ;; then draws nothing outside its fade. Saturate here, the one point a
    ;; level enters the byte domain (the measured tables are bytes already;
    ;; LUT32 applies the same rule to the scaled palette), so the hold
    ;; below also compares byte-domain values.
    li    t3, 255
    sltu  t4, t3, t0
    beqz  t4, sf_byte
    nop
    move  t0, t3
sf_byte:
sf_take:
    sb    t0, 0(t6)
    addiu t6, t6, 1
    addiu t7, t7, 8
    addiu t8, t8, -1
    b     sf_line
    nop
sf_done:
    lw    ra, 0x04(sp)
    addiu sp, sp, 0x08
    jr    ra
    nop

sig_match:
    ;; v0 = 1 when the cached composite is exactly this frame's band
    lw    t0, S_CACHE_E
    nop
    bne   t0, s0, sm_no
    nop
    lw    t0, S_CACHE_S
    nop
    bne   t0, s3, sm_no
    nop
    lw    t0, S_CACHE_L
    nop
    lw    t2, S_CUR_L
    nop
    bne   t0, t2, sm_no
    nop
    lw    t0, S_CACHE_P
    nop
    lw    t2, S_CUR_P
    nop
    bne   t0, t2, sm_no
    nop
    lbu   t1, 4(s0)             ; nlines
    nop
    lw    t0, S_CACHE_N
    nop
    bne   t0, t1, sm_no
    nop
    li    t2, S_CUR_A
    li    t3, S_CACHE_A
sm_loop:
    beqz  t0, sm_yes
    addiu t0, t0, -1
    lbu   t4, 0(t2)
    lbu   t5, 0(t3)
    nop
    bne   t4, t5, sm_no
    addiu t2, t2, 1
    b     sm_loop
    addiu t3, t3, 1
sm_yes:
    li    v0, 1
    jr    ra
    nop
sm_no:
    move  v0, zero
    jr    ra
    nop

cache_publish:
    ;; this frame's state becomes the cache key (the composite follows)
    sw    s0, S_CACHE_E
    lw    t0, S_SCALE           ; the scale the plate was painted at
    nop
    sw    t0, S_CACHE_S
    lw    t0, S_CUR_L
    nop
    sw    t0, S_CACHE_L
    lw    t0, S_CUR_P
    nop
    sw    t0, S_CACHE_P
    lbu   t0, 4(s0)             ; nlines
    nop
    sw    t0, S_CACHE_N
    li    t1, S_CACHE_A
    li    t2, S_CUR_A
cp_loop:
    beqz  t0, cp_done
    addiu t0, t0, -1
    lbu   t3, 0(t2)
    nop
    sb    t3, 0(t1)
    addiu t1, t1, 1
    b     cp_loop
    addiu t2, t2, 1
cp_done:
    jr    ra
    nop

cache_blit:
    ;; one vram -> vram copy: the cached composite over the band
    addiu sp, sp, -0x60
    sw    ra, 0x5C(sp)
    li    t0, 0x80000000        ; image copy
    sw    t0, 0x40(sp)
    li    t0, CACHE_X
    li    t1, CACHE_Y
    sll   t1, t1, 16
    or    t0, t0, t1
    sw    t0, 0x44(sp)          ; source x,y
    lw    t0, S_BANDX0
    nop
    lw    t2, S_BUFY
    nop
    lw    t3, S_BANDY0
    nop
    sll   t4, t0, 1
    addu  t4, t4, t0
    srl   t4, t4, 1             ; dest x (halfwords)
    addu  t2, t2, t3            ; dest y
    sll   t2, t2, 16
    or    t4, t4, t2
    sw    t4, 0x48(sp)
    lw    t0, S_BANDW
    nop
    sll   t1, t0, 1
    addu  t1, t1, t0
    srl   t1, t1, 1             ; w (halfwords)
    lw    t2, S_BANDROWS
    nop
    sll   t2, t2, 16
    or    t1, t1, t2
    sw    t1, 0x4C(sp)          ; w,h
    addiu t7, zero, 4
    jal   pq_send
    nop
    lw    ra, 0x5C(sp)
    addiu sp, sp, 0x60
    jr    ra
    nop

;; ---------------------------------------------------------------
;; plate_upload / plate_store - the plate (patch_pass's output, before
;; the text is blended over it) keeps its own rectangle in vram at
;; (PLATE_X, PLATE_Y). A frame that only moves the text alphas then
;; rebuilds the composite by storing the plate back instead of painting
;; it from the palette again - the fades are exactly those frames, one
;; store against a whole-band palette walk.
;; ---------------------------------------------------------------
;; The gpu helpers link into $ra (they are C functions), so nothing that
;; calls one can keep its own return address in $ra: it is parked on the
;; stack across every jalr here.
plate_upload:                   ; scratch -> vram (called: returns)
    addiu sp, sp, -0x10
    sw    ra, 0x0C(sp)
    li    t0, PLATE_X
    sh    t0, 0(sp)
    li    t0, PLATE_Y
    sh    t0, 2(sp)
    jal   plate_rect
    nop
    move  a0, sp
    li    a1, SCRATCH
    lw    t0, S_LOAD
    nop
    jalr  t0
    nop
    move  a0, zero              ; the upload must land before the cpu reads
    lw    t0, S_DSYNC           ; the band or the gpu gets another command
    nop
    jalr  t0
    nop
    lw    ra, 0x0C(sp)
    addiu sp, sp, 0x10
    jr    ra
    nop

plate_store:                    ; vram -> scratch (branched into from
                                ; band_store, so it ends in the text loop)
    addiu sp, sp, -0x10
    li    t0, PLATE_X
    sh    t0, 0(sp)
    li    t0, PLATE_Y
    sh    t0, 2(sp)
    jal   plate_rect
    nop
    move  a0, sp
    li    a1, SCRATCH
    lw    t0, S_STORE
    nop
    jalr  t0
    nop
    move  a0, zero              ; the store must land before the band is read
    lw    t0, S_DSYNC
    nop
    jalr  t0
    nop
    addiu sp, sp, 0x10
    b     text
    nop

plate_rect:                     ; the band's width/height at 0x04/0x06(sp)
    lw    t2, S_BANDW
    lw    t1, S_BANDROWS
    sll   t4, t2, 1
    addu  t4, t4, t2
    srl   t4, t4, 1             ; w (halfwords) = band_w*3/2
    sh    t4, 4(sp)
    sh    t1, 6(sp)
    jr    ra
    nop

;; sig_plate - v0 = 1 when vram already holds this frame's plate: the
;; same entry, picture scale, zoom level and pan the cache was built
;; with, so only the text alphas moved.
sig_plate:
    lw    t0, S_CACHE_E
    nop
    bne   t0, s0, sp_no
    nop
    lw    t0, S_CACHE_S
    nop
    bne   t0, s3, sp_no
    nop
    lw    t0, S_CACHE_L
    nop
    lw    t2, S_CUR_L
    nop
    bne   t0, t2, sp_no
    nop
    lw    t0, S_CACHE_P
    nop
    lw    t2, S_CUR_P
    nop
    bne   t0, t2, sp_no
    nop
    li    v0, 1
    jr    ra
    nop
sp_no:
    move  v0, zero
    jr    ra
    nop

patch_quad:
    ;; paints the plate over the whole band: TEX x (scale/2) / 128 = plate x
    ;; scale. s0 = entry, s2 = frame, s3 = scale (8.8). tex_ptr 0 (a black
    ;; card) is just a flat black rectangle. An 8bpp texture page is 128
    ;; texels wide and 64 vram halfwords wide, so a wide band comes as
    ;; several pages and one quad each.
    addiu sp, sp, -0x80
    sw    ra, 0x7C(sp)
    ;; the frame before this one may have ended with a band upload still in
    ;; flight; poking GP0 into a live image transfer would feed our command
    ;; words to the gpu as pixels and desync it for good
    move  a0, zero
    lw    t0, S_DSYNC
    nop
    jalr  t0
    nop
    ;; the game's drawing area is the 320x240 display box, which does not
    ;; reach the frame's vram rows - set our own so the quads cannot be
    ;; clipped, and clear the texture window and mask bits while we are here
    li    t0, 0xE2000000        ; texture window
    sw    t0, 0x40(sp)
    li    t0, 0xE3000000        ; draw area top left (0,0)
    sw    t0, 0x44(sp)
    li    t0, 0xE407FFFF        ; draw area bottom right (1023,511)
    sw    t0, 0x48(sp)
    li    t0, 0xE5000000        ; drawing offset (0,0)
    sw    t0, 0x4C(sp)
    li    t0, 0xE6000000        ; mask bits
    sw    t0, 0x50(sp)
    addiu t7, zero, 5
    jal   pq_send
    nop

    lhu   t2, 22(s0)            ; band_x0 (24bpp pixels)
    lhu   t3, 26(s0)            ; band_w (pixels)
    lbu   t4, 6(s0)             ; band_y0
    lbu   t5, 7(s0)             ; band_rows
    ;; the GPU draws in vram halfword coordinates: a 24bpp pixel is 1.5
    ;; halfwords, so x goes through *3/2 exactly like the DMA rects
    sll   t6, t2, 1
    addu  t6, t6, t2
    srl   t2, t6, 1             ; x0 = band_x0*3/2 (halfwords)
    lw    t6, S_BUFY
    nop
    addu  t4, t4, t6            ; y0
    sw    t2, 0x00(sp)          ; x0 (halfwords)
    sw    t3, 0x04(sp)          ; band_w (pixels)
    sw    t4, 0x08(sp)          ; y0
    sw    t5, 0x0C(sp)          ; rows

    ;; the picture is painted from the patch as bytes (patch_pass), not as a
    ;; gpu quad: a raw texture in ram does not survive the game's movie
    ;; decode buffer, and a modulated quad cannot address 24bpp pixels.
    beqz  s3, pq_flat           ; scale 0: the picture is black here
    nop
    b     pq_done
    nop

pq_plate:
    ;; ---- one upload and one raw quad per 64-halfword page ----
    ;; A raw textured quad copies each texel to vram verbatim, so a texel is
    ;; one exact 16-bit halfword of the band's 24bpp byte stream: the quad is
    ;; a byte-exact blit of the plate. (Modulated or blended quads cannot do
    ;; this - the gpu's 2-byte pixels never line up with the display's 3-byte
    ;; pixels, so anything but a verbatim copy stripes.) Scale 256 is a
    ;; straight copy, which is every frame outside the short fade ramps.
    lw    t1, 28(s0)            ; tex_ptr
    li    t6, 0                 ; page number
pq_pg:
    ;; texels on this page = min(64, hw - page*64), hw = band_w*3/2
    lw    t7, 0x04(sp)          ; band_w (pixels)
    nop
    sll   t8, t7, 1
    addu  t7, t7, t8            ; band_w*3
    srl   t7, t7, 1             ; hw (halfwords)
    sll   t8, t6, 6             ; page*64
    subu  t7, t7, t8
    blez  t7, pq_done
    li    t8, 64
    slt   t9, t7, t8
    beqz  t9, pq_pw
    nop
    move  t8, t7                ; texels on this page
pq_pw:
    sw    t1, 0x30(sp)          ; page data pointer
    sw    t6, 0x38(sp)          ; page number
    sw    t8, 0x3C(sp)          ; texels on this page
    ;; upload the page block: always 64 halfwords wide, rows tall
    addiu a0, sp, 0x20
    sll   t0, t6, 6             ; page*64 halfwords
    li    t7, TEX_X
    addu  t0, t7, t0
    sh    t0, 0(a0)             ; vram x of this page
    li    t0, TEX_Y
    sh    t0, 2(a0)
    li    t0, 64
    sh    t0, 4(a0)
    lw    t5, 0x0C(sp)          ; rows
    nop
    sh    t5, 6(a0)
    move  a1, t1
    lw    t0, S_LOAD
    nop
    jalr  t0
    nop
    ;; LoadImage only waits for the gpu before it starts the transfer; the
    ;; pixels are still streaming in when it returns. Poking GP0 now would
    ;; feed the quad's words to the gpu as image data and desync it.
    move  a0, zero
    lw    t0, S_DSYNC
    nop
    jalr  t0
    nop

    ;; the quad: one texel is one halfword, so the page spans texels halfwords
    lw    t6, 0x38(sp)          ; page number
    lw    t8, 0x3C(sp)          ; texels on this page
    lw    t2, 0x00(sp)          ; x0 (halfwords)
    lw    t3, 0x08(sp)          ; y0
    lw    t5, 0x0C(sp)          ; rows
    nop
    sll   t4, t6, 6             ; page*64
    addu  t2, t2, t4            ; x0 of this page
    addu  t4, t2, t8            ; x1
    addu  t5, t3, t5            ; y1
    addiu t6, sp, 0x40
    li    t8, 0x2D000000        ; textured quad, raw (verbatim), opaque
    sw    t8, 0(t6)
    sll   t8, t3, 16
    or    t8, t8, t2
    sw    t8, 4(t6)             ; xy0
    sw    zero, 8(t6)           ; uv0 (0,0)
    sll   t8, t3, 16
    or    t8, t8, t4
    sw    t8, 12(t6)            ; xy1
    lw    t9, 0x38(sp)          ; page number
    li    t8, (TEX_X / 64)
    addu  t8, t8, t9            ; tpage x = this page's vram x / 64
    ori   t8, t8, 0x0200        ; 15bpp direct (colours = 2)
    sll   t8, t8, 16
    lw    t9, 0x3C(sp)          ; texels on this page
    nop
    addiu t9, t9, -1
    andi  t9, t9, 0xFF          ; u = texels-1
    or    t8, t8, t9
    sw    t8, 16(t6)            ; tpage | uv1
    sll   t8, t5, 16
    or    t8, t8, t2
    sw    t8, 20(t6)            ; xy2
    lw    t8, 0x0C(sp)          ; rows
    nop
    addiu t8, t8, -1
    andi  t8, t8, 0xFF
    sll   t8, t8, 8             ; v = rows-1
    sw    t8, 24(t6)            ; uv2 (0, rows-1)
    sll   t8, t5, 16
    or    t8, t8, t4
    sw    t8, 28(t6)            ; xy3
    lw    t9, 0x3C(sp)          ; texels on this page
    lw    t8, 0x0C(sp)          ; rows
    nop
    addiu t9, t9, -1
    andi  t9, t9, 0xFF
    addiu t8, t8, -1
    andi  t8, t8, 0xFF
    sll   t8, t8, 8
    or    t9, t9, t8
    sw    t9, 32(t6)            ; uv3
    addiu t7, zero, 9           ; nine words - nothing more may follow
    jal   pq_send
    nop

    ;; next page: each page block is 64 halfwords (128 bytes) per row
    lw    t1, 0x30(sp)
    lw    t6, 0x38(sp)
    lw    t5, 0x0C(sp)          ; rows
    nop
    sll   t8, t5, 7             ; rows*128 bytes
    addu  t1, t1, t8
    addiu t6, t6, 1
    b     pq_pg
    nop

pq_flat:
    ;; the picture is solid black here, so a single monochrome quad over the
    ;; whole frame hides every burned-in glyph. A 24bpp pixel is 1.5
    ;; halfwords, so 320 pixels span 480 halfwords: the quad writes all
    ;; three bytes of every displayed pixel, not just two of them.
    lw    t5, S_BUFY            ; y of the frame just decoded
    nop
    li    t4, 480               ; x1 (halfwords)
    addiu t1, t5, 240           ; y1
    addiu t6, sp, 0x40
    li    t8, 0x28000000        ; monochrome quad, rgb(0,0,0)
    sw    t8, 0(t6)
    sll   t8, t5, 16
    sw    t8, 4(t6)             ; xy0 = (0,y0)
    sll   t8, t5, 16
    or    t8, t8, t4
    sw    t8, 8(t6)             ; xy1 = (480,y0)
    sll   t8, t1, 16
    sw    t8, 12(t6)            ; xy2 = (0,y1)
    sll   t8, t1, 16
    or    t8, t8, t4
    sw    t8, 16(t6)            ; xy3 = (480,y1)
    addiu t7, zero, 5
    jal   pq_send
    nop
    b     pq_done
    nop

pq_send:
    ;; the packet at 0x40(sp), t7 words, poked straight into GP0 with
    ;; GPUSTAT (port+1) polled for room before every word. No DMA: nothing
    ;; then gets out of step with the game's own image transfers, and no
    ;; stray words can reach the GPU after the packet.
    addiu t6, sp, 0x40
    li    t8, GP0
    li    t9, GP0STAT
pq_w:
    beqz  t7, pq_ret
    nop
    li    t1, 0x800             ; never spin for long
pq_wait:
    lw    t0, 0(t9)
    addiu t1, t1, -1
    srl   t0, t0, 28            ; bit 28: ready for a command word
    bnez  t0, pq_ok
    nop
    bnez  t1, pq_wait
    nop
pq_ok:
    lw    t0, 0(t6)
    addiu t6, t6, 4
    sw    t0, 0(t8)
    addiu t7, t7, -1
    b     pq_w
    nop
pq_ret:
    jr    ra
    nop

pq_done:
    lw    ra, 0x7C(sp)
    addiu sp, sp, 0x80
    jr    ra
    nop

clear_band:
    li    t0, SCRATCH
    lw    t1, S_STRIDE
    lw    t2, S_BANDROWS
    nop
    mult  t1, t2
    nop
    nop
    mflo  t1
    addu  t1, t0, t1            ; end (rounded up to 16: a few spare bytes)
    addiu t1, t1, 15
    li    t3, -16
    and   t1, t1, t3
    addiu t4, t1, -64
cl_wide:
    sltu  t2, t4, t0
    bnez  t2, cl_loop
    nop
    sw    zero, 0(t0)
    sw    zero, 4(t0)
    sw    zero, 8(t0)
    sw    zero, 12(t0)
    sw    zero, 16(t0)
    sw    zero, 20(t0)
    sw    zero, 24(t0)
    sw    zero, 28(t0)
    sw    zero, 32(t0)
    sw    zero, 36(t0)
    sw    zero, 40(t0)
    sw    zero, 44(t0)
    sw    zero, 48(t0)
    sw    zero, 52(t0)
    sw    zero, 56(t0)
    sw    zero, 60(t0)
    addiu t0, t0, 64
    b     cl_wide
    nop
cl_loop:
    sltu  t2, t0, t1
    beqz  t2, text
    nop
    sw    zero, 0(t0)
    sw    zero, 4(t0)
    sw    zero, 8(t0)
    sw    zero, 12(t0)
    addiu t0, t0, 16
    b     cl_loop
    nop

    ;; ---- the text ----
text:
    lbu   s3, 4(s0)             ; nlines
    addiu s1, s0, 32            ; line cursor
line:
    beqz  s3, done
    nop
    lw    a0, 0(s1)             ; text
    lbu   a1, 4(s1)             ; x
    lbu   a2, 5(s1)             ; y_top

    ;; the alpha sig_fill computed for this line, so the text
    ;; is drawn at exactly the level the cache key carries
    subu  t0, s1, s0
    addiu t0, t0, -32
    srl   t0, t0, 3             ; the line index
    li    t1, S_CUR_A
    addu  t0, t0, t1
    lbu   s6, 0(t0)
    nop
line_draw:
    ;; H_TAB already contains this exact coverage ramp at alpha*256.
    ;; Invisible lines need neither a ramp nor a glyph walk.
    beqz  s6, line_next
    nop

    lbu   t0, 5(s0)             ; additive ink? (intro's black-card layer)
    nop
    andi  t1, t0, 0x20          ; compiled, positioned additive ink
    beqz  t1, line_glyphs
    nop
    jal   draw_ink
    nop
    b     line_next
    nop
line_glyphs:
    andi  s4, t0, 2
    jal   draw_line
    nop
line_next:
    addiu s1, s1, 8
    addiu s3, s3, -1
    b     line
    nop

done:
    ;; the new cache key (the composite that follows is its value)
    lw    t0, S_CACHEABLE
    nop
    beqz  t0, dp_nopub
    nop
    jal   cache_publish
    nop
dp_nopub:
    ;; ---- upload the composite once: scratch -> the cache rectangle ----
    addiu sp, sp, -0x10
    lw    t3, S_BANDW
    lw    t1, S_BANDROWS
    li    t4, CACHE_X
    sh    t4, 0(sp)
    li    t4, CACHE_Y
    sh    t4, 2(sp)
    sll   t4, t3, 1
    addu  t4, t4, t3
    srl   t4, t4, 1
    sh    t4, 4(sp)
    sh    t1, 6(sp)
    move  a0, sp
    li    a1, SCRATCH
    lw    t0, S_LOAD
    nop
    jalr  t0
    nop
    addiu sp, sp, 0x10
    move  a0, zero              ; the band upload must land before we
    lw    t0, S_DSYNC           ; hand control back to the game
    nop
    jalr  t0
    nop

    jal   cache_blit
    nop
    b     out
    nop

out:
    lw    t0, S_TRUE                ; remember the frame decoded this loop:
    sw    t0, S_DISP                ; it is what will be on screen next call
    lw    ra, 0x14(sp)
    lw    s0, 0x10(sp)
    lw    s1, 0x0C(sp)
    lw    s2, 0x08(sp)
    lw    s3, 0x04(sp)
    lw    s4, 0x00(sp)
    lw    s6, 0x18(sp)
    addiu sp, sp, 0x20
    lw    t0, S_TAILFN
    lw    a0, S_TAILARG
    jr    t0
    nop

;; ---------------------------------------------------------------
;; patch_pass - paint the burned-in text's pixels with the picture,
;; scaled by this frame's measured fade (s0 = entry, s2 = frame).
;;   a0 = patch blob: 256 x RGB (8 bits per channel), then row runs.
;;   scale = scale_ptr[frame-f0] (u16 8.8), 256 = straight copy.
;; Each channel goes through lut[v] = v*scale>>8 (clamped to 255), so the
;; pixel loop only looks the three scaled bytes up.
;; ---------------------------------------------------------------
patch_pass:
    addiu sp, sp, -0x18
    sw    ra, 0x14(sp)
    sw    s1, 0x10(sp)
    sw    s3, 0x0C(sp)
    sw    s4, 0x08(sp)
    sw    s5, 0x04(sp)
    move  s1, a0                ; palette (256 x RGB)
    addiu s4, a0, 776           ; palette, probe header, max-channel bound
    lw    s3, S_SCALE           ; the live fade this frame (0 = use the table)
    nop
    beqz  s3, pp_tab
    nop
    b     pp_lut
    nop
pp_tab:
    li    s3, 256               ; scale (8.8 fixed)
    lw    t0, 12(s0)            ; scale_ptr
    nop
    beqz  t0, pp_lut
    nop
    lhu   t1, 0(s0)             ; f0
    nop
    subu  t1, s2, t1            ; frame-f0
    sll   t1, t1, 1
    addu  t0, t0, t1
    lhu   s3, 0(t0)
pp_lut:
    ;; LUT32[v] = v * scale >> 8, saturated: the plate is baked at the
    ;; entry's plateau, so a frame at the plateau is 256 and a brighter
    ;; one brightens past it until the LUT clips
    li    t0, LUT32
    li    t1, 0
pp_lut_loop:
    mult  t1, s3
    nop
    nop
    mflo  t2
    addiu t2, t2, 128           ; round to nearest: truncation darkened
    srl   t2, t2, 8             ; the whole band half a level
    li    t3, 255
    sltu  t4, t3, t2
    beqz  t4, pp_lut_store
    nop
    move  t2, t3
pp_lut_store:
    sb    t2, 0(t0)
    addiu t0, t0, 1
    addiu t1, t1, 1
    li    t2, 256
    bne   t1, t2, pp_lut_loop
    nop
    lbu   t0, 774(a0)           ; largest unscaled channel in the palette
    li    t1, LUT32
    addu  t0, t0, t1
    lbu   t0, 0(t0)
    li    t1, 255
    subu  t0, t1, t0
    sw    t0, S_HEADROOM
    ;; SPAL: the whole palette already scaled for this frame, so the pixel
    ;; loop reads a packed RGB word (the fourth byte is ignored).
    li    s5, LUT32
    li    t0, SPAL
    move  t2, s1                ; palette cursor
    li    t5, 0
pp_pal_loop:
    lbu   t6, 0(t2)             ; R
    lbu   t7, 1(t2)             ; G
    lbu   t8, 2(t2)             ; B
    addiu t2, t2, 3
    addu  t6, t6, s5
    lbu   t6, 0(t6)
    addu  t7, t7, s5
    lbu   t7, 0(t7)
    addu  t8, t8, s5
    lbu   t8, 0(t8)
    sb    t6, 0(t0)
    sb    t7, 1(t0)
    sb    t8, 2(t0)
    sb    zero, 3(t0)
    addiu t0, t0, 4
    addiu t5, t5, 1
    li    t9, 256
    bne   t5, t9, pp_pal_loop
    nop
    li    s1, SPAL              ; the row loop reads the scaled palette
    ;; The rows this frame paints were picked in active (they are part of
    ;; the cache key): a zoomed patch holds one pre-scaled copy of the band
    ;; per level and the level table takes one - the drift is baked into
    ;; the levels, so there is no pan left to apply. A flat patch drifts
    ;; under the burned text, so the blob carries rows past the band on
    ;; both sides and each source row is painted at y+pan; rows that leave
    ;; the band are dropped (the band is the upload rect - nothing outside
    ;; it may be written).
    lw    s3, S_CUR_P            ; the pan (0 for a zoomed patch)
    lbu   t0, 5(s0)
    nop
    andi  t0, t0, 0x10          ; F_ZOOM: all levels use explicit pointers
    beqz  t0, pp_row
    nop
    lw    t0, S_CUR_L
    addiu t1, a0, 780           ; palette/probe header, count, then pointers
    sll   t0, t0, 2
    addu  t1, t1, t0
    lw    s4, 0(t1)
    move  s3, zero              ; drift is already baked into the level
pp_row:
    lbu   t0, 0(s4)             ; y
    nop
    li    t1, 0xFF
    beq   t0, t1, pp_done
    nop
    lbu   t2, 1(s4)             ; nruns
    addiu s4, s4, 2
    ;; row base = SCRATCH + (y+pan-band_y0)*stride + xoff
    addu  t0, t0, s3
    lw    t3, S_BANDY0
    nop
    subu  t0, t0, t3
    bltz  t0, pp_skip
    lw    t3, S_BANDROWS
    nop
    sltu  t4, t0, t3
    beqz  t4, pp_skip
    nop
    lw    t3, S_STRIDE
    nop
    mult  t0, t3
    nop
    nop
    mflo  t0
    li    t3, SCRATCH
    addu  t0, t0, t3
    lw    t3, S_XOFF
    nop
    addu  s5, t0, t3            ; row base (x = 0 folded in)
pp_run:
    beqz  t2, pp_row
    addiu t2, t2, -1
    lbu   t3, 0(s4)             ; x0 (byte reads: run rows are not aligned)
    lbu   t6, 1(s4)
    nop
    sll   t6, t6, 8
    or    t3, t3, t6
    lbu   t4, 2(s4)             ; len
    lbu   t6, 3(s4)
    nop
    sll   t6, t6, 8
    or    t4, t4, t6
    addiu s4, s4, 4
    addiu s4, s4, 3
    li    t5, -4
    and   s4, s4, t5            ; index runs start on a word boundary
    sll   t5, t3, 1
    addu  t5, t5, t3            ; x0*3
    addu  t3, s5, t5            ; pixel cursor
    beqz  t4, pp_run
    nop
    ;; Word stores overlap the next pixel by one byte. Save that byte at
    ;; the end of this run and restore it, including on the final band row.
    sll   t5, t4, 1
    addu  t5, t5, t4
    addu  a1, t3, t5
    lbu   a2, 0(a1)
    sltiu t5, t4, 4
    bnez  t5, pp_px
    nop
pp_four:
    lw    t9, 0(s4)             ; four indices, one main-RAM load
    addiu s4, s4, 4
    sll   t5, t9, 2
    andi  t5, t5, 0x3FC
    srl   t6, t9, 6
    andi  t6, t6, 0x3FC
    addu  t5, t5, s1
    addu  t6, t6, s1
    lw    t7, 0(t5)
    lw    t8, 0(t6)
    swl   t7, 3(t3)
    swr   t7, 0(t3)
    swl   t8, 6(t3)
    swr   t8, 3(t3)
    srl   t5, t9, 14
    andi  t5, t5, 0x3FC
    srl   t6, t9, 22
    andi  t6, t6, 0x3FC
    addu  t5, t5, s1
    addu  t6, t6, s1
    lw    t7, 0(t5)
    lw    t8, 0(t6)
    swl   t7, 9(t3)
    swr   t7, 6(t3)
    swl   t8, 12(t3)
    swr   t8, 9(t3)
    addiu t4, t4, -4
    addiu t3, t3, 12
    sltiu t5, t4, 4
    beqz  t5, pp_four
    nop
    beqz  t4, pp_restore
    nop
pp_px:
    lbu   t5, 0(s4)             ; palette index
    addiu s4, s4, 1
    sll   t5, t5, 2
    addu  t5, t5, s1            ; 4-byte scaled entry
    lw    t6, 0(t5)             ; packed RGB
    addiu t4, t4, -1
    swl   t6, 3(t3)
    swr   t6, 0(t3)
    bnez  t4, pp_px
    addiu t3, t3, 3
pp_restore:
    sb    a2, 0(a1)
    addiu s4, s4, 3
    li    t5, -4
    and   s4, s4, t5
    b     pp_run
    nop
pp_skip:
    beqz  t2, pp_row            ; drop this row's runs: 4 header bytes + pixels
    addiu t2, t2, -1
    lbu   t4, 2(s4)             ; len
    lbu   t5, 3(s4)
    nop
    sll   t5, t5, 8
    or    t4, t4, t5
    addiu s4, s4, 4
    addiu s4, s4, 3
    li    t5, -4
    and   s4, s4, t5
    addu  s4, s4, t4
    addiu s4, s4, 3
    and   s4, s4, t5
    b     pp_skip
    nop
pp_done:
    lw    ra, 0x14(sp)
    lw    s1, 0x10(sp)
    lw    s3, 0x0C(sp)
    lw    s4, 0x08(sp)
    lw    s5, 0x04(sp)
    addiu sp, sp, 0x18
    jr    ra
    nop

;; ---------------------------------------------------------------
;; draw_line(a0 = text, a1 = x, a2 = y_top) - walk the NUL-terminated
;; text and blend every glyph into the band. Each char looks up its
;; glyph's span list (H_PTRS: per row y u8, nruns u8, then per run
;; x0 u8, len u8 (bit 7 = every pixel has cov 255), len x (gray u8,
;; cov u8); 0xFF ends a glyph).
;; H_TAB[alpha*256] holds this line's fade ramp, so eff = ramp[cov].
;; s4 != 0: the ink adds over the band (the intro's black-card layer);
;; s4 == 0: the ink pastes over it (poems, speech). Preserves s4.
;; ---------------------------------------------------------------
draw_line:
    addiu sp, sp, -0x28
    sw    ra, 0x24(sp)
    sw    s0, 0x20(sp)
    sw    s1, 0x1C(sp)
    sw    s2, 0x18(sp)
    sw    s3, 0x14(sp)
    sw    s4, 0x10(sp)
    sw    s5, 0x0C(sp)
    sw    s6, 0x08(sp)
    sw    s7, 0x04(sp)
    move  s0, a0                ; text cursor
    move  s2, a2                ; y_top
    move  s3, a1                ; pen x
    ;; Build one row-base pointer per glyph cell row: 24 entries shared
    ;; by all glyphs in this line.
    lw    t0, S_BANDY0
    lw    t1, S_STRIDE
    lw    t2, S_XOFF
    subu  t3, s2, t0
    mult  t3, t1
    nop
    nop
    mflo  t3
    li    t4, SCRATCH
    addu  t3, t3, t4
    addu  t3, t3, t2
    li    t0, ROW_TAB
    li    t4, 24
dl_rowtab:
    sw    t3, 0(t0)
    addu  t3, t3, t1
    addiu t0, t0, 4
    addiu t4, t4, -1
    bnez  t4, dl_rowtab
    nop
    move  s2, s4                ; the additive-ink flag (s4 -> s2)
    lw    s4, H_TAB             ; T[eff][v] paste table
    sll   s7, s6, 8
    addu  s7, s7, s4            ; T[alpha][coverage], no per-line rebuild
dl_char:
    lbu   t0, 0(s0)
    nop
    beqz  t0, dl_done
    addiu s0, s0, 1
    lw    t1, H_PTRS
    addiu t2, t0, -GLYPH_FIRST
    sll   t2, t2, 2
    addu  t1, t1, t2
    lw    s1, 0(t1)             ; spans cursor
    nop
dl_row:
    lbu   t3, 0(s1)             ; y in the cell
    nop
    li    t4, 0xFF
    beq   t3, t4, dl_adv
    nop
    lbu   t4, 1(s1)             ; nruns
    addiu s1, s1, 2
    sll   t3, t3, 2             ; cell row * 4
    li    t5, ROW_TAB
    addu  t5, t5, t3
    lw    s5, 0(t5)             ; row base
dl_run:
    beqz  t4, dl_row
    addiu t4, t4, -1
    lbu   t6, 0(s1)             ; x0 in the cell
    lbu   t7, 1(s1)             ; run length | solid-run flag
    addiu s1, s1, 2
    andi  t9, t7, 0x80          ; every pixel fully covered?
    andi  t7, t7, 0x7F          ; actual run length
    addu  t6, s3, t6            ; absolute x
    sll   t8, t6, 1
    addu  t8, t8, t6            ; *3
    addu  s6, s5, t8            ; pixel cursor
    beqz  t7, dl_run
    nop
    beqz  s2, dl_paste_check
    nop
    lw    t8, H_CLAMP           ; additive: out = CLAMP[bg + gray*eff>>8]
    b     dl_add
    nop
dl_paste_check:
    ;; A flagged run is fully covered; if the line is (nearly) opaque the
    ;; result is just the ink gray, so skip the table blend entirely.
    beqz  t9, dl_paste
    nop
    lbu   t9, 255(s7)           ; T_TAB[255] = ramp[255]
    li    t6, 254
    sltu  at, t9, t6
    bnez  at, dl_paste
    nop
dl_solid:
    lbu   t0, 0(s1)             ; gray
    addiu s1, s1, 2
    sb    t0, 0(s6)
    sb    t0, 1(s6)
    sb    t0, 2(s6)
    addiu t7, t7, -1
    bnez  t7, dl_solid
    addiu s6, s6, 3
    b     dl_run
    nop
dl_add:
    ;; A black card's band is black everywhere (clear_band wrote it), so
    ;; there the additive blend collapses to the ink itself: out = p, with
    ;; no background to read and nothing to clamp. Same bytes, half the
    ;; walk - and the opening quote spends 120 of its 154 frames on black.
    lw    a0, S_SCALE           ; (a0 is free here; t8 is the clamp table)
    nop
    beqz  a0, dl_addblk
    nop
    lbu   t0, 0(s1)             ; gray
    lbu   t9, 1(s1)             ; cov
    addiu s1, s1, 2
    addiu t7, t7, -1
    beqz  t0, dl_addn           ; no gray: the ink adds exactly nothing and
    addu  t9, t9, s7            ; the pixel stays what it was (half the ink
                                ; is the black outline)
    lbu   t9, 0(t9)             ; eff = ramp[cov]
    nop
    mult  t9, t0
    nop
    mflo  t0
    addiu t0, t0, 128
    srl   t0, t0, 8             ; rounded additive contribution
    addu  t1, t0, t8            ; CLAMP + p
    lbu   t2, 0(s6)             ; bg0
    lbu   t3, 1(s6)             ; bg1
    addu  t2, t2, t1
    lbu   t2, 0(t2)             ; CLAMP[bg0+p]
    addu  t3, t3, t1
    sb    t2, 0(s6)
    lbu   t2, 2(s6)             ; bg2
    lbu   t3, 0(t3)             ; CLAMP[bg1+p]
    addu  t2, t2, t1
    sb    t3, 1(s6)
    lbu   t2, 0(t2)             ; CLAMP[bg2+p]
    nop
    sb    t2, 2(s6)
    bnez  t7, dl_add
    addiu s6, s6, 3
    b     dl_run
    nop
dl_addn:
    bnez  t7, dl_add
    addiu s6, s6, 3
    b     dl_run
    nop
dl_addblk:
    lbu   t0, 0(s1)             ; gray
    lbu   t9, 1(s1)             ; cov
    addiu s1, s1, 2
    addiu t7, t7, -1
    beqz  t0, dl_addn           ; no gray adds nothing over black either
    addu  t9, t9, s7            ; + ramp base
    lbu   t9, 0(t9)             ; eff = ramp[cov]
    nop
    mult  t9, t0
    nop
    mflo  t0
    addiu t0, t0, 128
    srl   t0, t0, 8
    ;; the band is black here unless a second glyph already added its ink
    ;; on this pixel - the outline overhangs the advance, so overlaps are
    ;; common and their sum still has to saturate
    lbu   t2, 0(s6)
    nop
    bnez  t2, dl_addov
    nop
    sb    t0, 0(s6)
    sb    t0, 1(s6)
    sb    t0, 2(s6)
    bnez  t7, dl_addblk
    addiu s6, s6, 3
    b     dl_run
    nop
dl_addov:
    addu  t1, t0, t8            ; CLAMP + p (the same saturating add the
    lbu   t2, 0(s6)             ; blended path uses)
    lbu   t3, 1(s6)
    addu  t2, t2, t1
    lbu   t2, 0(t2)             ; CLAMP[bg0+p]
    addu  t3, t3, t1
    sb    t2, 0(s6)
    lbu   t2, 2(s6)
    lbu   t3, 0(t3)             ; CLAMP[bg1+p]
    addu  t2, t2, t1
    sb    t3, 1(s6)
    lbu   t2, 0(t2)             ; CLAMP[bg2+p]
    nop
    sb    t2, 2(s6)
    bnez  t7, dl_addblk
    addiu s6, s6, 3
    b     dl_run
    nop
dl_paste:
    ;; paste: out = bg + T[eff][gray] - T[eff][bg], T[v] = v*eff>>8.
    ;; One 256-byte table row per eff; the ink and the background use the
    ;; same row, so the per-pixel blend is four lookups and no multiply.
dl_px:
    lbu   t0, 0(s1)             ; gray
    lbu   t9, 1(s1)             ; cov
    addiu s1, s1, 2
    addu  t9, t9, s7
    lbu   t9, 0(t9)             ; eff
    addiu t7, t7, -1
    sll   t8, t9, 8             ; eff*256
    addu  t8, t8, s4            ; T + eff*256
    addu  t5, t8, t0            ; + gray
    lbu   t3, 0(t5)             ; T[eff][gray]
    lbu   t2, 0(s6)             ; bg0
    lbu   t1, 1(s6)             ; bg1
    lbu   t6, 2(s6)             ; bg2 (t4 is the row's run counter)
    addu  a0, t8, t2
    lbu   a0, 0(a0)             ; T[eff][bg0]
    addu  a1, t8, t1
    lbu   a1, 0(a1)             ; T[eff][bg1]
    addu  a2, t8, t6
    lbu   a2, 0(a2)             ; T[eff][bg2]
    subu  t2, t2, a0
    addu  t2, t2, t3
    sb    t2, 0(s6)
    subu  t1, t1, a1
    addu  t1, t1, t3
    sb    t1, 1(s6)
    subu  t6, t6, a2
    addu  t6, t6, t3
    sb    t6, 2(s6)
    bnez  t7, dl_px
    addiu s6, s6, 3
    b     dl_run
    nop
dl_adv:
    ;; pen += advance[char] (the char is at -1(s0) now)
    lbu   t0, -1(s0)
    lw    t1, H_ADV
    addiu t0, t0, -GLYPH_FIRST
    addu  t1, t1, t0
    lbu   t2, 0(t1)
    nop
    addu  s3, s3, t2
    b     dl_char
    nop
dl_done:
    lw    ra, 0x24(sp)
    lw    s0, 0x20(sp)
    lw    s1, 0x1C(sp)
    lw    s2, 0x18(sp)
    lw    s3, 0x14(sp)
    lw    s4, 0x10(sp)
    lw    s5, 0x0C(sp)
    lw    s6, 0x08(sp)
    lw    s7, 0x04(sp)
    addiu sp, sp, 0x28
    jr    ra
    nop

;; Compiled additive ink. Evaluate each unique sum once, then draw positioned
;; spans. Saturating additions associate, including overhanging glyphs.
;; a0 = expression/span blob, s6 = alpha, s0 = entry. Preserve caller s*.
draw_ink:
    addiu sp, sp, -0x20
    sw    s1, 0(sp)
    sw    s2, 4(sp)
    sw    s3, 8(sp)
    sw    s4, 12(sp)
    sw    s5, 16(sp)
    sw    s7, 20(sp)
    subu  t8, s1, s0
    addiu t8, t8, -32
    srl   t8, t8, 3             ; line index in this entry
    lbu   t0, 7(s1)             ; line overlaps an earlier line's ink
    move  s1, a0
    sll   t1, t8, 12
    li    s2, INK_TAB
    addu  s2, s2, t1
    sll   t1, t8, 4
    li    s5, INK_META
    addu  s5, s5, t1
    lw    s3, S_SCALE
    lw    s4, H_CLAMP
    or    s3, s3, t0            ; overlap always takes the saturating blend
    sltu  s3, zero, s3
    beqz  s3, ink_mode
    nop
    bnez  t0, ink_mode          ; previous lines invalidate the plate-only bound
    nop
    sll   t0, s6, 1
    addu  t0, t0, s1
    lhu   t0, 2(t0)             ; peak contribution at this alpha
    lw    t1, S_HEADROOM
    nop
    sltu  t0, t1, t0
    bnez  t0, ink_mode
    nop
    li    s3, 2                 ; proven carry-free packed RGB add
ink_mode:
    lw    t0, 0(s5)
    lw    t1, 4(s5)
    bne   t0, a0, ink_build
    nop
    bne   t1, s6, ink_build
    nop
    lw    t0, 8(s5)
    nop
    bne   t0, s3, ink_build
    nop
    lw    s1, 12(s5)
    b     ink_row
    nop
ink_build:
    lhu   t8, 0(s1)
    addiu s1, s1, 514
    lbu   t0, 5(s0)
    li    s7, 128               ; full payload rounds to nearest
    andi  t0, t0, 0x40          ; OPEN preserves its floor-rounded blend
    beqz  t0, ink_round
    nop
    move  s7, zero
ink_round:
    beqz  t8, ink_align
    nop
ink_expr:
    lbu   t1, 0(s1)             ; number of positive contributions
    addiu s1, s1, 1
    move  t7, zero
ink_term:
    lbu   t2, 0(s1)             ; gray
    lbu   t3, 1(s1)             ; coverage
    addiu s1, s1, 2
    mult  t3, s6
    nop
    mflo  t3
    srl   t3, t3, 8
    mult  t2, t3
    nop
    mflo  t2
    addu  t2, t2, s7
    srl   t2, t2, 8
    addu  t7, t7, t2
    addiu t1, t1, -1
    bnez  t1, ink_term
    nop
    ;; min(255, bg + sum) == min(255, bg + min(255, sum)). This also
    ;; keeps the pointer inside the 512-byte clamp table on overlapping ink.
    sltiu t0, t7, 256
    bnez  t0, ink_gray
    nop
    li    t7, 255
ink_gray:
    li    t0, 1
    beq   s3, t0, ink_color
    nop
    ;; Black background: the expression is the final gray, not a blend.
    sll   t0, t7, 8
    or    t0, t7, t0
    sll   t7, t7, 16
    or    t7, t7, t0            ; packed 00BBGGRR, no carry into the next pixel
    b     ink_result
    nop
ink_color:
    addu  t7, t7, s4            ; pointer to CLAMP + summed contribution
ink_result:
    sw    t7, 0(s2)
    addiu s2, s2, 4
    addiu t8, t8, -1
    bnez  t8, ink_expr
    nop
ink_align:
    addiu s1, s1, 1             ; align the positioned spans to u16
    li    t0, -2
    and   s1, s1, t0
    sw    a0, 0(s5)
    sw    s6, 4(s5)
    sw    s3, 8(s5)
    sw    s1, 12(s5)
    ;; Restore the start of this line's lookup after the expression writes.
    li    t0, INK_META
    subu  t0, s5, t0
    sll   t0, t0, 8             ; metadata stride 16 -> lookup stride 4096
    li    s2, INK_TAB
    addu  s2, s2, t0
ink_row:
    lbu   t0, 0(s1)
    li    t1, 255
    beq   t0, t1, ink_done
    nop
    lbu   s5, 1(s1)
    addiu s1, s1, 2
    lw    t1, S_BANDY0
    lw    t2, S_STRIDE
    subu  t0, t0, t1
    mult  t0, t2
    nop
    mflo  t0
    lw    t1, S_XOFF
    li    t2, SCRATCH
    addu  t0, t0, t1
    addu  s7, t0, t2
ink_run:
    lhu   t0, 0(s1)             ; absolute x
    lhu   t4, 2(s1)             ; pixel count
    addiu s1, s1, 4
    sll   t1, t0, 1
    addu  t0, t0, t1
    addu  t3, s7, t0
    li    t0, 2
    beq   s3, t0, ink_fast
    nop
    bnez  s3, ink_blend
    nop
    sll   t0, t4, 1
    addu  t0, t0, t4
    addu  a1, t3, t0
    lbu   a2, 0(a1)             ; preserve byte beyond the packed stores
ink_black:
    lhu   t0, 0(s1)
    addiu s1, s1, 2
    sll   t0, t0, 2
    addu  t0, t0, s2
    lw    t1, 0(t0)
    addiu t4, t4, -1
    swl   t1, 3(t3)
    swr   t1, 0(t3)
    bnez  t4, ink_black
    addiu t3, t3, 3
    sb    a2, 0(a1)
    b     ink_next
    nop
ink_blend:
    lhu   t0, 0(s1)
    addiu s1, s1, 2
    sll   t0, t0, 2
    addu  t0, t0, s2
    lw    t1, 0(t0)             ; CLAMP + summed contribution
    lbu   t5, 0(t3)
    lbu   t6, 1(t3)
    lbu   t7, 2(t3)
    addu  t5, t5, t1
    addu  t6, t6, t1
    addu  t7, t7, t1
    lbu   t5, 0(t5)
    lbu   t6, 0(t6)
    lbu   t7, 0(t7)
    sb    t5, 0(t3)
    sb    t6, 1(t3)
    sb    t7, 2(t3)
    addiu t4, t4, -1
    bnez  t4, ink_blend
    addiu t3, t3, 3
    b     ink_next
    nop
ink_fast:
    lhu   t0, 0(s1)
    addiu s1, s1, 2
    sll   t0, t0, 2
    addu  t0, t0, s2
    lw    t1, 0(t0)             ; packed contribution, high byte zero
    lwl   t2, 3(t3)
    lwr   t2, 0(t3)
    addiu t4, t4, -1
    addu  t2, t2, t1            ; each RGB channel proven <= 255
    swl   t2, 3(t3)
    swr   t2, 0(t3)
    bnez  t4, ink_fast
    addiu t3, t3, 3
ink_next:
    addiu s5, s5, -1
    bnez  s5, ink_run
    nop
    b     ink_row
    nop
ink_done:
    lw    s1, 0(sp)
    lw    s2, 4(sp)
    lw    s3, 8(sp)
    lw    s4, 12(sp)
    lw    s5, 16(sp)
    lw    s7, 20(sp)
    addiu sp, sp, 0x20
    jr    ra
    nop

ink_reset:
    li    t0, INK_META
    li    t1, 8
ink_reset_loop:
    sw    zero, 0(t0)
    addiu t0, t0, 16
    addiu t1, t1, -1
    bnez  t1, ink_reset_loop
    nop
    jr    ra
    nop

;; Exact sum of t4 bytes at t0 -> t5. Four aligned words per iteration;
;; two independent 16-bit lanes each sum two bytes per word. At most 128
;; words enter one accumulator, so each lane is <= 65280 and cannot carry.
sum_bytes:
    li    t5, 0
    li    t1, 0x00FF00FF
sum_align:
    andi  t2, t0, 3
    beqz  t2, sum_block
    nop
    beqz  t4, sum_return
    nop
    lbu   t6, 0(t0)
    addiu t0, t0, 1
    addu  t5, t5, t6
    addiu t4, t4, -1
    b     sum_align
    nop
sum_block:
    srl   t2, t4, 4             ; complete 16-byte groups
    beqz  t2, sum_tail
    nop
    sltiu t6, t2, 33
    bnez  t6, sum_start
    nop
    li    t2, 32                ; 512 bytes per lane accumulator
sum_start:
    move  a0, zero
sum_words:
    lw    t6, 0(t0)
    lw    t7, 4(t0)
    lw    t8, 8(t0)
    lw    t9, 12(t0)
    and   a1, t6, t1
    srl   t6, t6, 8
    and   t6, t6, t1
    addu  a1, a1, t6
    addu  a0, a0, a1
    and   a1, t7, t1
    srl   t7, t7, 8
    and   t7, t7, t1
    addu  a1, a1, t7
    addu  a0, a0, a1
    and   a1, t8, t1
    srl   t8, t8, 8
    and   t8, t8, t1
    addu  a1, a1, t8
    addu  a0, a0, a1
    and   a1, t9, t1
    srl   t9, t9, 8
    and   t9, t9, t1
    addu  a1, a1, t9
    addu  a0, a0, a1
    addiu t0, t0, 16
    addiu t4, t4, -16
    addiu t2, t2, -1
    bnez  t2, sum_words
    nop
    andi  t6, a0, 0xFFFF
    srl   t7, a0, 16
    addu  t5, t5, t6
    addu  t5, t5, t7
    b     sum_block
    nop
sum_tail:
    beqz  t4, sum_return
    nop
    lbu   t6, 0(t0)
    addiu t0, t0, 1
    addu  t5, t5, t6
    addiu t4, t4, -1
    b     sum_tail
    nop
sum_return:
    jr    ra
    nop

;; StGetNext wrappers. Ready data always goes straight back to the stock
;; decoder. Only a failed poll AND a completed MDEC frame permit early draw;
;; dec.done is read, never cleared, so the stock StrSync still runs normally.
poll_movie:
    li    t0, 0x80089ED0        ; MOVIE StGetNext
    li    t1, 0x800FF8F0        ; g_dec.done
    li    t2, frame_entry
    b     poll_common
    nop
poll_open:
    li    t0, 0x80092850        ; OPEN StGetNext
    li    t1, 0x801146EC        ; g_dec.done
    li    t2, frame_entry_open
poll_common:
    addiu sp, sp, -0x30         ; preserve SDK argument-home space at +0..15
    sw    ra, 0x2C(sp)
    sw    t1, 0x10(sp)
    sw    t2, 0x14(sp)
    lw    t3, S_TRUE            ; this frame, before the next header is read
    nop
    sw    t3, S_DISP
    jalr  t0
    nop
    sw    v0, 0x18(sp)
    sw    v1, 0x1C(sp)
    beqz  v0, poll_return       ; next frame ready: never delay its decoding
    nop
    lw    t0, S_RENDERED
    nop
    bnez  t0, poll_return       ; at most one draw per completed frame
    nop
    lw    t0, 0x10(sp)
    nop
    lw    t0, 0(t0)
    nop
    beqz  t0, poll_return       ; MDEC is still writing: leave it alone
    nop
    li    t0, 1
    sw    t0, S_EARLY
    lw    t0, 0x14(sp)
    nop
    jalr  t0
    nop
    sw    zero, S_EARLY
    li    t0, 1
    sw    t0, S_RENDERED
poll_return:
    lw    v0, 0x18(sp)
    lw    v1, 0x1C(sp)
    lw    ra, 0x2C(sp)
    addiu sp, sp, 0x30
    jr    ra
    nop
early_return:
    jr    ra
    nop

.if . > S_FRAME
    .error "FMV renderer overlaps its per-frame state"
.endif

.org 0x80161FC0
trueframe_open:                     ; OPEN.EXE 0x80089410 -> here (v1 = frame_count)
    sw    v1, S_TRUE
    j     0x80089414
    nop

.org 0x80161FE0
trueframe_movie:                    ; MOVIE.EXE 0x800813B4 -> here (v1 = frame_count)
    sw    v1, S_TRUE                ; save it before the compare destroys v1
    addiu v0, v0, -3                ; the two instructions that were replaced:
    sltu  v1, v1, v0
    j     0x800813BC
    nop

.close
