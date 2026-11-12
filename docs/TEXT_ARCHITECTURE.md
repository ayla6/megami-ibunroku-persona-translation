# Text architecture

The text tables under `translation/` and `data/extracted_text/` share
paths, schemas, and lifecycle helpers in
`src/injection_tools/toolbelt.py` (reading/writing/merging/validating) and
`src/injection_tools/strlib.py` (encoding-adjacent helpers) — no script may
hand-roll TSV parsing, file placement, or merging.

## Layout: one TSV per real disc file

Text tables mirror the disc's file tree. A table for the PSX file
`data/psx/D00/D00M.BIN` lives at `translation/generated/D00/D00M.tsv` (and
`translation/manual/D00/D00M.tsv` when the human has touched it). The PSP
extraction mirrors the PSP tree the same way
(`data/extracted_text/psp_us/pack/E2.tsv`, `.../pack/dng/d00.tsv`, ...).

One table per real file even when the file hosts several text kinds
(name fields, boxes, door lines in one map pack) — the builder selects its
rows structurally (entry table vs box scan) from the binary, never by a
marker column. Nothing is gathered "by kind" into bucket files and
scattered back.

## PSX event scripts (ADV/E0..E3.BIN)

Verified against `data/psx/ADV/E0.BIN`; the community notes in
`references/Revelations-Persona-Deloc-Docs/` (`EBIN_Structure.md`,
`persona_ps1_ebin.bt`) describe the same container:

- Sector 0 is a zero-terminated table of cumulative `u16` sector offsets.
  Entry `i` occupies sectors `t[i]..t[i+1]`; byte offset = sector ×
  `0x800`. This is the table the community notes call "section pointers";
  the multiplier and the zero terminator are the same.
- Each entry starts with the little-endian word `08 00 10 80`
  (`0x80100008`) and a `u32` end address. The image loads at
  `0x80100000`, so body index = address − `0x80100000`.
- The section begins with a `0x1F8`-byte header (the first 8 bytes are the
  load/end words), then `0xED0` bytes of metadata; the command stream and
  text pool start at section + `0x10C8`. `efile.py` does not need to
  interpret the metadata, but it must preserve it.
- Text boxes end with `FF 01` and are zero-padded to 4 bytes. A
  `FF 55 00 00 <u32>` command says "box at this address"; boxes after it
  that parse as text are reached sequentially. Other `FF op` with
  `op >= 0x20` are commands; `op < 0x20` are text control codes.
- `efile.rebuild()` re-lays the image (boxes may change length), keeps
  every segment's 4-byte alignment, and remaps every `u32` pointer whose
  target is a box start or a gap. A pointer into the middle of a resized
  box is a hard error, not a guess.

## Print speed

English needs about twice the glyphs of the Japanese line, so each
interpreter prints glyphs in batches and keeps the retail wait between
batches. Every interpreter keeps its scripted pauses unchanged. A key
prompt, choice or pause ends the batch, so one press satisfies one prompt.

| Interpreter | Text | Batch | Notes |
|---|---|---|---|
| `MsgStep` (ADV / DNG / S2D) | event and E-file dialogue, menus | 2 per call at 30 fps (ADV, S2D), 3 at 20 fps (DNG) | `delay` reloads from `speed` after each glyph; [`vwf/msg_pace.asm`](../src/asm/vwf/msg_pace.asm) |
| `FieldRunScript` (DNG) | dungeon script boxes (D0x) | 3 on Fast, 2 on Normal / Slow | the batch shares the setting's frames; [`dng/script_pace.asm`](../src/asm/dng/script_pace.asm) |
| text objects (S2D, 0x8009B2F4) | overworld comments, banner, area labels | 2 per call | a finished delay reads again in the same call; [`s2d/text_pace.asm`](../src/asm/s2d/text_pace.asm) |

At Fast, `MsgStep` and the script boxes both print one glyph per vsync, so a
dungeon's 20 fps frame no longer makes its text slower than ADV's.
`tools/tests/test_text_pace.py` runs each patched interpreter and counts
glyphs per call.

## Battle configuration and controller boards

The canonical `BTLP` extract and manual worklist include the physical,
FF-terminated small-font strings from the retail configuration and controller
board pools. `battle_board_text.scan()` verifies pool boundaries, alignment,
glyphs and board descriptor pointers, and extracts shared strings only once;
changing the original Japanese source positions or aliasing fails closed. Some
pool strings are named by initial descriptors, and the code directly assigns
an alternate mode string at runtime.

