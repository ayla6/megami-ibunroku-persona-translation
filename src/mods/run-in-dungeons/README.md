# Run in dungeons (`--mods=run-in-dungeons`)

Hold Cross to run in dungeons. Choose an integer speed from 2× through 4×;
the default is 2×. For example:

    python src/pipeline/build.py '--mods=run-in-dungeons(speed=3)'

The web patcher offers the same range, and a single released layer supports
all three speeds. `values.tsv` targets the speed byte at the start of the
reserved run block; the shared range writer and all patchers use that map.

## Running in dungeons (`--mods=run-in-dungeons`)

`mods/run-in-dungeons/dng.asm`, plus `runtext.py` writing `build/runtext_dng.asm`. The retail walk block at
`0x80068F64` inside `FieldWalk` advances the view nine times per tile and draws a frame after each
advance. The hook keeps all nine advances - the tile, the collision checks, the step counter and the
landing position are unchanged - and draws only some of the frames: 5/4 frames at 2×, 3 frames at 3×, and
3/2/2/2 frames at 4× over their repeating cycles. Every mask draws the final
advance, and the average frame counts give the selected speed exactly. Every drawn frame still
runs one `FieldFrame`, i.e. one 20 Hz tick, so the play clock and the animation counters keep their
real rate. The mask alternates per run tile and returns to zero when the button is released.

`FieldTurn`'s nine-frame heading swing gets the same treatment: its per-frame `FieldFrame` call at
`0x80069084` goes through a wrapper that draws only the frames the selected-speed mask covers while Cross
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

`src/mods/run-in-dungeons/test_mod_run.py` executes the hooks for both pad types and checks the page bytes: the
name table copy, the two changed layout entries (and only those), that Cross is the only button that
runs, that Triangle and R2 do not run, and that FieldTurn's loop draws all three speeds through its wrapper. CPU checks
cover cycle averages, release-to-walk reset and preservation of all nine steps.
