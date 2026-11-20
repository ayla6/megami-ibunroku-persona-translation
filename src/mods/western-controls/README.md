# Western controls

TYPE 1 swaps Circle/Cross and Triangle/Square at the resident pad reader;
TYPE 2 retains its controls. The title's independent button tests are patched
separately. The run action follows Cancel when Run in dungeons is selected.

Casino minigames keep native physical inputs for both controller types.
`casino.asm` routes CasinoReadPad to the mod's unremapped physical-input API.
The existing casino artwork and English instructions therefore keep their
physical button names. Dialogue symbols are not globally substituted.

Shared menu button cells are remapped at initialization in ADV, DNG and S2D.
This includes the Velvet Room Persona-list view hint. The controller settings
page compensates its cell indices so its physical-key icons retain their
order while the existing action-label mappings remain in effect. CPU tests
cover switching type and reopening the physical-key page.

The battle controller page retains its existing icon UV mappings.
`images.tsv` installs the existing choice-menu corner indicator through the
shared image compiler. The original BtlDrawIndicator also uses fixed UVs and does not select its
bitmap by controller type. The replacement retains that fixed-bitmap behavior. A complete visual audit of
other baked button artwork has not been performed. These paths still need in-game visual confirmation.
