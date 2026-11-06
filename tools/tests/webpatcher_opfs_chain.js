'use strict';
/* Node harness for the optional OPFS scratch space.
 *
 * Applies the same decode chain as worker.js, but writes the two output
 * slots through webpatcher/opfsfs.js instead of MEMFS. OPFS is simulated by
 * tools/tests/fake_opfs.js over real temp files, so this exercises the
 * Emscripten filesystem (write, truncate, stat, getFile) and the worker's
 * one-output-at-a-time rule. Called by tools/tests/test_webpatcher.py; never
 * used in the browser. */

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const vm = require('vm');
const {FakeDirHandle} = require('./fake_opfs');

const vendorJs = path.resolve(process.argv[2]);
const workerfsJs = path.resolve(process.argv[3]);
const scratchJs = path.resolve(process.argv[4]);
const opfsfsJs = path.resolve(process.argv[5]);
const xdeltaJs = path.resolve(process.argv[6]);
const work = process.argv[7];
const expectedSha = process.argv[8];
const patches = process.argv.slice(9);

const Module = require(vendorJs);
globalThis.Module = Module;
vm.runInThisContext(fs.readFileSync(workerfsJs, 'utf8'));
vm.runInThisContext(fs.readFileSync(scratchJs, 'utf8'));
vm.runInThisContext(fs.readFileSync(opfsfsJs, 'utf8'));
vm.runInThisContext(fs.readFileSync(xdeltaJs, 'utf8'));

/* The browser worker has FileReaderSync; Node does not. */
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

const shaOf = bytes =>
    crypto.createHash('sha256').update(bytes).digest('hex');

async function main() {
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

  const scratchRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'webpatcher-opfs-'));
  const day = 24 * 60 * 60 * 1000;
  const staleName = 'persona-patch-' + (Date.now() - 2 * day).toString(36) + '-stale';
  const keptName = 'persona-patch-' + (Date.now() - 2 * day).toString(36) + '-kept';
  const freshName = 'persona-patch-' + Date.now().toString(36) + '-fresh';
  for (const name of [staleName, keptName, freshName]) {
    fs.mkdirSync(path.join(scratchRoot, name));
    fs.writeFileSync(path.join(scratchRoot, name, 'leftover.bin'), 'x');
  }

  /* Storage that cannot be opened must disable OPFS, not fail the patch:
   * worker.js then takes the MEMFS path. */
  const denied = await OPFSWorkspace.open(['out0.bin', 'out1.bin'], {
    getDirectory: async () => { throw new Error('denied'); },
  });
  if (denied !== null) {
    console.error('OPFS_FAIL: denied storage did not fall back');
    process.exit(1);
  }

  const storage = {getDirectory: async () => new FakeDirHandle(scratchRoot)};
  const workspace = await OPFSWorkspace.open(
      ['out0.bin', 'out1.bin'], storage, keptName);
  if (!workspace) {
    console.error('OPFS_FAIL: scratch space was not created');
    process.exit(1);
  }
  /* Old dirs go, except the one still backing the page's download; recent
   * dirs may belong to another tab and stay. */
  const afterCleanup = fs.readdirSync(scratchRoot).sort();
  if (afterCleanup.includes(staleName)) {
    console.error('OPFS_FAIL: stale scratch directory was not removed');
    process.exit(1);
  }
  for (const name of [keptName, freshName]) {
    if (!afterCleanup.includes(name)) {
      console.error(`OPFS_FAIL: live scratch directory ${name} was removed`);
      process.exit(1);
    }
  }
  OPFSWorkspace.mount(FS, workspace, '/work/out');

  try {
    let from = mount + '/source.bin';
    for (let index = 0; index < patches.length; index++) {
      const to = `/work/out/out${index % 2}.bin`;
      const status = runXdelta(
          ['-d', '-f', '-q', '-s', from, mount + '/' + patches[index], to]);
      if (status !== 0) {
        console.error(`OPFS_FAIL step ${index} (${patches[index]}): exit ${status}`);
        process.exit(1);
      }
      if (from !== mount + '/source.bin') FS.truncate(from, 0);
      from = to;
      const live = ['out0.bin', 'out1.bin'].filter(
          name => FS.stat('/work/out/' + name).size > 0);
      if (live.length !== 1 || live[0] !== path.basename(to)) {
        console.error(`OPFS_FAIL step ${index}: live outputs ${JSON.stringify(live)}`);
        process.exit(1);
      }
    }

    const file = await OPFSWorkspace.finish(workspace, from);
    const kept = fs.readdirSync(workspace.dir.path);
    if (kept.length !== 1 || kept[0] !== path.basename(from)) {
      console.error(`OPFS_FAIL: scratch slot cleanup left ${JSON.stringify(kept)}`);
      process.exit(1);
    }
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (bytes.length !== FS.stat(from).size) {
      console.error('OPFS_FAIL: getFile size differs from the stat size');
      process.exit(1);
    }
    const sha = shaOf(bytes);
    if (sha !== expectedSha) {
      console.error(`OPFS_FAIL sha mismatch: got ${sha}, expected ${expectedSha}`);
      process.exit(1);
    }

    /* The File stays valid after the worker closes its handles, because the
     * page still owns the directory and removes it when the result is
     * replaced. */
    await OPFSWorkspace.close(workspace);
    if (!fs.existsSync(workspace.dir.path)) {
      console.error('OPFS_FAIL: kept scratch directory disappeared');
      process.exit(1);
    }
    await workspace.root.removeEntry(workspace.dirName, {recursive: true});
    if (fs.existsSync(workspace.dir.path)) {
      console.error('OPFS_FAIL: explicit scratch directory removal failed');
      process.exit(1);
    }

    /* With Web Locks, an old directory is removed as soon as its lock is
     * free; a live page's lock keeps its directory alive. */
    const lockRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'webpatcher-locks-'));
    const lockHeld = new Set();
    const fakeLocks = {
      async request(name, options, callback) {
        if (options && options.ifAvailable && lockHeld.has(name)) {
          return callback(null);
        }
        lockHeld.add(name);
        try { return await callback({name}); } finally { lockHeld.delete(name); }
      },
    };
    const stamp = (Date.now() - 11 * 60 * 1000).toString(36);
    const orphanName = 'persona-patch-' + stamp + '-orphan';
    const heldName = 'persona-patch-' + stamp + '-held';
    for (const name of [orphanName, heldName]) {
      fs.mkdirSync(path.join(lockRoot, name));
    }
    lockHeld.add(heldName);
    const lockedWorkspace = await OPFSWorkspace.open(
        ['out0.bin'], {getDirectory: async () => new FakeDirHandle(lockRoot)},
        undefined, undefined, fakeLocks);
    if (!lockedWorkspace) {
      console.error('OPFS_FAIL: lock-test scratch space was not created');
      process.exit(1);
    }
    const afterLocks = fs.readdirSync(lockRoot);
    if (afterLocks.includes(orphanName)) {
      console.error('OPFS_FAIL: unlocked old directory was not removed');
      process.exit(1);
    }
    if (!afterLocks.includes(heldName)) {
      console.error('OPFS_FAIL: locked old directory was removed');
      process.exit(1);
    }
    await OPFSWorkspace.close(lockedWorkspace);
    fs.rmSync(lockRoot, {recursive: true, force: true});

    console.log('OPFS_CHAIN_OK ' + sha);
  } finally {
    fs.rmSync(scratchRoot, {recursive: true, force: true});
  }
}

main().catch(err => {
  console.error('OPFS_FAIL ' + (err && err.stack || err));
  process.exit(1);
});
