# Build and port pipeline

## Current boundaries

- `src/porting/port.py` regenerates the canonical generated
  translations from the PSX data, PSP-US data and the tracked source plans in
  `translation/generated_mappings/`. It does not read PSP-JP text when the plans
  for a porter exist: `port.py` appends `--without-psp-jp` to that porter's
  command. Without a plan, a porter falls back to the live two-region match, so
  a fresh clone with only PSX + PSP-US + the tracked plans reproduces the
  generated tables. The current PSP-JP-free run was compared byte-for-byte with
  the two-region run.
- Plans are text-free snapshots: source offsets, decisions and input digests,
  never Japanese or English wording. Capturing or refreshing a plan is the one
  operation that still needs both PSP regions. `port.py` refuses a stale plan
  (changed inputs or matching rules) instead of silently dropping or guessing a
  row.
- `src/pipeline/build.py` (porting is off by default) builds the current
  translation tables without either PSP disc, PSP text extracts, or the decrypted US BOOT
  cache. It still requires the retail PSX data and tracked translation inputs.
  Dungeon titles, party names, battle commands and CONTACT personalities use
  the canonical generated/manual rows for their PSX files. A port with both
  PSP regions refreshes the latter three from the proven PSP tables via
  `psp_build_sources.py`; a US-only port retains their existing rows. To
  regenerate them independently, run `python src/porting/psp_build_sources.py`
  with both PSP regions and the US EBOOT text extract available.
- Assembly inputs, including the overlay name-tail banks and dungeon-title
  table, are generated during every build, with or without `--port`; they do not
  depend on a pre-existing `build/` directory.
- `python src/extraction/psp/eboot.py --us-only` refreshes the US EBOOT
  extract without opening the Japanese BOOT. Running it without the option
  retains the existing two-region extraction behavior.
- `port_talk.py` ports from the PSX and PSP-US TALK files without reading
  PSP-JP text: its former PSP-JP input was passed only to a rule that ignores it.

## Write and disc integrity checks

Two general checks run on every assembly, not on selected rows or screens:

- `build.py` passes `-erroronwarning` to both armips invocations, so a
  load-delay or branch-delay warning aborts the build. armips otherwise exits
  0 on those warnings, which is how a hook can assemble "successfully" while
  reading a stale register and silently falling back to retail.
- `build.py` passes `armips -temp build/armips-main.lst` (and
  `build/armips-subs.lst` for the subtitle renderer) and then runs
  `src/pipeline/write_guard.py check --listing ...`. The listing is the
  complete account of emitted bytes: virtual address, source line and the
  surrounding `.open`/`.create`. The guard requires every output under
  `build/`, no output opened twice, and no non-padding write covered by a later
  write. A later write may reuse covered bytes only when both statements emit
  the same bytes there (the shared glyph prefixes/suffixes in the VWF atlas).
  Every write must stay below its output's declared memory limit, and every
  byte of the built file that differs from its input must appear on a listed
  write. PS-X EXE `t_size` must equal file size minus the `0x800` header.
- Limits are the `X_OUTPUT` / `X_IMAGE_LIMIT` pairs in
  `src/mods/base/asm/common/addresses.inc`. An output without a declared limit may not
  grow past its retail input; declaring the limit is how growth is allowed.
  This is the single place a new output must be registered.
- `tools/verify_disc.py` audits the finished image against a baseline image:
  ISO record framing and both-endian fields, unique paths, file and directory
  extents inside the volume, no overlaps, directory records changed only in
  their extent/size, and `FNAME.DAT` / `FSECT.DAT` / `FSIZE.DAT` agreeing with
  the ISO tree. Outside the changed files, their old and new extents, the
  directory sectors, the PVD and the two game tables, every sector must match
  the baseline; beyond the baseline volume only relocated file data and zero
  padding may appear. This catches a builder writing bytes it did not claim,
  not just a wrong directory record. The baseline is the retail disc for an
  ordinary build. A composed release image passes its parent variant instead,
  so each link is checked and the chain ends at the base translation, which
  is checked against retail.

Movies (`.STR`) are the one kind of file `build/` holds as raw 2352-byte
sectors (their XA audio sectors are Form 2): `build_disc.py` writes them in
place, sector for sector, and both the placement hash and `verify_disc.py`
compare them from each sector's subheader on. Two movies built with the same
bytes are written once and share an extent, which the audit accepts for files
the builder wrote there.

The translation presence scan reports fixed battle-message capacity fallbacks
separately. It requires an immovable source record, encoded text extending
into the next fixed record or past the zone, and an exact retail-byte match
in the finished disc. Missing or corrupted translations still fail.

