# Build and port pipeline

## Current boundaries

- `src/extraction_tools/matching/port.py` regenerates the canonical generated
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
- `src/injection_tools/build.py --no-port` builds the current translation
  tables without either PSP disc, PSP text extracts, or the decrypted US BOOT
  cache. It still requires the retail PSX data and tracked translation inputs.
  Dungeon titles, party names, battle commands and CONTACT personalities use
  the canonical generated/manual rows for their PSX files. A port with both
  PSP regions refreshes the latter three from the proven PSP tables via
  `psp_build_sources.py`; a US-only port retains their existing rows. To
  regenerate them independently, run `python src/injection_tools/psp_build_sources.py`
  with both PSP regions and the US EBOOT text extract available.
- Assembly inputs, including the overlay name-tail banks and dungeon-title
  table, are generated during the build even with `--no-port`; they do not
  depend on a pre-existing `build/` directory.
- `python src/extraction_tools/psp/eboot.py --us-only` refreshes the US EBOOT
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
  `src/injection_tools/write_guard.py check --listing ...`. The listing is the
  complete account of emitted bytes: virtual address, source line and the
  surrounding `.open`/`.create`. The guard requires every output under
  `build/`, no output opened twice, and no non-padding write covered by a later
  write. A later write may reuse covered bytes only when both statements emit
  the same bytes there (the shared glyph prefixes/suffixes in the VWF atlas).
  Every write must stay below its output's declared memory limit, and every
  byte of the built file that differs from its input must appear on a listed
  write. PS-X EXE `t_size` must equal file size minus the `0x800` header.
- Limits are the `X_OUTPUT` / `X_IMAGE_LIMIT` pairs in
  `src/asm/common/addresses.inc`. An output without a declared limit may not
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

`build_disc.py` also writes `<image>.placement.tsv`, the record of every file
it packed (path, extent, size, SHA-256 of exactly the bytes written). Passing
`--placement` to `verify_disc.py` audits the image against that record instead
of walking `build/`, and `--side-files DIR` points at the small builder report
files (`dng_spill.asm`, the draft tables) copied alongside it. The image is
then self-describing: the same verification runs on a finished release disc
with no build tree in sight, and it can run while the tree is being rebuilt.

```sh
python src/injection_tools/write_guard.py check --listing build/armips-main.lst
python tools/verify_disc.py dist/Persona-TL.bin
python tools/verify_disc.py disc.bin --placement disc.bin.placement.tsv --side-files snap
```

## Incremental builds

`build.py --incremental` caches character-table generation, dialogue-font
generation and FMV subtitle-data generation. Each step has explicit inputs
and outputs; it is reused only if the input fingerprint and all output hashes
match the previous successful run. The FMV key includes Pillow and FreeType
versions. The manifests under `build/.step-cache/` record individual source
hashes as well as the input fingerprint and output hashes. An input change,
edited or missing output, or a failed run regenerates the step; inputs that
change during a step do not get a reusable stamp. A non-incremental build
always regenerates these steps and refreshes their stamps. `--incremental` does not skip
porting; combine it with `--no-port` when the existing translation tables are
the intended input. Assembly, placement verification and disc creation still
run for each selected patch set. Builds sharing one `build/` directory must not
run concurrently.

`build.py '--variants=base;saves;saves,60fps'` performs common preparation
once, then independently assembles and verifies each combination and writes
`dist/Persona-TL-base.bin`, `dist/Persona-TL-saves.bin`, and
`dist/Persona-TL-saves-60fps.bin` with corresponding CUE files. Patch names are
the same as `--qol`; `base` means no QoL patches. Quote the argument to keep
the shell from interpreting semicolons. Batch mode rejects `--no-disc`,
`--qol` and `--no-qol` to avoid ambiguous or overwritten results. Combine
with `--no-port` and `--incremental` where appropriate. The shared `build/`
tree holds the **last** variant after the command; the distinct disc images
hold each result. As with separate builds, each image is made from the original
disc and each variant runs the placement checks and the post-assembly builders
that depend on its assembled outputs; builders that do not depend on the QoL
choice run once during preparation.

## Release patches

`python tools/build_patches.py` produces a complete xdelta3 release in
`dist/patches/` (`--output` chooses another directory). It needs `xdelta3`
(installed by `python src/setup_external_tools.py`, or available on PATH), the
Redump Rev 0 and Rev 1 single-track BINs (or `--rev0` and `--rev1` paths), and
the ordinary build dependencies. The script defaults to `--no-port` and
incremental asset preparation; `--port` explicitly refreshes translations
first and rebuilds every variant patch. A release directory written by the
old per-combination layout is refused: move it away before the first build
of this layout.

