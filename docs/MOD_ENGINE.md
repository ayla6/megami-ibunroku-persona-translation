# The mod engine: direction and plan

The patch is going to become an **engine for an English-translatable Persona 1**:
a base patch that turns the retail game into something a language can be poured
into, with the translation as its first mod and every enhancement as a mod
after it. This file records that direction - what has been decided, why, and
the order the work goes in. It describes a plan; what is built today is
described where noted ("today"), and the docs it links to.

Nothing here is meant only for the end user. The project is also meant to be
fun to extend: modular, capable of taking new things, even ones nobody may
ever ask for (a Portuguese translation, a Korean one).

## Layers

1. **Base.** Language-neutral hooks, bounds, relocated-text mechanics and
   disc layout, applied to retail Rev 0.
2. **Latin alphabet.** Variable-width renderers, font machinery, extended
   names and Latin name entry. It requires base and contains no English
   wording.
3. **English translation.** The English text, its used glyphs, name tables,
   message entries and label artwork. It requires the alphabet. The page
   enables it by default and shows its recommendation warning when disabled.
4. **Mods.** Each option declares its dependencies in `mod.tsv`; `asm.tsv`
   places its assembly, and `asm_main.py` writes `build/main.asm` from the
   selected components. A mod can require base, alphabet or English according
   to its actual code, memory and text dependencies.

Separation test: the engine alone, without the translation, should boot and
play. Where it does not, an engine piece assumes something about the language,
and that is the line to fix.

The engine is split by script and language into dependency-ordered release layers:

| tier | holds |
|---|---|
| **base** (`src/mods/base`) | the language-neutral engine: hooks, relocated text, file layout, viewports that grow, the free-space registry |
| **Latin alphabet** (`src/mods/latin-alphabet`, requires base) | the VWF renderers and the small-font kit, the longer-text mechanics, Latin glyph pages, 8-character player names, ABC-only name entry, western name order |
| **English** (`src/mods/english-translation`, requires Latin alphabet) | the wording, the glyph set it uses, its label art |

A kanji or kana language needs none of the alphabet tier; Portuguese or Spanish
needs all of it. Western name order is a convention of the languages, not
the script, but every Latin-script language this would get uses it.

### The engine build (today)

A build whose `--mods` leaves out `english-translation` (`build.py --mods=latin-alphabet,...`; the release tools pass `--engine-only`) builds the engine alone: every tool reads
`build/engine-translation`, translation/ with its English emptied
(`src/pipeline/engine_translation.py`: the `en` and `note` columns, and the
`text` column of the ending pages and movie subtitles), so each row falls
back to its Japanese as an untranslated row does. translation/ is named in
one place, `toolpath.TRANSLATION` (`PERSONA_TRANSLATION` overrides it), which
is what makes the switch possible. This build contains base and alphabet.

One that also leaves out `latin-alphabet` (`--mods=60-fps`; the release tools pass `--base-only`) also omits the alphabet assembly and disables its
small-font gates. The name-entry binaries remain byte-identical to retail;
the overlay census checks that alphabet-owned hooks remain retail too.
Language-neutral relocation and bounds checks remain installed.

The rule every tool follows: **a row, label or slot with no English keeps
its retail bytes**, and a family with nothing translated changes nothing.
Applied to menu and name-entry label art, party names, battle boards,
battle UI labels and personalities, CONTACT commands, and story-battle text.
Untranslated CONTACT and negotiation strings are repacked as retail bytes;
direct retail readers keep their original addresses. When no story-battle
message has English, the decoder passes native Japanese through and the
messages displaced by its code live at the bounded end of the battle data
extension. Both halves of code references follow those relocated messages.
Negotiation allocations are checked against that reservation.

The battle boards' ownership directory uses reclaimed text when available,
and otherwise the freed glyph function after the original-font ranges.
Assembly bounds both homes. Menu button and battle status wording comes
from translation/manual/terms.tsv; an empty entry retains its retail art.

The release writes `base.p1mod` from retail to the base-only build,
`latin-alphabet.p1mod` from that build to the engine-with-alphabet build,
and `english-translation.p1mod` from that build to English. Production builds native trees needed for each layer, supported tier, choice
and overlapping compatibility pair. Owning mods declare known higher-order
interactions in `compatibility.tsv`. Default release verification compares foundations,
combined sets and discovered interactions, and checks browser/standalone
disc/PPF parity before marking the release `verified`. In-game evidence is
tracked separately. `--no-verify-release` produces files marked `untested`.

