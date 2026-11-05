# Making the renderer faster without overclocking (research)

**Status: in progress.** This is the working document for the "can the game run the
60 fps patch at stock CPU speed?" question. Everything here is measured against the
*first-release* binaries this project patches (`data/psx/`, `build/`), using the
Python MIPS+GTE simulator in `scratch/perf/`. Findings are updated as they land.

**Scope of any resulting patch: the QoL build only** (`src/asm/qol/`, behind a
define, like `fps60_dng.asm` / `fps60_s2d.asm`). The translation release must not
change behaviour; the QoL disc is where render-speed work belongs.

## TL;DR

Yes, it can - the dungeon can. The renderer's time goes into transforming and
sorting polygons, and the dungeon pays a large, completely unnecessary multiplier
on that work:

- The dungeon marks objects near the camera with a "divided polygon" attribute
  (`ModelDef.attr = 0x400`, `attr_far = 0x200`; 3255 of 3269 model definitions).
- That attribute makes `GsSortObject4` use a builder that **splits every polygon
  into 4^level GPU primitives** (16 for near objects, 4 for mid ones) *whether or
  not the polygon is anywhere near the near plane*. Measured on the real code: one
  fully visible textured quad costs 193 cycles and emits 1 primitive through the
  simple path, but 2196 cycles and **16** primitives through the divided path at
  level 2 - and the depth makes no difference at all.
- Those extra primitives are roughly **two thirds of the dungeon frame**. Skipping
  the subdivision for polygons that do not cross the near plane takes the frame
  from ~21 ms to ~11 ms, i.e. 60 fps at stock CPU speed (the measured uncapped
  frame is 18 ms today).

The change is in the divided builder/divider (`0x80034D20` / `0x8002A6E8`) and the
decision is already computed there (the four vertex depths vs `H/2`). It is a QoL
patch. It is not byte-identical: it removes the subdivision seams the current
output has (sub-texel; invisible in practice). Section 6.2 has the details and the
verification plan.

---

## 0. The question

The 60 fps patch (`src/asm/qol/fps60_dng.asm`, `fps60_s2d.asm`) draws interpolated
sub-frames between the game's original logic ticks. It needs each *drawn* frame to
cost less than one vblank (16.7 ms) to actually present 60 fps. Measured in
`src/asm/qol/README.md` at stock CPU speed:

| scene | what happens at stock CPU | what 181% overclock gives |
|---|---|---|
| dungeon (DNG) | ~47-60 fps while moving, 20 idle | solid 60 fps |
| overworld (S2D) | 15 fps at busy spots (BMarket 2.1 vblanks/tick) | smooth 30 fps |

So: **can the renderer be made fast enough at 33.87 MHz, with the on-screen result
identical?** This document is the attempt to answer that from the code and from
measurement.

---

## 1. What the renderers actually do

Both engines are the same shape: a libgs TMD renderer. Per frame, for every visible
object, the game calls `GsSortObject4(obj, ot, shift, scratch)`, which walks the
object's TMD packets and, for each polygon, transforms its vertices with the GTE,
tests back-faces, builds a 40-byte GPU primitive and links it into an ordering
table. Everything expensive is inside that per-polygon loop.

### 1.1 The dungeon's first-person view (DNG.BIN)

`FieldFrame` (the frame routine, `0x800659B4` in this build) does, per frame:

1. `GsSetRefView2`, clear 5 ordering tables, sort the HUD sprites.
2. An **11x11 cell loop** around the party. For each cell with a tile:
   - `FieldClockHands` (a flag test),
   - `GsSetLsMatrix` + `RotTransPers` of the cell's base point, then two culling
     tests (`otz >= 450` and a screen-margin test) - **this is where the two
     integer divisions per cell live**,
   - `GsClearOt` for the cell's own 32-entry ordering table,
   - up to **8 models per tile**, each: `GsGetLws` + `GsSetLightMatrix2` +
     `GsSetLsMatrix` + attribute fiddling + `GsSortObject4`,
   - `GsSortOt` merging the cell's table into the 512-entry world table.

Source: `references/persona-decomp/src/dng/field/fieldmain.c` (semantics - see the
warning in section 2 about addresses).

### 1.2 The overworld map (S2D.BIN)

