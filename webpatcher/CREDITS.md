# Credits and licenses

## Vendored software

**xdelta3** (`vendor/xdelta3.js` + `vendor/xdelta3.wasm`) - the xdelta3
3.2.2 command-line tool compiled to WebAssembly from the unmodified
upstream sources at <https://github.com/jmacd/xdelta>, under the
**Apache License 2.0**. The license text is kept in
`vendor/LICENSE-xdelta3`; the build recipe is
`build-xdelta3-wasm.sh`, and provenance plus artifact checksums are in
`vendor/README.md`.

**xz / liblzma 5.4.6** - linked into the wasm build for lzma secondary
decompression (the XZ Utils authors placed it in the public domain). The
release patches are encoded by the official xdelta3 3.2.2 binaries, whose
default secondary compression is lzma, so the browser build needs it to
decode them.

**Emscripten** (MIT) - compiles all of the above to WebAssembly.
`workerfs.js` is adapted from Emscripten's `src/lib/libworkerfs.js` (MIT)
so the worker can mount the selected disc even though the vendored build
does not include that library.

## Inspired by

- <https://github.com/kotcrab/xdelta-wasm> (Apache-2.0) - studying it
  settled the design: run the real xdelta3 C code in a wasm worker instead
  of reimplementing the format in JavaScript, and build xz the way it does.
  No code was copied.

## Licensing

This repository is MIT (see the root `LICENSE`). The vendored build above
stays Apache-2.0; keeping its notice, license text, and provenance in this
directory is all that requires. Nothing about the project license needs to
change to include it.