### Preparation ownership

`english-translation/preparation.tsv` owns the translation compilation order,
porting and source QA; `translation_preparation.py` validates and executes it
and owns movie-text preparation. `latin-alphabet/alphabet_preparation.py` owns
cached character-table and font generation. `build.py` coordinates their
cached preparation and subsequent assembly rather than listing text-family
commands. Shared file-format encoders stay under `src/injection`: they also
support native rows and are not copies of English-specific implementations.

The native tiers consume the same compiler recipe against the blank-English
provider described above. This still shares the translation table structure;
it is not an independent native-only asset pipeline. Source QA is deferred
by `--no-verify`, while builder bounds, assembler errors and write guards
remain active. The preparation cache keys verified and unchecked products
separately. The early small-font generation supplies widths, and the final
one regenerates the affinity pool after its wording inputs are finalized.

## The engine owns free space

Allocation must be deterministic for identical input data, font, components,
mods and choices. A different configuration may repack the free areas.
Within one configuration, use stable source order and explicit size/address
tie-breaks; hash iteration order, process identity and random choices must
not rank candidate homes. Determinism QA compares clean builds from separate
Python hash seeds, including their game files, symbol addresses and final
disc bytes.

Mods ask the engine for space instead of hardcoding addresses, and the
translation receives its text space the same way. If a mod truly needs space
freed by another component and no independent allocation works, declare that
component in its mod.tsv requires rows; the patcher enables the dependency. Pools today: reclaimed code
(unreachable debug paths, e.g. the battle entry's "SND INIT" dump that
`--mods=restore-formation-after-ambushes` lives in), the ADV text spill zone, BTLP's reclaimed
negotiation text, the free FONT.BIN slots. `write_guard.py` and
`scratch_map.py` already know most of this; they become the registry.

Why: `--mods=restore-formation-after-ambushes` needed 98 bytes, and the first home tried (a reservation
inside the reclaimed negotiation text) pushed 100 bytes of text into a tail
that runs into the sound-work buffer. Nothing could answer "where is free";
the engine should.

## The patch format

The release is P1MOD layers (xdelta is gone): a layer carries **file
changes**, not disc bytes. A raw PS1 sector carries its own EDC/ECC, so a
raw-disc patch carries checksums for one exact set of options - that is what
forced the old xdelta release into partner encodings, a fixed solver order,
size changers applied first and a low-RAM mode. Layers have none of that:

- an engine or mod is a set of edits per disc file ("in file X, these bytes",
  and for the containers it understands, entries - below);
- the patcher reads the ISO9660 tree from the player's disc, **merges every
  selected layer's edits in memory first**, plans the layout once (files that
  grow are relocated into freed extents; the ISO records and the game's own
  FNAME / FSECT / FSIZE.DAT tables follow) and writes each changed sector once
  with fresh EDC/ECC;