`scan_lists()` discovers the `BtlGfxTextList` heads structurally, never from
wording or a fixed table address. A row with `count == 0` is a structural row
whose text pointer the renderer never reads, and a deliberate blank is an
all-zero run or a leading `FF`; neither is missing text. Nine source lists are
discovered: taunts, tactics, No. 1-4, control keys, personal auto, equipment
labels, gems, config and debug.

With `SF_VWF` on, `plan()` translates a list only when every visible text row
has English and every English row fits before the next row at the same y. A
list that fails the gate keeps all its Japanese and its translated rows are
reported; no row is shortened. Eight lists ship. The debug list is deferred
because `there isn't enough memory.` (128 px) and `In the name of the moon`
(114 px) exceed the 96 px column pitch. Three further translated rows have no
proven consumer and stay Japanese: Set shortcut, Toggle status display and
Remember cursor position. `verify_disc.py` reports every unshipped row as kept
Japanese instead of treating it as missing.

English is deduplicated and packed longest-first into the union of the source
pools used by the shipped lists. A record another descriptor still reads is
protected; records behind hidden (`count == 0`) rows are reusable. Over-capacity
is a build error, never a truncation. The `Normal`/`Easy` mode values share one
descriptor, so its static count covers the longer word and the shorter value is
space-padded inside its own retail record. Descriptors receive the new pointer
and count. The ownership directory at `BTL_BOARD_SPANS_ADDR` lists every arena
pool plus the three ANALYZE buffers for the resident `btl_owned_span` lookup;
it lives in the overlay because the resident VWF table area is full. No game
text or name is authored by this extractor.

## Text layout

[TEXT_LAYOUT_SPEC.md](TEXT_LAYOUT_SPEC.md) defines glyphs, wrapping,
pagination, labels, and choice gates. `vwf_wrap` owns line flow;
`port_story.paginate` owns box pagination. Dialogue has three visible lines
and one scroll to the next three; family-specific skeletons retain their
own line and page codes. Do not apply the retail fixed-character budget
to VWF text.

## Small-font overlay ownership

Each ADV/DNG/S2D load supplies its own zero-filled 64-record row table and
21-byte full-name scratch; neither uses the main program's BSS. Config pointers
name that overlay's table. ADV packs data, full-name banks/helpers, renderer,
recorder, table and scratch after the sysmsg extension. Assembly and post-build
readback enforce their order, exact zero-filled storage, registration guards,
and the sector-rounded CD load ceiling below the packet work area. DNG/S2D
retain their assigned code slots and append the table/scratch after their
full-name block. Optional S2D frame glue starts after the complete extension.

## Columns

```
extracted:  id  entry  box  pos  text
generated:  id  pos  psp  en
manual:     id  pos  psp  en  note
```

### extracted — one shape for every file, both sides

Every extracted file (`data/extracted_text/{psp_us,psp_jp,psx}/...`) has the
same five columns, so a viewer can render the context of any text unit the
same way and pair the two sides without special cases:

- `id` — source order in the file; the stable guiding number.
- `entry` — the container the unit lives in: the archive entry index for
  story/talk archives (matching `map_jp_psx`/`map_us_jp`'s `entry`), the
  section for TALK files (0 = dialogue units, 1 = answer table), empty for
  flat files.
- `box` — the unit's index within its entry (the maps' `psx_box`/`jp_box`/
  `us_box` coordinate); within its file for flat files. Neighbouring rows
  are the surrounding text.
- `pos` — the unit's byte locator, the SAME cell format as generated/manual
  `pos` (`0x28b5e2`, or `entry:0xoffset` for archive boxes): the key the
  editor joins extracted context onto translation rows with.
- `text` — the unit text, control codes inline.

`(entry, box)` identifies a unit within each source tree. Alignment maps
link PSX, PSP-JP, and PSP-US coordinates; their indexes need not be equal.
`toolbelt.write_extracted` derives
`entry`/`box`/`id` from `pos` + source order when a caller passes only
`pos`+`text`, so no extractor can invent a shape of its own.

### generated and manual

