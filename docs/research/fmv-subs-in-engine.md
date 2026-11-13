# In-engine FMV subtitles (MOVIE.EXE) - research and design

Goal: render every FMV text overlay from the game itself instead of burning
pixels into the STR frames: the spoken-movie subtitles (Philemon / Kandori
speeches, 71 rows in `translation/manual/fmv/subtitles.tsv`) over the live
frame, and the opening quote cards / ending poems - whose Japanese is baked
into the video - as a measured patch plus in-engine text (see "Renderer").

Text provenance: the PSP release carries no FMV subtitle *text* - the lines
exist there only as voiced audio - so the wording comes from the GameFAQs script
transcription kept in `translation/manual/fmv/subtitles.tsv` (restored from
`translation/manual.bak/`), a manual TSV entry with its source identified.

Target binary: Rev 0 (`SLPS-00500`, first release). The decomp under
`references/persona-decomp` is **Rev 1** - its addresses do not apply, but its
source (`src/movie/movie.c`, `src/movie/str.c`, `include/persona/common/str.h`)
is a line-for-line map of the player, and every structure offset and small-data
offset below was confirmed identical between the two builds. On rebase to Rev 1
the addresses change; the map in this document must be re-derived the same way
(the scanner scripts in `scratch/movie_re/` do it mechanically).

## 1. What the movie player is

`EXE/MOVIE.EXE` is a standalone PS-EXE the resident loads with
`LoadAndExecPsExe("\\EXE\\MOVIE.EXE;1")` (decomp `src/main/main.c`,
`GAME_STATE_MOVIE`). It is Sony's stock STR streaming sample: MDEC decodes one
frame while the CD interrupt feeds the ring buffer and the previous frame's
slices are `LoadImage`d into one of two display areas. Video is **24 bpp,
320x240** (`StrSetDecEnv` sets the display rects 480 halfwords wide = 320
pixels at 3 bytes; slices are 24x240), so frames land in VRAM as raw 24-bit
data and anything drawn on top must be composited as 24-bit pixels
(`LoadImage`) - GPU primitives write 15-bit halfwords and would display as
wrong colors in 24 bpp mode.

### Rev 0 map (derived from Rev 1 decomp shape + our binary)

| what | Rev 0 | Rev 1 (decomp) |
|---|---|---|
| `main` | `0x80080C20` | `0x80080E3C` |
| `MoviePlay` | `0x80080CE8` | `0x80080F04` |
| frame loop body | `0x80080F54 .. 0x80081018` | - |
| `StrOutCallback` | `0x800811A0` | `0x80081388` |
| `StrDecodeNextFrame` | `0x800812D8` | `0x800814B4` |
| `StrGetReadyFrame` | `0x80081360` | `0x8008153C` |
| `StrSync` | `0x800813E0` | `0x800815B8` |
| `StrSetDecEnv` | `0x80081458` | `0x80081630` |
| `StrKickCD` | `0x800814CC` | `0x800816A4` |
| `StrPutHex` | `0x80081518` | `0x800816F0` |
| `start` (crt0, sets gp) | `0x80081594` | - |
| `DecDCTin` / `DecDCTout` | `0x80081710` / `0x8008178C` | - |
| `LoadImage` / `DrawSync` | `0x80082720` / `0x800824F8` | - |
| `PadRead` / `VSync` / `ResetGraph` | `0x8008A910` / `0x8008AD88` / `0x8008205C` | - |
| `GsInitGraph` / `GsSwapDispBuff` | `0x80084DC8` / `0x80085F94` | - |
| `g_movie_frames[39]` | `0x80095F0A` | `0x80096A64` |
| `g_movie_after[27]` | `0x80095F58` | `0x80096AB4` |
| gp (small data base) | `0x800A929C` | `0x800A9E7C` |
| `g_movie_end` / `g_movie_no` | gp+0 / gp+4 | same offsets |
| `g_movie_first` / `g_movie_again` | gp+5 / gp+6 | same offsets |
| `g_movie_frame` / `g_str_loc` | gp+0x18 / gp+0x20 | same offsets |
| `g_vlc_buf0` / `g_vlc_buf1` (0x28000 each) | `0x800A92C0` / `0x800D12C0` | `0x800A9EA0` / `0x800D1EA0` |
| `g_img_buf` (one slice) | `0x800F92C0` | `0x800F9EA0` |
| `g_dec` (StrDecodeTarget, 0x30) | `0x800FF8C4` | `0x801004A8` |
| `g_ring_buf` (StSetRing(..., 20)) | `0x800FF920` | `0x80100504` |
| `StCdIntrFlag` (libcd) | `0x800FF72C` | `0x80100310` |
| `g_movie_id` / `g_movie_next_state` (resident) | `0x801F15C2` / `0x801F15C4` | identical |
| `MAP_ID` etc. (resident) | `0x801F5350+` | identical |

