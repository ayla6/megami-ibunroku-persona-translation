'use strict';
/* Node harness for a -n decode chain through the wasm: xdelta runs with -n
 * (the patch's window checksums describe the encode source, not the
 * decorated state it is applied over) and every step's output is hashed
 * with the native crypto.subtle and compared with the expected target
 * hash. Called by tools/tests/test_webpatcher.py with a synthetic release
 * chain; the worker's choice of -n is covered by CanonicalSourceTest.
 *
 *   node webpatcher_sha256_chain.js <vendor/xdelta3.js> <workerfs.js>
 *       <xdelta.js> <work> <patch> <expectedSha> [...]
 *
 * Each (patch, expectedSha) pair is one step; the chain starts from
 * <work>/source.bin.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const vendorJs = path.resolve(process.argv[2]);
const workerfsJs = path.resolve(process.argv[3]);
const xdeltaJs = path.resolve(process.argv[4]);
const work = process.argv[5];
const stepArgs = process.argv.slice(6);

const Module = require(vendorJs);
globalThis.Module = Module;
vm.runInThisContext(fs.readFileSync(workerfsJs, 'utf8'), {filename: workerfsJs});
vm.runInThisContext(fs.readFileSync(xdeltaJs, 'utf8'), {filename: xdeltaJs});

const steps = [];
for (let i = 0; i + 1 < stepArgs.length; i += 2) {
  steps.push({patch: stepArgs[i], expected: stepArgs[i + 1]});
}

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
          ...steps.map(step => ({name: step.patch,
              data: blobOf(fs.readFileSync(path.join(work, step.patch)))})),
  ],
}, mount);

async function main() {
  let from = mount + '/source.bin';
  for (const [index, step] of steps.entries()) {
    const to = `/work/out${index % 2}.bin`;  // never the source of this step
    const status = runXdelta(
        ['-d', '-f', '-q', '-n', '-s', from, mount + '/' + step.patch, to]);
    const size = status === 0 ? FS.stat(to).size : -1;
    if (size < 0) {
      console.error(`SHA_CHAIN_FAIL step ${index} (${step.patch}): exit ${status}`);
      process.exit(1);
    }
    const node = FS.lookupPath(to).node;
    const digest = await crypto.subtle.digest(
        'SHA-256', node.contents.subarray(0, node.usedBytes));
    const hex = [...new Uint8Array(digest)]
        .map(byte => byte.toString(16).padStart(2, '0')).join('');
    if (hex !== step.expected) {
      console.error(`SHA_CHAIN_FAIL step ${index} (${step.patch}): got `
          + `${hex}, expected ${step.expected}`);
      process.exit(1);
    }
    if (from !== mount + '/source.bin') FS.truncate(from, 0);
    from = to;
    const live = FS.readdir('/work').filter(
        name => name.startsWith('out') && FS.stat('/work/' + name).size > 0);
    if (live.length !== 1 || live[0] !== path.basename(to)) {
      console.error(`SHA_CHAIN_FAIL step ${index}: live outputs ${JSON.stringify(live)}`);
      process.exit(1);
    }
  }
  FS.unmount(mount);
  console.log('SHA_CHAIN_OK');
}

main().catch(err => {
  console.error('SHA_CHAIN_FAIL ' + err);
  process.exit(1);
});
