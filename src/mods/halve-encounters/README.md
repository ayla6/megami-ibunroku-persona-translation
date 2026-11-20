# Halve encounters (`--mods=halve-encounters`)

Halves the rate of random encounters. Like everything else in this section, this is an option. In this case, if you want an easier game. This is not the intended original experience of the game!

- Half the random encounter rate: `mods/halve-encounters/s2d.asm` (overworld: grace period 16 -> 32 steps, roll
  rand() % 32 -> % 64 against the zone threshold 2 / 4 / 8; mean steps between battles 32 / 24 / 20 ->
  64 / 48 / 40) and `mods/halve-encounters/dng.asm` (3D dungeons: cooldown 7 -> 14 steps, per-step chance 1 / 8,
  1 / 4, 1 / 2 -> 1 / 16, 1 / 8, 1 / 4; mean 15 / 11 / 9 -> 30 / 22 / 18). Constants only.
