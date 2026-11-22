# Unified save menu (`--mods=unified-save-menu`)

Merges the slot 1 and slot 2 menus into one, so that you don't have to worry about which one to select. Requires "speed up on memory card access" to not feel like a slog.

## The save / load patch (opt in with `--mods=unified-save-menu`)

`mods/unified-save-menu/adv.asm` and `mods/unified-save-menu/open.asm`, with the addresses they share
in `mods/unified-save-menu/saves.inc`. The reference decomp in `references/persona-decomp` describes this code (the
save screen's `savescreen.c`, the card routines' `card.c` and the title's `title.c`); its addresses
are for a different pressing of the disc, so every address here was found in this project's own
binaries instead.

* **No memory card selection screen.** Each column identifies its card; save/delete adapters
  derive the physical card and local slot from the combined row. The retail argument loads and
  load-delay instruction remain intact. Every retail ADV rescan enters the two-card scanner.
* **Fourteen slots in two columns of seven** - rows 0-6 on memory card 1, rows 7-13 on card 2.
  A formatted card has fifteen usable blocks, so seven two-block saves fit; the second column is where
  the extra room comes from (the rows need a second card to be usable; DuckStation's Memory Card 2
  is off by default).
* **The load list opens on the first row**, as retail. Saves are written exactly as retail
  writes them; nothing is stamped into them.
* **Card polls never overlap a card write.** The list polls a port every frame to notice a card
  coming or going, and a poll leaves its `_card_info` running. A directory write the BIOS starts
  on top of it (a new slot's room check, `CardCheckFree`, creates and erases a dummy file; saving;
  deleting) fails, and the BIOS's own rollback of a failed create never returns. So each poll is
  waited out (bounded) before the list goes on.

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

Summary tables borrow the bounded battle-decoder scratch at 0x80057400 while ADV is active;
BTLP and ADV are mutually exclusive. ADV's item-pickup name block (latin-alphabet
`adv/chest_name.asm`: an 8-byte cel header and `ITEM_NAME_MAXLEN` cells) sits at the scratch's
start, so the tables begin after it (`MOD_SCRATCH`). The dialogue compositor ring starts after
that scratch and is not borrowed. Every scan initializes the save state. Nothing uses
0x80055C10..0x80056000, the CD-system's globals.
The patch does not grow ADV into another sector or into its packet work area. Assembly bounds
the scratch, retired code runs and both OPEN code/asset allocations.

Bad ADV summaries remain occupied for overwrite handling but never supply display bytes.
Both menus reject summary levels outside 1..99, including erased all-FF headers that pass
retail's XOR checksum.
Failed scans leave empty rows. Title card-change events rebuild the combined
list, clear stale text, and return to list state; a saved parent frame keeps nested error/reset
calls from writing the wrong stack locals.

`sysmsg.py` gates retail text-reference rewrites in the retired function ranges declared in
`saves.inc`: those instructions belong to the new scanner/helpers when `MOD_UNIFIED_SAVE_MENU` is enabled.
A default save-disabled build still relocates those references. The save regression suite also
compares the fully assembled save-owned ranges with isolated assembly; a build with mods runs it
before disc packaging so a later generator cannot silently overwrite the save patch.

Status: the user confirms the overwrite flow no longer crashes and the layout/confirmation fixes
are working. The final LOAD-panel texture-depth and grey-placeholder corrections pass real GPU-packet
and palette readback tests; their final appearance still awaits in-game confirmation. Save
regressions pass (`python tools/run_tests.py test_mod_saves.py`), and built
assets are checked against the matching variant's disc bytes. Full text-presence QA currently flags two DNG effect-expiry
messages outside this patch. Broader card coverage still needs testing: save/overwrite
on both cards (especially right-column slots), leave and reload, load a legacy save, cancel
confirmation, and remove/reinsert a card.

Build-option tests cover opt-in selection and explicit exclusions; the default save-disabled
assembly is checked against retail at the ADV cursor and title-entry hooks.
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

For UI/code iteration, `python src/pipeline/build.py --no-port` skips PSP
extraction/matching and worklist trimming. It still regenerates all text/graphics from the current
tables, assembles every patched image, checks placement, and packages the disc; it does not rely
on stale generated S2D or TALK binaries. Use the normal build when re-porting source wording.
