'use strict';
/* Node harness for xdelta's check-only mode (-J) through the vendored wasm.
 * worker.js identifies the disc by applying rev1-to-rev0 or rev0-to-base
 * with -J and reading the exit status; this performs the same call and
 * asserts the status. Called by tools/tests/test_webpatcher.py; never used
 * in the browser.
 *
 *   node webpatcher_identify.js <xdelta3.js> <workerfs.js> <source> \
 *        <patch> <expected-exit>
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const vendorJs = path.resolve(process.argv[2]);
const workerfsJs = path.resolve(process.argv[3]);
const sourcePath = process.argv[4];
const patchPath = process.argv[5];
const expected = Number(process.argv[6]);

const Module = require(vendorJs);
globalThis.Module = Module;
vm.runInThisContext(fs.readFileSync(workerfsJs, 'utf8'));

globalThis.FileReaderSync = class {
  readAsArrayBuffer(blob) {
    const bytes = blob.bytes;
    return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  }
};

const blobOf = bytes => ({
  size: bytes.length, lastModified: Date.now(),
  slice(start, end) { return {bytes: bytes.subarray(start, end)}; },
});

const FS = Module.FS;
const work = '/identify';
FS.mkdir(work);
const patchName = path.basename(patchPath);
FS.mount(FS.filesystems.WORKERFS, {blobs: [
  {name: 'source.bin', data: blobOf(fs.readFileSync(sourcePath))},
  {name: patchName, data: blobOf(fs.readFileSync(patchPath))},
]}, work);

let status;
try {
  status = Module.callMain(
      ['-d', '-J', '-q', '-s', work + '/source.bin', work + '/' + patchName]);
} catch (err) {
  if (err && typeof err.status === 'number') status = err.status;
  else throw err;
}
FS.unmount(work);

if (status !== expected) {
  console.error(`IDENTIFY_FAIL: exit ${status}, expected ${expected}`);
  process.exit(1);
}
/* Under Node the wasm runtime sets process.exitCode to the command status,
 * so an expected nonzero exit would still fail the harness. */
console.log('IDENTIFY_OK ' + status);
process.exit(0);
