# Local data and generated mappings

`data/` is local input and is never tracked. Provide your own game files.

`python tools/prepare_data.py` finds PSX Rev 0/Rev 1 images and PSP JP/US ISOs
anywhere under `data/discs/` and fills the matching trees below. Identification
comes from the image itself (size/CRC32 for PSX, ISO9660 plus
`PSP_GAME/PARAM.SFO` DISC_ID for PSP), never from the file name. Run it with
`--list` to see what was recognized, `--only KIND` to extract one kind, or
`--force` to redo a complete tree. The build performs the same discovery for
the PSX image and for `psp_us` when porting, so placing the discs in
`data/discs/` is enough for a normal build.

| Path | Contents | Tracking |
|---|---|---|
| `cache/` | BOOT bank chains, BE records, decoded tables | ignored; rebuildable |
| `extracted_text/` | one canonical decoded TSV per real game file | ignored; rebuildable |
| `psx/`, `psx_rev1/`, `psp_us/`, `psp_jp/`, `discs/` | local game files/images | ignored; provide your own |
| `fonts/smallfont_page_retail.png` | retail font reference, written by `smallfont_vwf.py` | ignored; rebuildable |

Authored extraction and alignment inputs are **source**, not generated
mappings: `src/extraction_tools/psp_glyphs.tsv` is the authoritative PSP
character table, and `src/extraction_tools/matching/*.tsv` holds reviewed
structural correspondences. Their producers and consumers are in
[MAPPINGS.md](MAPPINGS.md). Manual wording lives in `translation/manual/`,
including `terms.tsv`. Never regenerate these source files as caches.

Generated alignments, split maps, labels and PSP pairs live in
`translation/generated_mappings/`. Those snapshots are tracked so the project
is shareable; other products of `build/` stay local. The modified small-font
sheet and FMV assets are maintained in `src/assets/`.

`port.py` and `build.py` bootstrap missing generated mappings. This requires the
local game trees and authored source inputs, not just Python sources. Bootstrap
must fail visibly if inputs are missing; it must never invent correspondences.
See [DEVELOPMENT.md](../DEVELOPMENT.md) for the workflows.
