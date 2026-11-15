'use strict';
/* Persona translation web patcher - patch worker.
 *
 * Applies the release patch chain with the real xdelta3 codec (3.2.2, the
 * same version the release patches were produced with; see
 * build-xdelta3-wasm.sh). The manifest row names the canonical source it
 * was encoded from; the page plans the steps, and this worker decides how
 * each one is verified:
 *
 * - the applied options are exactly the row's canonical source: the patch
 *   carries xdelta's per-window checksums for that source, so xdelta's own
 *   verdict decides (a wrong disc or corrupt patch fails loudly).
 * - the disc is decorated (other in-place options riding along): those
 *   checksums describe another flavor of the target, so the step decodes
 *   with -n. The release build verified sampled chains applied exactly
 *   like this one (manifest `verified`), and in-place decorations never
 *   change the image size.
 *
 * Every patch file's SHA-256 is checked against the manifest before it is
 * used, and every step's output size is checked too.
 *
 * The selected disc is identified by applying a release patch with xdelta's
 * check-only mode (-J, decodes and verifies, writes nothing): rev1-to-rev0
 * succeeds only on a Rev 1 disc, rev0-to-base only on a Rev 0 disc.
 *
 * A PPF is built without applying anything: vcdiff.js follows each patch's
 * instructions over a sparse view of the original disc and the PPF holds the
 * bytes where the result differs from the disc it patches. A PPF only
 * overwrites bytes and a Rev 1 disc is shorter than Rev 0, so for a Rev 1
 * source the PPF patches the Rev 0 disc (the first step's result), which is
 * handed back as a Blob of slices of the user's file plus the patched bytes.
 *
 * Message in:  {type: 'apply', source, patchFiles, steps, sourceExpect,
 *               keepScratch, scratchName, useScratch}  // page-held OPFS dirs
 *              {type: 'ppf', source, patchFiles, steps, sourceExpect,
 *               description, chd, keepChd, rev0Handle}
 *                // chd: the source is a CHD (Rev 0 only); keepChd: keep its
 *                // parts; rev0Handle: write the Rev 0 disc made from a Rev 1
 *                // source straight into this file instead of returning it
 *              {type: 'identify', source, expect}
 * Message out: {type: 'progress', message}
 *              {type: 'done', blob, bytes, scratchDir, onDisk}
 *              {type: 'ppf-done', ppf, rev0}  // rev0: Blob, Rev 1 sources only
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
              'xdelta.js', 'plan.js', 'ppf.js', 'vcdiff.js', 'lzma.js', 'inflate.js',
              'chd.js');

/* The whole-file SHA-256 that certifies a patch file against the manifest.
 * crypto.subtle does the hashing natively; this just hands it the bytes: a
 * MEMFS file is already one contiguous view, an OPFS slot is read through
 * its mounted filesystem into one preallocated buffer first. Hex, because
 * that is what the manifest records. */
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

/* What a PPF reads from a CHD is kept in IndexedDB (when the page's "Keep
 * CHD parts" option is on; unticking it deletes the database): one record per disc, keyed by its raw SHA-1 - the same
 * disc always holds the same bytes - with the stretches of the .bin a PPF
 * read and their bytes. A later PPF from that CHD (other options, Update
 * PPF, a new release) unpacks only blocks for stretches the record lacks,
 * and the record grows by them. Only the bytes really read are kept, not
 * the whole blocks they
 * came from (31.5 MB for the translation with Black Mark, saves and
 * 60 fps). Storage that is blocked or evicted just means unpacking. */
const PART_DB = 'patcher-chd';
const PART_STORE = 'parts';

function partDb() {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(PART_DB, 2);
    open.onupgradeneeded = () => {
      const db = open.result;
      if (db.objectStoreNames.contains('blocks')) db.deleteObjectStore('blocks');
      if (!db.objectStoreNames.contains(PART_STORE)) db.createObjectStore(PART_STORE);
    };
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  });
}