The nine release choices are save UI, Mark artwork, battle speed, 60 fps,
double battle rewards, half random encounters, running in dungeons,
Upper Right movement and Start-to-skip movies. Rewards and encounters ship
as separate options, so someone can take one without the other. Debug is not
included.

The release ships twelve patch files and twelve manifest rows - one row per
file, never one per combination. `rev1-to-rev0.xdelta` and
`rev0-to-base.xdelta` convert the retail disc to the base translation;
every option is an `add-<option>.xdelta`.

In-place options come first in solver order, one file each, encoded from the
base translation: Mark, battle speed, rewards, encounters, run, upright and
skipfmv are `add-<option>.xdelta`. Their patches keep every offset and the
image size, so they compose over one another by same-offset copies.

Size-changing options come last: the save menu is `add-saves.xdelta`, 60 fps
is `add-60fps.xdelta` without the save menu or `add-60fps-saves.xdelta` with
it. A size-changer is assembled one-shot from retail, exactly like
`build.py --qol=...`; building it on the base translation would extend the
image instead of using retail's free space (`saves` alone is about 2 MB
larger that way) and would not produce the disc the option really builds.
Applying it rewrites the source layout into the canonical one-shot layout,
and its same-offset copies carry the earlier in-place edits along. These
three patches are emitted by `tools/sizedelta.py`, not by xdelta's matcher:
the writer copies each target byte from its true preimage (the same file
and offset in the source layout) and writes literals everywhere else. A
matcher is free to use a same-content decoy - a zero run in one file for a
different file - which silently dropped skipfmv's edits in `EXE/MOVIE.EXE`
when `add-saves` was encoded with xdelta3.

A row names the option it adds (`adds`), the size-changers it was encoded
against (`anchor`), its fixed apply position (`order`), and the canonical
state it produces (`choices`). The web patcher in `webpatcher/` derives the
chain from those four fields: selected options in `order`, picking the most
specific `adds` row whose `anchor` is already applied. No combination list
exists in the manifest or the page.

The build assembles the canonical states - the base translation, the four
size-changer layouts (none, `saves`, `60fps`, `saves+60fps`, each laid out
one-shot from retail), and each in-place option on its own - and then a
sample of real selections (the two expected-popular combinations and
`--sample` seeded random ones), each built once from retail for the
byte-for-byte comparison. That is eleven canonical builds plus five sample
builds by default, not 512.

#### Why the graph looks like this (invariants other agents must keep)

- **Solver order**: in-place options first (CHOICES order), then
  size-changers. In-place patches keep every offset and the image size, so
  their copies are same-offset and compose over earlier in-place edits;
  one file per option is enough. A size-changer's insertion shifts every
  offset after it, so it must come after the in-place edits that should
  ride along, and each size-changer is encoded against the layout built
  before it - that is the whole reason for the order and for anchor
  files. Compositions that do not hold stop the build (see the sampling
  check below); they are never worked around.
- **ISO record sizes are whole sectors**: `build_disc` records the same
  allocation length in each ISO file record that `FSIZE.DAT` stores, and
  normalizes every record even when the file itself did not change. The
  game resolves files through `FSECT.DAT`/`FSIZE.DAT`; the ISO byte count is
  only metadata. An in-place option keeps the file's sector allocation, so
  the directory sector - and its EDC/ECC - is byte-identical regardless of
  which in-place options are selected. Without this, a size-changer's
  literal EDC (which no delta can recompute) would describe the canonical
  build but not a decorated chain, and the sampled comparison would be off
  by that checksum even though every data byte matched.
- **File layout**: one file per in-place option, plus one file per
  (size-changer, subset of earlier size-changers). With m size-changers
  that is 2^m size-changer layouts and one file per size-changer per
  subset; in-place options never multiply. Adding an in-place option
  costs one file; adding a size-changer doubles its own anchor rows.
- **Size-changers are assembled from retail**: a size-changer variant is
  laid out from retail in one pass, so its bytes match a one-shot
  `build.py --qol=...` build. The base translation has already used its
  own free space, so building the option on top of it would extend the
  image and produce a disc the option never builds. In-place variants are
  written onto a reflink clone of the base translation (their patches keep
  the layout), so `build_disc` rewrites only the files the option
  changes.
- **Hashes only where they describe a real disc**: the revision
  conversions and the base translation record whole-image
  `source_sha256`/`target_sha256`, because their inputs are exactly a
  retail or translated disc. An add- row's source is whatever the player's
  earlier options made it, so its hash columns stay empty; there is no one
  canonical hash for a decorated disc. The runtime checks each patch
  file's SHA-256 (`patch_sha256`) and every step's output size, and uses
  xdelta's own window checksums when the applied set is exactly the row's
  canonical source. On a decorated disc it decodes with `-n`, because
  in-place decorations never change the size.
