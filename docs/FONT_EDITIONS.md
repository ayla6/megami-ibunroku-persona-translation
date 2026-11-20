# The dialogue font has two editions

The English dialogue font (`vwf_*`, the proportional face all boxed text is
drawn in) exists in **two editions**. Every layout rule is the same in both;
only the glyph widths differ, so the same wording breaks, fills and paginates
differently. Anything that lays out, measures or draws text is only correct
when it is correct in **both**.

| edition | sheet | note |
| --- | --- | --- |
| `large` | `sheet.png` | **the default**; the release's pretty face |
| `small` | `small_serif.png` | narrower glyphs; fewer boxes and scrolls |

This is *not* `docs/SMALLFONT.md`. That page is the retail 8x12 **menu** font
(items, skill names, battle panels, name entry). This page is the dialogue
VWF face only.

## Picking an edition

The edition is `toolpath.FONT_EDITION`, read once from `PERSONA_FONT`:

| how | value |
| --- | --- |
| environment (every tool) | `PERSONA_FONT=small python3 <tool> ...`; unset means `large` |
| build | `python3 src/pipeline/build.py ... --mods='english-translation(font=small)'` |
| tests | `python3 tools/run_tests.py '<glob>'`; with `PERSONA_FONT` unset it uses the edition in `build/font_edition` (what `build/` was last assembled in) |
| textview | `--edition=large`, `--edition=small` or `--edition=both` |
| textvis / textvis server | `edition=large` / `edition=small` query or body field |

`english-translation/mod.tsv` owns the group: `font=large` is listed first, so
it is the default when the build names nothing. `--mods=list` prints it.

The build writes the edition it used to `build/font_edition`. That file is a
build record, not a preference: it can be stale after a checkout or an
aborted build, so do not read it as "the edition we care about". Pass
`PERSONA_FONT` explicitly when a result must be tied to one face.

Built discs carry the edition in the name:

| edition | plain | with mods | engine-only |
| --- | --- | --- | --- |
| `large` | `dist/Persona-TL.bin` | `dist/Persona-TL-mods.bin` | `dist/Persona-engine.bin` |
| `small` | `dist/Persona-TL-small.bin` | `dist/Persona-TL-mods-small.bin` | `dist/Persona-engine-small.bin` |

## Files

Inputs (hand-drawn sheets) and generated outputs live together in
`src/mods/latin-alphabet/assets/fonts/`:

```
sheet-characters.tsv                      one cell label per character, one row per line
sheet.png            small_serif.png          the two faces
vwf_font_<edition>.bin     glyph rows
vwf_width_<edition>.bin    pen advance per character
vwf_index_<edition>.bin    u16 offset into FONT.BIN
vwf_glyphs_<edition>.asm   armips: store the rows in free FONT.BIN slots
vwf_preview_<edition>.png  drawn preview (not assembled)
```

`src/injection/fonts/make_vwf_font.py` builds **both** editions on every run;
`make_vwf_font.py verify` checks the edition being built. A disc carries one
edition (both use the same free slots). `toolpath.font_path(kind, edition)`
is the one place those filenames are spelled. Allocation uses the repository
translation corpus, including drafts and runtime names, for every build mode;
`PERSONA_TRANSLATION` overrides do not repack the shared glyph assets.
Generation leaves matching output bytes and timestamps untouched.

## Editing the sheet

The `characters` column in `sheet-characters.tsv` follows the art cell by cell.
Each physical TSV line describes a row of 8 × 16 pixel cells in both images.
A space skips an empty cell. To move a glyph, move its character and the
corresponding art in both faces. To add symbols, draw each one in both faces
and add the characters at those positions in the list.

ASCII and existing symbols keep their codes. The first four additional
characters use one-byte codes EC–EF. Remaining characters use two-byte codes
from `reclaimed-kanji.tsv`. The listed atlas cells were screened against the
extracted PSX text and current translation sources. Only cells assigned to a
sheet label are replaced. Keep the list in order to preserve code assignments.

An opaque white vertical line in an RGBA sheet counts as its cell's last ink column
for spacing, including the usual one-pixel gap. Put it to the right of the ink.
The line itself is never drawn. Transparent space before ink still sets the left bearing.
Without a marker, the advance is the last ink column plus the usual spacing.
Both the assembler and Textvis use these widths. Rebuild the font and restart
Textvis after changing the sheet's character list. Fixed menu fonts and the
short one-byte-only field title format have their own encoding limits.

## Rows carry both layouts

A porter lays each row out once per edition and writes both layouts into the
one `en` cell (`vwf_wrap.merge_editions`):

- a separator both editions agree on stays plain: `<FF03>`, a space, ...
- where they differ, each edition's codes carry its letter: `<LFF03>` is a
  break only `large` makes, `<SFF03>` only `small` (pages and waits too:
  `<LFF02><LFF04>` is a box turn only `large` takes). Inside one separator
  the codes both share stay plain and only the difference is lettered;
- wording only one edition has is a span, `<L{>...<}>` / `<S{>...<}>` (an
  erratum marked for one face, or a layout's own ` - `).

`vwf_wrap.ROW_EDITION` is `large`: it anchors the merge. A row whose layouts
cannot be written that way keeps the `large` layout for both.

Read one edition back with `vwf_wrap.edition_text(en, edition)`;
`vwf_wrap.per_edition(fn, en)` runs `fn` per edition and merges the results;
`vwf_wrap.measured_as(edition)` is the context manager for ad-hoc measuring.
`text_width`, `etext.encode` and the QA gate all resolve the edition first, so
never measure a stored row without it. A reader gets rows as the edition being
built reads them (`toolbelt.read_generated`, `read_manual`, `merged_rows`);
the writers read the cell as stored.

Every family porter lays out every edition: `port_story` in one run (workers
start in each face), `port.py` once in the `small` face into
`build/edition-translation/small` and once normally, with
`toolbelt.upsert_generated` writing both. A redrawn glyph changes widths, so
it needs a re-port: `python3 src/pipeline/build.py --port`.

## Checking a change

There is no single-edition answer, so check both:

```sh
# both faces, the layout tests (runs in the edition build/ was built in, or
# set PERSONA_FONT explicitly):
PERSONA_FONT=large python3 tools/run_tests.py 'test_typography.py'
PERSONA_FONT=small python3 tools/run_tests.py 'test_typography.py'
```

```sh
# one stored row as each edition reads it
python3 - <<'EOF'
import sys
sys.path.insert(0, 'src')
import toolpath
import vwf_wrap as w
line = open('translation/generated/ADV/E0.tsv', encoding='utf-8').readlines()[1]
en = line.rstrip('\n').split('\t')[3]
for edition in toolpath.FONT_EDITIONS:
    print(edition, w.edition_text(en, edition))
EOF
```

For a corpus-wide before/after, compare `vwf_wrap.edition_text(row, e)` for
`e` in `toolpath.FONT_EDITIONS`, not the stored cell: a lettered `<LFF03>` in
one edition is a space or another break in the other, and counting the raw
cell mixes the two layouts. Expected for a pure wrapping change: no row gains
a box in either edition; inside the three-line box a row may save a line.