`g_movie_frames` values are identical across Rev 0/Rev 1 (same STR files):
39 entries, indexed by movie number (`MV11` in the TSV = `0x11`, the file name
is `\STR<movie_no>>4\MV<movie_no & 0xF><hi nibble>.STR`).

### Frame loop (Rev 0)

```
80080F54  DecDCTin(g_dec.vlc_buf[g_dec.vlc_id], 1)
80080F94  DecDCTout(g_dec.img_buf, slice.w*slice.h/2)   ; slices -> StrOutCallback
80080F9C  StrDecodeNextFrame(&g_dec)                    ; VLC next frame, frees ring slot
80080FA4  g_movie_frame++                               ; gp+0x18
80080FB4  StrSync(&g_dec)                               ; frame is fully in VRAM now
80080FBC  PadRead(1)                                    ; <-- subtitle hook goes here
80080FC4  VSync(0)
80080FCC  ResetGraph(1)
80080FD4  GsSwapDispBuff()                              ; shows the frame just filled
80080FDC  while (g_movie_frame < g_movie_frames[g_movie_no]-3 && !g_movie_end)
```

`StrOutCallback` (`0x800811A0`) runs on each MDEC slice: `LoadImage(&slice,
img_buf)`, `slice.x += slice.w`, and at the end of the display area flips
`g_dec.rect_id` and raises `g_dec.done`. So **after `StrSync` returns, the
completed frame is in `g_dec.rect[1 - rect_id]`** (`rect[0]` = (0,0,480,240),
`rect[1]` = (0,240,480,240)) and nothing else writes to it until the next
loop iteration - that is where subtitles must be composited, before
`GsSwapDispBuff` displays it.

## 2. Where the subtitle data can live

RAM is tight; the movie player's own footprint (image + MDEC buffers + ring)
runs `0x80080000..~0x80114000`, the resident's save/state lives at
`0x801F0000+`, and the sub-EXE stack is `0x801FBFF0` down. The decomp documents
the staging areas the resident re-reads around every scene change:

| address | owner |
|---|---|
| `0x80118000` | SEQ/scene staging (`SEQ_DATA`, `SCENE_AT`) |
| `0x80140000` | NAME / BTL field / S2D model staging |
| `0x80150000` | VAB body staging (ADV audio) |
| `0x80180000` | `ADV_DEST` / `SCENE_PACKED` |
| `0x80190000` / `0x801B8000` | S2D map / ADV scene pack |
| `0x801CD000` | BGM pack |
| `0x801E0000` | `FONT_DEST` (game font, permanent) |
| `0x801F0000` | `SAVE_WORK` (permanent) |

The movie scene runs `LoadAndExecPsExe` *first* and calls `PreloadDng/Adv/S2d/
Name` only **after** the movie returns (every `g_movie_after` state is covered),
so `0x80118000..0x801E0000` is stale scratch during playback. There are two
payloads, because the two executables have different neighbours:

- **MOVIE.EXE** (every movie) loads the full blob at `0x80160000` and may use
  the whole window up to `FONT_DEST` (`0x801E0000`). `0x80180000` and above
  are stale staging ranges during playback and re-staged after the movie
  returns.
- **OPEN.EXE** (opening quote only) shares its window with `OPEN.BIN`: the
  resident loads the title pack at `0x80180000` *immediately before*
  `LoadAndExecPsExe` starts OPEN.EXE, so a blob reaching past that address
  overwrites the title's TIM/VAB/SEQ data and the main menu comes up broken.
  Its reduced blob therefore ends below `0x80180000`.

The `OPEN.EXE` payload contains only what the quote needs: the four quote
card entries, compiled positioned ink, and three measured zoom levels instead of
the full ladder. Two levels use the auxiliary bank below the renderer, so the
primary blob still fits below the title pack. It needs neither a glyph atlas
nor a blend table. Its additive arithmetic retains floor rounding. The residual zoom error is covered by padding
the band by the residual measured shift, so the burned Japanese text stays
painted over at both ends of the fade. Plate textures are omitted entirely:
the quote cards composite pre-scaled band patches, and OPEN.EXE has no free
window for them.

