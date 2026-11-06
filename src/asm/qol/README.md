# Persona (SLPS-00500) enhancement patches ("QoL")

All enhancements, including the combined save/load UI, are opt-in. The default translation
build retains the retail save/card flow and its single-card access pattern.

| | translation release | enhancement build |
|---|---|---|
| command | `python src/injection_tools/build.py` | `python src/injection_tools/build.py --qol[=NAME,...]` |
| disc | `dist/Persona-TL.bin/.cue` | `dist/Persona-TL-QoL.bin/.cue` |
| sources | translation only | translation + selected enhancements, minus exclusions |

`--qol` selects the combined save/load UI by default; `--qol=saves` selects it
explicitly (a space instead of `=` works too). A named selection such as
`--qol=60fps` selects only the named patches.
`--no-qol=saves` excludes it from a larger selection, for example `--qol=all --no-qol=saves`.
Exclusions win regardless of order, and `all` works with either option.
`--qol=list` lists patches. Each patch remains
behind its own `-definelabel` in `main.asm`. Either QoL option selects the enhancement output
filename; a plain build uses the retail save flow and the regular translation filename.

| name | define | what it does |
|---|---|---|
| `saves` | `QOL_SAVES` | one bottom-aligned two-card save/load panel, matching row fields and hh:mm clock, newest save preselected when loading |
| `60fps` | `QOL_60FPS` | 60 fps 3D dungeons and overworld (interpolated; wants an emulator CPU overclock to actually reach 60) |
| `encounters` | `QOL_ENCOUNTERS` | half the random encounter rate |
| `rewards` | `QOL_REWARDS` | EXP, Persona points and money after a battle x2 |
| `run` | `QOL_RUN` | hold Cross to walk and turn at double speed in the 3D dungeons; the controller page lists it as its own RUN/CANCEL action on Cross in both control schemes |
| `upright` | `QOL_UPRIGHT` | Upward Movement Orientation: Upper Right in the 2D rooms - pressing Up walks to the upper right instead of the retail upper left |
| `battlespeed` | `QOL_BATTLESPEED` | summons and skill effects at double speed |
| `debug` | `QOL_DEBUG` | battle debug menu: drops the party-leader name gate, so the hidden controller-2 button sequence works and Cancel in the command phase opens the debug page |
| `mark` | `QOL_MARK` | Mark wears the Revelations design: the dialogue/status headshot, battle sheet and overworld walk sheet are swapped for the art in `src/assets/mark/black` (edit those PNGs to change it; see `src/assets/mark/README.md`). No code changes: the BST face slot and his B/P.BIN battle entry are rewritten in place and the ~207 MES.BIN scene entries carrying his walk sheet are re-encoded around the swapped page |

`build/` is shared and holds whichever variant was built last (armips rewrites every overlay from
`data/psx/` on each run, so enabled and disabled variants do not inherit patch bytes from each other).

Raw research log with measurements for the frame-rate patches: `docs/research/FPS60.md`.

## The save / load patch (opt in with `--qol=saves`)

