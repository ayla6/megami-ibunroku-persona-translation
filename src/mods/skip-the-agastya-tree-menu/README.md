# Skip the Agastya tree menu (`--mods=skip-the-agastya-tree-menu`)

Opens the save list right away at an Agastya tree, without the SAVE / GAME END choice. Cancel leaves the tree.

## Direct Agastya entry (opt in with `--mods=skip-the-agastya-tree-menu`)

`mods/skip-the-agastya-tree-menu/adv.asm`, with its retired ranges in `mods/skip-the-agastya-tree-menu/agastya.inc`.
Without it the retail SAVE / GAME END selector stays: SAVE enters the save
list (with `saves`, the combined one) and a cancel returns to the selector;
GAME END returns to the game after its "turn off the power" notice, or with
`gameend` goes straight to the title screen.

Opening the facility initializes its badge and immediately runs the
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
SaveTopStep runs once per opening; entered again it can only come from a
cancel (the list with one card, or retail's card-choice screen with two when
`saves` is off), and it closes the facility then.

The adapters live in the selector's retired sprite setup and in its input
code inside SaveTopStep, which the patch jumps past (nothing else enters it).
