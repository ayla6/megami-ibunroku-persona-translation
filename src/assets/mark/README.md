# Mark's assets (QoL `--qol=mark`)

The Revelations: Persona disc ships a redesigned Mark; this folder holds that
art, exported from both discs, as the base for the edited version the QoL
patch installs. Mark's battle sheet is exported from the JP disc: the
Revelations sheet is 128x256 and the JP slot it has to fit is 128x250, so the
editable file starts from the JP art and is drawn over by hand. The patch is
opt-in: without `--qol=mark` the build actively removes the swap files from
`build/`, so a plain build always ships the original JP art.

| file | what it is | where it comes from |
|---|---|---|
| `black/headshot.png` | dialogue / status headshot, 88x96, transparent | Revelations `ADV/BST.BIN`, face slot 2 |
| `black/battle.png` | battle sprite sheet, 128x250, transparent | JP `B/P.BIN`, party member 5 entry |
| `black/walk.png` | overworld walk sheet, 128x250, transparent | Revelations `ADV/MES.BIN`, scene entry 11 member 1 |
| `og/headshot.png` | the original JP headshot, for reference | JP `ADV/BST.BIN`, face slot 2 |
| `og/battle.png` | the original JP battle sheet, for reference | JP `B/P.BIN`, party member 5 entry |
| `og/battle_gun.png` | original JP gun-action sheet, for reference | JP `B/P.BIN`, party member 15 entry |
| `black/battle_gun.png` | edited gun-action sheet | JP `B/P.BIN`, party member 15 entry |
| `og/ending.png` | original ending portrait, 149x208 RGB | JP `EXE/END.BIN`, 16bpp TIM at `0xA7804` |
| `black/ending.png` | edited ending portrait | JP `EXE/END.BIN`, 16bpp TIM at `0xA7804` |
| `black/ending_revelations.png` | Revelations ending portrait reference | US `EXE/END.BIN`, 16bpp TIM at `0xA7804` |
| `og/walk_variant.png` | original alternate overworld sheet | JP `ADV/MES.BIN`, entry 187 member 3 |
| `black/walk_variant.png` | edited alternate overworld sheet | JP `ADV/MES.BIN`, entry 187 member 3 |
| `og/walk.png` | the original JP walk sheet, for reference | JP `ADV/MES.BIN`, scene entry 11 member 1 |
| `og/mother.png` | candidate for Mark's mother, original art | JP `ADV/MES.BIN`, entry 18 member 4 |
| `black/mother.png` | editable candidate sheet | initially copied from the original art |
| `black/mother_revelations.png` | Revelations reference for the candidate | Revelations `ADV/MES.BIN`, entry 18 member 4 |

The user confirmed the woman on this page is Mark's mother. Other appearances
still need in-game confirmation.

Provenance: slot and member indices were established by rendering every
BST face (80), every distinct MES page (105 JP / 107 US), and the 20 party
battle sheets in `B/P.BIN`, then identifying Mark visually; the user
confirmed party member 5 is Mark. The battle entry is found through
`g_btl_member_file` in `BTLP.BIN` (20 start offsets, each entry ending where
the next starts), not a typed address. The walk sheet is byte-identical in
all ~207 scene entries that carry it on each disc, so one page per disc
covers the whole game.

Gun actions reload the corresponding member entry plus 10: the reference
decomp's `roundflow.c` calls `BtlReloadMemberGfx(member + 10, ...)` for
action `0xC`, and `memberreload.c` selects that entry from the same sector
table. Consequently Mark's gun-action sheet is entry 15, separate from the
normal sheet at entry 5. The patch installs and verifies both battle sheets.

The ending portrait follows the ending text page at `0x9E004`, mapped to
Masao's profile by `src/extraction_tools/matching/endtext_map.tsv` and the
PSP-US ending transcription. The Mark patch replaces only its 16bpp pixel
data after `endtext.py` builds `EXE/END.BIN`, preserving the translated text.
Switching to a variant without Mark restores just the retail portrait.

The alternate walk page shares all but 1,565 of 32,000 pixel indices and
the palette with Mark's normal JP walk sheet. It appears in MES entries
187–190 and 195–198. Its differing region might depict a different character
or a different appearance of Mark. The patch replaces exact copies of this
separate sheet with `black/walk_variant.png` as a precaution.

## Editing

Edit `black/headshot.png`, `black/battle.png`, `black/battle_gun.png` and
`black/walk.png` in place
(that is what the patch installs), keep to the rules below, then build with
`--qol=mark`:

- same pixel size as the export (88x96 / 128x250); the battle and walk frames
  must stay on the same grid - the game's frame definitions point at fixed
  cells, and both 128x250 sheets use the same cell layout as the export;
- fully transparent pixels (alpha 0) are palette slot 0, the PS1 transparent
  key; an opaque black is kept separate and gets its own slot, so it will not
  turn into a hole;
- at most 255 opaque colours (slot 0 belongs to transparency); colours that
  match the original sheet keep their palette slot, new colours take unused
  slots - so small edits change as few bytes as possible;
- partly transparent pixels are installed as fully opaque, with a warning:
  the PS1 has no per-pixel alpha.

Regenerate the reference exports from any extracted disc tree with:

    python src/injection_tools/mark.py export data/psx src/assets/mark/og
    python src/injection_tools/mark.py export <revelations-tree> <new-output-directory> --suffix _revelations

Exports refuse to overwrite existing files. The plain filenames in `black/`
are working edits; do not replace them with disc exports. The Revelations
tree exports its battle sheet at 128x256, the size of its own `B/P.BIN`
entry; the JP entry is 128x250, so `black/battle.png` comes from the JP
export.

`mark.py build` / `mark.py verify` run inside the build and swap the BST
face, the `B/P.BIN` battle entry and the MES walk pages; `mark.py retail`
removes the swap files again. The MES re-encode processes 207 scene entries
in parallel and reports progress; its duration depends on the machine.
