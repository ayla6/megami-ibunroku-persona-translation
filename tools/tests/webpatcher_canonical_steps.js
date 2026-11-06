'use strict';
/* Node harness for the worker's canonical-source decision.
 *
 * webpatcher/plan.js decides whether the options applied so far are
 * exactly the row's canonical source. The worker passes the patch's window
 * checksums through only in that case; over a decorated source (the same
 * layout with in-place options riding along) it decodes with -n and checks
 * the output size. This harness applies the same plan.js arguments with
 * the real xdelta3 wasm and proves:
 *
 * - the canonical source applies without -n and yields the built target;
 * - a decorated source is refused without -n (the window checksums
 *   describe the canonical source);
 * - the same decorated source decodes with -n and keeps the target's
 *   changes while preserving the decorations.
 *
 *   node webpatcher_canonical_steps.js <vendor/xdelta3.js> <workerfs.js>
 *       <xdelta.js> <plan.js> <work>
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const vendorJs = path.resolve(process.argv[2]);
const workerfsJs = path.resolve(process.argv[3]);
const xdeltaJs = path.resolve(process.argv[4]);
const planJs = path.resolve(process.argv[5]);
const work = process.argv[6];

const Module = require(vendorJs);
globalThis.Module = Module;
vm.runInThisContext(fs.readFileSync(workerfsJs, 'utf8'), {filename: workerfsJs});
vm.runInThisContext(fs.readFileSync(xdeltaJs, 'utf8'), {filename: xdeltaJs});
const Plan = require(planJs);

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
  blobs: ['canonical.bin', 'decorated.bin', 'add.xdelta'].map(name => ({
    name, data: blobOf(fs.readFileSync(path.join(work, name))),
  })),
}, mount);

const step = {
  patch: 'add.xdelta',
  adds: 'z',
  source: [],
  expectBytes: Number(fs.statSync(path.join(work, 'target.bin')).size),
  patchHash: sha256(fs.readFileSync(path.join(work, 'add.xdelta'))),
};

function sha256(bytes) {
  return require('crypto').createHash('sha256').update(bytes).digest('hex');
}

function apply(sourceName, applied, out) {
  try { FS.unlink(out); } catch (err) {}
  const args = Plan.decodeArgs(step, applied);
  args.push('-s', mount + '/' + sourceName, mount + '/add.xdelta', out);
  const status = runXdelta(args);
  let size = -1;
  if (status === 0) {
    try { size = FS.stat(out).size; } catch (err) {}
  }
  return {status, size};
}

function read(out) {
  const node = FS.lookupPath(out).node;
  return Buffer.from(node.contents.subarray(0, node.usedBytes));
}

function fail(message) {
  console.error('CANONICAL_STEPS_FAIL ' + message);
  process.exit(1);
}

const out = '/work/out.bin';

/* 1. The canonical source: xdelta's own checksums decide, and they pass. */
const canonical = apply('canonical.bin', new Set(), out);
if (canonical.status !== 0) fail('canonical source did not decode: ' + canonical.status);
if (canonical.size !== step.expectBytes) {
  fail(`canonical output is ${canonical.size}, expected ${step.expectBytes}`);
}
if (!read(out).equals(fs.readFileSync(path.join(work, 'target.bin')))) {
  fail('canonical decode did not produce the built target');
}

/* 2. The decorated source over the canonical path: the patch's window
 * checksums describe the canonical source, so xdelta must refuse it. */
const wrong = apply('decorated.bin', new Set(), out);
if (wrong.status === 0) fail('decorated source passed the canonical checksums');

/* 3. The same source through plan.js's decorated path: -n decodes it, and
 * the result keeps the decorations while carrying the target's changes. */
if (!Plan.decodeArgs(step, new Set(['a'])).includes('-n')) {
  fail('plan.js did not ask for -n on a decorated source');
}
const decorated = apply('decorated.bin', new Set(['a']), out);
if (decorated.status !== 0) fail('decorated source did not decode with -n: ' + decorated.status);
if (decorated.size !== step.expectBytes) {
  fail(`decorated output is ${decorated.size}, expected ${step.expectBytes}`);
}
if (!read(out).equals(fs.readFileSync(path.join(work, 'decorated-target.bin')))) {
  fail('decorated decode did not carry the decorations through');
}

FS.unmount(mount);
console.log('CANONICAL_STEPS_OK');