The data itself rides **at the end of each EXE file**: the resident's
`CdLoadPsExe` (decomp `src/main/psexe.c`) reads the PS-EXE header from the
file and then `exec->t_size` bytes to `exec->t_addr`. Each blob is assembled
at `0x80160000` and `t_size` (file offset 0x1C) covers the padded gap, so the
*loader itself* drops the payload straight into its final home - no copy step.
The files just gain zero padding up to the blob (fine: the disc has headroom,
and the padding lands on buffer space the game only starts using later, then
re-initialises).

That was not the first design. Originally the blob sat at `0x800A9800` (`g_vlc_buf0`'s head) and a small init stub at `0x800A92C0` copied it to
`0x80160000` once, at `main` entry. Both of those addresses are *inside the
player's own buffers*: the first frame's decode destroyed the stub and its
source, so the **second** play of any movie jumped into MDEC pixel garbage
(`jal` to `0x800B3780` returns decoded RGB as instructions -> CPU exception ->
the BIOS hangs in `printf`). Attract-mode replay of the opening froze exactly
that way. Loading at the home address removes the stub, the copy, and the
whole class of bug.

Memory plan:

- `0x80160000..` - MOVIE.EXE's loaded blob: renderer code (assembled for this
  address), glyph atlas, per-movie entry lists, the replace patch + fade
  tables, compiled additive ink and one 64K paste table. It runs below `0x801E0000`,
  deliberately overlapping the `0x80180000`/`0x80190000`/`0x801B8000`
  staging ranges (all stale during playback and re-staged after every
  movie); the hard stop is `FONT_DEST` at `0x801E0000`, and `fmv_subgen`
  asserts the blob stays below it.
- `0x80160000..0x80180000` - OPEN.EXE's reduced blob: the same renderer and
  quote-card data, three zoom levels (two in the auxiliary bank), compiled ink,
  and no glyph atlas or blend table. `OPEN.BIN` is already sitting at
  `0x80180000` when OPEN.EXE starts, so this payload must end below it;
  `fmv_subgen` asserts its end against `OPEN_BLOB_END`.
- `0x80128000..0x8012FFFF` - eight compiled-ink expression lookups, each
  1024 four-byte results. This is above both movie drivers' CD ring buffers.
  The largest current dictionary has 593 expressions; the builder rejects
  an overflow rather than truncating text or corrupting another bank.
  `0x8013FF00..0x8013FF7F` holds eight `{program, alpha, mode, spans}` keys.
  An entry transition invalidates all keys; replay reloads the renderer state.
  No unused raw plate textures are staged over this window.
- `0x80130000..0x8013FEFF` - OPEN's auxiliary zoom bank. The PS-EXE loader
  places `build/movie_subs_open_zoom.bin` here, below both the cache metadata
  and the blend scratch. It contains two raw measured zoom levels (63,608
  bytes of the 65,280-byte window with current data). It does not overlap
  the decoder, ink lookups, scratch band, primary blob or `OPEN.BIN`.
- `0x80140000..0x801400FF` - the patch's 256-entry channel-scale LUT;
  `0x80140100..0x8014015F` - the
  24-entry glyph-row base table; `0x80140640..` - the frame band (24bpp rows,
  `band_rows * band_w * 3` bytes plus padding, asserted under 0x1F9C0 so it ends before
  the blob at `0x80160000`; all of it is stale scratch during playback).
  Each entry carries its own band geometry - the rows/cols it paints; x0 is
  even so the GPU rect is halfword aligned, and a full-band patch's width
  is a multiple of 4 so every band row starts on a word.
- `0x1F800000..0x1F8003FF` - the CPU's 1 KB data scratchpad: the patch
  palette scaled for this frame (256 x RGB0), then, once the patch is
  painted, each additive line's 256-byte coverage ramp. Neither driver nor
  the resident executable touches the scratchpad.
- Per-entry state `S_*` sits at `0x80161F00..0x80161F97`
  (frame/movie/buffy/tail/store/load/dsync/stride/xoff/band, then the
  true stream frame, the composite cache key and this frame's level/pan/
  alphas); vram carries the composite cache at `(512, 256)` and the plate
  at `(480, 0)`, both band-sized.

