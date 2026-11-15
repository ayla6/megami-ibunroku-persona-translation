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
  buttons, no filename sniffing. Build disc stays available while that check (and
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
- **Build PPF** (the first button; Build disc, which applies the patches, comes last) writes a `.ppf` (PPF 3.0, `ppf.js`) for
  players who soft-patch instead of keeping a patched `.bin`. Nothing is
  applied: the release patches are plain VCDIFF (`xdelta3 -S none`), and
  `vcdiff.js` follows their instructions over a sparse view of the disc - a
  list of "the original's bytes from offset f" and literal-byte segments,
  where an unchanged 8 MB window is one same-offset COPY. The PPF is written
  from the stretches where the result differs from the disc it patches, so
  only those are ever read from the user's file (through a 16 MB block
  cache). The base translation plus three options takes about 2.5 s and
  about 0.5 GB of memory, against a full image per step for Build disc. Every
  release image keeps retail Rev 0's length (`build_disc.py` shares
  retail's duplicate files instead of growing the image). The PPF has
  records of at most 255 bytes, short unchanged gaps joined, and the block
  check of the 1024 original bytes at 0x9320 that appliers compare before
  patching; it is about 15-30 MB because each changed sector's EDC/ECC is
  carried as plain bytes. xdelta3 still identifies the disc first, each
  patch file must match its manifest SHA-256 and each step its output size;
  the window checksums are not computed (that would read the whole disc
  per step).