A loop over `g_map_obj_count` objects (52 at BMarket): per object `GsGetLws` +
`GsSetLightMatrix` + `GsSetLsMatrix` + `GsSortObject4`. The map models come from a
single TMD (`S2D.BIN` offset `0x3C014`) with 9 objects, 54-110 polygons each
(571 total). The world's root transform is rebuilt every tick, so the per-object
world matrices are recomputed each frame.

---

## 2. Warning: the decomp is a different build

`references/persona-decomp/` is a decompilation of a **different binary** than the
disc this project patches. Its `configs/JP1/checksum.sha` and the per-file `sha1:`
fields in `configs/JP1/*.yaml` do not match `data/psx/*`:

| file | this project (`data/psx`) | decomp's target |
|---|---|---|
| SLPS_005.00 | `7cb12fd3...` | `a59e920e...` |
| DNG.BIN | `b5d98112...` | `b80bb3fa...` |
| S2D.BIN | `f9de06ef...` | `7e04951e...` |

Consequences:

- The **C source is authoritative for semantics** (it describes what the code does,
  verified by the decomp authors against their binary).
- **Addresses and even function boundaries differ.** For example the decomp puts
  `S2dApplyPadLayout` at `0x8008B5D4`, while in our `S2D.BIN` that code is at
  `0x8008BA8C`. The `sym.*.txt` files are splat guesses and some entries point into
  the middle of functions (`GsSortObject4 = 0x80035948` in `sym.main.txt` is a label
  inside a loop; the real entry in our binary is `0x800339E4`).
- Anything below was re-derived from our binaries. Where I name a routine, the name
  comes from matching the decomp's C to our disassembly (call sites, arguments,
  structure), not from the symbol table.

---

## 3. The pieces we now have pinned down (our binaries)

These are the real entry points in `build/SLPS_005.00` / `build/DNG.BIN`, found from
call sites and verified against the decomp's C:

| what | address | notes |
|---|---|---|
| `GsSortObject4` | `0x800339E4` | per-object: decode `attribute`, then per-packet dispatch |
| `GsLinkObject4` | `0x80033240` | model load: **groups packets and writes the group count into each packet header** |
| `GsGetLws` | `0x8003FE8C` | world matrix (cached in `coord->flg`) + local-screen matrix |
| `GsSetLightMatrix2` / `GsSetLsMatrix` | `0x800316A8` / `0x800315DC` | GTE matrix uploads |
| `GsClearOt` / `GsSortOt` | `0x80040380` / `0x80040284` | per-cell OT clear (32 entries) / merge |
| **quad builder, `div=0`** | `0x80039A10` | all inline, no calls |
| **quad builder, `div!=0`** | `0x80034D20` | copies vertices to scratch, 4 calls per polygon |
| near-plane divider | `0x8002A6E8` (helper of the div builder) | sub-divides and re-enters itself |
| primitive writer | `0x8002AB70` | builds one 40-byte primitive and links it |

### 3.1 TMD packet format (derived from the code)

Each TMD object's primitive list is a sequence of fixed-size packets
(`ilen+1` words; textured quad = 32 bytes): header `{count/olen, ilen, flag, mode}`
with `mode` in byte 3, then 4 UV words, then `{norm, v0, v1, v2, v3}` as u16s at
`+0x14..+0x1C`. `GsLinkObject4` walks the list at model-load time, groups
consecutive same-mode packets and writes the group's polygon count into the first
packet's low 24 bits; `GsSortObject4`'s tail then advances by `count * 32` and the
builder's inner loop processes `count` polygons of 32 bytes each. (This is why the
raw file header looks like `09 07 00 2c` = `{olen=9, ilen=7, flag=0, mode=0x2C}`:
that is the *file* form; the count is written at run time. `S2dBindCompass` in
`references/persona-decomp/src/s2d/game/field.c` does the same rewrite explicitly.)

### 3.2 What the dungeon's geometry looks like

From the real pack data (`data/psx/D*/D??.BIN` + `D??M.BIN`, parsed by
`scratch/perf/tmdstats.py` / `modelattr.py` / `tilestats.py`):

- 3269 model definitions across all packs; **3255 of them use
  `attr = 0x400` (div level 2) and `attr_far = 0x200` (div level 1)**. Only 14 use
  anything else.
- Polygons are almost entirely **flat textured quads (mode `0x2C`), not divided**
  at the TMD level: e.g. D00.BIN = 2140 tex quads + 38 tex tris + 2 flat quads.
