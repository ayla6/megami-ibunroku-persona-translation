#!/bin/sh
# Rebuild webpatcher/vendor/xdelta3.js + xdelta3.wasm from the xdelta 3.2.2
# sources, including the lzma secondary compressor: the release patches are
# encoded with the official xdelta3 3.2.2 binary (see
# src/setup_external_tools.py), whose default secondary compression is lzma,
# so the browser build must include it to decode release patches.
#
# Requires emsdk (https://emscripten.org) on PATH.
#
#   git clone --depth 1 --branch v3.2.2 https://github.com/jmacd/xdelta
#   curl -LO https://github.com/tukaani-project/xz/releases/download/v5.4.6/xz-5.4.6.tar.gz
#   tar -xzf xz-5.4.6.tar.gz
#   source .../emsdk_env.sh
#   (cd xz-5.4.6 && emconfigure ./configure --disable-shared \
#        --disable-scripts --disable-doc && emmake make)
#   ./build-xdelta3-wasm.sh /path/to/xdelta /path/to/xz-5.4.6
#
# After rebuilding, update the SHA-256 checksums in vendor/README.md
# (tools/tests/test_webpatcher.py checks them).
set -eu
SRC="${1:?usage: build-xdelta3-wasm.sh <xdelta-checkout> [xz-checkout]}"
XZ="${2:-}"
cd "$(dirname "$0")"

if [ -n "$XZ" ]; then
  EXTRA="-I $XZ/src/liblzma/api $XZ/src/liblzma/.libs/liblzma.a -D SECONDARY_LZMA=1 -D HAVE_LZMA_H=1"
else
  EXTRA="-D SECONDARY_LZMA=0"
  echo "warning: no xz checkout given; without lzma the release patches" \
       "will NOT decode" >&2
fi

emcc "$SRC/xdelta3/xdelta3.c" -O2 -o vendor/xdelta3.js \
  -I "$SRC/xdelta3" \
  -D XD3_MAIN=1 -D XD3_DEBUG=0 \
  -D SIZEOF_SIZE_T=4 -D SIZEOF_UNSIGNED_INT=4 \
  -D SIZEOF_UNSIGNED_LONG=4 -D SIZEOF_UNSIGNED_LONG_LONG=8 \
  -D SECONDARY_DJW=1 -D SECONDARY_FGK=1 \
  $EXTRA \
  -s ENVIRONMENT=web,worker,node \
  -s INVOKE_RUN=0 -s EXIT_RUNTIME=0 \
  -s EXPORTED_RUNTIME_METHODS=callMain,FS \
  -s FORCE_FILESYSTEM=1 -lworkerfs.js \
  -s ALLOW_MEMORY_GROWTH=1 -s MAXIMUM_MEMORY=2GB -s ABORTING_MALLOC=1 \
  -s WASM_ASYNC_COMPILATION=0
echo "wrote vendor/xdelta3.js and vendor/xdelta3.wasm"