## 3. Renderer

The band is composited with a CPU blend - `StoreImage` the band rows of the
just-filled frame, blend on the CPU, `LoadImage` the band back (a few ms of
CPU and the band's worth of VRAM DMA per subtitled frame at 15 fps; only
active while a subtitle is on screen). GPU drawing is not usable in 24 bpp
mode (15-bit halfwords), and opaque subtitle boxes were rejected to keep the
current look (white text, black outline, no box).

### Use idle CD waits without changing synchronization

Both players call `StGetNext` while waiting for the following frame. Their
wrappers call the original SDK function first and preserve its return values,
argument pointers, callee-saved registers and argument-home stack space. If
the next frame is ready, they return immediately so the stock decoder is not
delayed. If the poll fails and `g_dec.done` is already set, the current frame
is complete and can be composited during that otherwise idle wait.

The early renderer reads but never clears `dec.done`; the original `StrSync`
remains responsible for consuming it. Existing GPU barriers still wait for
the final slice transfer. An early call returns directly, without PadRead or
VSync. A per-frame flag makes the regular frame hook skip only the duplicate
composite, then publish the next true frame and call its original PadRead or
VSync exactly once. True stream indices are latched before the next header
can replace them, including when CD frames are dropped. No clocks, stream
mode, fade values, display swaps or authored timings are changed.

The user-tested scheduling optimization does not demonstrate an FPS gain. The
assembled-code tests exercise ready/waiting polls, finished/unfinished MDEC,
duplicate prevention, SDK stack/result preservation and frame advancement in
both drivers. The local GPU-transfer simulator produces identical normal
and idle-render images for the moon, black cards, speech and an ending poem.

Speed is the whole ballgame here: at 15 fps there are 66 ms per frame and a
naive per-pixel blend cost ~42 instructions per *cell* pixel, which dropped the
opening to 8-9 fps and could wedge the stream. The loop therefore (a) walks
only each glyph's baked ink spans instead of its cell (the cell is mostly air),
(b) drops transparent pixels on a single compare, (c) stores fully covered
runs straight once the line is near-opaque, with no blend lookups, and (d)
reads `coverage*alpha>>8` from a selected 256-byte ramp table
instead of multiplying per pixel. The old three `mult`s per paste pixel are
gone: a 64K table `T[eff][v] = v*eff>>8` (built at pack time, pointed to by
`H_TAB`) makes the paste four byte lookups, and the per-glyph-row band base
is built once per line in `ROW_TAB`. Additive entries use compiled positioned
ink instead of the glyph walker; they need no 64K additive table.

The coverage ramp is selected directly from `H_TAB[alpha*256]`: those
256 bytes already contain exactly `coverage*alpha>>8`, so there is no
per-line table construction. Zero-alpha lines skip the glyph walk entirely.

### Compiled additive ink

`src/injection_tools/fmv_ink.py` positions the unchanged glyph pixels at
build time. Each pixel references an interned expression: the positive
`(gray, coverage)` contributions of all glyphs covering it, in source draw
order. At runtime each distinct expression is evaluated once at the current
line alpha; positioned spans then use its result. This preserves coverage
rounding, overhanging glyphs and saturated addition exactly. Full MOVIE uses
round-to-nearest; OPEN retains its floor rounding. Entry flag `0x20` selects
compiled ink and `0x40` selects floor rounding. A line's last record byte
marks overlap with earlier lines, preventing a black-background overwrite
from losing earlier ink.

Each line's lookup is cached by program, exact alpha and blend mode. A fade
of one line does not force the other lines' expressions to be evaluated
again. No alpha steps or video frames are held or discarded for this cache.
There are at most eight lines and 1024 expressions per line; the builder
enforces both limits. The blob starts with the expression count and 256
u16 peak-contribution bounds, followed by expressions and aligned positioned
row spans. Blank pixels and zero-gray outlines have no additive work.

The patch header carries the maximum unscaled palette channel after its
six-byte probe header. Non-zoom patches start their rows at byte 776;
zoom patches put a u16 level count, u16 reserved field and absolute u32
level pointers there (the first pointer is at byte 780). The scale LUT turns this
into a conservative background headroom. If a line's precomputed peak at its
current alpha fits that headroom, all three RGB channels can be added in one
packed word with no inter-channel carry. Overlapping lines and any unproved
case retain separate saturated channel adds. Black cards write the final
gray directly. Clearing their scratch bands uses bounded 64-byte blocks
with a 16-byte tail; pixels, wording and fades do not change.