/* One request; it resolves when its transaction has committed, not when
 * the request succeeds - the page ends this worker as soon as the PPF is
 * done, and a write still committing then is lost. */
async function partStore(mode, use) {
  const db = await partDb();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(PART_STORE, mode);
      const request = use(tx.objectStore(PART_STORE));
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = () => reject(tx.error || request.error);
      tx.onabort = () => reject(tx.error || new Error('IndexedDB transaction aborted'));
    });
  } finally {
    db.close();
  }
}

/* A set of stretches of the .bin with their bytes: sorted, disjoint
 * [start, end) pairs and the bytes laid end to end. */
class Parts {
  constructor(spans = [], data = new Uint8Array(0)) {
    this.spans = spans;        // [[start, end], ...]
    this.data = data;
    this.at = [];              // where each span's bytes start in data
    let pos = 0;
    for (const [start, end] of spans) {
      this.at.push(pos);
      pos += end - start;
    }
  }
  find(offset) {               // index of the span holding offset, or -1
    let lo = 0, hi = this.spans.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const [start, end] = this.spans[mid];
      if (offset < start) hi = mid - 1;
      else if (offset >= end) lo = mid + 1;
      else return mid;
    }
    return -1;
  }
  read(offset, length) {       // null unless one span holds all of it
    const k = this.find(offset);
    if (k < 0 || offset + length > this.spans[k][1]) return null;
    const from = this.at[k] + offset - this.spans[k][0];
    return this.data.subarray(from, from + length);
  }
}

/* Sorted, merged [start, end) spans; gaps up to `join` bytes are bridged
 * (a few extra bytes cost less than another span). */
function mergeSpans(spans, join = 64) {
  const sorted = spans.slice().sort((a, b) => a[0] - b[0]);
  const out = [];
  for (const [start, end] of sorted) {
    const last = out[out.length - 1];
    if (last && start <= last[1] + join) last[1] = Math.max(last[1], end);
    else out.push([start, end]);
  }
  return out;
}

async function storedParts(sha1) {
  try {
    const record = await partStore('readonly', store => store.get(sha1));
    if (record) return new Parts(record.spans, record.data);
  } catch (err) { /* nothing kept */ }
  return new Parts();
}

async function keepParts(sha1, parts) {
  postMessage({type: 'progress', message: 'Keeping the CHD parts'});
  try {
    await partStore('readwrite', store => store.put({spans: parts.spans, data: parts.data}, sha1));
  } catch (err) {
    // not kept: the next PPF unpacks again, and the page says why
    postMessage({type: 'progress', message: 'Could not keep the CHD parts: '
        + String((err && err.message) || err)});
  }
}

/* The bytes of `needed` (sorted [start, end) spans of the .bin) from a CHD:
 * what the kept record already holds, the rest unpacked from the blocks
 * that hold it. With `keep`, the record grows by what was unpacked. */