- A PPF can only overwrite bytes, never grow a file, and a Rev 1 disc is
  14 sectors shorter than Rev 0. Build PPF on a Rev 1 disc therefore makes
  the PPF against the Rev 0 disc (the first step's result) and offers that
  Rev 0 `.bin`/`.cue` beside it, as a Blob of slices of the user's file plus
  the converted bytes, with a note to keep using that disc for this and
  future PPFs.
- Build PPF also takes a **CHD** of Rev 0 (`chd.js`, `lzma.js`, following
  libchdr and the LZMA SDK in DuckStation's `dep/`). DuckStation applies a
  `<image>.ppf` to whatever image it loads, sector by sector, so the same
  PPF serves the `.bin` and the `.chd`; it is named after the CHD. The CHD
  is recognised by its header's raw SHA-1 against the manifest's
  `source_chd_sha1`, so identifying it unpacks nothing; then a first pass
  over the chain records which of its blocks the PPF reads, only those are
  unpacked (about a tenth of the disc for the base translation and three
  options), each checked against the CRC-16 in the CHD's map, and the PPF
  is built from them. Unpacking is spread over up to four block workers
  (`chdblocks.js`, one per spare core). With **Keep CHD parts** (under
  Memory and storage, on by default) the exact stretches of the disc a PPF
  read are kept in IndexedDB, one record per disc under its raw SHA-1 - the
  same disc always holds the same bytes - so a later PPF from that CHD
  (other options, a new release) unpacks only blocks for
  stretches the record lacks: 31.5 MB for the translation with Black Mark,
  saves and 60 fps, and another option set then needed one more block
  (unticking the option deletes the record; clearing the site's data
  drops it too). chdman's default CD codecs are read - `cdlz` (LZMA,
  `lzma.js`) and `cdzl` (deflate, `inflate.js`; both synchronous, since a
  stream per small block costs more than the unpacking) - and a block in any
  other codec (`cdfl` FLAC, `cdzs` zstd), a parent CHD or a Rev 1 CHD is
  refused with the reason. Build disc does not take a CHD (it shows dimmed, and hovering or clicking
  says why: Build PPF, or the .bin): xdelta patches only
  the raw `.bin`.
- With the File System Access API (Chrome, Edge) **Source disc** starts
  with the disc folder: "Disc folder: ... [Choose folder]". Below it, a
  search over the folder's `.bin` and `.chd` files picks the disc: it starts
  as "Megami Ibunroku Persona", every word must appear somewhere in a name,
  and an empty search lists nothing. The discs the page recognises - a
  `.bin` by its size, a `.chd` by the raw SHA-1 in its 124-byte header -
  carry their revision and come first, and the best one is picked at once:
  the disc used last, else the file picked with the file input, else one
  that already has a `.ppf.txt`, else a Rev 0 disc, else the first. The
  picked disc is highlighted and always heads the list, whatever the
  search (an empty search shows it alone); any
  listed file can be picked by clicking it, and the usual disc check then
  decides. Choosing a folder always picks from it; on a reload it does so
  only when no disc is picked yet. The folder is remembered (its handle in
  IndexedDB); when the browser has dropped the permission, the button reads
  Allow access and one click brings it back. A file picked with the file
  input instead is looked up in the folder by name; when it is not there
  the page says so, and the search stays up to pick from.
  A PPF built from a disc picked there is saved next to it at once -
  from a Rev 1 disc together with the Rev 0 `.bin`/`.cue` it patches, which
  becomes the disc from then on.
- **Build PPF** with a disc chosen from the disc folder (Chrome and Edge)
  writes the `.ppf` and its `.ppf.txt` straight next to the disc - where an
  emulator looks for the PPF - with the options ticked now, and says "The
  PPF was placed alongside the selected disc"; there is nothing to download.
  From a Rev 1 disc the PPF patches the Rev 0 copy: the copy already in the
  folder (checked like any picked disc), or a new `.bin`/`.cue` written
  there with the PPF, which becomes the disc used from then on. A `.ppf`
  this patcher did not write (its description must start with
  `Persona-TL-`) is never overwritten, and a PPF whose note already holds
  this release and these options is left alone. The same button therefore
  updates a PPF after a new release. With a disc from the file picker, or
  without the folder API, Build PPF offers the `.ppf` and `.ppf.txt` (and a
  converted Rev 0 disc) as downloads instead.
- Under the title, a banner says when there is a new update: on load the
  page compares this release's stamp with the release this browser last
  patched with - the newest Patched before entry, or the remembered disc's
  `.ppf.txt` once the disc folder is open - and names both ("You're on
  ..."). It goes away as soon as something is patched with this release,
  and never shows for an unstamped (local) release, which has nothing to
  compare.
- **Patched before** (collapsed until opened) lists everything patched in
  this browser, from its localStorage: when, which release, disc or PPF,
  from which revision, with which options, and the file name. A result is
  recorded once, when it is first saved (a link, or written into the disc
  folder); the
  latest 200 are kept, and the list can be cleared.
- Patches travel gzipped: the Pages deploy writes `<patch>.gz` next to each
  `.xdelta` (GitHub Pages sends `.xdelta` as uncompressed binary), and the
  page fetches the `.gz` and unpacks it with `DecompressionStream` - about
  5.4 MB for the whole release instead of 8.2 MB; the Rev 1 conversion
  shrinks from 3.3 MB to 1.1 MB. Without a `.gz` (a local copy of
  `dist/patches`) it fetches the plain file, and the manifest's SHA-256 is
  checked on the unpacked bytes either way.
- The page and its patches are always one release. The deployed page
  carries its release in `<html data-release>` (stamped with the title by
  `tools/stamp_webpatcher.py`) and the manifest names it in its `release`
  column; when a browser kept an old copy of either, the page refuses to
  patch and asks for a reload (Ctrl+Shift+R). Everything stays cached as
  usual; each patch is fetched with `?sha=` and the start of its manifest
  hash, which keeps it cached within a release but never hands a new
  release an old file of the same name. An unstamped (local) page or
  manifest has nothing to compare.
- Downloads other than a PPF and its Rev 0 disc are named from the
  release, not from the file the user picked:
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
`release` column before upload, which is what stamps result filenames. The
Pages workflow replaces `$VERSION` in `index.html` with the release in the
deployed `manifest.tsv` (without the `patches-` prefix), and embeds the
checkout's `RELEASE_NOTES.md` as escaped text. Clicking the version expands
those notes without leaving the page. The zip holds the patch files,
`manifest.tsv` and `README.txt`: people applying xdelta by hand download
it directly, and the Pages workflow unpacks it, so the page can still
fetch `manifest.tsv` first and then only the patches along the chosen
chain (usually a handful).

`python tools/serve_webpatcher.py --no-tailscale` serves the same stamped
page locally without modifying the HTML template. If the local manifest has
not yet been stamped by the publisher, its version is shown as `local`.
Restart the server after editing the page, release notes, or manifest.

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
