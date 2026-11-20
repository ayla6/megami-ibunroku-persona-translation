# Web patcher

A static page that applies the release to the player's own disc in the
browser: they pick their original Rev 0 disc image (a `.bin`, or a `.chd`
for a PPF), tick options, and get a patched `.bin` plus a generated `.cue`,
or a PPF. Nothing is uploaded; everything runs locally. Works on GitHub
Pages or any static host.

The release uses three foundation layers: `base.p1mod`,
`latin-alphabet.p1mod` (requires base), and `english-translation.p1mod`
(requires alphabet). Optional mods follow, with conditional compatibility
parts inside their layers. The page applies them with `modpack.js`, the
JavaScript twin of `src/pipeline/modpack.py` and `build_disc.py`.

## How it works

- `manifest.tsv` drives everything: one row per layer, with its kind
  (base / option), label, choices, requirements, release, size, SHA-1 and
  verification state. The page applies base and selected options in order;
  the worker selects their conditional parts. Ticking a component enables
  its dependencies. Required components stay checked and locked until their
  dependents are disabled; automatically enabled dependencies then turn off. Requirements
  are labels within the same release, without per-mod version ranges. The
  base row identifies the original disc by `source_bytes` and
  `source_chd_sha1`.
- What each option is called and what it does lives in its mod's
  `src/mods/<name>/mod.tsv` - the single place option wording exists.
  The release README is generated from them, and `tools/generate_features.py`
  turns them into `features.js` (git-ignored, generated), which `app.js` loads
  before anything renders. An option with `default yes` starts ticked
  when the visitor has no remembered selection.
- The disc is recognised at once from the manifest: a `.bin` by its size, a
  CHD by the raw SHA-1 in its header. A Rev 1 disc is named as such and
  refused - only Rev 0 is patched. The real check happens when a run
  applies the foundation layers: each checks the SHA-1 of its input files,
  so a dump of the right size with the wrong contents is refused there.
- Every layer is checked against its manifest SHA-1 before it is used.
  The base layer starts downloading as soon as the page opens, and every
  layer fetched stays cached for the visit.
- `worker.js` merges the selected layers' file edits in memory, then lays
  the disc out once (files that grow are moved into freed extents, the ISO
  records and the game's FNAME / FSECT / FSIZE tables follow, every changed
  sector gets fresh EDC/ECC). The result is the set of sectors that differ
  from the player's disc:
  - **Build disc**: a Blob made of slices of the player's own file with the
    changed sectors in between. Nothing disc-sized is copied in memory; the
    browser reads it while downloading. "I don't have enough RAM mode"
    (on by itself on a first visit from Android or a browser reporting
    under 4 GB) writes the disc to browser storage (OPFS) instead and lets
    each changed sector go once written; that copy is deleted the next
    time the page opens. Its `.cue` starts with `REM PATCHER <release>`
    and one `REM MOD <layer>(<settings>)` line per layer.
  - **Build PPF**: the changed sectors against the disc's own bytes
    (`ppf.js`, PPF 3.0). A selection that would make the disc larger has no
    PPF, since a PPF cannot change a file's size.
- A read of the player's file costs a fixed fraction of a second on some
  devices (Chrome on Android) whatever its size, so a `.bin` is read in a
  few large reads too: what the merge, the layout and the PPF are about to
  read is asked for up front, in slices of up to 16 MB (`binReader`), and
  the directory tree is read a depth at a time.
- A CHD is read only where the layers need it: the files they edit are
  unpacked up front by a few block workers in parallel (`chdblocks.js`),
  anything else the layout reads is unpacked on demand. With "Keep CHD
  parts" on, what was unpacked is kept in IndexedDB, so the next PPF from
  that CHD is much faster. Build disc needs the `.bin`.
- The PPF's note (`<disc>.ppf.txt`) is the release on its first line, then
  every layer applied with all of its settings, defaults included
  (`english-translation(font=large,...)`), then `own <file>` per mod of
  your own.
- With a disc folder (Chrome, Edge), Build disc writes `<disc> (Modded).bin`
  and its cue next to the disc as it goes (nothing held in memory or in
  browser storage, nothing downloaded), and Build PPF writes the PPF and its
  note next to the disc; a PPF this patcher did not
  write is never overwritten.
- The page and its layers must be one release: the page carries its
  release in `<html data-release>`, the manifest in its `release` column,
  and a mismatch (a browser that kept an old copy) asks for a reload.

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
those notes without leaving the page. The zip holds the layers,
`manifest.tsv` and `README.txt`: people applying the layers by hand
(`src/pipeline/modpack.py apply`) download it directly, and the
Pages workflow unpacks it, so the page can still fetch `manifest.tsv` first
and then only the layers of the chosen selection.

`python tools/serve_webpatcher.py --no-tailscale` serves the same stamped
page locally without modifying the HTML template. If the local manifest has
not yet been stamped by the publisher, its version is shown as `local`.
Restart the server after editing the page, release notes, or manifest.
With `--debug` the page and every patch worker also load
`tools/webpatcher_debug.js`: a log panel at the bottom of the page (each
status line, worker starts, messages and errors, every file read with its
offset, size and time, CHD block timings), mirrored to
`build/webpatcher-debug.log` on the serving machine, so a phone without dev
tools leaves its log there. The deployed site never loads it.

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
`https://<owner>.github.io/<repo>/`.
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
example a phone), serve it over real HTTPS with tailscale:

    tailscale serve --bg 8000

and open the `https://<machine>.ts.net` URL it prints (run
`tailscale serve status` to see it again). Both count as secure contexts,
so `crypto.subtle` is available in both.
