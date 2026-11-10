# Web patcher

A static page that applies the release patches in the browser: the user
picks their original disc image, selects options, and downloads the patched
`.bin` plus a generated `.cue`. Nothing is uploaded; everything runs
locally. Works on GitHub Pages or any static host.

The patches are decoded by the real xdelta3 3.2.2 (the same version that
produced the release patches) compiled to WebAssembly - see
[CREDITS.md](CREDITS.md) and [vendor/README.md](vendor/README.md).

## How it works

- `manifest.tsv` drives everything: one row per patch file names the option
  it adds (`adds`), the size-changers it was encoded against (`anchor`), its
  fixed apply position (`order`) and the canonical state it produces
  (`choices`). `plan.js` builds the options grid and turns a selection into
  the ordered chain; no combination list exists anywhere.
- Every step is checked before its result is used. The patch file's
  SHA-256 must match the manifest, and the output size must match the row.
  When the applied options are exactly the row's canonical source, xdelta's
  own window checksums verify the step. A decorated disc (other in-place
  options riding along) is decoded with `-n`; the release build verified
  the chains by sampling real built discs and recorded the selections that
  exercised each row in `verified`.
- What each option is called and what it does lives in
  `tools/release_options.json` - the single place option wording exists.
  The release README is generated from it, and the Pages workflow turns
  it into `features.js` (git-ignored, generated), which `app.js` loads
  before anything renders; `app.js` itself never carries wording.
  `tools/tests/test_webpatcher.py` fails if a release choice is missing
  its name or description.
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
  buttons, no filename sniffing. Apply stays available while that check (and
  its patch download) is still running; a click waits for it. A file that is
  neither revision is refused with the reason, and nothing is written.
- The base patch (`rev0-to-base.xdelta`, about 3 MB) is downloaded as soon
  as the page opens, before a disc is picked, and every patch fetched stays
  cached for the visit. Identifying a disc and then applying it - or applying
  again - downloads each file only once.
- The chain is derived from the manifest itself: selected options apply in
  `order`, each picking the most specific `add-` row whose `anchor` is
  already applied (for example `rev1-to-rev0` on Rev 1 discs, then
  `rev0-to-base`, `add-mark`, `add-saves`, `add-60fps-saves`). In-place
  options come first, one file each; size-changers come last, each encoded
  against the layout built before it. A wrong or corrupt file fails with a
  clear message instead of producing a download.
- The source disc and patch files are mounted read-only through a small
  WORKERFS (`workerfs.js`) because the vendored wasm build exposes
  Emscripten's `FS` but not its workerfs library. A rebuild that includes
  workerfs makes the shim a no-op. xdelta's output goes to the writable
  directory around that mount: MEMFS in the worker heap by default, or OPFS
  files on disk in low-RAM mode (`opfsfs.js`). Either way the source disc is
  never copied into the worker heap.
- The `.cue` is generated fresh (single MODE2/2352 track, the same
  convention as `src/injection_tools/build_disc.py`) because retail cue
  sheets are often wrong for single-track images.
- Downloads are named from the release, not from the file the user picked:
  the manifest's release stamp comes first (`2026-11-10`, or `2026-11-10-2`
  for a second release that day), then the chosen labels (for example
  `Persona-TL-2026-11-10-2-saves-mark.bin`). A manifest without a stamp
  keeps the old unstamped name. A dump name or hash never leaks into the
  output name, and there is no source-revision suffix: a Rev 1 disc is
  converted to Rev 0 before the translation is applied.

## Assembling a release site

The public page serves the patches from its own origin: the Pages workflow
downloads the latest release's `persona-patches.zip` and unpacks it into
`webpatcher/patches/` right before it uploads the artifact, so patch
updates are just a new release. One script uploads it:

    python tools/publish_patches.py

It uploads the release as one zip asset (tag `patches-YYYY-MM-DD`,
becoming `-2`, `-3`, ... for another release that day) via the gh CLI, to
the repository named by `RELEASE_REPO` in `app.js` - publishing must not
depend on what `origin` points at. The tag is written into the manifest's
`release` column before upload, which is what stamps result filenames. The zip holds the patch files,
The Pages workflow replaces `$VERSION` in `index.html` with the release in
the deployed `manifest.tsv`, so the page identifies the patch set it serves.

`manifest.tsv` and `README.txt`: people applying xdelta by hand download
it directly, and the Pages workflow unpacks it, so the page can still
fetch `manifest.tsv` first and then only the patches along the chosen
chain (usually a handful).

The page itself is deployed by `.github/workflows/pages.yml`. The workflow
runs on every push to `main`, on `release: published`, and manually; each
run downloads the release's zip, unpacks it into `webpatcher/patches/`
(git-ignored, so a fresh checkout does not have it) and uploads
`webpatcher/` as the Pages artifact - no build step.
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

For local testing, generate the option wording once and sync the patches;
`features.js` and `webpatcher/patches/` are both git-ignored (a symlink
to dist/patches works for the patches too):

    python tools/generate_features.py
    python tools/publish_patches.py --no-release

`localhost` is already a secure context for `crypto.subtle`, so this is
enough on the machine itself:

    python -m http.server -d webpatcher 8000

Then open <http://localhost:8000>. To test from another device (for
example a phone, to exercise the low-RAM OPFS path), serve it over real
HTTPS with tailscale:

    tailscale serve --bg 8000

and open the `https://<machine>.ts.net` URL it prints (run
`tailscale serve status` to see it again). Both count as secure contexts,
so `crypto.subtle` is available in both.

## Memory

The worker keeps one output slot at a time: each verified step truncates the
previous intermediate, so the chain never accumulates disc images. The
selected source is read on demand through `workerfs.js`, not copied into the
worker heap.

MEMFS is the default: a computer holds the chain in its tab and no disc image
ever lands in browser storage. Its peak is around 1.5 GB in the tab (one disc
image plus the Blob handed to the download), which is fine on a desktop but
not on a phone.

"I don't have enough RAM mode" moves the output to OPFS instead, where both
slots are real files in the origin private filesystem, mounted into the xdelta
runtime by `opfsfs.js` (current Chrome, Edge, Firefox and Safari). The tab heap
then stays small instead of holding a patched disc; OPFS needs room for the
source being read and the output being written, up to about two disc images
while a step runs. The page turns the mode on by itself on Android and when
the browser reports less than 4 GB of memory; it can also be toggled by hand.

The final image stays in OPFS as the download Blob because Chrome invalidates
a `File` once its entry is removed. A result that is actually backed by OPFS
shows the storage warning and the Delete button below the download links, so
the user knows to download and clean up. The image is removed when the page
replaces the result with a newer run, when the user clicks Delete, or when the
tab goes away once a download has had a minute to finish. The page also sweeps on load. A directory left by a crash or a close
that could not finish deleting is no longer behind a Web Lock, so the next
visit or run removes it after ten minutes; without Web Locks the fallback is
a day. If OPFS or a sync access handle is unavailable, the run quietly uses
MEMFS and the page says so.

Leaving the page asks for confirmation while a patch is still running, while
a finished disc has not been downloaded, and while an OPFS copy is still
there (so it can still be deleted). Browsers use their own wording for that
dialog.

The page checks the source file up front and verifies every step before
writing anything, so a failure never produces a partial download.

## Rebuilding the vendored wasm

See `build-xdelta3-wasm.sh` (requires emsdk). After rebuilding, update the
checksum table in `vendor/README.md` - `tools/tests/test_webpatcher.py`
keeps it honest and exercises a full decode chain under Node.
