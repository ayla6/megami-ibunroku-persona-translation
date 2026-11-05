# Small-font artwork

- `smallfont_page_modified.png`: **editable Latin-only regular face**, 14
  columns of 8×12 cells, the same cell order as the compact sheet. This is the
  proportional face the VWF draws; redraw its ink freely; builds derive the
  shadow. The retail page keeps the kana cells and fixed-cell UI, so there is
  nothing else to carry here. (A legacy full-page 256×256 form is still read:
  its first 84 rows are used as the whole text band.)
- `smallfont_page_compact.png`: **editable 112×60 Latin-only compact face**,
  14 columns of 8×12 cells. This is the stage-3 face: narrower than the
  regular one and drawn as its own art, never squeezed from the regular
  advances. Redraw its ink freely; builds derive the shadow. Keep the
  existing retail palette. Space is measured separately, not drawn.

Both sheets list their glyphs in `build/smallfont_compact_cells.tsv`
(character, code, sheet cell, and the page cell each face is drawn into).
Missing glyphs fail the build; wording is never shortened.

A missing compact sheet is seeded with intact regular glyphs, without
resampling, merging or dropping columns. It is an editing template, not an
automatically finished compact font. Existing compact artwork is never replaced.

`python3 src/injection_tools/smallfont_vwf.py variants` writes the character/
code/sheet-cell index and the page cell each face lands in to
`build/smallfont_compact_cells.tsv`. It creates the sheet only when it is
missing and never overwrites authored art. The compact sheet uses only letters,
digits and punctuation; there is no need to redraw Japanese cells or UI
artwork.

Check live measurements without rebuilding the game:

```sh
python3 src/injection_tools/smallfont_vwf.py names --items-only --over
```

Omit `--over` for all names, or omit `--items-only` to include demons. Output
is TSV, suitable for a spreadsheet. Stages are **1 normal**, **2 narrow
spaces only**, **3 compact artwork**. All three widths are shown; signed
`*_spare` columns report pixels left (negative means over budget). Both faces
keep a 1px letter gap; stage 2 uses 2px word spaces and stage 3 uses 1px
(4 >> stage). Widths include the
trailing gap, so the 80px advance budget is 79px of ink. Missing glyphs fail
the build; wording is never shortened.

The primary full-height menu page carries original fixed-cell artwork plus
both proportional Latin faces. Both faces live in text-band cells the
translated game never prints as kana, inside the 84 rows every page copy
already receives; the ASCII, blank-space, lowercase-extension and punctuation
fallback cells stay retail. Map-specific and OPEN page copies therefore carry
the same faces without a whole-page overwrite, preserving their distinct
bitmap/palette data. Battle's 128px-high page retains its existing
proportional face; it does not load the field-menu variants.