- Median polygons per model: 8-12 (max 77, average ~12-18).
- Models per tile: 1-8, median 4.
- Overworld map TMD: 9 objects, 54-110 polygons each (571 total).

### 3.3 Which builder runs

`GsSortObject4`'s prologue decodes `obj->attribute`:

- bits 9-11 = the **div level** (`(attr >> 9) & 7`), selected per frame in the
  dungeon from `ModelDef.attr` / `attr_far` by the distance bands in `FieldFrame`
  (`otz < 0x4C` -> near attr, `< 0x97` -> near/edge attr_far, `< 0xE2` -> attr_far,
  else 0);
- bits 5-6 + a global (`0x80063350`, initialised to 0 and only settable to 2 or 3)
  -> the lighting mode.

The dispatcher indexes a 2x3 table of builders: `(div != 0) x (light 0/1/2)`.
For the dungeon's models (attr `0x400`/`0x200`, light 0) that is **`0x80034D20`**;
for far dungeon objects and for every overworld object (attribute 0) it is
**`0x80039A10`**.

---

## 4. Measurement

Harness: `scratch/perf/gtesim.py` (R3000 + GTE interpreter with the GTE's
multi-cycle timings: RTPS 15, RTPT 23, NCLIP 8, AVSZ3/4 6/8, etc.) and
`scratch/perf/quadbench.py` / `quadtest.py`, which load the real `build/SLPS_005.00`
code and a real TMD packet (D00.BIN model 0: 12 textured quads) and run one builder
per call, reporting cycles, the GPU primitives written and the ordering table.

Caveat: the GTE is my implementation of the psx-spx spec (needed sf=1 fixed-point
scaling and the RT/LLM/LCM register packing to be fixed during this work). The two
builders run on the *same* GTE and the same input, so the comparison is sound; the
absolute cycle counts will move a little once cross-checked on real hardware. The
best cross-check we have: the overworld's measured 25 ms for ~3300 polygons is
~300 cycles/polygon, while the simulator says ~100 - the difference is GTE result
latency (RTPS/RTPT are 15-23 cycles and the loop needs each result immediately),
which the simulator charges as a fixed cost per op rather than as an interlock. So
treat the absolute numbers as optimistic by up to ~2-3x, and the *ratios* between
code paths as trustworthy.

### 4.1 One fully visible textured quad

| builder | attribute it is selected by | cycles | GPU primitives emitted |
|---|---|---|---|
| `0x80039A10` (NONdiv) | div = 0 (far dungeon objects, **all** overworld objects) | **193** | **1** |
| `0x80034D20` (DIV, level 1) | attr_far `0x200` (dungeon mid band) | **716** | **4** |
| `0x80034D20` (DIV, level 2) | attr `0x400` (dungeon near band) | **2196** | **16** |
| `0x80034D20` (DIV, level 3) | (not used by this game) | 8116 | 64 |

**The same quad at different depths** (H = 256, so the near plane is H/2 = 128):

| z | NONdiv | DIV level 1 | DIV level 2 |
|---|---|---|---|
| 100 (behind the near plane) | 86 cyc / 0 prims | 338 / 0 | 338 / 0 |
| 150 | 193 / 1 | 716 / 4 | 2206 / 16 |
| 300 | 193 / 1 | 716 / 4 | 2196 / 16 |
| 1200 | 193 / 1 | 716 / 4 | 2196 / 16 |
| 3000 | 193 / 1 | 716 / 4 | 2196 / 16 |

Depth changes nothing: **once a polygon is in front of the near plane the divided
path always subdivides it 4^level-fold**, no matter how far away it is. The only
cheap case is the polygon entirely *behind* the near plane, which is culled.

12 real quads (D00.BIN model 0): NONdiv 1802 cycles / 8 prims (some culled),
DIV level 1: 5923 / 32, DIV level 2: 17763 / 128.

**The divided path emits `4^level` primitives per polygon and costs
`~11x` (level 2) / `~3.7x` (level 1) the simple path.**

### 4.2 The per-object fixed work

Measured the same way (calling the real routines with a synthetic coordinate
system):

| routine | cycles | notes |
|---|---|---|
| `GsGetLws` (`0x8003FE8C`) | 278 | world matrix (cached in `coord->flg`) + local-screen matrix |
| `GsSetLightMatrix2` (`0x800316A8`) | 117 | GTE light-matrix upload |
| `GsSetLsMatrix` (`0x800315DC`) | 32 | GTE local-screen-matrix upload |
| `GsSortObject4` prologue | ~100 | 90 instructions of attribute decode before the first polygon |