async function chdParts(file, chd, needed, keep) {
  const stored = keep ? await storedParts(chd.rawSha1) : new Parts();
  const lacking = needed.filter(([start, end]) => !stored.read(start, end - start));
  const perBlock = chd.framesPerHunk * CHD.SECTOR;
  const indices = new Set();
  for (const [start, end] of lacking) {
    for (const index of CHD.hunksFor(chd, start, end - start)) indices.add(index);
  }
  if (!lacking.length) {
    postMessage({type: 'progress', message: 'Using the kept CHD parts'});
  }
  const blocks = await chdBlocks(file, chd, [...indices].sort((a, b) => a - b));
  const fromBlocks = (start, end, out, at) => {
    for (let pos = start; pos < end;) {
      const index = Math.floor(pos / perBlock);
      const skip = pos - index * perBlock;
      const take = Math.min(perBlock - skip, end - pos);
      out.set(blocks.get(index).subarray(skip, skip + take), at + pos - start);
      pos += take;
    }
  };
  // the new record: everything kept plus everything needed, exactly (no
  // bridged gaps: their bytes come from neither)
  const spans = mergeSpans(keep ? stored.spans.concat(needed) : needed, 0);
  const data = new Uint8Array(spans.reduce((n, [start, end]) => n + end - start, 0));
  // both inputs are sorted and disjoint: walk them alongside the output
  let at = 0, l = 0, k = 0;
  for (const [start, end] of spans) {
    while (l < lacking.length && lacking[l][1] <= start) l++;
    for (let i = l; i < lacking.length && lacking[i][0] < end; i++) {
      fromBlocks(Math.max(lacking[i][0], start), Math.min(lacking[i][1], end), data, at);
    }
    while (k < stored.spans.length && stored.spans[k][1] <= start) k++;
    for (let i = k; i < stored.spans.length && stored.spans[i][0] < end; i++) {
      const from = Math.max(stored.spans[i][0], start);
      const to = Math.min(stored.spans[i][1], end);
      data.set(stored.read(from, to - from), at + from - start);
    }
    at += end - start;
  }
  const parts = new Parts(spans, data);
  if (keep && lacking.length) await keepParts(chd.rawSha1, parts);
  return parts;
}

/* The sector bytes of `indices`, unpacked by a few block workers side by
 * side (chdblocks.js), batch by batch. This worker reads the compressed
 * blocks itself, in the few large slices CHD.readPlan picks (reads are
 * the slow part on some devices, and they do not run in parallel there),
 * reading the next slice while the block workers unpack the last one. */
async function chdBlocks(file, chd, indices) {
  const out = new Map();
  if (!indices.length) return out;
  const slices = CHD.readPlan(chd, indices);
  let unpacked = 0;
  const progress = () => postMessage({type: 'progress', message:
      `Unpacking the CHD (${unpacked} of ${indices.length} blocks)`});
  const store = blocks => {
    for (const [index, block] of blocks) out.set(index, block);
    unpacked += blocks.length;
    progress();
  };
  progress();

  // batches of up to 64 blocks, each with its own compressed bytes; at most
  // two slices are read ahead of the block workers
  const batches = [];
  let reading = 0;
  let wake = null;
  const readSlice = async slice => {
    const bytes = slice.start === null ? null
        : await chd.readAt(slice.start, slice.end - slice.start);
    for (let k = 0; k < slice.blocks.length; k += 64) {
      const blocks = slice.blocks.slice(k, k + 64);
      const pieces = bytes ? blocks.map(({offset, length}) => [offset,
          bytes.slice(offset - slice.start, offset - slice.start + length)]) : [];
      batches.push({indices: blocks.map(block => block.index), pieces});
    }
  };
  const reader = (async () => {
    for (; reading < slices.length; reading++) {
      while (batches.length > 2 * 4 + 8) await new Promise(resolve => { wake = resolve; });
      await readSlice(slices[reading]);
      if (wake) { const go = wake; wake = null; go(); }
    }
  })();
  let readError = null;
  reader.catch(err => { readError = err; });
  const take = async () => {
    for (;;) {
      if (readError) throw readError;
      if (batches.length) {
        const batch = batches.shift();
        if (wake) { const go = wake; wake = null; go(); }
        return batch;
      }
      if (reading >= slices.length) return null;
      await new Promise(resolve => setTimeout(resolve, 20));
    }
  };

  const portable = CHD.portable(chd);
  const cores = (self.navigator && navigator.hardwareConcurrency) || 2;
  const count = Math.max(1, Math.min(4, cores - 1, Math.ceil(indices.length / 64)));
  const lane = async () => {
    let helper;
    try {
      helper = new Worker('chdblocks.js');
    } catch (err) {
      helper = null;           // no nested workers here: unpack inline
    }
    try {
      for (let batch; (batch = await take());) {
        if (!helper) {
          const read = CHD.piecesReader(batch.pieces, chd.readAt);
          const blocks = [];
          for (const index of batch.indices) blocks.push([index, await CHD.hunk(chd, index, read)]);
          store(blocks);
          continue;
        }
        store(await new Promise((resolve, reject) => {
          helper.onmessage = ({data}) => (data.error ? reject(new Error(data.error))
                                                     : resolve(data.blocks));
          helper.onerror = event => reject(new Error(event.message || 'a CHD block worker failed'));
          helper.postMessage({file, chd: portable, indices: batch.indices, pieces: batch.pieces},
                             batch.pieces.map(([, bytes]) => bytes.buffer));
        }));
      }
    } finally {
      if (helper) helper.terminate();
    }
  };
  await Promise.all(Array.from({length: count}, lane));
  await reader;
  return out;
}