- **The chain is verified by sampling**: each sampled selection is built
  as a real one-shot disc from retail, the published chain is applied
  exactly the way the web patcher applies it, and the result must match
  that disc byte for byte. The manifest's `verified` column records the
  selections that exercised each row; rows no sample exercised are named
  in the build summary. That is the residual risk sampling accepts, and
  it covers patch composition, not in-game behavior (that is the audits
  and in-game QA).
- **`SIZE_CHANGERS` is checked, not trusted**: the build measures each
  solo variant against the base image and stops if the classification
  disagrees. If an option starts (or stops) growing the image, fix the
  constant and expect a full rebuild - the whole graph hangs off it.

#### Adding a release option (checklist)

1. Implement the patch and add it to `QOL_PATCHES` in
   `src/injection_tools/build.py` (with its verify gates).
2. Add it to `CHOICES` in `tools/build_patches.py`. If its build changes
   the image size, also add it to `SIZE_CHANGERS` - a wrong guess stops
   the build at the solo-size check.
3. Add its wording to `tools/release_options.json` (label, name,
   description - the single source of option wording: `CHOICES` derives
   from it, the release README is generated from it, and the Pages
   workflow builds the web patcher's `features.js` from it; tests enforce
   coverage and generator output).
4. Everything else derives: file names, manifest rows, the release
   completeness count, the webpatcher grid and chains. Update the
   hardcoded expectations in `tools/tests/test_build_patches.py` if a
   count moved.
5. Rebuild from scratch: the fingerprint changes, every canonical state
   is re-assembled and audited, and the sampled selections are rebuilt
   and their chains compared. Adding an in-place option costs one
   canonical state and one file; adding a size-changer adds 2^(m-1)
   canonical layouts and doubles its own anchor rows, the only part that
   grows exponentially.

`--publish-release` (formerly `--publish-web`) uploads the `--output`
directory (default `dist/patches`) to a GitHub release as one
`persona-patches.zip` holding the patch files, `manifest.tsv` and
`README.txt`: manual xdelta users download the zip directly. The upload
targets the repository named by `RELEASE_REPO` in `webpatcher/app.js`,
since `origin` is not GitHub.

The web patcher site itself deploys from this repository through
`.github/workflows/pages.yml` on every push to `main`, on every published
release, and on demand. Before uploading the artifact, the workflow
downloads the release's zip and unpacks it into `webpatcher/patches`
(git-ignored), so the site serves the patches from its own origin: a page
on `github.io` cannot fetch release assets, since github.com answers those
downloads without CORS headers. No build step, second repository or
`gh-pages` branch is involved. Enable it once under Settings -> Pages ->
Build and deployment -> Source -> GitHub Actions; the project site is
`https://<owner>.github.io/<repo>/`.

Common preparation runs once, and so do the variant-independent outputs: the
save-UI armips inputs, the TALK and ending builders, and their inventory unit
tests read only the translation and retail data, so they are generated and
checked before the first variant instead of once per variant. Each variant is
then injected and assembled on the shared `build/` tree, which is the only
sequential stage. Every image is written onto a clone of the staged retail
disc, exactly as the matching `build.py --qol=...` command writes it, so a
release target is the same bytes as the build a developer can reproduce by
hand. Parent variants are only delta sources; because unchanged file
contents still match between two variants, the patches stay small even when
the two images place those files at different extents. The audit compares
every image with retail, the same baseline an ordinary build uses.

As soon as the variant's disc image exists, its placement record and the few
builder report files are copied into a slot-private snapshot, and from there
everything - the disc audit, the xdelta encode, the check-only decode,
hashing and publication - runs in a worker pool (`--workers`, default 3),
pipelined behind the assembly of the next variant. The audit reads the
snapshot, not the tree the next variant is already rewriting, so it is
race-free and costs nothing on the sequential path. Layer variants keep their
images as hardlinked delta sources for their children.

Mark artwork is generated and verified once per run. Every later variant gets
a restored copy only after its hash matches the verified cache, so byte
identical artwork does not need the same pixel decode again. If a Mark input
(the art in `src/assets/mark/black`, its producer, or the retail scenes)
changes mid-run, the run stops and names the changed files: every variant
built so far carries the old artwork, so a release that mixed both would be
silently wrong.
Every xdelta is decoded in check-only mode (`xdelta3 -d -J`): every target
window is reconstructed and its checksum verified, but no decoded image is
written or read back, which removes two full disc-image passes per patch.
The Rev 1 conversion is completed first, followed by the base translation:
its disc audit and `rev0-to-base.xdelta` publication finish before any option
variant is assembled. On resume, an existing base patch is decoded and its
source and target hashes are checked before any option work. Option patch
audits and encoding may then run concurrently with later option assemblies.
Each patch is published to `dist/patches/` immediately - there is no
staging directory, and each patch is verified before its file appears.
The manifest records each patch file's SHA-256, the source/output sizes,
the whole-image hashes of the revision conversions and the base translation
(the only rows whose inputs are a real disc), the sampled selections that
exercised each row, and the build fingerprint that produced it.

