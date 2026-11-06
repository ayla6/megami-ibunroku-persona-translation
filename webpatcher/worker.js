'use strict';
/* Persona translation web patcher - patch worker.
 *
 * Applies the release patch chain with the real xdelta3 codec (3.2.2, the
 * same version the release patches were produced with; see
 * build-xdelta3-wasm.sh). xdelta verifies the source and target window
 * checksums itself on every step, so a wrong disc or a corrupt patch fails
 * instead of producing a download. Step output sizes are checked against
 * the manifest too, but no separate hash of our own is needed.
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
      const status = runXdelta(
          ['-d', '-f', '-q', '-s', from, input + '/' + step.patch, to]);
      const size = status === 0 ? FS.stat(to).size : -1;
      if (size !== step.expectBytes) {
        throw new Error(`${step.patch} did not apply - the selected disc does`
            + " not match the original image this release patches, or the"
            + ' release files are damaged');
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