/* The PPF for a plan, from the patches' instructions alone (see the top of
 * this file). The source was identified before this runs (xdelta3 for a
 * .bin, the header's raw SHA-1 for a CHD); each patch file must match its
 * manifest hash and each step its output size.
 *
 * A CHD is read only where the PPF needs the disc: a first pass over the
 * chain records which of its blocks are touched, those blocks alone are
 * unpacked, and the second pass reads from them. */
async function buildPpf(msg) {
  try {
    const reader = new FileReaderSync();
    const files = new Map(msg.patchFiles.map(({name, file}) => [name, file]));
    const patches = new Map();
    for (const step of msg.steps) {
      if (patches.has(step.patch)) continue;
      const patch = new Uint8Array(reader.readAsArrayBuffer(files.get(step.patch)));
      const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', patch))]
          .map(byte => byte.toString(16).padStart(2, '0')).join('');
      if (digest !== step.patchHash) {
        throw new Error(`${step.patch} does not match the release manifest`
            + ' - the release files are damaged or mixed from different'
            + ' releases; reload the page and retry');
      }
      patches.set(step.patch, patch);
    }

    let size;
    let readOriginal;
    let chd = null;
    let parts = null;            // CHD: the stretches a run may read, with bytes
    const requests = [];         // CHD: what a run read that `parts` lacked
    if (msg.chd) {
      const readAt = async (offset, length) =>
          new Uint8Array(await msg.source.slice(offset, offset + length).arrayBuffer());
      chd = await CHD.open(readAt);
      size = chd.binBytes;
      readOriginal = (offset, length) => {
        const bytes = parts && parts.read(offset, length);
        if (bytes) return bytes;
        requests.push([offset, offset + length]);
        return new Uint8Array(length);
      };
      chd.readAt = readAt;
    } else {
      size = msg.source.size;
      readOriginal = (offset, length) => new Uint8Array(
          reader.readAsArrayBuffer(msg.source.slice(offset, offset + length)));
    }
    if (size !== msg.sourceExpect.bytes) {
      throw new Error(`The selected disc is ${size.toLocaleString()} bytes`
          + ` but this release patches the ${msg.sourceExpect.bytes.toLocaleString()}`
          + '-byte original disc - select the .bin image, not the .cue');
    }

    // a CHD's parts are already in memory; a .bin is read through a cache
    const read = chd ? readOriginal : VCDIFF.cachedReader(readOriginal, size);
    const chain = () => {
      let image = VCDIFF.original(size);
      let reference = image;     // the disc the PPF patches
      let converted = false;     // reference is the Rev 0 disc made from Rev 1
      for (const step of msg.steps) {
        postMessage({type: 'progress', message: 'Reading ' + step.patch});
        image = VCDIFF.apply(image, patches.get(step.patch), read);
        if (image.size !== step.expectBytes) {
          throw new Error(`${step.patch} did not apply - the selected disc does`
              + ' not match the original image this release patches, or the'
              + ' release files are damaged');
        }
        if (step.patch === PatchPlan.REV1_PATCH) {
          reference = image;
          converted = true;
        }
      }
      return {image, reference, converted};
    };
    const write = ({image, reference}) => {
      postMessage({type: 'progress', message: 'Writing the PPF'});
      const block = VCDIFF.read(reference, PPF.BLOCK_AT, PPF.BLOCK_BYTES, read);
      return PPF.fromRegions(block,
          VCDIFF.differences(reference, image, read), msg.description || '');
    };

    let result = chain();
    if (chd) {
      // which stretches of the disc the PPF reads. The chain itself reads
      // the disc only for an overlapping copy; when it read nothing, its
      // images are already exact and only the writing is done again.
      const chainRead = requests.length > 0;
      write(result);
      const needed = mergeSpans(requests);
      requests.length = 0;
      parts = await chdParts(msg.source, chd, needed, msg.keepChd);
      if (chainRead) result = chain();
    }
    const {reference, converted} = result;
    const ppfParts = write(result);
    if (requests.length) throw new Error('the CHD was read outside the parts unpacked for it');
    if (chd && converted) throw new Error('a Rev 1 CHD cannot be turned into a Rev 0 disc here');
    const ppf = new Blob(ppfParts, {type: 'application/octet-stream'});
    let rev0 = null;
    if (converted) {
      // The Rev 0 disc, 8 MB at a time: Rev 1 and Rev 0 differ in so many
      // small places that a Blob of the image's pieces would have about a
      // million parts, which stalls the browser. Into the disc folder it is
      // streamed straight to its file; as a download it is a Blob of ~90.
      const CHUNK = 8 << 20;
      const read = VCDIFF.cachedReader(readOriginal, msg.source.size, 1 << 20, 16);
      const writable = msg.rev0Handle ? await msg.rev0Handle.createWritable() : null;
      let blob = new Blob([], {type: 'application/octet-stream'});
      for (let base = 0; base < reference.size; base += CHUNK) {
        if (base % (64 << 20) === 0) {
          postMessage({type: 'progress', message:
              `Writing the Rev 0 disc (${Math.floor(100 * base / reference.size)}%)`});
        }
        const chunk = VCDIFF.read(reference, base, Math.min(CHUNK, reference.size - base), read);
        if (writable) await writable.write(chunk);
        else blob = new Blob([blob, chunk], {type: 'application/octet-stream'});
      }
      if (writable) await writable.close();
      else rev0 = blob;
    }
    postMessage({type: 'ppf-done', ppf, rev0});
  } catch (err) {
    postMessage({type: 'error', message: String((err && err.message) || err)});
  }
}