- the result is the set of sectors that differ from the player's disc: a disc
  (the player's own file with those sectors in between) or a PPF of them.

Only the original Rev 0 disc is patched. A Rev 1 disc is named and refused:
converting it would need the whole Rev 0 layout rebuilt in the browser, too
much work for a disc anyone can replace with the right one.

### Today

- **Format P1MOD 1** (`src/pipeline/modpack.py`, the reference;
  `webpatcher/modpack.js`, its browser twin). One file per mod. It opens
  with a readable manifest in plain text, so one found on its own says what
  it is: its name, title, description, the release it belongs to (`version`,
  written when the release is published), the source it was built from (the
  short commit hash, `-dirty` with uncommitted changes), the mods it
  requires, its choices, then its **parts**: each a condition and one row
  per file the part changes, with the file's length before and after. Same-size
  byte edits preserve the existing file extent when their writes fit. A
  `--` line follows, then one raw LZMA1 stream of the rest: per part, `check`
  rows (the SHA-1 a file must have before the part edits it), `bytes` rows
  (offset and length) and their payload. All of a mod's parts share the
  stream, so what two of them have in common (the two font editions of the
  translation) is stored once in effect. LZMA finds repeats anywhere in the
  payload (Mark's walk sheets: 7.6 MB with gzip, about 0.2 MB with LZMA);
  compression uses LZMA preset 6, with the same raw stream and decoder settings;
  the page decodes it with `lzma.js`, the decoder it already had for CHDs. A
  layer is reproducible byte for byte. Movies are edited as raw 2352-byte
  sectors. FNAME / FSECT / FSIZE.DAT belong to the layout and are refused in
  a layer; the game looks files up by name (`CdSearchFileLoc`), so the
  layout updates them by name.
  Layers and release manifests use SHA-1.

  Base checks the original files consumed by the foundation layers before
  applying any edits. Latin Alphabet and English then apply their changes
  over the selected Base options. Their validity does not depend on the
  default Base output remaining byte-identical.
- **Prepared archive entries.** `src/pipeline/file_formats.tsv` registers
  `ADV/MES.BIN` as a sector-table container. Its packed `mes-entry` rows hold
  path, entry index, payload length and the source entry's SHA-1, followed by
  the already encoded payload. Applying one checks that entry, preserves
  extents when it fits, or rebuilds the sector table once in entry order with
  zero padding. Different entries compose even if an earlier edit relocates
  them; competing edits to the same source entry are refused. Python, the
  standalone applier and the browser use the same operation. PNG mapping and
  game compression happen during the build, never during patch application.
- **Numeric settings.** A `range` mod.tsv row declares key, minimum, maximum,
  step, default, display name and the builder's TSV edit map. A layer's readable
  `range` row stores `key`, `min,max,step,default` and display name. Its packed
  `scale` rows store file path, offset, parameter key and original unsigned byte.
  Percentage writes use integer rounding `(original * value + 50) // 100`,
  retaining a minimum of 1 for nonzero inputs and mapping zero percent to 0.
  Python, the standalone applier and JavaScript materialize these writes after
  static spans. They validate bounds and step and never mutate stored originals.
  Builders emit the edit map once; ranges do not enumerate a layer per value.
  Static maps may live in the mod itself. The shared native build writer uses
  the same transforms after mod construction; an original value of 100 stores
  the selected integer directly. Run in Dungeons uses this for its 2–4 speed
  byte, while menu sounds use percentage scaling.
- **Following ranges.** A range row may end with `follows=KEY`, naming an
  earlier range of the same mod that follows nothing itself. A build that
  does not name the follower gives it the followed range's value (the
  nearest allowed one). On the page the follower moves with the followed
  slider while the two are equal; set to a value of its own it keeps it
  until it is set back. Only the page and the build read it (features.js);
  a layer's `range` rows stay as they are. Battle speedup's `skills`,
  `actions` and `entry` follow its `speed`, which writes no byte itself.
- **Growth is not an edit.** A layer that makes a file longer records only
  the data it puts past the old end, never the zero padding; growing extends
  a file only when it is shorter, and only a shrinking layer truncates one.
  Two options that each grow a file to reach their own code never cut off or
  zero out each other's (`60-fps` and `psp-items-and-skills` both grow S2D.BIN, `run-in-dungeons` and
  `psp-items-and-skills` DNG.BIN, `unified-save-menu` and `psp-items-and-skills` OPEN.EXE).
- **Exact records.** A written file's ISO record carries its exact byte
  length and untouched files keep retail's records; FSIZE.DAT keeps whole
  sectors, the game's own convention. (The xdelta release rounded every
  record up to whole sectors so directory sectors stayed identical across
  combinations; layers lay the disc out once, after the merge, so nothing
  needs that.)
- **Verification.** The base layer checks every file it changes against the
  original disc's SHA-1. The release builder (`tools/build_patches.py`,
  BUILD_PIPELINE.md) builds every variant's tree without making a disc,
  diffs each mod against the base tree, checks that every mod at once equals
  its layers merged - at the default choices and again with each other
  choice - and has the browser applier lay out one
  disc that must match `build_disc.py`'s byte for byte.