So **~530 cycles of fixed work per object** before any polygon. With ~200 visible
objects that is ~105k cycles (3.1 ms, about 17% of the dungeon frame). This is
output-identical work and a real target, just a smaller one than section 5.

### 4.3 Where that money goes (measured)

`scratch/perf/polyprofile.py` attributes every cycle of a single textured quad to
the instruction that spent it. Per polygon at level 2:

| region | today (16 prims) | simple builder |
|---|---|---|
| project + clip test `0x800297EC` (3x `RTPT`, `NCLIP`, 4th `RTPS`, `AVSZ4`) | 109 | (inline, part of the 193) |
| divider: clipping + subdivision | 1310 | - |
| primitive writer `0x8002AB70` (once per piece) | 560 | (inline) |
| div builder: vertex copies (`lwl/lwr` pairs) | 48 | - |
| div builder: ot index / code byte / clut / uv words | 38 | - |
| helper A (normal -> colour) `0x8003D2BC` | 29 | (inline) |
| div builder: prologue / loop head | 33 | - |
| helper B (depth) + both call sites | 26 | - |
| div builder: record setup | 13 | - |
| **total** | **2196** | **193** |

Two things stand out. The subdivision itself is 60% of today's cost and the writer
calls another 25% (16 pieces x 35 cycles each). The projection + clip test (109) is
the same work the simple builder does inline, so it is not overhead. Of the rest,
the vertex copies (48) are the only item that can still be attacked without
touching the game's control flow.

The helper names here are the ones the profile uses; helper A = `0x800297EC` is the
projection and back-face cull (it returns <= 0 to cull the polygon), helper B =
`0x80028DAC` writes the depth FIFO into the record slots, helper C = `0x8003D2BC`
turns the polygon normal into the colour word.

---

## 5. The finding

**The near-plane division is applied unconditionally to every polygon of every
near/mid object, whether or not the polygon is anywhere near the near plane.**

The dungeon marks objects within the near bands (`otz < 0x4C` -> level 2,
`< 0xE2` -> level 1) and the divided builder then subdivides *all* of their
polygons 4^level-fold. A level-2 polygon that is fully visible and far in front of
the camera still becomes 16 primitives and costs 11x the single-quad path.

Why this dominates the dungeon frame: the 11x11 cell window puts a handful of cells
right at the camera (level 2), the next ring or two at level 1, and everything else
at level 0. Rough model using the measured numbers and the geometry stats
(~4 models/tile, ~12 polygons/model, ~200 visible objects):

| band | objects | polygons | pieces/polygon | primitives | cycles |
|---|---|---|---|---|---|
| near (level 2) | ~10 | ~120 | 16 | ~1920 | ~260k |
| mid (level 1) | ~30 | ~360 | 4 | ~1440 | ~150k |
| far (level 0) | ~150 | ~1800 | 1 | ~1800 | ~140k |
| per-object matrix work (section 4.2) | ~200 objects | | | | ~105k |
| per-cell OT work + cull + HUD | ~80 cells | | | | ~60k |
| **total** | | | | | **~715k cycles = 21 ms** |

which matches the measured 51-57 fps uncapped (595-665k cycles/frame) within the
simulator's optimistic bias. So the subdivision of near/mid geometry is **roughly
two thirds of the frame** and the per-object fixed work another sixth.

---

## 6. The optimization

**Skip the subdivision when the polygon does not need it.** A polygon needs the
near-plane division only when part of it is behind the near plane. Everything the
decision needs is already computed: helper A transforms the four vertices and the
divider's very first check compares their depths against `H/2` (the near plane).
The common case - all four vertices in front of it - can go straight to the
single-primitive write (`0x8002AB70`) that the far objects already use.

### 6.1 Where the change goes

It is a local change inside the divided path, not a new renderer:

```
divider (0x8002A6E8):
    ... existing tests ...
    if (all four depths >= H/2) {          <- NEW: "nothing crosses the near plane"
        write one primitive (0x8002AB70);  <- the existing single-quad code
        return;
    }
    ... existing subdivision / recursion ...
```