- `id` — stable integer per file, assigned deterministically from source
  order at dump time (box index / message index / table index). The human
  handle; "the guiding numbers".
- `pos` — ROM position within the file only, never RAM:
  `0xc88`, or `entry:offset` where a file needs sub-structure (archive
  members). Multi-spot rows (the same text at N offsets) are
  comma-separated; builders write every spot. Position is the merge key
  between manual and generated. A manual row may also be keyed at a pointer
  word that is not a slot when one source slot feeds two destinations: the
  S2D map labels key their shorter wording at a label-entry name word
  (`docs/TEXT_LAYOUT_SPEC.md`, "S2D location slot"), while the slot's own
  row stays the arrival banner name.
- `en` — the translation. In generated it is ephemeral (PSP-US wording,
  rewritten freely). In manual it is SACRED: automatic tools never edit
  it. They may only add rows for new positions and delete an empty row
  whose note is blank or machine-owned when generated holds a filled
  translation at the same `pos`; a row carrying human wording or a human
  note is never dropped. An emptied file is deleted and an emptied folder
  follows.
- `psp` — minimal pointer into the extracted PSP text:
  `E0:559` (the unit's `id`), `EBOOT:26b7c0` / `d00:239d8` (its `pos`
  offset), `KOUMAN:3` (a talk answer slot; comma-separated when a row was
  assembled from several units). Enough to open the extracted file and
  find the source. Empty when no source is mechanically known (human-only
  rows). Every port-derived row carries it - `tools/textview.py` shows it
  as the row's provenance.
- `note` — manual only: the tools' explanation of a queue row (gap reason,
  source lead, over-cap draft below). A row's `en` is the human's; a row
  with an empty `en` is the tools' - its note may be rewritten and the row
  deleted at any time. Notes never decide who owns a row.

### Provenance in manual notes

`translation/manual` is manual by definition, so a filled row's note never
says just `manual`. It says where the English came from:

- `PSP-US; ja ...` (or `PSP-US; JP: ... | US: ...`) — the PSP-US line
  for this row's own Japanese, verbatim; the only edits are the family's
  house-style ones (`DMG`, `, N turns`, the affinity ` / ` separator).
  A generic PSP phrase borrowed for a different line whose Japanese says
  something else is not PSP-US; it is `machine-translated`.
- `machine-translated; ja ...` — English written from the Japanese (or
  from a PSP-US line whose categories/facts differ) by a machine pass.
  It is a draft that still needs a human review; the marker is how we
  find every one of them.
- `same as JP; ja ...` — nothing was translated (`???`, a symbol).
- `debug test data; ja ...` — the source is not language: a padded
  scroll test, a rebus of the kana table, or cells left over from a debug
  routine. `en` stays empty because there is nothing to say; the row
  ships the Japanese/ASCII that is on the disc.
- `over limit Npx/Mpx; <draft>` — the rule below: the PSP draft is kept
  until a human shortens it into `en`.

Keep the source text in the note so the next translator can check the
wording without opening the disc.

### Over-cap drafts

A PSP wording that cannot fit its PSX slot never reaches `en` — a draft in
`en` would make the build fail until every row is hand-fixed. The single
writer `toolbelt.route_over` puts it in manual as:

```
en:   (empty — the Japanese ships until a human adopts the draft)
note: over limit 245px/239px; Medium Death damage each turn (area)
```

The note is `<reason>; <draft>`: the mechanical reason first
(`note_over` — `over limit Npx/Mpx`, `N chars/M chars`, `N cells/M cells`,
`NB/MB`, ..., unit-explicit, symbol units glue / word units space), then the
full PSP draft after `; `. Each family measures in the unit its destination
really has: rendered pixels for the VWF skill menu (120 px) and affinity row
(200 px) and the one-line description bank (239 px), cells for the casino
prize bar, characters only where the field is a fixed cell count. The human
shortens the draft into `en`; only then does the row become theirs and build.
`route_to_manual` fails loud if a draft ever shows up under `en`.

A human's own filled `en` is never rewritten by a tool (that is their word),
so a build that finds it over its destination's limit keeps the Japanese on
the disc and reports the row instead of failing: `descs` writes
`build/descs_drafts.tsv`, `sysmsg` writes `build/sysmsg_drafts.tsv` with the
row's position, the measured width and the draft. The row is work waiting
for a human, not a broken box.

