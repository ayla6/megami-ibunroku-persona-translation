# Vendored xdelta3 for the web patcher

`xdelta3.js` + `xdelta3.wasm` are the xdelta3 3.2.2 command-line tool
compiled to WebAssembly, built by `../build-xdelta3-wasm.sh` from the
unmodified upstream sources:

- xdelta 3.2.2 (https://github.com/jmacd/xdelta, Apache License 2.0) - the
  same version the release builder uses (`src/setup_external_tools.py`), so
  the browser decodes patches with the identical engine that produced them.
- xz 5.4.6 (https://tukaani-project/xz, public domain) - linked in for lzma
  secondary decompression. The release patches are encoded with the official
  xdelta3 3.2.2 binaries, whose default secondary compression is lzma; a
  build without it fails with `unavailable secondary compressor: LZMA`.

Enabled secondaries: lzma, djw, fgk. Emits the plain (non-modularized)
glue so `worker.js` can load it with `importScripts`.

The committed build exposes `FS` but not Emscripten's workerfs library
(`FS.filesystems.WORKERFS` is absent), so `../workerfs.js` supplies the
read-only mount for the source disc. It leaves a rebuild that does include
workerfs alone.

## Artifact checksums

`tools/tests/test_webpatcher.py` verifies these against the committed files;
update the table after every rebuild.

| file | sha256 |
|---|---|
| xdelta3.js | 4ae2dde54ba3419182fc1b2fb21072a7016464677ab8bb104b131b513b39e1a5 |
| xdelta3.wasm | 2fb7b16b279635925a3c294b8b0d14adaba3b53394d798bcb702a3d556cf9e1d |
