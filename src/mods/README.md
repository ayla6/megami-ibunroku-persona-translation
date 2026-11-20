# Mods

Each folder here is one mod, named after it (`Unified save menu` ->
`unified-save-menu/`). A folder holds everything that is only that mod's:
its assembly (one file per overlay it patches) and `asm.tsv`, which says
where each line goes in which disc file's block - `build/main.asm` is
written from the mods that are on (`src/pipeline/asm_main.py` documents the
columns), so a mod that is off is simply not in it - the generators it alone
uses, its files that are not code in `assets/` (art, fonts, movie frames),
its README, and `mod.tsv` - its label, name, description, requirements,
choices and whether it is on by default (`src/pipeline/mods.py` documents
every key).

Four mods are always on, in tiers (docs/MOD_ENGINE.md):

- `base`: the language-neutral engine - the disc files' blocks
  (`asm/files.tsv`), the shared definitions (`asm/common/`), every overlay's `feature.asm`, the bounded
  and relocated text, the free space;
- `latin-alphabet` (requires base): what an alphabet needs - the VWF
  engines and small-font kit (`asm/vwf/`), full-length names and the other
  longer-text mechanics, the glyph pacing, the Latin name entry
  (`asm/name/`, `asm/namedt/`) and the fonts (`assets/fonts/`);
- `fmv-translation` (requires base): the movie renderer that draws the
  subtitles and the translated movie text - a marker, never picked: on when
  English's movie subtitles or movie text (or Skip movies) require it;
- `english-translation` (requires base and alphabet): the English - its staff-roll
  pages (`asm/end_exe/`), its movie data (`fmv/`, the subtitle face), and
  translation/, which stays at the top of the repository.

Mods that patch the game's code require base, and the ones that change
text or menus require english; a mod that only replaces files (Black Mark,
the English dub) requires nothing. Mods are applied after the mods they
require, by name among equals - there is no typed order.

A mod's choices are named in parentheses after it:
`--mods='english-translation(font=small,subtitles=off)'` (quote it for the
shell); `--mods=list` lists every mod and choice.

`python src/pipeline/build.py` builds `english-translation` alone;
`--mods=LABEL,...` builds exactly the named mods and what they require
(a space instead of `=` works too). `base`, `latin-alphabet` and
`english-translation` are mods like the others: `--mods=60-fps` builds 60 fps
on the base alone, `--mods=english-translation,60-fps` the translation with
60 fps. Every build is written to `dist/Persona-TL.bin/.cue`.

`build/` is shared and holds whichever variant was built last (armips
rewrites every overlay from `data/psx/` on each run, so enabled and disabled
variants do not inherit patch bytes from each other).

A mod's block never claims a fixed window behind an image: it is placed
after the last blob that owns the overlay's extension, with its bounds
asserted at assembly time (`.error`), so an overlap is a build error, never a
crash in game. `tools/tests/test_mod_write_guard.py` assembles the real
`build/main.asm` for the base, every mod on its own and all together - each
with the markers it needs, with the movie renderer and without it - then runs
the write guard the release uses.

How mods become release layers, and where the format is going:
`docs/MOD_ENGINE.md`.