The draft stays the port's job. A queue row that has an empty `en` and a
`psp` source is *parked*: `port_lastresort.py --apply` re-derives every
parked row from that source after the renorm (`redraft`). A source that now
fits ships; one that does not gets a fresh `over limit ...; <draft>` note
measured against today's destination. The note is never parsed - the next
run uses the `psp` source again, so a fixed rule fixes the draft instead of
leaving a stale hand-written one.

No `ja` column anywhere: the source text is looked up via `pos` (PSX
disc) or `psp` (extracted PSP tree). No notes in generated. No draft
markers — generated is built only from the PSP discs (`boot`/`pack` extraction).

## Pipeline

```
PSX/PSP discs
  -> dump   extracted_text/  (per-file TSVs, position-keyed)
  -> port   generated/       (PSP-US wording at the matching positions)
  -> human  manual/          (gaps filled, wording overridden)
  -> build  bytes at pos     (manual wins where filled; no text search)
```

Manual is an override layer over generated, not a pipeline stage.

## Tool roles (single source of truth per role)

| role    | does | never |
|---------|------|-------|
| `dump`  | binary -> extracted TSVs; maintain empty manual worklists | invent wording |
| `port`  | match PSP wording, write generated rows, maintain manual gaps/drafts | overwrite human English |
| `build` | merge generated+manual, encode and place bytes at `pos` | search by text content |

`build` reads `id | pos | psp | en`, resolves `pos` through the one resolver for
that file family (table pointer / slot / archive member), encodes `en`, and
emits bytes or `.org` output. `toolbelt` supplies shared row I/O, merging,
encoding, and patch helpers; family builders own binary structure and placement.

## Failures fail loud

- `en` that exists but cannot ship (unencodable, over-cap, wrong structure)
  fails the build. Never skip, never silently keep Japanese.
- A stale manual `pos` (binary layout shifted) fails the build for human
  re-homing — never guessed by text.
- Missing inputs (disc dumps, caches) fail with the command that produces
  them.

## Current workflow and ownership

`src/extraction_tools/matching/port.py` is the port entry point used by
`build.py`. It prepares correspondence maps, builds the font advances used
for wrapping, refreshes extracts and shared tables, then runs family
porters. Its declared write sets determine execution waves: porters writing
the same table run sequentially.

- `port_widths.py`: the record-insert width table
  (`translation/generated/insert_widths.tsv`) - the widest name each
  message-machine insert code can print, measured from the canonical name
  rows after boot_tables and read by every later layout
  (`vwf_wrap.insert_widths`). Derived data with one owner, like any
  generated table.

- `port_story.py`: ADV story rows.
- `port_talk.py` and `port_answers.py`: TALK dialogue and answer rows.
- `port_dng.py`: dungeon-pack rows.
- `port_s2d.py`: S2D rows. For script gaps, it matches complete PSX and
  PSP-JP portrait dialogue, checks the speaker, and uses only a proven
  PSP-US twin. The shared matcher can prove whole EBOOT portrait gaps between
  independent anchors when complete-unit order, every page's independently
  learned speaker, and meaningful controls all agree; ambiguous or incomplete
  gaps stay untranslated. Authored waits and page changes are preserved.
- `boot_btlmsg.py`, `port_btlevt.py`, `port_btlneg.py`: BTLP rows. Plain
  negotiation notices may also be paired by `notice_consumer.py`: a unique
  exact JP record and relocated PSP pointer must have a unique matching
  regional executable-consumer fingerprint, with an adjacent independently
  proven pointer pair and no conflicting anchor. Equal relocation ordinals or
  text alignment alone are not proof; source pointers are decoded at their
  actual binary targets before resolving their extracted rows.
  `btlcmd.py` reads the CONTACT command names from both PSP indexed pointer
  tables, checks every JP slot against its PSX Japanese and checks repeated
  source identities, then emits the PSP-US strings. Its post-assembly verifier
  checks every pointer and complete encoded string. For the CONTACT offer,
  `personality_source.py` checks the PSX and PSP bit-index consumers and 193
  corresponding profiles, then reads all eight full PSP-US labels. With the
  small-font VWF gate on, `btlui.py` packs them into their existing private
  bank and checks full-quad column bounds. The scoped effect-quad hook uses
  resident VWF tail space, the reserved front of the existing command bank,
  and a guarded duplicate BTLP routine, without taking the unproved overlay
  sector tail. Post-assembly verification reads back every label, metric and
  hook; other effect rows retain the retail path.
  The battle text builder packs every original event message, including untranslated
  bytes, and relocates its references. The text clear and allocator stop at
  `BTLEVT_UNPACK_ADDR`; the unpacker and its pair table own the tail above it.
  Direct story-spill pointers use the story dictionary, while negotiation
  uses its own. `btlp.py verify` independently reassembles the reader and
  reads back its code, table, packed data and original-message references.