- **Parts for other mods.** Mod pairs whose layers write the same bytes are
  built together; where the pair differs from base + a + b, the difference
  ships as a part of the later mod, applied when the earlier one is on
  (`battle-speedup` + `fast-forward-battle-animations`: both rewrite the frame function,
  and with both on only fast-forward's rewrite, which runs the speeds too, is assembled). Each one is an interaction still
  to remove (below). The same goes for a choice of another mod: a mod whose
  layer, made over the large-font translation, does not give the small-font
  build gets a part applied while `english-translation(font=small)` is on.
- **Mods, requirements and the release version.** Every mod is a folder
  under `src/mods/` named after it, holding its assembly, its own generators,
  its non-code files in `assets/`, and `mod.tsv` (read by
  `src/pipeline/mods.py`): label, name, description, `requires LABEL` rows,
  its choices, and whether it is always on. A mod has no version of its own:
  a release is one build of every mod, and `tools/publish_patches.py`
  writes the release into the manifest's `version` column and every layer's
  `version` row when it publishes. `base` (the engine, with the disc files' blocks, `asm/files.tsv`),
  `latin-alphabet` and `english-translation` are mods too, always on (`fmv-translation` is a marker); the page ticks a
  mod's requirements with it and locks them while enabled mods need them.
  Dependencies are blue whether checked or unchecked; blue takes priority
  over the yellow selection border.
  Base and alphabet have their own layers. The FMV marker has
  no layer: its bytes ride in the parts of the component that enables it. Apply order is not typed: a mod comes after the mods it requires,
  then by name.
- **Your own mods on the page.** "Your own mods" loads `.p1mod` layers from
  files and keeps them in the browser (IndexedDB, store `mods`), each with an
  on box and Remove. They apply after the release's mods at their default
  choices, without a manifest hash. A layer whose `version` names another
  release is shown with a warning, and a requirement that the selection leaves
  out is refused. A layer named like one of the release's own mods is refused.

## A mod's own Japanese

A mod that adds words has them before any translation: its Japanese.
`src/mods/<mod>/text.tsv` (`rel pos ja note`) gives the Japanese for the
text positions the mod takes over (psp-items-and-skills: the unused item and
skill records it reuses, their descriptions); `src/mods/<mod>/terms.tsv`
(`domain key ja note`) gives it for terms (run-in-dungeons: the run action's
name). Every builder reads it through the one read path: a row with no
English (`toolbelt.merged_rows`) or a term with none (`strlib.glossary`)
reads the mod's Japanese. So the Japanese ships where the build has no
English (the engine alone, a mod's layer without the translation), and the
English wins wherever it exists. Two mods never give one position or term.
The Japanese is fixed text, not a porter draft: one that does not fit its
field fails the build (descs.py), and a shortened one carries its full
draft in an `over limit ...; <draft>` note. Item and skill names are one byte
per glyph, so they are kana (`items.is_kana`); PSP-JP's kanji names are
written in kana there.

## Mod choices and parts

An optional `author` row in `mod.tsv` credits the mod creator. The patcher
shows it in the mod info button and hover description; imported mods show
the credit in their list entry. The author also travels in the `.p1mod` metadata.

A mod's choices are rows in its `mod.tsv`:

- `option GROUP KEY NAME DESCRIPTION`: within a group one key is on at a
  time, the group's first by default (english: `font` = `large` / `small`,
  the font editions, docs/TEXT_LAYOUT_SPEC.md "Font editions");
- `extra KEY NAME DESCRIPTION`: an additive part of the mod, off by default.

Either may end with `requires=SLUG,...`: the mods that choice needs.
English's groups today: `font` (`large` / `small`) and `subtitles` (`on` /
`off`: the spoken lines of the movies), whose `on` requires
`fmv-translation`. Whenever the movie renderer is on, its movie text (the
opening quote, the ending poems) is English - that is not a choice. With the
English dub on, the subtitles are the dub-timed ones; they stay in the
translation.

A **marker** (`marker yes` in mod.tsv) is a mod that is only ever a
dependency: it does nothing useful by itself, so it is never picked - not on
the page, not by name in a build - and is on exactly when a mod or a picked
choice requires it (`mods.with_needs`). `fmv-translation`, the movie renderer, is one:
without subtitles or movie text to draw it shows nothing. Skip movies
requires it too, for the home of its stub (padding only the renderer's
blob makes loadable).

Two rows are only for the page. `warning TEXT`, once, is what it says when the
mod is turned off (the translation's). `integrates SLUG TEXT`, any number of
times, names something the mod genuinely does with another mod, or with one
of its choices (`english-translation(subtitles=on)`). A compatibility part is
not one. The page shows these dependency notes in the mod's info panel, with an
Enable button while the other side is off. The info button works on mobile.

On the page, **Mods** is a row of toggles. Required dependencies are checked,
shown in another colour and disabled while enabled mods need them. An
automatically enabled dependency goes off when nothing needs it; a dependency
selected manually stays on and becomes editable again. Uploaded mods also
lock their dependencies, including other uploaded mods. **Settings** shows choices only for enabled
mods that have them. English can be turned off when no enabled mod requires
it; its recommendation warning then appears. Base is always checked and locked.

A build names them on the mod: `build.py --mods='english-translation(font=small),60-fps'`
(an always-on mod is named only for its choices). What a mod needs because
ANOTHER mod is on is never named: the release finds it and ships it as a part.

Every part of a mod's layer has a condition written the same way: `-`
(whenever the mod is on: the mod at its defaults), `english-translation(font=small)`
(what that choice changes over the defaults), `english-translation(font=small,subtitles=off)`
(what two choices change together beyond their own parts, where they
interact), `battle-speedup`. The page shows
each mod's choices under it (a radio per option, a box per extra; the base
translation's at the top), sends the selection - `{label: picked tokens}` -
to the worker, and the worker applies every part whose condition holds.

Still to come with this: a more compact mod picker; three or more of one
mod's non-default choices at once are not built by the release (each one
alone and every pair are); and a marker with a layer of its own (today `fmv-translation`
has none: its bytes ride in the parts of what turns it on).

## Homes that do not depend on the selection

Half the point of layers is not needing fix-up patches for options that have
nothing to do with each other. Two rules get there:

1. **A selection-independent allocator at build time.** Options that share
   free space today take turns at it, so where each lands depends on which
   others are on. Instead, every build plans a home for every option -
   including the ones that are off - from the engine's registry of free
   space (`write_guard.py` and `scratch_map.py` already know most of it), so
   an option's address is the same in every variant and its layer is
   additive by construction. Nothing is typed by hand; the registry decides.
2. **Runtime checks for real overlaps.** Where one option changes code
   another rewrites, the rewrite keeps the changed instruction at its
   address and reads it at runtime: battle-speedup's speeds are bytes in
   fast-forward's frame engine (`ff_vars`, a fixed address) that the frame
   reads every tick, so the speed setting is a byte edit, not a rebuild.

## Relocatable blocks (custom mods)

For mods made outside this project the allocator cannot know them in
advance, so placement moves to apply time, like a linker:

- a layer can carry **blocks**: "N bytes of code in BTLP's memory, preferred
  at 0x..., with these relocations", besides its fixed edits (the hooks into
  retail code);