### Two entry kinds, one format

Speech subtitles draw over the live frame: the band is the lines' rows and the
text pastes in with a short ramp (`fade_shift`, 2-3 frames). Nothing else
happens - the frame is correct everywhere, only the text is added.

The three movies with **burned-in** text (the opening quote `MV1C`, the ending
poems `MV1E`/`MV25`) cannot show the live frame at all - the Japanese text is
part of the picture. Their entries composite two things instead, and the
English text then draws over it as one thing (no separate darkening pass, so
the text cannot pick up a wrong darkening):

1. a **patch**: the picture's own pixels where the original text sits, taken
   offline from the movie's clean frame and stored pre-darkened to the level
   of the entry's plateau. Painting it over the stream frame replaces the
   baked text with its own background. Every frame's real fade is reproduced
   by one 8.8 scale factor applied to the patch (`256` = straight copy at the
   plateau, so the flat phase costs a copy and only the ramps multiply).
2. the English text, with per-frame measured alpha.

Blend: intro (additive ink over the darkened picture - the original's
black-card layer) `out = CLAMP[bg + rounded(ink*eff/256)]`; poems/speech (paste)
`out = bg + T[eff][ink] - T[eff][bg]`. The quote's ink alpha is capped at the
picture's scale at build time, so the additive blend can never wrap past
white. The paste's split table is `eff = cov*alpha>>8`; at full coverage the
renderer's solid path writes `ink` directly, so white fill stays white and the
black outline stays black instead of losing the last LSB to the table floor.

### The composite cache, and what the GPU does

What lands in the band is a pure function of the frame's state - the entry,
the picture's measured scale, the zoom level and pan, and every line's alpha -
so the composited band is kept in vram at `(CACHE_X, CACHE_Y)` and every frame
in the same state is **one vram->vram copy**: the CPU only runs the
strip probe and cache bookkeeping. The key carries the *measured* scale
(the old gate only cached at exactly 0 or 256, which the live probe never
reports - it settles on 253 or 247 - so the cache never hit and every frame
paid the full composite), and the zoom level and pan, which are what the
patch rows hang off. Entries over the live frame are never cached - their
background is the movie's, not ours.

A frame whose state *did* change rebuilds the composite, and the plate - the
patch painted at the frame's scale - keeps its own rectangle at
`(PLATE_X, PLATE_Y)`: when only the text alphas moved (the fades), the plate
comes back with one `StoreImage` instead of being walked out of the palette
again. Only a change of entry, scale, level or pan repaints it. A black card
needs no plate at all - the full-frame black quad above already painted it,
so the band is cleared and the text blended over black.

The scale in that key comes from the live strip probe, not from the
stream-index table: the CD decoder can run a few frames ahead of the picture.
The probe value is held at the previous frame's only while it stays within
`2/256` - that is its noise floor on a still picture. A fade step is larger
(the opening quote's moon ramp moves about `8/256` per frame), so a real fade
rebuilds every frame. Holding through a fade used to leave the plate up to
two frames behind the live picture, measured at ~11% dark over the opening
quote - a visible rectangle even though the probe itself was exact.

Text opacity and zoom levels take their measured value on **every stream
frame**. Neither is held to manufacture cache hits; the composite cache
only reuses an actually identical state. The picture probe retains its
two-level noise tolerance described above.

The background expansion reads each scaled palette colour as one packed
RGB word from the scratchpad, so its four palette reads per source word
cost no main-RAM bus cycles. The source word carries four indices. On a
word-aligned cursor (every full-band row) four 3-byte pixels are exactly
three words: they are assembled in registers from the entries (whose
fourth byte is 0) and stored whole - three stores instead of eight
partial ones, nothing past the run touched. Any other cursor uses
overlapping `SWL`/`SWR` pairs and saves and restores the byte just past
the run. Patch index runs are word-aligned and padded at both ends; the
`FMS4` payload format also pads zoom-level terminators to a whole word.
A 320-pixel aligned run takes 80 source-word loads plus metadata from
main RAM.

The additive ink's expression terms read `cov*alpha>>8` from the line's
coverage ramp, built in the scratchpad by adding alpha 256 times, instead
of multiplying per term; the remaining multiply by the glyph gray keeps
both rounding modes exact.

The fade probe also reads aligned words. Four words are summed into two
independent 16-bit lanes, with at most 128 words per accumulator. Each lane
is bounded by 65280, so no carry can cross between lanes. The lanes are
then added to the full sum; byte prefixes and tails preserve arbitrary
source alignment and length. Every probe pixel is still sampled, with the
same integer mean and resulting measured fade as the byte-by-byte loop.

### Uniform zoom in the opening driver

All zoom levels use the same affine scale in X and Y about the frame centre.
The extracted zoom is one similarity fit per frame on a 2 per mille grid,
with a few per mille of noise around the movie's steady ramp (about -1 per
mille per frame over the moon fade). The builder follows one least-squares
line through those measurements, weighted by the picture's brightness and
held at the measured window's ends; picking the nearest level of each raw
measurement flipped frames between two levels and back, which showed as
the band popping.