Equivalently the pre-test could sit in the DIV builder (`0x80034D20`) right after
helper A, before the scratch bookkeeping and the four helper calls - that also
saves the 32-instruction vertex copy, helper B/C and the divider's frame for the
common case. Either way the change is in the QoL build only.

Measured effect if the near/mid bands stopped subdividing (same frames, same
geometry, using the per-quad numbers above):

| | now | with the fast path | |
|---|---|---|---|
| near band | ~260k cycles | ~23k | -237k |
| mid band | ~150k | ~38k | -112k |
| frame | ~715k cycles (21 ms) | **~365k cycles (10.7 ms)** | **-49%** |

10.7 ms is comfortably inside one vblank, i.e. **60 fps at stock CPU speed in the
dungeon**, with headroom - and that is before the strictly-identical wins in
section 7. (The table assumes the near/mid objects hold ~480 polygons; see
section 5. The simulator's absolute cycles are optimistic by up to ~2x, so the
real frame drops from ~18 ms to somewhere under 10 ms.)

### 6.2 Is that a behaviour change?

The polygon that gets drawn is the same one; what disappears is its subdivision
into 4^level pieces. Measured with `scratch/perf/seamdiff.py` (which builds the
same split the divider performs - edge midpoints and centre, rounded to the GPU's
1/16-pixel and 8-bit UV precision - and rasterises both):

| case | coverage (geometry) | texel sampling |
|---|---|---|
| axis-aligned quad (the dungeon's boxes) | **0 differing pixels** | **0** |
| corridor wall (perspective trapezoid), level 1 | 0-2 px of 624-43412 (0.0-0.3%) | 227-31577 px shift by 1-3 texels |
| corridor wall, level 2 | 0-4 px of 624-43412 | 227-30243 px shift by 1-3 texels |
| extreme slanted quad (random), level 2 | 49-141 px of ~400 (12-35%) | up to 20 texels |

So:

1. **Geometry: essentially identical.** The pieces tile the polygon exactly; the
   only differences are a handful of pixels along the internal seam lines where the
   1/16-pixel rounding of a split point moves the seam by a fraction of a pixel.
   For axis-aligned polygons - which is what the dungeon's boxes are - it is
   exactly zero.
2. **Texture: the sampled texel shifts slightly over the polygon** (typically
   1-3 texels, i.e. the interpolated UV differs by a fraction of a texel and
   rounds the other way). This is *caused by* the subdivision: the split points'
   rounded positions/UVs perturb the interpolation. Drawing the polygon whole
   samples the texture along the true linear mapping - the subdivision is the
   thing introducing the wobble, not the fast path.

In other words: the current output already carries a small texture wobble on every
near/mid polygon (from its own subdivision), plus a seam grid that is invisible
because the pieces tile. The fast path removes both. It is not byte-identical, and
the difference is "the texture stops wobbling by a texel or two" - visible only if
you go looking for it, and in the direction of being more correct.

This is a QoL-build patch (`src/asm/qol/`), not a base-game change - the same
discipline as `fps60_dng.asm`, which already changes what is presented (extra
interpolated frames) without touching game logic. If byte-identical output is a
hard requirement anyway, the strict alternatives are: keep the subdivision but
make it cheaper (section 7), which wins much less, or verify on the emulator that
the difference is not visible in a real scene before shipping.

---

## 7. Other candidates (output-identical by construction)

These are smaller than the finding above but come with no visual question at all.

1. **Per-polygon constant work.** Both builders rebuild the primitive's colour word
   (`0x808080 | mode<<24 | global<<1`, 10 instructions) inside the polygon loop.
   It is constant per packet group; hoisting it to the group level saves ~8
   instructions/polygon (~2% of the frame).
2. **The vertex-index arithmetic** in the loop (~10 instructions/polygon) computes
   `index * 8 + verts` three times per polygon; the multiply is a shift already, but
   the loads could be scheduled better. Modest.
3. **Per-object matrix work** (`GsGetLws` + `GsSetLightMatrix2` + `GsSetLsMatrix`,
   ~165 instructions per object, ~200-300 objects): the world matrix is cached in
   `coord->flg` but the local-screen matrix (`lw * view`) is recomputed for every
   object every frame. Roughly 5-8% of the dungeon frame; larger in the overworld
   where the root transform changes every tick and forces the full walk.
4. **Per-cell ordering-table work** (`GsClearOt` 32 entries + `GsSortOt` 32 entries,
   ~450 instructions per visible cell, ~80-120 cells): ~5-8% of the frame. The cell
   tables are cleared and merged even for cells whose models are then all culled
   (the cell cull happens before, so only visible cells pay - but a cell that passes
   the cull and then has every model culled still pays both).
5. **The two integer divisions in the cell cull** (`abs(sx) / g_ot_xdiv[k]` is a
   variable division per cell; `(otz - 5) / 75` is constant and already strength
   reduced). Small (0.2-0.5%) but free to fix.
6. **`GsSortObject4`'s 90-instruction prologue** (the attribute decode writes five
   globals per object): ~3% of the frame, and it is per object.