- the engine publishes its free pools in the base layer - free while the
  game runs, which only the engine knows, never guessed from bytes that
  happen to be zero on the disc;
- the patcher gives each block its preferred address when it is free (the
  fast path, nothing to rewrite) and otherwise another free spot, patching
  its relocations - so two mods written by different people coexist without
  knowing about each other;
- relocations are found without hand work: assemble the block at two
  different bases and compare - every word that differs is a reference to
  the block, and by how much says what kind (`jal` / `j` target, `lui` +
  `addiu` pair, 32-bit pointer), hooks in retail code included.

Our own options get preferred places from the build-time allocator that never
collide, so the release always takes the fast path. All of this is
arithmetic on byte arrays; it runs in the browser in milliseconds.

## Understanding the formats

Image mods declare `images.tsv` beside `mod.tsv`. Its columns are `file`,
`format`, `entry`, `member`, `image`, `mode`, `width`, `height`; PNG paths are
relative to the mod's `assets/`. The shared compiler
`src/pipeline/image_replacements.py` handles fixed BST slots, battle members
located through their sector table, TIMs at explicit offsets, matching TIM
pages inside MES entries, and headerless compressed indexed images.
`indexed` maps transparent PNGs into the page palette; `black-matte` replaces
opaque 16bpp art. Headerless images require explicit dimensions. Black Mark
declares its seven images here; Western Controls declares its existing
choice-menu indicator. The existing controller-page UV mappings stay in
assembly. The shared menu button cells are remapped at initialization for
TYPE 1 in ADV, DNG and S2D, including the Velvet Room Persona-list hint.
Western Controls owns a physical-input entry point and the casino call-site
integration in its own folder. Casino controls and printed button names remain
native for both controller types. Dialogue renders physical button symbols
unchanged; no global text substitution reaches into the alphabet renderer.