self.onmessage = async event => {
  const msg = event.data;
  if (msg && msg.type === 'identify') return identifySource(msg);
  if (msg && msg.type === 'ppf') return buildPpf(msg);
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

    const patchHashes = new Map();
    const applied = new Set();
    let from = sourcePath;
    for (let index = 0; index < msg.steps.length; index++) {
      const step = msg.steps[index];
      const to = `${outDir}/out${index % 2}.bin`;  // never the source of this step
      let patchHash = patchHashes.get(step.patch);
      if (!patchHash) {
        patchHash = await digestOf(FS, input + '/' + step.patch);
        patchHashes.set(step.patch, patchHash);
      }
      if (patchHash !== step.patchHash) {
        throw new Error(`${step.patch} does not match the release manifest`
            + ' - the release files are damaged or mixed from different'
            + ' releases; reload the page and retry');
      }
      const canonical = PatchPlan.canonicalSource(step, applied);
      postMessage({type: 'progress',
                   message: 'Applying ' + step.patch});
      const args = PatchPlan.decodeArgs(step, applied);
      args.push('-s', from, input + '/' + step.patch, to);
      const status = runXdelta(args);
      let size = -1;
      try { size = FS.stat(to).size; } catch (err) {}
      if (status !== 0 || size !== step.expectBytes) {
        throw new Error(`${step.patch} did not apply - the selected disc does`
            + " not match the original image this release patches, or the"
            + ' release files are damaged');
      }
      if (step.adds) applied.add(step.adds);
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
    postMessage({type: 'done', blob, bytes, onDisk: !!scratch,
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