The levels cover the fitted range. No frame is further from its level than
a uniform ladder's half step, and within that bound they sit where the
brightness-weighted worst mismatch is smallest, since a rectangle edge
shows in proportion to the picture under it. The level nearest the plate's
own size moves to exactly 1000 when that keeps every frame inside the
bound (a 1:1 crop needs no resampling). OPEN keeps three levels; with the
current measurements they are 1000, 1008.5 and 1020.8 per mille, used in
one run each across the fade. The band margin is derived from the largest
residual between each raw measurement and its selected level.

The builder places independent raw level streams in the auxiliary bank and
primary blob and emits their absolute pointers. The renderer picks one
pointer; it neither decompresses nor rescales a pixel during playback.
MOVIE uses the same fitted placement with its larger ladder. Bank/ink limits
are enforced at build time and the verifier reads all sources back from the
disc, including the extra OPEN bank. The user reports the latest fade looks
somewhat better but still has glitches, with the same approximately 12 FPS
minimum. The geometry correction is QA-tested; a fully correct fade or
sustained native 15 FPS is not claimed.

`tools/tests/test_fmv_renderer.py` executes the assembled loops with
R3000 load and branch delays, checks every destination alignment and run
tails against exact RGB bytes, and checks small opacity steps in both
directions. It also checks compiled ink against scalar reference pixels in
both rounding modes, cached and uncached draws, overhanging glyphs, black
and coloured backgrounds, carry-free adds and saturation fallbacks. Probe
sums cover alignment, tails, the 512-byte accumulator boundary and all-white
inputs; padded patch tests cover multiple runs, odd lengths and panned rows
clipped at both band edges.

For the committed `78410bf` word-load/probe renderer, the local MIPS/GPU-transfer
simulator's opening stream frame 470 takes 433,918 instructions and 76,761 RAM loads
versus the confirmed `5d81310` build's 440,173 instructions and 100,713
loads. OPEN's reduced payload takes 454,340 instructions and 80,053 loads
versus 460,328 instructions and 105,985 loads. Thus the moon-frame sample
eliminates about 24% of all renderer RAM loads. Both rendered images are
byte-identical to the confirmed build, as are a black-card frame and an
ending-poem frame. Every stored patch palette, row and zoom level also
decodes identically; only padding and access granularity change. These are
instruction/load profiles, **not** cycle-accurate or in-game FPS measurements.

For the scratchpad palette, whole-word patch stores and coverage ramps,
OPEN's stream frame 470 in the same simulator takes 468,487 instructions,
48,405 main-RAM loads and 38,799 stores, versus 449,090, 79,251 and 78,089
before: 4% more instructions, 39% fewer RAM loads, half the stores. The
patch and ink tests still pass byte-exact. This too is a load/store
profile, not an in-game FPS measurement.

In-game evidence for `5d81310`: the user reports the moon transition's minimum
improving from about 8 FPS to 12 FPS. Some opening-start hiccups remain.
For `78410bf`, the user confirms identical
appearance but the same approximately 12 FPS minimum: its reduced RAM-load
count does not demonstrate an in-game FPS improvement. The user reports CPU
overclocking resolves the transition slowdown. Sustained 15 FPS at stock
CPU speed is not yet demonstrated; stock-speed performance remains distinct
from the optional 60 FPS/overclocked configuration.

Latest in-game evidence, including the uniform-zoom and idle-poll changes:
the user still observes approximately 12 FPS at worst and remaining fade
glitches, with some visual improvement. This is the accepted checkpoint,
not a completed fade fix or a native 15 FPS result.

