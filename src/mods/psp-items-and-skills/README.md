# PSP items and skills (`--mods=psp-items-and-skills`)

Clean Salt and Emergency Exit from the PSP version, sold in the Satomi Tadashi pharmacies, and the Persona skills Estoma and Traesto (fusing with those items teaches them too).

## The PSP items and skills (opt in with `--mods=psp-items-and-skills`)

`mods/psp-items-and-skills/pspitems.inc` (shared constants) and `mod/pspitems_{slps,adv,btlp,dng,s2d,open}.asm`.

* **Clean Salt** (PSP item 384) and **Emergency Exit** (PSP item 385) take
  the unused item records 110 and 111 (the never-given "last" pies), and
  **Estoma** (PSP skill 243) the unused skill record 0x70 (Trafuri). Their
  names and descriptions are the PSP's own rows
  (`boot_tables.py` `PSP_SLOTS`, `matching/descs_bank.tsv`).
* **Shops**: both items for 10,000 yen in the three Satomi Tadashi
  pharmacies (lists 10, 11, 16; 10 and 11 are also the Snow Queen route's
  school pharmacy), `src/mods/psp-items-and-skills/shops.py`.
* **Clean Salt / Estoma**: for 16 moon phases, random battles whose
  strongest demon is below the party leader's level do not happen, in the
  dungeons and on the overworld (`src/mods/psp-items-and-skills/estoma.py` builds the
  per-formation levels from `B/D.BIN`); the dungeon says when it wears off.
* **Emergency Exit / Traesto**: in a dungeon, warp to the tile where the
  party entered it: dungeons entered from the overworld, the Kama Palace
  and the Mana Castle; greyed elsewhere. The entrance and the Clean Salt
  timer are kept in memory-card saves (the location sector's spare bytes).
* **Personas**: Estoma in Cu Chulainn, Urdr, Shouki and Byakko, Traesto in
  Otohime, Aonbarr and Quetzalcoatl, each in an empty slot; fusing with
  Clean Salt or Emergency Exit teaches the skill in the 7th slot, like the
  spell stones.
* **Battle**: every skill the battle list greys (record +0x0A bit 0x80
  clear: Estoma, Traesto, Liftoma) is refused with the buzzer.

The state (entrance, timer) is one resident FONT.BIN cell
(`FONT_STATE_PSPITEMS`), zero at boot in every build. The dungeon code takes
one sector behind DNG's last, the overworld code one behind S2D's, so this
patch changes the disc layout (`build_patches.py` `SIZE_CHANGERS`).