`qol/saves_slps.asm`, `qol/saves_adv.asm` and `qol/saves_open.asm`, with the addresses they share
in `qol/saves.inc`. The reference decomp in `references/persona-decomp` describes this code (the
save screen's `savescreen.c`, the card routines' `card.c` and the title's `title.c`); its addresses
are for a different pressing of the disc, so every address here was found in this project's own
binaries instead.

* **Save serials for ordering.** `CardSave` stamps the highest serial found on the cards plus one
  into the two spare summary bytes, before the block's XOR checksum. Serials are not displayed.
  Legacy saves still load; zero/unset-serial ties retain scan order. FFFF is erased/unset metadata,
  not an ordering number. The 16-bit field saturates at 65534 rather than wrapping to zero;
  saves tied at that ceiling retain scan order. Existing FFFF stamps are treated as unsequenced,
  so the next save recovers from the highest usable serial rather than perpetuating FFFF.
  Both save kinds contribute to the maximum even when the normal save wins a shared display row.
* **No memory card selection screen.** Each column identifies its card; save/delete adapters
  derive the physical card and local slot from the combined row. The retail argument loads and
  load-delay instruction remain intact. Every retail ADV rescan enters the two-card scanner.
* **Direct Agastya entry.** Opening the facility initializes its badge and immediately runs the
  normal card checks and combined list before the facility's fade-in, without the SAVE / GAME END
  selector or an extra Accept. The complete badge/frame/text appears together; the first visible
  dispatcher tick does not rebuild and rescan it. Initial warnings/format choices explicitly
  fade up before waiting for input, so pre-fade preparation cannot hide an interactive prompt.
  Hidden preparation resets both BG-layer RGB and the independent slot fade level before the
  retail ramp; otherwise an inherited bright BG can make its loop terminate in one frame.
  Save entry returns to the unmodified retail fade setup/call (step 4, limit 128); initial
  prompts use that same rate. After the last card operation, a hidden 30-frame preparation
  phase precedes the fade. This consumes DuckStation's post-access fast-forward window without
  changing its settings or the game's fade speed; it costs about half a second on real hardware.
  The tree's fade-out and other facilities' fade-in rates are unchanged.
  Cancel from the list closes the facility. Initial card errors are shown once before closing;
  declined formatting closes it, while successful formatting retries the list. Confirmation
  cancellation still returns to the list, and scene-ending saves retain their retail behavior.
* **Fourteen slots in two columns of seven** - rows 0-6 on memory card 1, rows 7-13 on card 2.
  A formatted card has fifteen usable blocks, so seven two-block saves fit; the second column is where
  the extra room comes from (the rows need a second card to be usable; DuckStation's Memory Card 2
  is off by default).
* **The newest save is preselected** when the load list opens.

Both screens use one 320×192 panel at y=40, with its bottom border at the visible screen edge,
below the badge; no SLOT
headings or separate card frames. `save_ui.py` composes the title's panel from ADV's actual frame
tiles; ADV draws the same map with its retail routines. Rows show name / dedicated Lv artwork,
level, dedicated TIME artwork and `hh:mm`, with the same field offsets and empty placeholders.
There are no seconds. Only minute tens are zero-padded, matching retail. Layout rules are in
`docs/TEXT_LAYOUT_SPEC.md`. All 238 title text sprites fit below the confirmation slots, without
private overflow or a second rendering pass. The LOAD badge's two sprites remain intact.
Both badges use sphere origin (16,8) and lettering origin (8,16). The title panel retains both
retail palette banks in one lossless 8bpp palette; inner boxes do not use the outer frame's
gold/transparent colors. List text/cursor/panel sort at 4/5/6, behind confirmation's 0/1/2.

The title's card messages ("Loading data" and the error prompts) use the same 4bpp page as the
panel. Retail `OpenMessageOpen` uploads them at y=256.., the panel's first strips, so a message
erased the panel while a card was read. `saves_open.asm` moves the message scratch to y=448 and
follows with the sprite `v`; that row is free, and the panel keeps its full 256..447 rectangle.

The dialogue codec treats control operands as raw bytes. A legacy blank after FF0E is choice
index zero, not VWF space 0x88. Passing 0x88 indexes unrelated data as a choice definition and
overwrites the following cel lists while setting up the choice cursor. The real handler was
checked through live DuckStation GDB with argument zero: cursor width 3, adjacent cel definitions
unchanged. CPU tests reproduce the original 0xB400 corruption with the bad argument and verify
the corrected one is bounded. System-message warning/question layout waits once, clears the
window, then shows the question and options without a second wait. No wording is changed.

Summary tables and serial state borrow the bounded battle-decoder scratch at 0x80057400 while
ADV is active; BTLP and ADV are mutually exclusive. The dialogue compositor ring starts after
that scratch and is not borrowed. Every scan initializes the save state. The stamp adapter lives
in retired ADV code, and the resident CardSave hook reaches it only while ADV is loaded (all
retail CardSave calls are in ADV). Nothing uses 0x80055C10..0x80056000, the CD-system's globals.
The patch does not grow ADV into another sector or into its packet work area. Assembly bounds
the scratch, retired code runs and both OPEN code/asset allocations.

Bad ADV summaries remain occupied for overwrite handling but never supply display bytes or
ordering serials. Both menus reject summary levels outside 1..99, including erased all-FF
headers that pass retail's XOR checksum; those headers cannot win newest-save selection.
Failed scans leave empty rows. Title card-change events rebuild the combined
list, clear stale text, and return to list state; a saved parent frame keeps nested error/reset
calls from writing the wrong stack locals.

`sysmsg.py` gates retail text-reference rewrites in the retired function ranges declared in
`saves.inc`: those instructions belong to the new scanner/helpers when `QOL_SAVES` is enabled.
A default save-disabled build still relocates those references. The save regression suite also
compares the fully assembled save-owned ranges with isolated assembly; the QoL build runs it
before disc packaging so a later generator cannot silently overwrite the save patch.

Status: the user confirms the overwrite flow no longer crashes and the layout/confirmation fixes
are working. The final LOAD-panel texture-depth and grey-placeholder corrections pass real GPU-packet
and palette readback tests; their final appearance still awaits in-game confirmation. Save
regressions pass (`python -m unittest discover -s tools/tests -p test_qol_saves.py -v`), and built
assets are checked against the matching variant's disc bytes. Full text-presence QA currently flags two DNG effect-expiry
messages outside this patch. Broader card coverage still needs testing: save/overwrite
on both cards (especially right-column slots), leave and reload, load a legacy save, cancel
confirmation, and remove/reinsert a card.

Newest-save regression coverage runs the ADV scanner, serial stamp and title selection together
for successive writes to all fourteen rows. Fixtures include a checksum-valid erased header,
a valid legacy FFFF serial, and both save kinds sharing one display row. Build-option tests cover
opt-in selection and explicit exclusions; the default save-disabled assembly is checked against retail
at the resident stamp, ADV cursor and title-entry hooks.
Direct-entry tests execute the facility dispatcher through ready/missing/damaged cards, card
removal, and accepted/declined formatting, and check that list Cancel never reopens a parent menu.
The actual facility initialization call is checked separately: list setup precedes its first
fade, while initial warning/format adapters make prompts visible before running them.
Timing tests execute the real hidden-frame loop and require 30 black frames after the final card
operation, before any visible fade frame; a modeled card fast-forward countdown must expire first.
This new phase still needs in-game confirmation with memory-card fast-forward enabled.
The real fade routine and both brightness steppers are executed in regression tests: a prepared
menu ramps from 4 to 128 over successive frames even with initially bright BG layers, and initial
warnings are fully visible before interaction without being blacked out again afterwards.

For UI/code iteration, `python src/injection_tools/build.py --no-port` skips PSP
extraction/matching and worklist trimming. It still regenerates all text/graphics from the current
tables, assembles every patched image, checks placement, and packages the disc; it does not rely
on stale generated S2D or TALK binaries. Use the normal build when re-porting source wording.

## The battle debug menu (`--qol=debug`)

`qol/debug_btlp.asm`. The retail cheat is `BtlCheatWatch` (decomp `src/btlp/cheat.c`): it first
compares the party leader's eight-byte battle name with the kana string `しんけたがるべよ`, then
watches controller 2 for a ten-press sequence. Reaching the end of that sequence flips the hidden
flag `g_btl_debug_hud`; `BtlOrdersMenu` then opens `BtlDebugMenu` (decomp `src/btlp/debugmenu.c`)
instead of the orders menu, as long as Cancel is held.

The translation build's name entry is ABC-only (`name/abc_only.asm`), so the kana name the first
gate wants can never be typed on a translated disc - and only the hero's typed nickname reaches
the battle. This patch nops that one branch (`0x8008F098`, `beqz a2, 0x8008F134` in this
project's BTLP.BIN), which leaves the pad sequence as the only key. Nothing else changes: the pad
table at `0x800CF100`, its step counter and `g_btl_debug_hud` are untouched, so the flag stays
zero until the sequence is entered.

In battle, on **controller 2**: Up Up Down Down Left Right Left Right Cross Circle, one fresh
press each (a wrong press restarts the count). `g_btl_debug_hud` is then on, and holding
**Cancel** in the command phase opens the fifteen-row debug page instead of the orders menu (Cross
on the default control scheme; the bindings are whatever Config's control scheme says):
stat and ailment edits, a summon, an item, and the BGM index stepped through its `0x43` values.
The page answers zero, so the round carries on as though nothing had been ordered.

## Running in dungeons (`--qol=run`)

`qol/run_dng.asm`, plus `runtext.py` writing `build/runtext_dng.asm`. The retail walk block at
`0x80068F64` inside `FieldWalk` advances the view nine times per tile and draws a frame after each
advance. The hook keeps all nine advances - the tile, the collision checks, the step counter and the
landing position are unchanged - and draws only some of the frames: a five-frame mask on one tile and
a four-frame mask on the next, 4.5 of nine on average, exactly double speed. Every drawn frame still
runs one `FieldFrame`, i.e. one 20 Hz tick, so the play clock and the animation counters keep their
real rate. The mask alternates per run tile and returns to zero when the button is released.

`FieldTurn`'s nine-frame heading swing gets the same treatment: its per-frame `FieldFrame` call at
`0x80069084` goes through a wrapper that draws only the frames the shared 5/4 mask covers while Cross
is held, so turning is as fast as walking. Every heading step still runs and the final snap to the
exact quarter is unchanged; without Cross the wrapper draws all nine frames and resets the mask.

The button is not a setting of its own. `runtext.py` appends one action to the controller page's own
action-name table: the retail 19 pointers sit directly in front of `g_pad_layout_actions` with no room
for a twentieth, so the table is copied into the DNG image extension (name at `0x800B5800`, table at
`0x800B5810`, hook at `0x800B5860`, all below the base image's loaded end at `0x800B5BC4`) and
`PadDrawLayout`'s table base load (`0x800906FC`/`0x80090700`) is repointed at the copy. The run action
then replaces Cross in the 3D column of both field pad types: layout 0 entry 1 (`0x8009CB19`, CANCEL in
retail) and layout 1 entry 1 (`0x8009CB2D`, UNUSED in retail). The walk hook waits on Cross in both
types, so the page and the field always agree. Cross still cancels - cancel is edge-triggered while
running reads the held pad. The 2D columns and the battle layouts keep their retail entries, because
running only applies to the 3D view.

`tools/tests/test_qol_run.py` executes the hooks for both pad types and checks the page bytes: the
name table copy, the two changed layout entries (and only those), that Cross is the only button that
runs, that Triangle and R2 do not run, and that FieldTurn's loop draws the 5/4 masks through its
wrapper.

## Upper Right movement in the 2D rooms (`--qol=upright`)

`qol/upper_right_adv.asm`. The isometric room view has four walking directions and `AdvFieldRun`
maps the d-pad to them. Retail is the PSP's **Upper Left** scheme: Up walks to the upper left, Right
to the upper right, Down to the lower right, Left to the lower left. The patch keeps the same
clockwise order but starts it at the upper right: Up walks to the upper right, Right to the lower
right, Down to the lower left, Left to the upper left - the PSP's **Upper Right** setting. The disc
has no setting row for this, so the patch is the choice.

Only the four direction constants change, in place (`0x8007EB54`, `0x8007EB68`, `0x8007EB84`,
`0x8007EBA0`). The branch order, and so which button wins when two are held, stays retail, and the
scripted walk directions, triggers, exits and facing are untouched. `tools/tests/test_qol_upright.py`
runs `AdvFieldRun`'s direction selection for each d-pad button and checks the stored walk direction,
plus the bytes that changed.

## 1. Status (2026-10-09, evening): approach B implemented in both engines

Game logic is untouched (original step / turn / pan constants, 20 Hz dungeon ticks, 15 Hz overworld ticks).
Extra frames are drawn between logic ticks with the camera interpolated; per-frame side effects run on real
ticks only. A measured draw cost decides how many extra frames fit, so the game speed is always the original
(verified live: dungeon ticks 3 vblanks apart, overworld 4 vblanks apart, also while turning / walking).

- Dungeon (`qol/fps60_dng.asm`): hook on F's GsSetRefView2 (0x800659F4) draws up to 2 subframes at 1/3, 2/3
  by calling F recursively (`dngq_sub`), view = GsRVIEW2 at `*(0x800A0D70)+0x1580` (eye moves <= 40/tick,
  look-at radius 5000; eye jump > 200 = warp, no interpolation). Gated in subframes: pad read 0x80067640
  (returns the previous held buttons), HUD counter 0x80065FE8, door animation 0x80066AC4, light pulse /
  flash 0x80066AF8, texture scroll 0x80066BD4; play clock(3) + rand() only on real ticks. Subframes only
  when the last frame cost 1 vblank. Measured in the mall (stock CPU): turn 60 fps, step ~47 fps, idle 20.
- Overworld (`qol/fps60_s2d.asm`): driver on the main loop's draw-tick call 0x8008B77C. State lerped
  (k/4): view GsRVIEW2 0x800B1574 (6 words), map transform inputs 0x800B1040 (rot) / 0x800B1048 (pos), root
  transform (rot 0x800B152C, position recorded at 0x8008B4F4) and second root (0x800B14B4 / 0x800B14BC);
  both roots are rebuilt with S2DQ_BUILD 0x8008DEA0 per subframe and restored exactly afterwards. Gated:
  VSync / clock / frame counter 0x800B8D60 / pad 0x8008E6F4 / upload queue / idle animation + rand()
  0x8008EE40. The banner viewport offset at 0x80093E20 runs on every draw,
  matching its plate; it is not an animation counter. Policy from the measured draw cost: 1 vblank -> 3 subframes (60),
  2 -> 1 subframe (30), 3+ -> none (15, original).
- Fixed 2026-10-09 (user report: the world snapped back before each step, also with Up held): at the first
  tick of a step the overworld re-centres the map on the new cell: the root position jumps by the step
  vector 0x800B143C (0 -> 640 from standing, 160 -> 640 when walking on), and the map shift that cancels it
  is not interpolated. Detection: the step's remaining counter 0x800B144C went up since the previous tick.
  Then the previous root position is moved by the step vector too, so the in-between frame continues the
  motion. Word jump threshold also lowered 0x1000 -> 480. Verified with Up held: drawn root positions
  560 480 400 320 240 160 | 720 640 560 ... (80 per frame, no backward frame).
- Placement: the extension behind the S2D image holds the VWF glue at
  `S2D_GLUE_ADDR` (0x800BB200), the name spill at 0x800BB8F0, the small-font
  data window at `S2D_SF_DATA_ADDR` (0x800BC200), the full-name block at
  `S2D_ITEM_DATA_ADDR` (0x800BD200), and the status bar's fixed slots from
  `S2D_BAR_LIST` (0x800BE800) to `S2D_BAR_HOOK_END` (0x800BE930).
  The shared dialogue ring is in resident runtime scratch, not the S2D overlay. The block starts at
  `S2D_BAR_HOOK_END`, after both the bar and the full-name block
  (`sf_extension_end_s2d`), with build-time guards instead of a claimed window; see
  the rules below.
- Measured overworld at BMarket (stock CPU): a draw tick costs ~2.1 vblanks, 1.5 of them in the world
  object sort 0x8008B968 (52 GsSortObject4 objects), so the overworld stays at 15 fps there. Setting the
  CPU overclock through the MCP API did not change that time (2x, 4x); with the overclock set in the
  DuckStation UI (181%) the user gets a smooth 30 fps there (see the recommended setting below).
- Space: DNG reserves 0x5C0 bytes at the next 16-byte boundary after
  `dng_glue_end`, bounded by `DNG_SPILL_ADDR`; its placement follows dialogue
  code/buffer growth instead of overlapping it. S2D code starts at
  `S2D_BAR_HOOK_END`; it grows the image past the base build's last sector
  (base 370028 bytes, 60fps 371520) and is bounded by `S2D_ITEM_DATA_END`
  (0x800E0000).
- Placement rule for QoL blocks: never claim a fixed window behind an image. Place the block after the
  last blob that owns the overlay's extension (S2D: `S2D_BAR_HOOK_END`; DNG: behind `dng_glue_end`), and
  assert the bounds at assembly time (`.error`); an overlap must be a build error, never a crash in game.
  `tools/tests/test_qol_write_guard.py` assembles the real `main.asm` for the base, every QoL option on
  its own and all together in an isolated tree, then runs the same write guard the release uses; any
  QoL block that covers another block's bytes fails the suite, not the release.
- Test helpers (scratchpad, not in the repo): fps.py (presented frames vs vblanks), ticks.py (vblank
  stamps of real ticks, `dngq_vars+4` / `s2dq_vars+4`), qpatch.py / qpatch_s2d.py (live patch from build/).

### Gameplay tweaks in the QoL build (2026-10-09, user request)
Only in the QoL disc (`.ifdef QOL60` in main.asm); the translation release keeps the original balance.
- Half the random encounter rate: `qol/encounters_s2d.asm` (overworld: grace period 16 -> 32 steps, roll
  rand() % 32 -> % 64 against the zone threshold 2 / 4 / 8; mean steps between battles 32 / 24 / 20 ->
  64 / 48 / 40) and `qol/encounters_dng.asm` (3D dungeons: cooldown 7 -> 14 steps, per-step chance 1 / 8,
  1 / 4, 1 / 2 -> 1 / 16, 1 / 8, 1 / 4; mean 15 / 11 / 9 -> 30 / 22 / 18). Constants only.
- EXP, Persona points (P.P.) and money after a battle x2 (x << 1; was x1.5 until 2026-10-10): `qol/rewards_btlp.asm`, three
  hooks at 0x800F8900 (behind the BTLP image, inside its last loaded sector). The totals
  0x800F746C (EXP), 0x800F70F0 (P.P.) and 0x800F83A4 (money) are multiplied when the end-of-battle code
  first reads them (0x80097A38, 0x80097A88, 0x800AAD70), so the split between members, the results screen
  and the wallet all see the new values. Bosses get x2 as well.
- Verified live with the old x1.5 (same battle twice): money 5460 -> 8190, EXP total 1783 -> 2674, P.P. per member
  224 / 326 / 282 / 236 / 118 -> 336 / 489 / 424 / 354 / 178. The encounter changes are verified by
  disassembly only; the user tests them in a new game.
- 2026-10-10: rewards raised to x2 (`sll a0, a0, 1`); QoL disc rebuilt 13:09 and checked on user slot 5 (dungeon
  battle, AUTO Replay): hooks present at 0x800F8900, results screen paid out. AUTO Normal can stall on a last
  enemy (everyone DEF); Replay finishes the battle.

### Recommended emulator setting (user-tested 2026-10-09)
DuckStation: Settings > Console > CPU emulation > enable **Overclock** and set it to **181%** (61.30 MHz).
Result reported by the user: the 3D dungeons run at 60 fps with no lag spikes (also the heavy mall area)
and the overworld at a smooth 30 fps. Verified live: with 181% the dungeon turn is a full 60 fps and the
logic ticks stay exactly 3 vblanks apart, so the game speed is the original. Without overclock the patch
still never slows the game down; it only draws fewer extra frames (dungeon ~45-60, overworld 15 at heavy
spots like BMarket). The overclock must be set in the DuckStation UI: changing it through the MCP API did
not affect timing in our tests. Real hardware cannot overclock, so expect the stock-speed results there.

## 2. Engine facts

Common
- Overlays load at 0x800643C4 (`OVERLAY_SLOT_ADDR`); DNG.BIN = dungeon, S2D.BIN = overworld.
- PsyQ `VSync` = SLPS 0x80025C98, `DrawSync` = 0x8002B5E8, `rand()` = 0x800413F8 (BIOS A(0x2F)).
- The vblank counter variable used by VSync is 0x8004FD3C (`VSync(-1)` returns it).

VSync semantics (read from the code, important):
- `VSync(-1)`: returns the vblank counter, no wait.
- `VSync(0)`: waits for the next vblank. **Use this for 60 fps.**
- `VSync(1)`: returns immediately (horizontal count since the last call), no wait. The live tests used
  this, i.e. they were uncapped: below 60 at stock speed, but with enough CPU overclock the game logic
  runs faster than real time.
- `VSync(n>1)`: waits until n vblanks have passed since the previous call (3 = 20 fps, 4 = 15 fps).

### Dungeon (DNG)
- Frame routine 0x800659B4 (draws the 3D view, 11x11 cell loop, HUD) ends with
  `DrawSync(0)` 0x8006756C, `VSync(3)` 0x80067574, play clock `0x800678AC(3)` 0x8006757C,
  `rand()` 0x80067584 (result unused: it only stirs the RNG every frame).
- Play clock 0x800678AC: byte 0x800A0380 += a0 (wraps at 60); in-game time bytes 0x801F29BC..C3.
- Game logic is written as blocking loops: "update; call 0x800659B4" N times. 72 call sites.
- Step (0x80068F64): 5 x advance 0x80068AA0 (pos 0x800A0CD0 / 0x800A0CDC += dir*30), event check
  0x8007108C, 4 x advance, snap 0x80068B64 (300 units per cell), then 0x80069754.
- Turn (0x80069028, a0 = dir): 9 x (angle `*(0x800A0D70)+0x15AC` += dir*96; 0x800690F4 rebuilds the
  camera), then angle = start + dir*1024 (90 degrees = 1024).
- Camera copy: 0x80067D40 copies `*(0x800A0D70)+0x1580..` (player pos/angle struct, base 0x801F0000)
  to 0x800A0CD0..
- Measured: 19.8 fps capped; uncapped 51-57 fps at stock CPU (Joy Street school corridor); 30 fps
  holds 29.9. CPU-bound in GTE render code (SLPS 0x8003A9xx); the user reports a small DuckStation CPU
  overclock gives a solid 60.
- Free space: DNG bss ends 0x800A1124; the VWF script glue starts at
  `DNG_GLUE_ADDR`. The QoL block follows `dng_glue_end` with 16-byte alignment
  and reserves 0x5C0 bytes. Assembly rejects any growth reaching the dungeon
  spill window at `DNG_SPILL_ADDR`; the overlay extension loads both regions.

### Overworld (S2D)
- Tick based. Main loop 0x8008B774: update 0x8008F91C (state machine, jump table indexed by
  0x800A5438), then tick 0x8008FA08 -> render 0x8008A438 with a0 = 4 (0x8008FAC0). Another caller
  passes 4 (0x80091988), others 2 (0x80091D2C, 0x800922B0, 0x80094A34) or 0.
- Render routine: `VSync(s4)` 0x8008AF68 and play clock `0x800978E0(s4)` 0x8008B0D0.
- Step: 0x8008B2F4(speed), single caller 0x8008D73C with 0x400 (4 ticks) or 0x800 (2 ticks) from
  0x8008D734/38. Remaining 0x800B144C starts at 0x1000, -= speed per tick in 0x8008B39C; vector
  0x800B143C (640 units per step, rotated by the heading). The world (not the camera) is translated;
  object matrices are rebuilt by SLPS 0x80040xxx.
- End of every step (0x8008B42C..): step counter 0x800B1618, every 16 steps 0x801F2B30 += 1 (mod 16,
  read by the HUD, probably the moon phase), then 0x8009686C and 0x80096B5C (use rand(), most likely
  encounter / event checks).
- Turn: 0x8008C01C loads the tick count from 0x80064F08 (8 left, 8 right, 16 about-face) and the
  direction from 0x80064F10; per tick 0x8008BFA4: heading 0x800B152E += dir<<7 (0x8008BFE4); the
  rendered heading 0x800B1042 = 0x800B14B4 + 0x800B152E.
- Camera lerps: 0x8008F244 / 0x8008F28C set targets and speeds (a2 -> 0x800B3464, a3 -> 0x800B3468);
  0x8008F2EC advances t (0x800A5718, 0x800A573C) by the speed per tick, clamped at 0x1000. Speeds
  0x100 at 0x8008FE34, 0x8008FF3C, 0x80091170 (a2) and 0x8008FE48, 0x8008FF6C, 0x80091184 (a3);
  0x8008EC28 passes 0x1000 (instant).
- Measured: 14.9 fps idle and walking; uncapped ~42 fps at stock CPU (needs more overclock than the
  dungeon for 60); 30 fps holds.
- Free space: S2D glue area 0x800BB200..0x800BB8E8 (used up to 0x800BB7A8), then the name spill
  (0x800BB8F0..0x800BB9C5), the small-font / full-name block from 0x800BC200 to `sf_extension_end_s2d`
  (0x800BE62C), and the status bar slots from `S2D_BAR_LIST` (0x800BE800) to `S2D_BAR_HOOK_END`
  (0x800BE930). The QoL block starts after those (0x800BE930..0x800BEF04); nothing else may claim a
  fixed window in this range.

### Encounters / RNG
- Encounter-related work happens per step in both engines, so encounter odds per step do not depend on
  the frame rate.
- The dungeon frame routine calls rand() every frame. A plain unlock would draw 3x more numbers
  between steps (same odds, different sequence). The QoL stub calls rand() once every 3 frames, so the
  number of draws per step/turn matches the original.
- The overworld frame/tick routines do not call rand() directly.

## 3. What the current QoL build patches

`qol/fps60_dng.asm`
| addr | change |
|---|---|
| 0x80067574..84 | `jal dng_frame_sync` + nops (replaces VSync(3), clock(3), rand()) |
| 0x80068AE8/EC, 0x80068B38/3C | step delta dir*30 -> dir*10 |
| 0x80068F7C / 0x80068FA4 | step loops 5 -> 15, 4 -> 12 frames |
| 0x80069050 / 0x8006908C | turn delta dir*96 -> dir*32, loop 9 -> 28 frames (ends with the original snap) |
| 0x800A1800 | `dng_frame_sync`: VSync(0); clock(elapsed vblanks, 1..6); rand() every 3rd frame |

`qol/fps60_s2d.asm`
| addr | change |
|---|---|
| 0x8008AF68 | `jal s2d_vsync`: mode 4 -> VSync(0), other modes unchanged |
| 0x8008B0D0 | `jal s2d_clock_sync`: mode 4 -> clock(elapsed vblanks), other modes unchanged |
| 0x8008D734/38 | step speed 0x400 -> 0x100, 0x800 -> 0x200 |
| 0x80064F08 | turn ticks 8/8/16 -> 32/32/64 |
| 0x8008BFE4 | heading step dir<<7 -> dir<<5 |
| six lerp speed sites | 0x100 -> 0x40 |

Consequence of approach A: when a frame takes longer than one vblank, the game logic slows down
(like any PS1 slowdown). Real-time speed matches the original only at a locked 60.

## 4. Test procedure

User save states (on the translation disc; for the QoL disc make new ones from a hard save):
- Dungeon: slot 1 = 2D room, press Down once -> 3D dungeon (Joy Street / school).
- Overworld: slot 2 = school hall, Up once -> overworld. Left/Right twice = about-face, Up into the
  school 2D room; from the overworld about 10 steps Down = school 3D dungeon (and back: about-face,
  10 steps Up).
Checks: fps (DuckStation OSD), step/turn duration vs the original disc, door/stairs/menu/fade speed,
in-game play time vs a stopwatch, encounters after the story allows them, entering/leaving rooms.

Measuring from a script: DuckStation MCP over HTTP at `http://127.0.0.1:2346/mcp` (not `localhost`:
that costs 2 s per call); `get_status` gives `frame_number` (vblanks) and `internal_frame_number`
(presented frames), so fps = d(internal)/dt. A breakpoint on 0x80025C98 + `ra`/`a0` shows who calls
VSync with what.

## 5. Next steps

### Dungeon: approach B (camera interpolation), chosen by the user
Keep all game logic at 20 Hz exactly as the original; draw up to 3 frames per logic tick.
1. Revert the step/turn/loop constants (logic unchanged), keep VSync(3) timing semantics per tick.
2. Split 0x800659B4 into side effects and drawing. Known side effects: play clock, rand(), counters
   inside the HUD/map code (to be audited: compass, moon icon, map blink, text box, effect timers).
3. Per logic tick: remember the previous camera (pos 0x1580.., angle 0x15AC, and the copy at
   0x800A0CD0); draw subframes k = 1..3 with camera = lerp(prev, cur, k/3) (angle with wrap-around),
   VSync(0) between subframes; run the side effects once on the real tick. Skip remaining subframes
   when the vblank counter shows the tick budget (3 vblanks) is used up, so game speed stays constant.
4. Disable interpolation when the camera jumps (floor change, warp, battle return): delta above one
   cell (300) or angle step above 1024.
5. Needs ordering-table / double-buffer care: each subframe must build and draw a full frame
   (check how 0x800659B4 swaps buffers: 0x80040464 at its start returns the buffer index 0x800A0388).

### Overworld
- Option 1: finish approach A (audit banner, marker animation, fades, menus, the other mode-4 caller
  0x80091988 and the 2-mode loops).
- Option 2 (preferred, consistent with the dungeon): keep ticks at 15 Hz and interpolate. The step
  is already a lerp (remaining 0x800B144C) and the turn a linear counter, so subframes can evaluate
  them at fractional ticks (remaining - speed*k/4, heading + (dir<<7)*k/4) without touching logic.

### Performance / options
- Stock hardware: dungeon 51-57 fps, overworld ~42 fps uncapped. Offer a 30 fps option (dungeon
  VSync(0) x2 subframes, overworld 2 subframes) for real hardware, 60 fps for emulators with CPU
  overclock. With approach B, dropped subframes cost smoothness, not speed.

### Open questions
- Exact routines behind 0x8009686C / 0x80096B5C (encounter?).
- Whether any dungeon timer (damage floors, effect durations) counts frames instead of steps.
- BTLP (battles) frame rate was not examined.

### Sync note (2026-10-09)
`dist/Persona-TL-QoL.bin` was built BEFORE the dungeon "wore off" / name-insert fix; rebuild it with `python src/injection_tools/build.py --qol` to get the fix plus the 60 fps patches (they touch different addresses).
