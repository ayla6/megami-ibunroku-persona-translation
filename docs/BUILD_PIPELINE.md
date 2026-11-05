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
first and rebuilds every variant patch.

The five release choices are save UI, Mark artwork, battle speed, 60 fps,
and double rewards plus half encounters together. Debug is not included.
The 32 combinations produce 33 patches: Rev 1 to Rev 0, Rev 0 to base, and
one incoming patch for each of the 31 non-base combinations. Because Mark's
artwork is duplicated across 207 scene entries (~810 KB per delta) and the
save UI costs ~210 KB, big choices are layered: the combinations containing
them are patched from a variant that already includes them
(`mark-to-mark-60fps.xdelta`), so their bytes are encoded once instead of
sixteen times. Every patch name is SOURCE-to-TARGET, and `manifest.tsv`
describes the whole graph: each row's `source_sha256` is the previous
patch's `target_sha256`, so the chain from the base translation to any
combination can be read straight from the manifest (the web patcher in
`webpatcher/` walks it automatically). A patch against one variant never
fits another; apply whole chains only.

`--publish-release` (formerly `--publish-web`) uploads the `--output`
directory (default `dist/patches`) as a GitHub release. The release keeps
every file individual so the page can fetch `manifest.tsv` and only the
patches along the chosen chain, and adds one `persona-patches.zip` with the
same files for manual xdelta use. The upload targets the repository
named by `RELEASE_REPO` in `webpatcher/app.js`, since `origin` is not
GitHub.

The web patcher site itself deploys from this repository through
`.github/workflows/pages.yml` on every push to `main`, on every published
release, and on demand. Before uploading the artifact, the workflow
downloads the release's `manifest.tsv`, `README.txt` and `.xdelta` files
into `webpatcher/patches` (git-ignored), so the site serves the patches
from its own origin: a page on `github.io` cannot fetch release assets,
since github.com answers those downloads without CORS headers. No build
step, second repository or `gh-pages` branch is involved. Enable it once
under Settings -> Pages -> Build and deployment -> Source -> GitHub
Actions; the project site is `https://<owner>.github.io/<repo>/`.

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
The patch is then published to `dist/patches/` immediately - there is no
staging directory, and each patch is verified before its file appears.
The manifest records SHA-256 hashes of each input, output and patch plus
the build fingerprint that produced it.

Reruns are incremental. A completed release rerun verifies its recorded
patches and builds nothing. A missing or invalidated patch rebuilds only
the variants it needs: an intermediate delta source is reconstructed by
decoding its verified patches (`rev0-to-base`, then the layer chain), so a
rebuilt combination still has its parent's exact bytes without rebuilding
that parent.
Any input change (source, translation, game data) invalidates the affected
build keys, and inputs that change mid-run abort the run rather than
stamping unverified patches. The fingerprint deliberately watches only
what feeds the disc - `src/`, `translation/`, the extracted data, and the
two scripts it runs - so unrelated churn in `tools/tests/` never
invalidates a running release. The Rev 1 to Rev 0 conversion never depends
on build inputs and is reused across any same-source run. A release is
complete when its manifest lists all 33 patches.

The run's scratch images live in a private workspace that is deleted on
exit. It prefers the system temp directory (tmpfs on most Linux systems) when
it can hold a few images, then `build/`; `PERSONA_BUILD_SCRATCH` names the
parent directory explicitly. The retail image is staged there once, so the
spinning disc is read once rather than once per variant, and the number of
images allowed to wait for the delta pool is bounded by the available space.
On a reflink filesystem (btrfs) image clones share their unchanged extents
and cost almost no data blocks; elsewhere the bound reserves room for the
staged original, the base image, the image being assembled and up to three
reconstructed layer images. Builds sharing `build/` must not run together.

### Browser patcher

`webpatcher/` is a static page that applies a release in the browser: the
disc revision is identified by applying `rev1-to-rev0` (or `rev0-to-base`)
in xdelta's check-only mode, then the chain (`rev1-to-rev0` when needed,
`rev0-to-base`, then the chosen `base-to-*`) is decoded by the real xdelta3
3.2.2 compiled to WebAssembly (see `webpatcher/vendor/README.md`), and
xdelta's own source and target checksums verify every step before the next
applies. The page also generates a correct single-track `.cue` for
the patched image, and names both downloads from the release
(`Persona-TL.bin`, `Persona-TL-saves-mark.bin`, ...) instead of reusing the
file name the user picked. The name carries no revision: the Rev 1 step
already converts the source to Rev 0, so the output is Rev 0 either way. Which options exist comes from the manifest; what each
one is called and what it does is the `FEATURES` table in `app.js`, keyed
by the manifest label, and the test suite fails if a release choice has no
entry there. See `webpatcher/README.md` for assembly and hosting.

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

The batch command and release patch builder share common preparation within
one process; each variant still receives the ordinary assembly and QA checks.