Reruns are incremental. A completed release rerun verifies its recorded
patches and builds nothing. A missing or invalidated patch rebuilds only
the canonical state it belongs to: a canonical image not assembled this
run is reconstructed by decoding its verified patch (`rev0-to-base`, then
the add- steps), so a rebuilt child still has its parent's exact bytes
without rebuilding that parent. A rebuilt row clears its `verified`
selections, so only the samples that use it are rebuilt and compared
again.
Any input change (source, translation, game data) invalidates the affected
build keys, and inputs that change mid-run abort the run rather than
stamping unverified patches. The fingerprint deliberately watches only
what feeds the disc - `src/`, `translation/`, the extracted data, and the
two scripts it runs - so unrelated churn in `tools/tests/` never
invalidates a running release. The Rev 1 to Rev 0 conversion never depends
on build inputs and is reused across any same-source run. A release is
complete when its manifest lists all 12 steps across the 12 patch files.

The run's scratch images live in a private workspace that is deleted on
exit. It prefers the system temp directory (tmpfs on most Linux systems) when
it can hold every image the run keeps (the staged retail copy, the base
translation and the parent states that later steps decode from), then
`build/`; `PERSONA_BUILD_SCRATCH` names the parent directory explicitly. The
retail image is staged there once, so the spinning disc is read once rather
than once per variant, and the number of images allowed to wait for the
delta pool is bounded by the available space. On a reflink filesystem
(btrfs) image clones share their unchanged extents and cost almost no data
blocks; elsewhere the bound reserves room for the staged original, the base
image, the image being assembled and the kept parent images. Builds sharing
`build/` must not run together.

### Browser patcher

`webpatcher/` is a static page that applies a release in the browser: the
disc revision is identified by applying `rev1-to-rev0` (or `rev0-to-base`)
in xdelta's check-only mode, then the chain (`rev1-to-rev0` when needed,
`rev0-to-base`, then each chosen option's `add-*` in the manifest's order)
is decoded by the real xdelta3 3.2.2 compiled to WebAssembly (see
`webpatcher/vendor/README.md`). `webpatcher/plan.js` derives the chain from
the manifest's `adds`/`anchor`/`order`/`choices` columns alone, picking the
most specific `add-` file whose anchor is already applied. Every step is
checked before the next applies: the patch file's SHA-256 must match the
manifest, xdelta's own window checksums run when the applied options are
exactly the row's canonical source, and a decorated disc is decoded with
`-n` (the release build proved that exact decode over the maximally
decorated parent) with the output size checked. The page also generates a
correct single-track `.cue` for
the patched image, and names both downloads from the release
(`Persona-TL.bin`, `Persona-TL-saves-mark.bin`, ...) instead of reusing the
file name the user picked. The name carries no revision: the Rev 1 step
already converts the source to Rev 0, so the output is Rev 0 either way. Which options exist comes from the manifest; what each
one is called and what it does lives in `tools/release_options.json`,
the single source of option wording. `app.js` reads the generated
`features.js` (written by `tools/generate_features.py`, run by the Pages
workflow) keyed by the manifest label, and the test suite fails if a
release choice has no entry there. See `webpatcher/README.md` for
assembly and hosting.

## Source plans

The tracked plans cover S2D, dungeons, story speaker arbitration, battle
dialogue, dungeon names, answers, and the EBOOT boot strings (including the
notice/control consumer proofs). Each plan is validated against the PSX and
PSP-US inputs and the matching rule files before replay. Recapture a plan with
its producer when those rules or the correspondence inputs change:

```sh
python src/extraction_tools/matching/s2d_port_plan.py
python src/extraction_tools/matching/dng_port_plan.py
python src/extraction_tools/matching/story_port_plan.py
python src/extraction_tools/matching/btlevt_port_plan.py
python src/extraction_tools/matching/dngnames.py plan
python src/extraction_tools/matching/answers_port_plan.py
python src/extraction_tools/matching/eboot_twin_plan.py
python src/extraction_tools/matching/reward_notice.py
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

The batch command and release patch builder share common preparation within
one process; each variant still receives the ordinary assembly and QA checks.
