# Skip movies (`--mods=skip-movies`)

Press Start to skip the currently playing movie.

## Skipping the movie that is playing (`--mods=skip-movies`)

`mods/skip-movies/movie.asm`. `MOVIE.EXE` plays every story FMV - Philemon's scenes among them - and its
frame loop already calls `PadRead(1)` at `0x80080FBC`, but throws the result away, so the scene always
runs to its last frame. `OPEN.EXE` (the Zhuangzi quote) and `ATLUS.EXE` (the logo) have their own
loops and already leave on Start; this patch adds the same to the movie player.

The loop's `jal VSync` at `0x80080FC4` still has PadRead's result in `v0` (the subtitle hook at
`0x80080FBC` tail-jumps to PadRead), so that call is routed through a stub: when Start is held it
raises `g_movie_end`, the flag `StrGetReadyFrame` raises two frames from the end, and the loop leaves
through the ordinary end-of-stream path. The movie-after table still sets the scene, map and position
the movie returns to, and the player runs its normal teardown. The stub sits in the zero padding the
EXE already carries below the subtitle blob at `0x80160000` (inside the loader's `t_size`), so the
disc image does not grow. `src/mods/skip-movies/test_mod_skipfmv.py` runs the loop's VSync call with and
without Start and checks the flag and the bytes that changed.