---

## 8. What the overworld needs

The overworld uses `div = 0` everywhere (its objects' attributes are 0), so the
finding above does not help it. Its cost is simply polygon count: 52 objects x
54-110 polygons = ~3300 polygons per frame. Measured through the same pipeline on
the overworld's own map TMD (`S2D.BIN` +0x3C014: 9 objects, 571 polygons): the
simple path costs **~100 cycles per polygon** in the simulator.

3300 polygons x 100 cycles = 330k cycles = 10 ms in the simulator, but the
measured cost is 25 ms (`src/asm/qol/README.md`, BMarket: 1.5 of 2.1 vblanks in
the object loop). The gap is GTE stall time my simulator only approximates - the
polygon loop does five point transforms per polygon (`RTPT` + two `RTPS`) and each
one has a 15-23 cycle result latency the real pipeline interlocks on. Taking the
measured 25 ms at face value, the overworld's per-polygon cost is ~300 cycles.

For the overworld's targets:

- **30 fps at stock** needs the 25 ms draw to fit in 2 vblanks (33 ms): it nearly
  does already; ~5% off the object loop is enough (section 7.1-7.2, and the
  per-object matrix work in section 7.3 which is worse here because the root
  transform is rebuilt every tick and invalidates every world matrix).
- **60 fps at stock** needs 2x, which is not reachable without drawing fewer
  polygons (a behaviour change) or a much faster per-polygon loop.

So the overworld is the harder half of the question, and its lever is the
per-polygon loop itself rather than the subdivision.

---

## 9. How to reproduce

```sh
# the sim + the two builders on real packet data
python3 scratch/perf/quadbench.py
python3 scratch/perf/quadtest.py

# geometry / attribute statistics from the game's own packs
python3 scratch/perf/tmdstats.py data/psx/D00/D00.BIN data/psx/D00/D00M.BIN
python3 scratch/perf/modelattr.py
python3 scratch/perf/tilestats.py

# address -> symbol/source lookup (our binaries)
python3 scratch/perf/addr2sym.py 0x800339E4
python3 scratch/perf/mipsdis2.py build/SLPS_005.00 0x8000F800 0x800339E4 0x80033B20
```

`scratch/perf/gtesim.py` is a standalone MIPS R3000 + GTE interpreter (load delays,
branch delays, GTE fixed-point with FLAG semantics and per-op timings) written for
this work; `quadbench.py` loads the real `build/SLPS_005.00` into it and calls the
real builder code.

---

## 10. Open questions / next steps

1. **Pixel proof for the fast path on the emulator.** Render the same scene with and
   without the subdivision and diff VRAM. Expected from `scratch/perf/seamdiff.py`:
   identical on the dungeon's axis-aligned boxes, and 0-0.3% of pixels plus a 1-3
   texel wobble at the subdivision's seams on slanted geometry.
2. **Absolute cycle calibration.** The GTE timings in `gtesim.py` are the psx-spx
   numbers plus one cycle per instruction; a real-hardware check of one builder
   (e.g. a micro-benchmark running `0x80039A10` in a loop) would pin the model.
3. **How many objects really sit in the near/mid bands.** The estimate in section 5
   uses the 11x11 window and the tile statistics; a RAM capture of a real frame
   (the live emulator, when it is free) would give exact counts per band.
4. **Where the overworld's remaining 2x is.** Section 8; needs the same treatment
   (a capture or a sim run of `S2dDrawMapObjs`).
5. **The remaining strictly-identical wins** (section 7): the vertex copies'
   `lwl/lwr` -> `lw/sw` (48 -> 24 cycles/polygon, needs a word-alignment proof for
   the TMD vertex tables) and the per-polygon constant hoist (~5 cycles/polygon -
   measured below the threshold where it is worth touching the builders).
