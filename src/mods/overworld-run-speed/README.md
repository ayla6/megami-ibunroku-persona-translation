# Overworld run speed (`--mods=overworld-run-speed`)

The overworld map's own run, faster.

`mods/overworld-run-speed/s2d.asm` (its header has the full mechanism). The overworld already runs:
holding the pad type's run button makes the walking mode start a step with a per-tick step of 0x800
instead of 0x400, so a cell takes two 15 Hz ticks instead of four. A step's remaining count starts
at 0x1000 every step, so a step always takes a whole number of ticks. The mod's call at 0x8008D73C
replaces the run's step by the `speed` slider's cycle: 2x is retail's 0x800, 4x 0x1000 (one tick a
cell), 3x 0x1000, 0x1000, 0x800 in turn (three cells in four ticks). Walking is unchanged and
restarts the 3x cycle.

The speed byte and the code live in the dead StatusSlotDraw's bytes from `S2D_BSD_ADDR + 0x180`;
battle-speedup's overworld transition code has the first 0x180.
