# Web patcher

A static page that applies the release patches in the browser: the user
picks their original disc image, selects options, and downloads the patched
`.bin` plus a generated `.cue`. Nothing is uploaded; everything runs
locally. Works on GitHub Pages or any static host.

The patches are decoded by the real xdelta3 3.2.2 (the same version that
produced the release patches) compiled to WebAssembly - see
[CREDITS.md](CREDITS.md) and [vendor/README.md](vendor/README.md).

## How it works

- `manifest.tsv` drives everything: the options grid is built from the
  `choices` column and each combination of checkboxes maps to its exact
  row. Nothing is hardcoded per release.
- Every step is applied by xdelta3 with its own source and target window
  checksums, so a wrong disc or damaged patch makes xdelta fail instead of
  producing a download. The manifest's recorded output sizes are checked
  too; no separate hash is computed in the page.
- `FEATURES` at the top of `app.js` holds the wording shown for each
  option, keyed by the manifest label: `name` is the title, `description`
  the paragraph under it. Rewording is a site change, not a release.
  `tools/tests/test_webpatcher.py` fails if a release choice has no entry.
- The manifest and patches come from `patches/` next to the page, served
  from the same origin. The public site gets that directory from the Pages
  workflow, which mirrors the latest release into it; release assets cannot
  be fetched at runtime because github.com serves release downloads without
  CORS headers, so a browser blocks them. `tools/publish_patches.py`
  uploads the release to `RELEASE_REPO` at the top of `app.js`.
- The disc revision is detected automatically: the worker applies a release
  patch in xdelta's check-only mode (`-J`, decode and verify but write
  nothing). `rev1-to-rev0` succeeds only on a Rev 1 disc and `rev0-to-base`
  only on a Rev 0 disc, so the patch's own checksums decide - no radio
  buttons, no filename sniffing.
- The chain is derived from the manifest itself: each patch's
  `source_sha256` equals the `target_sha256` of the patch before it, so
  the page walks the chain (for example `rev1-to-rev0` on Rev 1 discs,
  then `rev0-to-base`, `base-to-mark`, `mark-to-saves-mark`, then the
  final combination). A wrong or corrupt file fails with a clear message
  instead of producing a download.
- The source disc and patch files are mounted read-only through a small
  WORKERFS (`workerfs.js`) because the vendored wasm build exposes
  Emscripten's `FS` but not its workerfs library. xdelta's output is written
  to the writable directory around that mount, so the 700 MB disc is never
  copied into the worker heap. A rebuild that includes workerfs makes the
  shim a no-op.
- The `.cue` is generated fresh (single MODE2/2352 track, the same
  convention as `src/injection_tools/build_disc.py`) because retail cue
  sheets are often wrong for single-track images.
- Downloads are named from the release, not from the file the user picked:
  `Persona-TL.bin` for the base translation, with the chosen manifest labels
  appended (for example `Persona-TL-saves-mark.bin`). A dump name or hash
  never leaks into the output name, and there is no source-revision suffix:
  a Rev 1 disc is converted to Rev 0 before the translation is applied.

## Assembling a release site

The public page serves the patches from its own origin: the Pages workflow
downloads the latest release into `webpatcher/patches/` right before it
uploads the artifact, so patch updates are just a new release. One script
uploads it:

    python tools/publish_patches.py

It uploads `dist/patches/` as release assets (tag `patches-YYYYMMDD`;
re-running the same day clobbers the assets) via the gh CLI, to the
repository named by `RELEASE_REPO` in `app.js` - publishing must not depend
on what `origin` points at. The files stay individual on purpose: the page
reads `manifest.tsv` first and then only the patches along the chosen chain
(usually a handful), so a zip would make it fetch and unpack everything in
the browser. The same files are also uploaded as `persona-patches.zip` for
people applying xdelta by hand.

The page itself is deployed by `.github/workflows/pages.yml`. The workflow
runs on every push to `main`, on `release: published`, and manually; each
run downloads the release's `manifest.tsv`, `README.txt` and `.xdelta`
files into `webpatcher/patches/` (git-ignored, so a fresh checkout does not
have it) and uploads `webpatcher/` as the Pages artifact - no build step.
Serving the patches from the site is not cosmetic: a page at
`<owner>.github.io` cannot fetch release assets, because github.com answers
those downloads without `Access-Control-Allow-Origin`. Replacing the assets
of an existing release fires no event, so `tools/publish_patches.py`
dispatches the workflow after a clobbering upload.

Enable Pages once in the repository settings: Settings -> Pages -> Build
and deployment -> Source -> GitHub Actions. The project site is then
`https://<owner>.github.io/<repo>/`; the wasm is served with the correct
MIME type, so the subpath project site works.
`python tools/build_patches.py --publish-release` uploads the release after
a finished build and the site redeploys from it.

For local testing the page reads `webpatcher/patches/`, which
`tools/publish_patches.py --no-release` keeps in sync with `dist/patches/`
(a symlink works too):

    python -m http.server -d webpatcher 8000

Then open <http://localhost:8000>.

## Memory

Patch application peaks around 1.5 GB in the browser tab (source read plus
patched output), so desktop browsers are the realistic target. The page
checks the source file up front and verifies every step before writing
anything, so a failure never produces a partial download.

## Rebuilding the vendored wasm

See `build-xdelta3-wasm.sh` (requires emsdk). After rebuilding, update the
checksum table in `vendor/README.md` - `tools/tests/test_webpatcher.py`
keeps it honest and exercises a full decode chain under Node.