- `port_descs.py` and BOOT table extraction: SLPS rows.
- `port_affinity.py`: queues each affinity row with its PSX Japanese and the
  PSP-US counterpart for manual wording. The PSP table rebalanced the rules, so
  it never generates affinity English; the human's `en` is the only source.
- `port_quote.py`: the opening-movie quote. The ending pages need no porter: their text is the
  hand transcription of the PSP images (`translation/manual/ending/ENDALL.tsv`), cut into pages by
  `endtext.py` when it draws them.
- `port_lastresort.py`: only `ADV.tsv`, `CASINO.tsv`, and `DNG.tsv`, the
  string banks outside the family porters' write sets. It must never
  re-derive a family porter's rows.

Each owner derives its rows from source and applies layout at the write
point. Do not add a pass that rewrites other owners' completed rows.
`toolbelt.upsert_generated` applies textbox format invariants;
`route_to_manual`, `route_over`, and `route_gaps` maintain the human queue
without overwriting human wording. Regenerate generated data with its
owning porter; do not restore it from Git or copy it into manual tables.

Canonical extracts live in `data/extracted_text/`, one TSV per real game
file. Working BOOT tables, bank chains, and BE-record caches live in
`data/cache/`; generated alignments live in `translation/generated_mappings/`. See
[MAPPINGS.md](MAPPINGS.md) for their producers and prerequisites.

`src/injection_tools/build.py` coordinates family builders including
`etext.py`, `talk.py`/`etctalk.py`, `slps.py`, `s2d.py`, `btlp.py`, and
`dngpacks.py`, plus specialized tables, graphics, fonts, and overlays.
Assembly outputs are patched into the disc by `build_disc.py`.

Dungeon spill text and its redirect code own
`DNG_SPILL_ADDR..DNG_SPILL_LIMIT` in `addresses.inc`. Generated assembly
sets its own origin; it never inherits an unrelated hook's position.
The window is above the retail overlay, dialogue glue and optional FPS glue,
and below the held-START title renderer. That renderer and its 160x16 scratch
own `DNG_FIELD_TITLE_ADDR..DNG_FIELD_TITLE_LIMIT`, immediately before the
shared map-title table. `dngnames.py` generates both that table and an
independent byte image; its verification reassembles the field hook in
isolation and checks every code/data byte and the original entry prologue.
Assembly guards and `dngspill.py verify` also check spill placement, bytes,
entry jump, and the sector-rounded CD load's separation from the GPU area.

Each spilled dungeon box contributes its own raw 24-byte fingerprint, including
bytes after FF01 for short boxes. Distinct fingerprints share an encoded text
blob only when their encoded English is identical; conflicting English for one
fingerprint refuses the build. Only occurrences that cannot build in place
contribute entries. Both redirect paths compare six words, advance by 28 bytes,
and read the pointer at +24, with R3000 load delays respected. The glyph-entry
fallback replaces an already-consumed first glyph with the spill's first glyph;
a leading control code returns without drawing so the interpreter handles it.
`tools/tests/test_dng_spill_layout.py` executes both assembled paths with load
and branch delays, checks all alignments, and checks every spilled occurrence
against the built pack and table.

## Verification

Run `tstatus.py qa` and `talktl.py qa` for text checks. After a disc build,
`tools/verify_disc.py` checks built files against disc bytes (level 1 -
from the live `build/` tree, or from the builder's placement record when
`--placement` is given),
decodes textbox rows back from disc bytes (level 2), and checks other
translated rows in their disc files (level 3, with format-specific
round-trips and pixel-rendered ending-text exceptions). Two consecutive
ports must produce identical tables. In-game checks remain necessary for
rendering and interaction; a previous verification result is not evidence
for a different build.