Controller settings compensate their cell indices using the initialized
table's actual artwork, keeping their physical-key legends in retail order
even when the controller type changes or the page is reopened.

MES page identity comes from the original declared entry/member and matches
every exact copy automatically. Changed entries are encoded in parallel,
round-trip checked, then packed in source order. Unchanged entries retain
their original encoded bytes. A verified cache is keyed on source bytes,
declarations, assets and compiler inputs. Conflicting changes inside the same
MES entry still need a finer operation; entry edits do not claim to combine
individual TIM changes within one compressed stream.

File-targeted edits are good; edits that understand the format they patch are
better. A content entry says "event bank E0, message 1163 is this", and the
patcher knows the container - its pointer table, its packing - and repacks it.
Two mods that change different messages of one file then never conflict, even
though every byte after the first edit moves.

Entries are shipped **almost final**: the expensive work stays at build time in
Python (porting, wrapping, VWF glyph encoding, pagination), and the entry
carries the encoded message plus the slot it fills. The patcher only does the
container's mechanics, which are small. A mod written as plain text would need
an encoder in JavaScript (easy) and either a wrapper or hand-placed breaks.

Worth understanding first: the ADV event banks and TALK packs (most of the
script), the system messages, images inside archives (Mark's sheets in
MES.BIN), XA audio as whole files. Some text stays bytes owned by the engine:
BTLP's negotiation text is packed into reclaimed code space by `btlp.py`, which
today decides both where the space is and what goes in it - in the engine,
the space is the engine's and the text is the translation's.

## Fonts and languages

Today: the dialogue font is exactly ASCII 0x20-0x7E, one byte per character,
its glyphs stored in the free FONT.BIN slots (1344 bytes, so only glyphs the
translation prints are stored). Anything else falls back to the Japanese 16 px
font - that is why non-ASCII is a mess.

Direction:

- **The engine renders glyph indices**, not ASCII. The font - glyph sheet,
  widths, and the character-to-code table - belongs to the language mod, so a
  language with accents (Portuguese: á à â ã é ê í ó ô õ ú ç and capitals)
  keeps the variable width and spacing the English has.
- **Glyph space comes from the Japanese font.** No Japanese text is left on
  screen: the script is translated, name entry no longer shows kana (removed
  on purpose - Japanese glyphs sit oddly beside English, whose line rides
  higher to leave room for descenders), and the only Japanese left in the data
  is debug material that is never drawn. A few full-width symbols are still
  shown (the fancy parentheses and similar); they keep their slots, and every
  other slot of the Japanese font is free. The build knows every glyph code
  the shipped text, menus and UI print, so it can claim the rest and fail if a
  reclaimed glyph is still used.
- **The renderer is an engine component.** The VWF is necessary for the
  English, but a language with different needs (Korean: two-byte codes, many
  glyphs) could bring its own renderer.

## Two editions: large and small font

A second English edition with a smaller dialogue font, to have fewer boxes
that need a fourth line (a box cannot show four lines, so a smaller font is the
only lever). From early testing it does not remove many of the boxes that
scroll, but it helps. Both editions come out of the same build.

Most breaks are not hand-written: `vwf_wrap` places them from the font's width
table, so the small edition is the same translation laid out a second time
with the small font's widths. The flow, inside the single write of each row
(rows are written once - see AGENTS.md; no pass rewrites them afterwards):

1. port the row once;
2. apply what is true for every edition (names spelled the way the PSX version
   spells them, and the other shared rules);
3. wrap it twice, once per font profile;
4. merge: a break both editions agree on stays a plain code; a break only one
   has gets an edition prefix (`L` for large, `S` for small);
5. at injection each edition drops the other's codes and encodes its own as
   ordinary breaks - the game never sees an `L` or `S`.

Before building it, measure it: run the wrapper over the whole script with
the small font's widths and count, per edition, the boxes that still need a
fourth line or an extra page. A smaller font only saves lines where a box is
limited by width, not where it holds four sentences or forced breaks.

## Order of work

1. Done: file-level layers, merge-then-write patcher (`modpack.js`), PPF and
   disc outputs, the release built from layers; xdelta, partners, solver
   order and low-RAM mode removed.
