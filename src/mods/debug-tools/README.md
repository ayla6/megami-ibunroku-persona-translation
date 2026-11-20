# Debug tools (`--mods=debug-tools`)

Battle debug menu: press Select on either controller in battle; on the title L1/L2/R1/R2/Select start endings 0-4, R1 held fast-forwards an ending and Start skips its movies; battles check their primitive pool every frame and stop on the first broken one (red square at the top left).

## The battle debug menu (`--mods=debug-tools`)

`mods/debug-tools/btlp.asm`. The retail cheat is `BtlCheatWatch` (decomp `src/btlp/cheat.c`): it first
compares the party leader's eight-byte battle name with the kana string `しんけたがるべよ`, then
watches controller 2 for a ten-press sequence. Reaching the end of that sequence flips the hidden
flag `g_btl_debug_hud`; `BtlOrdersMenu` then opens `BtlDebugMenu` (decomp `src/btlp/debugmenu.c`)
instead of the orders menu, as long as Cancel is held.

The translation build cannot type the kana name the retail gate wants. With this option,
a fresh **Select** press on either controller opens the debug page (Start during a turn is `fastforward`'s). The hook runs at the
end of `BtlDrawFrame`, guards against recursion and a closing battle, saves `g_btl_step`,
sets the page's initial step, and restores the battle step on return. It does not enable
the separate debug HUD. The page includes stat and ailment editors and a BGM selector;
Cancel leaves it. The Select hook has instruction-level tests but still needs in-game QA,
particularly when opened during other battle screens. The debug board's fitting
translated rows use the same battle small-font VWF bridge as other boards, in
both normal and debug-enabled builds.

## The endings from the title (`--mods=debug-tools`)

`mods/debug-tools/open.asm`, `mods/debug-tools/end.asm`. Every ending - its epilogue pages and the staff roll - is
`END.EXE` running one of five real scripts (`g_movie_id` 0x30..0x34 in the resident's movie state).
On the title menu a fresh press of L1, L2, R1, R2 or Select starts ending 0, 1, 2, 3 or 4: the hook
sets `g_movie_id`, `g_movie_next_state = -1` (back to boot when the script returns) and the
resident's `g_state_next` (`0x80055C5C`, off the resident's gp - OPEN.EXE has its own) to the movie
state, then leaves through the menu's retail tail with a choice no title case takes. Other presses
run the retail confirm test (or the western one) unchanged. In `END.EXE`, holding R1 skips
`EndDraw`'s vblank wait, so the script runs as fast as it draws; Start during an ending movie raises
the stream's own end flag. Nothing in a script is copied or changed, so each page shows exactly
where and how the real ending shows it. The staff roll is in endings 1-4; ending 2 reaches it
first (two epilogue pages, one movie). Endings 1 and 2 end on the retail hold, so the console is
reset after them. The story flags of a fresh boot are clear, so the pages that ending 1 and ending 3 pick by flag are
the ones their flag tests choose with every flag clear.