`build_disc.py` also writes `<image>.placement.tsv`, the record of every file
it packed (path, extent, size, SHA-1 of exactly the bytes written). Passing
`--placement` to `verify_disc.py` audits the image against that record instead
of walking `build/`, and `--side-files DIR` points at the small builder report
files (`dng_spill.asm`, the draft tables) copied alongside it. The image is
then self-describing: the same verification runs on a finished release disc
with no build tree in sight, and it can run while the tree is being rebuilt.

```sh
python src/pipeline/write_guard.py check --listing build/armips-main.lst
python tools/verify_disc.py dist/Persona-TL.bin
python tools/verify_disc.py disc.bin --placement disc.bin.placement.tsv --side-files snap
```

## Incremental builds

Text/font preparation excludes Python test modules and the PNG assets and
manifests declared by mod images.tsv files. Those images are compiled and
checked after assembly by their own cache. Editing a mod image therefore
does not regenerate dialogue, fonts, movies or ending text. Alphabet font
assets, production Python and assembly sources remain preparation inputs.

Three optional-patch steps cache themselves in every build, `--clean` or not,
because their inputs almost never change: Black Mark's re-encoded MES.BIN
(`images/black-mark/MES.BIN`/`.tsv`, keyed on source archive bytes, images.tsv,
the declared PNGs and the shared image compiler; verification checks the
validated cached output) and each dubbed movie (`fmv-dub/<MV>.STR`/`.tsv`, keyed on fmv_dub's
code, the movie's retail sectors, its PSP track and its map row; `fmv_dub.py
verify` skips the XA decode of bytes it already passed), and the English
battle calls (`battle-voice/PS.BIN`/`.tsv`, keyed on battle_voice's code, the
retail B/PS.BIN, the call map and the PSP-US calls; `battle_voice.py verify`
skips the decode likewise). All three live under
`build/step_cache/` and serve normal builds and `tools/build_patches.py`.

`build.py` keeps verified text/font preparation for each configuration under
`build/step_cache/preparation/`. Its key covers source files, translation,
retail/extracted data, interpreter and library versions, font edition,
and feature gates. Movie data, renderer assembly and packing use a separate
cache keyed by renderer choices, so changing subtitles reuses text and fonts.
Generated character tables and
font products are outputs, never their own inputs. The smaller character-table,
dialogue-font and FMV-data caches also remain available on preparation misses.

Preparation records only products it wrote, plus the declared products of
those smaller caches. Shared content-addressed blobs use copy-on-write clones
where supported. A hit verifies every cached blob and restores missing or
edited products; switching configurations removes products owned only by the
previous preparation. Inputs that change during generation do not receive a
reusable manifest. Ending pages also have a separate cache for the dub and ordinary
cast variants. Ending preview PNGs are generated only by explicitly running
`endtext.py --previews`.

File digests persist across processes in `build/step_cache/file-digests.tsv`.
Reuse requires matching device, inode, size, modification time and change time;
a same-size edit with a preserved modification time still invalidates the hash.
`--clean` regenerates preparation and ending pages. `--port` always runs the
porters and preparation. Assembly, binary write guards, placement verification
and requested disc creation still run for every patch set. Builds sharing one
`build/` directory must not run concurrently.

On systems with sufficient writable `/dev/shm` space, main assembly writes
its binaries into a temporary RAM workspace. After successful assembly, only
changed results replace live build files; unchanged files retain their inode
and timestamps. Stable output aliases resolve back to live files afterwards,
so retained listings remain usable by the write guard. If RAM staging is not
available, ordinary assembly output is used. Assembler errors leave live files
unchanged while RAM staging is active. Source and output bounds are checked
through canonical paths, including aliases.

Variant cleanup runs in the build process. The shared image compiler restores
declared image regions while preserving other edits to their files; MES
reconstruction is left to assembly. Selected mods' images.tsv declarations
are applied and verified after assembly. Voice overrides are removed between
variants. Movie audio keys use subtitle cue timing,
not wording; battle-call keys use map contents rather than translation-tree
locations. Equivalent language tiers therefore share audio caches.

Release composition checks merge the same byte spans and validate the same
source digests and bounds without constructing discarded conflict reports.
Interactive/CLI merging retains those reports by default.

`build.py '--variants=base;unified-save-menu;unified-save-menu,60-fps'` performs common preparation
once, then independently assembles and verifies each combination and writes
`dist/Persona-TL-base.bin`, `dist/Persona-TL-saves.bin`, and
`dist/Persona-TL-saves-60fps.bin` with corresponding CUE files. Names are
the same as `--mods` (the mods' names); `base` means no mods beyond the translation. Quote the argument to keep
the shell from interpreting semicolons. Batch mode rejects `--no-disc`
and `--mods` to avoid ambiguous or overwritten results. Combine
with `--port` (and `--clean`) where appropriate. The shared `build/`
tree holds the **last** variant after the command; the distinct disc images
hold each result. As with separate builds, each image is made from the original
disc and each variant runs the placement checks and the post-assembly builders
that depend on its assembled outputs; builders that do not depend on the mod
choice run once during preparation.

The optional `softer-menu-sounds` mod scales note velocities for the shared
field/ADV menu navigation, confirm and back cues, with a configurable integer
range of 0–100%, defaulting to 75%. These are MIDI velocity percentages,
not calibrated acoustic loudness. Six cue roles are analyzed; the navigation, confirm and default back cues
are selected, while the softer open/back-alternate cue keeps its level.
Their identities come from the common
input helpers, cursor code and ADV's sequence-table addressing. Complete
matching event streams cover their overworld and other shared copies.
Audio previews are opt-in: run
`python src/mods/softer-menu-sounds/analyze.py` explicitly. Normal game and
patch builds never run the analyzer. It renders dry previews using the retail SEQ notes and shared VAB
ADPCM samples, pitch and gains, and writes relative level and spectral metrics.
It is a comparison aid, not SPU emulation: ADSR, reverb and interpolation differ
from the game. Timing, pitch, programs and other bytes are preserved by the
patch. The cached TSV edit map includes the selected level in its key;
variant cleanup reverses only the recorded velocity edits.

To rebuild one configured optional patch without rebuilding the release:

```sh
python tools/build_patch.py softer-menu-sounds
```

This builds its baseline and the selected mod, verifies their delta and
serialized layer, and writes `dist/single-patches/<mod>.p1mod`. It does not
update the complete release manifest. The default tier is English;
`--tier=base` or `--tier=alphabet` builds against those foundations instead.
Discrete choices remain configured at build time. Numeric ranges are stored
in the layer with their bounds, step and default, plus original byte values.
The patchers calculate the requested value at apply time, so one layer covers
the entire range. For example, use `--choose 'softer-menu-sounds(level=63)'`
with either command-line patcher. The browser offers a slider and number field.
The configured layer carries input checks for its baseline files.

## Release patches

`python tools/build_patches.py` produces a complete release in
`dist/patches/` (`--output` chooses another directory): P1MOD layers
(see [MOD_ENGINE.md](MOD_ENGINE.md) for the format), a `manifest.tsv` and a
generated `README.txt`. Only the original Rev 0 disc is patched.

- `base.p1mod`: retail to the language-neutral base.
- `latin-alphabet.p1mod`: base to the alphabet engines, fonts and name entry.
- `english-translation.p1mod`: alphabet to English at its defaults.
- `<name>.p1mod`: one per optional mod, with conditional parts for higher
  tiers, choices and interacting mods. Apply layers after their requirements.

The foundations check the SHA-1 of their input files. Base and alphabet
build in separate processes, with English cells emptied at the translation
reader. Base also omits alphabet assembly. Builder bounds and fatal assembler
warnings remain active in production. Native-tier assembly write guards also
run in production. The full English write audit runs with build verification.

This command produces and verifies all release files by default.
It builds individual mods, overlapping pairs, alternate choices and the
known compatibility recipes in each mod's `compatibility.tsv`. Shared format
encoders run through `english-translation/preparation.tsv`; source QA and
assembled readbacks are deferred for these production trees. Compatibility
lives inside mod layers, without separate pair files.

Default verification includes foundation
readbacks, comparisons of combined native builds with merged layers,
higher-order interaction discovery, and final browser/standalone disc/PPF
parity. The manifest uses `testing` during final checks and becomes `verified`
only after they pass. Publishing requires verified files.
Use `--no-verify-release` for explicit production-only output marked `untested`.

Intermediate parts stay uncompressed in memory. Each completed layer is
compressed once, then read back and compared with its staged parts. The
manifest is empty until the complete set has been written. Intermediate
native trees contain only changed game files. Identical files share immutable
blobs under `build/step_cache/tree-blobs/` through hard links (with a clone
fallback). Live build files remain independent, so later assembly cannot
change snapshots. Dependency-scoped native snapshots are reused only after
checking their input key, contents and inventory. `--recheck` bypasses that
reuse and requests full verification. No disc is made per patch combination;
only explicit final verification makes a native comparison image.

Unified save menu requires base and works without the translation. Latin
alphabet owns the retail title's proportional saved-name writer and the
separate compatibility includes for unified save menu's geometry and metrics.
Those compatibility writes are active only with the small-font VWF kit.

The manifest has one row per layer: `layer`, `kind` (base / option),
`label`, `choices`, `requires`, `version`, `state`, `bytes`, `sha1`,
`build_key` and `release`. Requirements are component labels, without
individual versions; the release has one version. The base row also carries
`source_bytes` and `source_chd_sha1` for disc identification. Unchanged
production outputs can be reused; a verification request requires verified
status or runs the checks. Stale output files are removed.

#### Adding a release option (checklist)

1. Make its folder `src/mods/<name>/`, named after the mod's name, with its
   assembly, its `asm.tsv` (where each of its files goes in which disc
   file's block: `src/pipeline/asm_main.py` writes `build/main.asm` from the
   mods that are on) and its `mod.tsv` (label, name, description,
   `requires` rows, default, always, release, its choices;
   `src/pipeline/mods.py` documents each key) - the single source of
   its wording: `build.py --mods`, the release README, the layer and the web
   patcher's generated `features.js` all read it.
2. Everything else derives: layer names, manifest rows, compat pairs, the
   webpatcher grid.

`--publish-release` (formerly `--publish-web`) uploads the `--output`
directory (default `dist/patches`) to a GitHub release as one
`persona-patches.zip` holding the layers, `manifest.tsv` and `README.txt`:
anyone applying the layers by hand (`src/pipeline/modpack.py apply`)
downloads the zip directly. The release tag is `patches-YYYY-MM-DD`; a
second release that day becomes `-2`, then `-3`, so releases are never
silently clobbered. The tag is written into the manifest's `release` column
and therefore into the web patcher's result filenames. The upload targets
the repository named by `RELEASE_REPO` in `webpatcher/app.js`, since
`origin` is not GitHub.

The web patcher site itself deploys from this repository through
`.github/workflows/pages.yml` on every push to `main`, on every published
release, and on demand. Before uploading the artifact, the workflow
downloads the release's zip and unpacks it into `webpatcher/patches`
(git-ignored), so the site serves the layers from its own origin: a page on
`github.io` cannot fetch release assets, since github.com answers those
downloads without CORS headers. Enable it once under Settings -> Pages ->
Build and deployment -> Source -> GitHub Actions; the project site is
`https://<owner>.github.io/<repo>/`.

### Browser patcher

`webpatcher/` is a static page that applies a release in the browser. The
disc is recognised from the manifest (a `.bin` by its size, a CHD by its
header's raw SHA-1; a Rev 1 disc is named and refused), the selected layers
are merged and laid out by `webpatcher/modpack.js`, and the result is either
the patched disc (a Blob of slices of the player's file with the changed
sectors in between) or a PPF of the changed sectors. Every layer's SHA-1
is checked against the manifest, and the base layer checks every file it
changes. The page also generates a correct single-track `.cue` for the
patched image, and names the download from the release
(`Persona-TL-2026-11-10.bin`, `Persona-TL-2026-11-10-2-saves-mark.bin`,
...) instead of reusing the file name the user picked. See
`webpatcher/README.md` for the details and for hosting.

## Source plans

The tracked plans cover S2D, dungeons, story speaker arbitration, battle
dialogue, dungeon names, answers, and the EBOOT boot strings (including the
notice/control consumer proofs). Each plan is validated against the PSX and
PSP-US inputs and the matching rule files before replay. Recapture a plan with
its producer when those rules or the correspondence inputs change:

```sh
python src/porting/s2d_port_plan.py
python src/porting/dng_port_plan.py
python src/porting/story_port_plan.py
python src/porting/btlevt_port_plan.py
python src/porting/dngnames.py plan
python src/porting/answers_port_plan.py
python src/porting/eboot_twin_plan.py
python src/porting/reward_notice.py
```

A plan freezes the correspondences a two-region pass found; discovering new
ones requires a fresh capture with PSP-JP.

A plan must stay valid across a from-zero `port.py` run, where `generated/` is
empty and porters run in wave order rather than capture order. The EBOOT twin
capture therefore ignores rows already in `generated/` and records the full
decision domain (replay applies the subset its tables leave open). The
reward-notice plan digests only the item-name rows it reads from
`generated/SLPS_005.00.tsv`, not the whole table, so an unrelated row change
does not stale it.

The batch command and release patch builder reuse verified preparation across
processes and configurations; each variant still receives the ordinary assembly and QA checks.

Release movie comparisons use bounded views of sector bodies, ignoring the
same 16-byte headers as raw_body without constructing whole copied streams.
The changed-file read cache has a 512 MiB hard cap so a dubbed-movie variant
can remain cached across scans. The retained files are still checked against
file signatures, and content changes invalidate those entries.
