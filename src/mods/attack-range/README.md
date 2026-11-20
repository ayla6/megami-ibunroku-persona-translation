# Attack range (`--mods=attack-range`)

Shows the range of an attack on the battle floor while you pick its target. Yeah somewhat like the PSP version but with somewhat less info since it's just on the battle floor.

## The reach on the battle floor (`--mods=attack-range`)

`mods/attack-range/btlp.asm` (its header has the details). Retail never shows a move's reach: the target cursor
only stops on the fighters it reaches. The reach is `g_btl_reach[5 lanes][15 rows]` (decomp
`src/btlp/reach.c`), and a pick puts the fighters it would hit on the target motion (10/11).

The picks run inside a wrapper that raises a state byte while they run: BtlCommandAttack (the sword's and
the gun's rows of `g_btl_command_fn`), BtlPickMoveTarget (the cast's and the item's), and the item
command's BtlPickTargetMember / Party / Enemies. Before the pick, the wrapper fills the reach with the side
it picks from (by the move's kind for BtlPickMoveTarget); the line and burst picks write their own reach
over it. BtlPickMoveTarget's whole-party pick clears the reach with BtlPartyResetGfx after it starts, so that
call is followed by the party's side again. Every frame, while a pick is up and a fighter is on the target motion, the reach is painted
orange and those fighters' cells red. Outside a pick the motion counts for nothing, so the negotiation's
demons and the acting member (bobbed on motion 10 through the whole command by BtlSingleOutMember) paint
nothing. Party members count only in a party pick: the item command's member and party picks, and
BtlPickMoveTarget's once it calls BtlSetPartyPickable. There the acting member is a target like any other.

Three menus preview what is under the cursor in red for two frames:
- the command menu (BtlPickUpdate's call in BtlCommandEntry), on the sword and the gun: the weapon's line,
  thrown with BtlMarkMoveArea as BtlCommandAttack throws it;
- the skill board (BtlPersonaSpellUpdate's call) and the item board (the BtlMenuKey call that opens each of
  its frames): moves aimed by their own data are thrown with BtlMarkMoveArea, as the pick will throw them;
  support kinds paint the party's side, and every other move the enemies' side. The nine items the item
  command aims itself paint the side their pick uses.

Each lane's run of same-coloured cells is one semi-transparent floor quad, projected the way the retail
debug grid projects its cells. The overlay replaces that grid (BtlDrawObjects 0x80082B78), which nothing in
the game turns on. Code also lives in BtlDebugPause and BtlLoadDebugGrid (unreferenced) and in BtlDebugWait /
BtlDebugWaitArgs (called only behind `g_btl_debug`, which no code sets). The colours are `RNG_RGB_AREA` /
`RNG_RGB_TARGET` in `common/addresses.inc`. `src/mods/attack-range/test_mod_range.py` runs the overlay with a stand-in
GTE and the wrappers and previews with stubbed callees.
