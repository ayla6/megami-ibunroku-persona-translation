'use strict';
/* Persona translation web patcher - patch worker.
 *
 * Applies the release patch chain with the real xdelta3 codec (3.2.2, the
 * same version the release patches were produced with; see
 * build-xdelta3-wasm.sh). Every step is verified before its result is
 * used, in one of two ways named by the manifest row's `verify` column:
 *
 * - verify=xdelta: the patch carries xdelta's per-window checksums and was
 *   encoded from exactly the source it is applied to; xdelta's own verdict
 *   decides (a wrong disc or corrupt patch fails instead of downloading).
 * - verify=sha256: the step is applied over a variant the patch was not
 *   encoded from (the same layout with other options riding along), so
 *   those checksums describe another flavor of the target and the step
 *   decodes with -n. The release build has proven this exact (patch,
 *   source) pair by decoding it and comparing with the audited built disc;
 *   here the whole result is hashed and compared with the manifest's
 *   target_sha256, a strictly stronger check than the window checksums.
 *
 * Step output sizes are checked against the manifest too.
 *
 * The selected disc is identified by applying a release patch with xdelta's
 * check-only mode (-J, decodes and verifies, writes nothing): rev1-to-rev0
 * succeeds only on a Rev 1 disc, rev0-to-base only on a Rev 0 disc.
 *
 * Message in:  {type: 'apply', source, patchFiles, steps, sourceExpect,
 *               keepScratch, scratchName, useScratch}  // page-held OPFS dirs
 *              {type: 'identify', source, expect}
 * Message out: {type: 'progress', message}
 *              {type: 'done', blob, bytes, scratchDir}
 *              {type: 'identified', rev}
 *              {type: 'error', message}
 */

let markRuntimeReady;
const runtimeReady = new Promise(resolve => { markRuntimeReady = resolve; });

var Module = {
  locateFile: path => new URL('vendor/' + path, self.location).href,
  onRuntimeInitialized: () => markRuntimeReady(),
};

importScripts('vendor/xdelta3.js', 'workerfs.js', 'scratch.js', 'opfsfs.js',
              'xdelta.js');

/* The whole-file SHA-256 that certifies verify=sha256 steps (see the
 * manifest column). crypto.subtle does the hashing natively; this just
 * hands it the bytes: a MEMFS output is already one contiguous view, an
 * OPFS slot is read through its mounted filesystem into one preallocated
 * buffer first. Hex, because that is what the manifest records. */
async function digestOf(FS, path) {
  const node = FS.lookupPath(path).node;
  let data = null;
  if (node && typeof node.usedBytes === 'number' && node.contents) {
    data = node.contents.subarray(0, node.usedBytes);
  } else {
    const size = FS.stat(path).size;
    data = new Uint8Array(size);
    const stream = FS.open(path, 'r');
    try {
      const chunk = 8 * 1024 * 1024;
      for (let pos = 0; pos < size; pos += chunk) {
        FS.read(stream, data, pos, Math.min(chunk, size - pos), pos);
      }
    } finally {
      FS.close(stream);
    }
  }
  const digest = await crypto.subtle.digest('SHA-256', data);
  return [...new Uint8Array(digest)]
      .map(byte => byte.toString(16).padStart(2, '0')).join('');
}

/* Match the selected file against the manifest's original discs by running
 * a release patch in check-only mode from it: the patch's own source and
 * target checksums decide, so no filename sniffing and no hash of our own. */
async function identifySource(msg) {
  try {
    await runtimeReady;
    const FS = Module.FS;
    const work = '/identify';
    FS.mkdir(work);
    FS.mount(FS.filesystems.WORKERFS, {blobs:
        [{name: 'source.bin', data: msg.source}]
            .concat(msg.expect.filter(entry => entry.file)
                .map(entry => ({name: entry.patch, data: entry.file})))}, work);
    try {
      const path = work + '/source.bin';
      const size = FS.stat(path).size;
      const candidates = msg.expect.filter(
          entry => entry.bytes === size && entry.file);
      if (!candidates.length) {
        const sizes = [...new Set(msg.expect.map(entry => entry.bytes))];
        throw new Error(`the selected file is ${size.toLocaleString()} bytes but`
            + ` the original disc is ${sizes.map(n => n.toLocaleString()).join(' or ')}`
            + ' bytes - select the .bin image, not the .cue');
      }
      for (const candidate of candidates) {
        postMessage({type: 'progress',
                     message: `checking it against the ${candidate.label} disc`});
        const status = runXdelta(
            ['-d', '-J', '-q', '-s', path, work + '/' + candidate.patch]);
        if (status === 0) {
          postMessage({type: 'identified', rev: candidate.rev});
          return;
        }
      }
      throw new Error('this file has the size of the original disc but its'
          + " contents don't match (xdelta checksum failure) - it may be a"
          + ' different or modified dump');
    } finally {
      FS.unmount(work);
    }
  } catch (err) {
    postMessage({type: 'error', message: String((err && err.message) || err)});
  }
}

