# Fast forward battle animations (`--mods=fast-forward-battle-animations`)

Toggled by pressing Start during the battle animations. Way faster than just double speed.

## The battle fast-forward (`--mods=fast-forward-battle-animations`)

`mods/fast-forward-battle-animations/btlp.asm` (its header has the full mechanism). BtlDrawFrame is rewritten compactly in
place, and the ticks run in groups of `FF_RATE` (3, odd). Tick 0 of a group waits for the vblank and
shows the frame the group before drew. The middle ticks are hidden: BtlDrawObjects' per-object handler
call (0x80082A9C) and its arena / floor-mesh tail (0x80082E6C) are skipped, and the ordering table goes
to the GPU with an empty drawing area. The last tick draws normally. Hidden ticks still run all battle
logic and BtlDrawObjects' state work (position hand-down, colour fades): the handlers only build
primitives (decomp `src/btlp/obj*.c`). The extra code also uses the dead `BtlFrontPost` (0x80065D88).
With `battlespeed` the rewrite has no half-rate second VSync and main.asm leaves
`battle_speed_btlp.asm` out; alone it keeps that wait. Start arms it only in `BtlStageRound`
(`g_btl_stage` 2) or with AUTO on; anywhere in `BtlStageCommand` (the picker, the per-member walk,
the formation grid, a negotiation) Start stays the game's. `g_btl_step` is no test there: the command
stage and `BtlCommandEntry` use it as their own inner state. `src/mods/fast-forward-battle-animations/test_mod_fastforward.py` runs the frame tick by
tick on the R3000 model.