GPU drawing still cannot produce 24 bpp colors (its primitives write 15-bit
halfwords that the display would read as packed 24-bit bytes), so the *pixel
values* of the plate and the text are always CPU work; what the GPU does is
carry finished bands around (the cache copy, the plate rectangle, the black
quad).

### Where the timing/picture data comes from

`src/extraction_tools/fmv_frames.py measure` decodes the movies (ffmpeg -
extraction only, never needed to build) and measures, per movie, into
`src/assets/fmv/`:

- `<MV>.png` - the clean plate frame (full frame; cropping is a build concern
  because the build knows the new text's size),
- `<MV>.timing.tsv` - per frame: the dark filter's opacity and one text alpha
  per band (the quote's cards fade per line, the poems as one block),
- `<MV>.patch.bin` - the pixels the burned-in text touches, as binary row
  runs, tagged per band (the quote's cards share rows and must not
  cross-contaminate).

The curves were validated frame-for-frame against the original's behaviour
(MV1C: black card to 459, a linear 460-489 moon fade; MV1E: text 47-70 in,
205-228 out with the filter; MV25: 24-46 in, 167-188 out). Layout (cards,
bands, pins, poem rects) lives in `src/injection_tools/fmv_layout.py`; the
wording comes from `translation/generated/fmv/opening.tsv` and
`translation/manual/fmv/poems.tsv` verbatim (the poem's lines are re-flowed to
this font's width - wording untouched).

### Glyph data

- Glyph atlas (speech/paste entries): 95 printable ASCII glyphs rendered at build time with the same
  pipeline the burned text used (`PublicSans-Medium.ttf`, 3x supersample +
  LANCZOS downscale, white text over a dilated black outline), packed as
  per-glyph row spans - `(y, nruns, then (x0, len, len x (gray, cov)) per
  run, 0xFF ends the glyph)` - so the renderer only touches ink pixels.
  Exact same look as the burned version, including antialiasing.
- Text + timing: per movie, a list of entries `(start_frame, end_frame,
  nlines, flags, band geometry, patch/scale/alpha pointers, lines)`. Frames
  are 0-based 15 fps stream frames; the hook compares against
  `g_movie_frame - 1` (the counter is 1-based after the loop's increment).

### Build asserts

`fmv_subgen.py` refuses to assemble a band whose bytes exceed the scratch
window (0x1F9C0), refuses a full MOVIE.EXE blob that would reach
`FONT_DEST` (`0x801E0000`), and refuses an OPEN.EXE blob that would reach
`OPEN.BIN` at `0x80180000`; line widths are checked against the frame with a
4px margin. The OPEN build also asserts that no plate texture was requested.

## 4. Hooks and loading

1. `0x80080FBC` `jal PadRead(1)` in the frame loop -> `jal 0x80160000` (frame
   entry). The delay slot still sets `a0 = 1`; the frame routine ends with
   `j PadRead`, so the loop is unchanged. Drawn target is
   `g_dec.rect[1 - g_dec.rect_id]` (the frame `StrSync` just completed).
    OPEN.EXE gets the same treatment at `0x80088F90` (`VSync(0)` -> `jal
   0x80160008`, the renderer tail-jumps to `VSync`).
2. PS-EXE header `t_size` (`0x8007F81C`) extended to `0xE0000 + blob`, so the
   loader lands the blob at `0x80160000`. MOVIE.EXE carries the full blob;
   OPEN.EXE carries the reduced one and its header therefore stays below
   `0x80180000`, leaving the title pack
   intact. `CdReadPolled` reads whole sectors, so the generator also checks
   the sector-rounded image against `0x80180000`.
3. The two `StGetNext` call sites are wrapped: MOVIE `0x80081374` ->
   `0x80160010`, OPEN `0x800893BC` -> `0x80160018`. Their argument delay
   instructions are unchanged. The wrappers call the original SDK functions
   at `0x80089ED0` and `0x80092850` respectively; only a failed poll with a
   finished current frame permits early compositing.

## 5. Phases

1. **This**: hooks + renderer + generator (`fmv_subgen.py`); all three
   text movies (quote cards + both poems) render in-engine with the measured
   fades, speech subs from `translation/manual/fmv/subtitles.tsv`. No
   external tool is needed to build - Java/jPSXdec burning is gone.
2. QA each movie in-game (timings against the original, transparency through
   the fades, legibility over bright scenes); fixes land as general rules,
   not per-row edits.
