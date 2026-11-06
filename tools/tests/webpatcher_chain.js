'use strict';
/* Node harness for webpatcher/vendor/xdelta3.js: applies a decode chain the
 * same way worker.js does - source and patches mounted read-only through
 * WORKERFS, outputs written to the writable parent - and checks the final
 * bytes against the CLI's ground-truth SHA-256. Called by
 * tools/tests/test_webpatcher.py with a synthetic release chain; never used
 * in the browser. */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const vm = require('vm');

const vendorJs = path.resolve(process.argv[2]);
const workerfsJs = path.resolve(process.argv[3]);
const xdeltaJs = path.resolve(process.argv[4]);
const work = process.argv[5];
const expectedSha = process.argv[6];
const patches = process.argv.slice(7);

const Module = require(vendorJs);
globalThis.Module = Module;
vm.runInThisContext(fs.readFileSync(workerfsJs, 'utf8'));
vm.runInThisContext(fs.readFileSync(xdeltaJs, 'utf8'));

/* The browser worker has FileReaderSync; Node does not. Feed it the same
 * Blob-like slice objects the mount receives. */
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
const mount = '/work/in';
FS.mkdir('/work');
FS.mkdir(mount);
FS.mount(FS.filesystems.WORKERFS, {
  blobs: [{name: 'source.bin', data: blobOf(fs.readFileSync(path.join(work, 'source.bin')))},
          ...patches.map(name => ({name,
              data: blobOf(fs.readFileSync(path.join(work, name)))})),
  ],
}, mount);

const shaOf = bytes =>
    crypto.createHash('sha256').update(bytes).digest('hex');

let from = mount + '/source.bin';
for (let index = 0; index < patches.length; index++) {
  const to = `/work/out${index % 2}.bin`;  // never the source of this step
  const status = runXdelta(
      ['-d', '-f', '-q', '-s', from, mount + '/' + patches[index], to]);
  if (status !== 0) {
    console.error(`CHAIN_FAIL step ${index} (${patches[index]}): exit ${status}`);
    process.exit(1);
  }
  /* Same cleanup as worker.js: only the current input and the output being
   * written may exist. */
  if (from !== mount + '/source.bin') FS.truncate(from, 0);
  from = to;
  const live = FS.readdir('/work').filter(
      name => name.startsWith('out') && FS.stat('/work/' + name).size > 0);
  if (live.length !== 1 || live[0] !== path.basename(to)) {
    console.error(`CHAIN_FAIL step ${index}: live outputs ${JSON.stringify(live)}`);
    process.exit(1);
  }
}
const node = FS.lookupPath(from).node;
const sha = shaOf(node.contents.subarray(0, node.usedBytes));
if (sha !== expectedSha) {
  console.error(`CHAIN_FAIL sha mismatch: got ${sha}, expected ${expectedSha}`);
  process.exit(1);
}
FS.unmount(mount);
console.log('CHAIN_OK ' + sha);