self.onmessage = async event => {
  const msg = event.data;
  if (msg && msg.type === 'identify') return identifySource(msg);
  if (!msg || msg.type !== 'apply') return;

  const work = '/patchwork';
  const input = work + '/in';      // mounted read-only; outputs go in `out`
  const out = work + '/out';
  let FS = null;
  let scratch = null;
  let outMounted = false;

  try {
    await runtimeReady;
    FS = Module.FS;

    postMessage({type: 'progress', message: 'checking the source disc'});
    FS.mkdir(work);
    FS.mkdir(input);
    FS.mount(FS.filesystems.WORKERFS, {blobs: [{name: 'source.bin', data: msg.source}]
        .concat(msg.patchFiles.map(({name, file}) => ({name, data: file})))}, input);

    const sourcePath = input + '/source.bin';
    const sourceSize = FS.stat(sourcePath).size;
    if (sourceSize !== msg.sourceExpect.bytes) {
      throw new Error(`The selected file is ${sourceSize.toLocaleString()} bytes but this`
          + ` release patches the ${msg.sourceExpect.bytes.toLocaleString()}-byte original`
          + ' disc - select the .bin image, not the .cue');
    }

    /* Memory is the default. The page asks for OPFS only in its low-RAM
     * mode; then the two output slots live on disk, so the chain never holds
     * a disc image in the JS heap. `scratch` is null when OPFS is
     * unavailable and the slots live in MEMFS as usual. */
    scratch = msg.useScratch ? await OPFSWorkspace.open(
        ['out0.bin', 'out1.bin'], undefined, msg.keepScratch, msg.scratchName)
        : null;
    if (scratch) {
      OPFSWorkspace.mount(FS, scratch, out);
      outMounted = true;
    }
    const outDir = scratch ? out : work;

    let from = sourcePath;
    for (let index = 0; index < msg.steps.length; index++) {
      const step = msg.steps[index];
      const to = `${outDir}/out${index % 2}.bin`;  // never the source of this step
      postMessage({type: 'progress', message: 'Applying ' + step.patch});
      const args = ['-d', '-f', '-q'];
      const proven = step.verify === 'sha256';
      if (proven) args.push('-n');  // its checksums describe the anchor source
      args.push('-s', from, input + '/' + step.patch, to);
      const status = runXdelta(args);
      let size = -1;
      if (status === 0 || proven) {
        try { size = FS.stat(to).size; } catch (err) {}
      }
      if (size !== step.expectBytes) {
        throw new Error(`${step.patch} did not apply - the selected disc does`
            + " not match the original image this release patches, or the"
            + ' release files are damaged');
      }
      if (proven) {
        // -n skips xdelta's window checksums on purpose; this hash is the
        // step's actual certificate, recorded in the manifest by the build
        // after it decoded this patch over this exact source and compared
        // with the audited built disc
        postMessage({type: 'progress', message: 'Verifying ' + step.patch});
        const digest = await digestOf(FS, to);
        if (digest !== step.expectHash) {
          throw new Error(`${step.patch} produced a disc that does not match`
              + ' the release manifest - the release files are damaged or'
              + ' mixed from different releases; reload the page and retry');
        }
      }
      /* Drop the previous intermediate before the next step: only the
       * current input and the output being written exist at any time. */
      if (from !== sourcePath) FS.truncate(from, 0);
      from = to;
    }

    postMessage({type: 'progress', message: 'Preparing the download'});
    let blob;
    let bytes;
    if (scratch) {
      /* The OPFS File is a disk-backed Blob: no disc-sized copy is made
       * here. finish() keeps the one slot it returns, and the page removes
       * the directory once a newer result replaces this download. */
      blob = await OPFSWorkspace.finish(scratch, from);
      bytes = blob.size;
    } else {
      /* MEMFS already holds the bytes as a Uint8Array. FS.readFile would
       * add a disc-sized copy and the Blob copies again; hand the node's
       * view to the Blob instead. */
      const node = FS.lookupPath(from).node;
      const data = node && typeof node.usedBytes === 'number'
          ? node.contents.subarray(0, node.usedBytes)
          : FS.readFile(from);
      blob = new Blob([data], {type: 'application/octet-stream'});
      bytes = data.length;
    }
    postMessage({type: 'done', blob, bytes,
                 scratchDir: scratch ? scratch.dirName : null});
  } catch (err) {
    postMessage({type: 'error', message: String((err && err.message) || err)});
  } finally {
    if (FS) {
      try { FS.unmount(input); } catch (err) {}
      if (outMounted) {
        try { FS.unmount(out); } catch (err) {}
      }
    }
    if (scratch) await OPFSWorkspace.close(scratch);
  }
};
