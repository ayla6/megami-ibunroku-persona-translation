# Restore formation after ambushes (`--mods=restore-formation-after-ambushes`)

When you get ambushed the game turns your party around and leaves it like that after the battle. This puts everyone back where they were before the ambush, even if you moved them during the fight.

## The formation after an ambush (`--mods=restore-formation-after-ambushes`)

When the enemies get the jump on the party (the field's surprise roll fails:
battle kind 2), the battle entry turns the party round: the battle's formation
grid (0x8004E1BC) has its front half swapped end for end with its back half
(decomp src/btlp/entry.c, Rev 0 0x80080D14). When the fight ends,
BtlStoreParty (inlined at 0x8008768C) copies that grid into the save block's
live formation row (0x801F264C), which is where the field stands the party, and
retail never swaps it back - the party stays reversed after every ambush.
`mods/restore-formation-after-ambushes/btlp.asm` copies the grid aside just before the swap and writes the
copy over the live row as the battle entry returns to the field (0x80080F04),
after that store: the formation from before the ambush, whatever was moved
during the fight. The copy and its flag (the length to copy back, 25 or 0) sit
in the entry's own "SND INIT" debug dump (0x800802CC-0x800803E8), which only
runs behind `g_btl_debug`; each battle's fresh load of the overlay starts them
clear.