2. The selection-independent allocator and the free-space registry (the
   battle board directory first), the runtime check for battlespeed /
   fastforward, until no mod carries a part for another; the base / Latin alphabet / English release layers, checked by
   `build.py --base-only`, `--engine-only`, and layer composition. Boot
   and play still require in-game evidence.
3. Relocatable blocks placed at apply time, for mods made outside the
   project.
4. Container-aware entries for the event banks and TALK, so the translation
   is data on top of the engine.
5. Configurable VWF character repertoires, rather than the current fixed
   encoding scheme, with arbitrary editable symbols as well as letters. Allocate glyphs deterministically from Japanese atlas
   space after extracting the characters still reachable in untranslated
   text and UI. Preserve the remaining decorative brackets and PlayStation
   face-button symbols, while allowing them to be added or edited through
   the same font tooling. Both font editions must use the generated mapping.
   This is future work, separate from the current release optimization.

### Mod lifecycle declarations

Optional producer steps live in a mod's build.tsv. Columns are phase, action,
target and arguments. Build and verify phases run a Python tool inside that
mod's folder; verify steps are omitted only when the existing build verification
mode disables them. Arguments are split without a shell and option keys such
as {level} bind to the selected mod configuration. Restore phases call a
no-argument function in the mod in-process, avoiding extra interpreter launches
for cleanup. Cleanup runs even when a previously selected mod is now disabled.
The dub and softer-menu-sounds declare their steps this way. Shared TIM/MES
handling remains in the image compiler, driven by images.tsv.

English assembly injection is already declared in its asm.tsv. Production of
shared/native fallback files still has
pipeline-specific wiring; lifecycle declarations do not yet make every part
of translation preparation independent. Moving wording files or generators
requires separating English data from reusable layout/format machinery.

Mods may contribute ending-preparation arguments with an ending / arguments
row (target -). Only selected mods contribute arguments; the resulting tuple
is part of the ending cache key. English dub declares its --dub contribution
this way rather than being named by the main pipeline.

Assembly rows obey prerequisite dependencies before numeric order. Within each
file block, all rows from a prerequisite mod precede the dependent mod's rows;
transitive dependencies apply even when an intermediate mod has no rows in that
block. Among ready rows, numeric order and the canonical mod rank remain the
tie-breakers. This orders writes, not arbitrary runtime scratch allocation.

The base component owns command-table repacking and the resulting free-tail
allocation. The alphabet component owns the dungeon spill/title table layouts
its runtime hooks read. Their generated contents use the current translation
provider, including native fallback data. A translation changes those contents
through its layer; it does not own prerequisite engine placement declarations.
This prevents later translation writes from clearing code already injected by
a prerequisite component.

Movie outputs can declare `restore-disabled` instead of `restore`: cleanup
runs only when that mod is absent from the next variant. Builders using this
phase must retain verified identical outputs, replace changed outputs and
remove outputs dropped from their declarations. English dub uses this for
cached movies; battle voices keep unconditional restoration because assembly
and other mods also rebuild their archive.

## Incremental native release references

The release keeps native variant trees in `build/step_cache/variants` rather
than discarding them after each attempt. Each tree contains only game files
that differ from retail, backed by shared content-addressed blobs. A manifest
is published only after all files exist; every hit checks file hashes and the
complete file inventory. Partial, damaged or extra-file entries are misses.

A variant key includes shared code/data, verified prepared product hashes,
selected mods and their dependencies, effective choices, feature gates and
tier, library versions, and the verification level. Shared generators can read
optional mod declarations: their prepared output hashes retain that coupling.
Disabled mods' cleanup remains an input, and global image cleanup declarations
are retained. A mod can declare additional project-relative source files or
directories in `inputs.tsv` (header `path`); English dub declares its audio
tracks and extracted voice banks there.

Generated numeric-setting maps under build/ are cached and restored alongside
the game tree. Cache restoration never writes source files. Consumers receive
the snapshot's explicit directory rather than relying on whatever currently
occupies mutable build/. Foundation snapshots built with readback checks are
distinct from ordinary unchecked release variants.

Normal releases reuse matching native trees and still compare composed layers
against those references. Interrupted runs can therefore retain completed
work. New configurations need their initial native references; shared generator
edits can still invalidate many variants. `--recheck` explicitly requests a
complete native rebuild and remains expensive. A normal preferred-mod build
and `tools/build_patch.py` do not invoke this matrix.
