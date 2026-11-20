# Black Mark (`--mods=black-mark`)

Makes Masao Inaba black. It uses a custom sprite I made for him so that he's both black and still wears his original outfit. Doesn't change the script.

The Revelations: Persona disc ships a redesigned Mark; this folder holds that
art, exported from both discs, as the base for the edited version this
mod installs. Mark's battle sheet is exported from the JP disc: the
Revelations sheet is 128x256 and the JP slot it has to fit is 128x250, so the
editable file starts from the JP art and is drawn over by hand. The patch is
opt-in: without `--mods=black-mark` the build actively removes the swap files from
`build/`, so a plain build always ships the original JP art.

`assets/` holds what the patch installs - one PNG per sheet - and the PSD each
is edited in (`assets/<name>.psd` beside `assets/<name>.png`):

| file | what it is | where it goes |
|---|---|---|
| `assets/headshot.png` | dialogue / status headshot, 88x96, transparent | `ADV/BST.BIN`, face slot 2 |
| `assets/battle.png` | battle sprite sheet, 128x250, transparent | `B/P.BIN`, party member 5 entry |
| `assets/battle_gun.png` | gun-action sheet, 128x250 | `B/P.BIN`, party member 15 entry |
| `assets/walk.png` | overworld walk sheet, 128x250, transparent | `ADV/MES.BIN`, scene entry 11 member 1 |
| `assets/walk_variant.png` | alternate overworld sheet | `ADV/MES.BIN`, entry 187 member 3 |
| `assets/mother.png` | Mark's mother | `ADV/MES.BIN`, entry 18 member 4 |
| `assets/ending.png` | ending portrait, 149x208 RGB | `EXE/END.BIN`, 16bpp TIM at `0xA7804` |

The original JP and Revelations exports are not kept: the PSDs hold
everything the edits were drawn from, and `image_replacements.py export` writes them again
from a disc (below).

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
Masao's profile by `src/porting/endtext_map.tsv` and the
PSP-US ending transcription. The Mark patch replaces only its 16bpp pixel
data after `endtext.py` builds `EXE/END.BIN`, preserving the translated text.
Switching to a variant without Mark restores just the retail portrait.

The alternate walk page shares all but 1,565 of 32,000 pixel indices and
the palette with Mark's normal JP walk sheet. It appears in MES entries
187–190 and 195–198. Its differing region might depict a different character
or a different appearance of Mark. The patch replaces exact copies of this
separate sheet with `assets/walk_variant.png` as a precaution.

## Editing

Edit the PSDs in `assets/` and save each over its PNG
(the PNGs are what the patch installs), keep to the rules below, then build with
`--mods=black-mark`:

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

Export the original sheets from any extracted disc tree for reference
with:

    python src/pipeline/image_replacements.py export black-mark --tree data/psx --output <new-output-directory>
    python src/pipeline/image_replacements.py export black-mark --tree <revelations-tree> --output <new-output-directory> --suffix _revelations

Exports refuse to overwrite existing files; never export into `assets/`, whose
PNGs are the edits. The Revelations tree exports its battle sheet at
128x256, the size of its own `B/P.BIN` entry; the JP entry is 128x250, so
`assets/battle.png` was drawn over the JP export.

`images.tsv` declares all seven replacements. The build invokes the shared
`src/pipeline/image_replacements.py` compiler and verifies its output after
assembly. The compiler replaces matching walk pages across 215 scene entries,
encodes changed entries in parallel, and caches the verified archive under
`build/step_cache/images/black-mark/`. Unchanged builds reuse it. Patch layers
carry prepared MES entry edits, so patch application only checks and packs
encoded entries. Reference exports use the same declarations and shared compiler.
