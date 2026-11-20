'use strict';
/* Persona translation web patcher - patch worker.
 *
 * Applies P1MOD layers (webpatcher/modpack.js; docs/MOD_ENGINE.md): every
 * selected layer's file edits are merged in memory, then laid out on the
 * player's disc once, giving the sectors that change. Every layer file is
 * checked against its manifest SHA-1 first, and the base layer checks every
 * file it edits against the original disc's, so a wrong or damaged disc is
 * refused.
 *
 * - disc: the result is a Blob of slices of the player's own file with the
 *   changed sectors in between - nothing disc-sized is copied in memory. In
 *   low-RAM mode (lowRam) the disc is written to browser storage (OPFS)
 *   instead and the changed sectors let go as they are written.
 * - ppf: the changed sectors against the disc's own bytes; a selection that
 *   would grow the disc has no PPF (a PPF cannot change a file's size).
 *
 * A .bin is read the same way: what the merge, the layout and the PPF are
 * about to read is asked for up front, in a few large reads (binReader).
 *
 * A CHD is read only where the layers need it, in a few large reads: the
 * files they edit are unpacked up front (in parallel, and kept in IndexedDB
 * when the page's "Keep CHD parts" option is on) - a movie edited in place
 * only in the sectors its edits land in (MODPACK.touched: the dub rewrites
 * one in eight) - and what the layout is about to compare is unpacked before
 * it compares it (Disc.prefetch), so the layout does not pay a read per
 * block. A CHD can only take a PPF.
 *
 * Message in:  {type: 'run', output: 'disc' | 'ppf', source, chd, keepChd,
 *               layers: [{name, file, hash, own}], selection, description,
 *               lowRam, target}
 *              target: a file handle in the disc folder that Build disc
 *              writes the disc into (then nothing is held in memory)
 *              own: a mod loaded by the user (no manifest hash), after the release's
 *              selection: {label: option key ('' for a mod without options)},
 *              which parts of each layer apply (MODPACK.selected)
 * Message out: {type: 'progress', message}
 *              {type: 'done', blob, bytes, stored}  // output 'disc'; stored: an OPFS file
 *              {type: 'done', bytes, written}      // output 'disc' into target
 *              {type: 'ppf-done', ppf}           // output 'ppf'
 *              {type: 'error', message}
 */

importScripts('modpack.js', 'ppf.js', 'lzma.js', 'inflate.js', 'chd.js');

const SECTOR = MODPACK.SECTOR;

async function hexDigest(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-1', bytes))]
      .map(byte => byte.toString(16).padStart(2, '0')).join('');
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
/* The database version drops every record older code kept (3: the layer
 * patcher); each record also carries PART_FORMAT, and one without it is
 * ignored. A run whose source check fails on kept parts drops the record and
 * unpacks again (run()), so a stale record can never block a real disc. */
const PART_DB_VERSION = 3;
const PART_FORMAT = 1;

function partDb() {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(PART_DB, PART_DB_VERSION);
    open.onupgradeneeded = () => {
      const db = open.result;
      for (const name of ['blocks', PART_STORE]) {
        if (db.objectStoreNames.contains(name)) db.deleteObjectStore(name);
      }
      db.createObjectStore(PART_STORE);
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
  /* As much of [offset, end) as the span holding offset has: what is left of
   * it, if any, comes from the next span - a read wider than one kept stretch
   * is served stretch by stretch instead of being read from the CHD again. */
  take(offset, end) {
    const k = this.find(offset);
    if (k < 0) return null;
    const to = Math.min(end, this.spans[k][1]);
    const from = this.at[k] + offset - this.spans[k][0];
    return this.data.subarray(from, from + to - offset);
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
    if (record && record.format === PART_FORMAT) return new Parts(record.spans, record.data);
  } catch (err) { /* nothing kept */ }
  return new Parts();
}

async function dropParts(sha1) {
  try {
    await partStore('readwrite', store => store.delete(sha1));
  } catch (err) { /* nothing kept, or storage blocked */ }
}

async function keepParts(sha1, parts) {
  postMessage({type: 'progress', message: 'Keeping the CHD parts'});
  try {
    await partStore('readwrite', store => store.put(
        {format: PART_FORMAT, spans: parts.spans, data: parts.data}, sha1));
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

/* A reader over a CHD: bytes from the unpacked parts when they hold the
 * request, else from the blocks holding it, unpacked here and cached. A read
 * is taken from the parts stretch by stretch (a read wider than one kept
 * stretch, or crossing two, still takes what they hold), and only what they
 * lack is unpacked - a read costs a fixed fraction of a second on some
 * devices (chd.js readPlan), so a block the parts already hold is never read
 * again. */
function chdReader(chd, parts, file) {
  const blocks = new Map();
  const perBlock = chd.framesPerHunk * CHD.SECTOR;
  const read = async (offset, length) => {
    const out = new Uint8Array(length);
    const end = offset + length;
    for (let pos = offset; pos < end;) {
      const kept = parts && parts.take(pos, end);
      if (kept) {
        out.set(kept, pos - offset);
        pos += kept.length;
        continue;
      }
      const index = Math.floor(pos / perBlock);
      let block = blocks.get(index);
      if (!block) {
        block = await CHD.hunk(chd, index, chd.readAt);
        blocks.set(index, block);
      }
      const skip = pos - index * perBlock;
      const take = Math.min(perBlock - skip, end - pos);
      out.set(block.subarray(skip, skip + take), pos - offset);
      pos += take;
    }
    return out;
  };
  /* Unpack the blocks these spans hold before they are read (Disc.prefetch):
   * the reads below unpack one block each, and a read costs a fixed fraction
   * of a second on some devices, so they are unpacked the way the merge
   * unpacks its own - in the few large slices CHD.readPlan picks. */
  read.prefetch = async spans => {
    const indices = new Set();
    for (const [start, end] of spans) {
      for (const index of CHD.hunksFor(chd, start, end - start)) {
        if (index >= chd.hunks) continue;             // a sector the image does not have
        const from = index * perBlock;
        if (parts && parts.read(from, perBlock)) continue;   // the parts hold it
        if (!blocks.has(index)) indices.add(index);
      }
    }
    if (!indices.size) return;
    for (const [index, block] of await chdBlocks(file, chd,
        [...indices].sort((a, b) => a - b))) {
      blocks.set(index, block);
    }
  };
  return read;
}

/* A reader over the .bin: bytes from what a prefetch read when it holds
 * them, else read from the file. A read of the file costs a fixed fraction
 * of a second on some devices whatever its size, so what the merge, the
 * layout and the PPF are about to read is asked for up front (prefetch):
 * read in slices of up to 16 MB that bridge gaps up to 4 MB, and only the
 * asked-for stretches of each slice kept, not the bridged gaps. */
const SLICE_GAP = 4 << 20;
const SLICE_MOST = 16 << 20;

function binReader(file) {
  let parts = new Parts();
  const fromFile = async (offset, length) =>
      new Uint8Array(await file.slice(offset, offset + length).arrayBuffer());
  const read = async (offset, length) => {
    const out = new Uint8Array(length);
    const end = offset + length;
    for (let pos = offset; pos < end;) {
      const kept = parts.take(pos, end);
      if (kept) {
        out.set(kept, pos - offset);
        pos += kept.length;
        continue;
      }
      // up to where the parts start holding bytes again
      const next = parts.spans.find(([start]) => start > pos);
      const to = next ? Math.min(end, next[0]) : end;
      out.set(await fromFile(pos, to - pos), pos - offset);
      pos = to;
    }
    return out;
  };
  read.prefetch = async spans => {
    const wanted = mergeSpans(spans.map(([start, end]) => [start, Math.min(end, file.size)])
        .filter(([start, end]) => start < end && !parts.read(start, end - start)), 0);
    if (!wanted.length) return;
    const slices = [];
    for (const [start, end] of wanted) {
      const last = slices[slices.length - 1];
      if (last && start - last.end <= SLICE_GAP && end - last.start <= SLICE_MOST) {
        last.end = end;
        last.spans.push([start, end]);
      } else slices.push({start, end, spans: [[start, end]]});
    }
    const pieces = [];
    for (const slice of slices) {
      const bytes = await fromFile(slice.start, slice.end - slice.start);
      for (const [start, end] of slice.spans) {
        pieces.push([start, bytes.slice(start - slice.start, end - slice.start)]);
      }
    }
    // the new parts: what was held plus what was read
    const all = mergeSpans(parts.spans.concat(pieces.map(([start, bytes]) =>
        [start, start + bytes.length])), 0);
    const data = new Uint8Array(all.reduce((n, [start, end]) => n + end - start, 0));
    const grown = new Parts(all, data);
    const put = (start, bytes) => {
      const k = grown.find(start);
      data.set(bytes, grown.at[k] + start - all[k][0]);
    };
    parts.spans.forEach(([start, end], k) => put(start, parts.data.subarray(parts.at[k],
                                                                           parts.at[k] + end - start)));
    for (const [start, bytes] of pieces) put(start, bytes);
    parts = grown;
  };
  return read;
}

/* The base layer's source check failed while reading a CHD. */
class SourceMismatch extends Error {
  constructor(message, chdSha1) {
    super(message);
    this.chdSha1 = chdSha1;
  }
}

async function run(msg) {
  const packs = [];
  for (const {name, file, hash, own} of msg.layers) {
    postMessage({type: 'progress', message: `Reading ${name}`});
    const bytes = new Uint8Array(await file.arrayBuffer());
    // a mod of your own has no manifest row to check against
    if (!own && await hexDigest(bytes) !== hash) {
      throw new Error(`${name} does not match the release manifest - the release`
          + ' files are damaged or mixed from different releases; reload the page'
          + ' and retry');
    }
    packs.push(await MODPACK.parseLayer(bytes));
  }
  const layers = MODPACK.selected(packs, msg.selection || {});

  let size;
  let read;
  let chdSha1 = null;
  if (msg.chd) {
    const readAt = async (offset, length) =>
        new Uint8Array(await msg.source.slice(offset, offset + length).arrayBuffer());
    const chd = await CHD.open(readAt);
    chd.readAt = readAt;
    size = chd.binBytes;
    // the files the layers edit, unpacked (or taken from the kept parts) at once
    const probe = MODPACK.source(chdReader(chd, null), size);
    const spans = mergeSpans(await MODPACK.touched(probe, layers), 0);
    const parts = await chdParts(msg.source, chd, spans, msg.keepChd);
    chdSha1 = chd.rawSha1;
    read = chdReader(chd, parts, msg.source);
  } else {
    size = msg.source.size;
    read = binReader(msg.source);
    // the files the layers edit, read at once
    await read.prefetch(await MODPACK.touched(MODPACK.source(read, size), layers));
  }

  postMessage({type: 'progress', message: 'Merging the layers'});
  const disc = MODPACK.source(read, size);
  let merged;
  try {
    merged = await MODPACK.merge(disc, layers);
  } catch (err) {
    if (chdSha1 && /is not the file the .* layer was made for/.test(err.message)) {
      throw new SourceMismatch(err.message, chdSha1);
    }
    throw err;
  }
  const {files, entries, twins} = merged;
  postMessage({type: 'progress', message: 'Laying out the disc'});
  const plan = await MODPACK.layout(disc, files, entries, twins.length ? twins : null);
  const total = plan.total * SECTOR;

  // contiguous runs of changed sectors, in disc order
  const runs = [];
  for (const [lba, sector] of plan.sectors) {
    const last = runs[runs.length - 1];
    if (last && last.lba + last.sectors.length === lba) last.sectors.push(sector);
    else runs.push({lba, sectors: [sector]});
  }
  plan.sectors.clear();            // the runs hold them now
  const joined = sectors => {
    const out = new Uint8Array(sectors.length * SECTOR);
    sectors.forEach((sector, k) => out.set(sector, k * SECTOR));
    return out;
  };

  if (msg.output === 'ppf') {
    if (total > size) {
      throw new Error('this selection makes the disc larger, which a PPF cannot'
          + ' do - use Build disc instead');
    }
    postMessage({type: 'progress', message: 'Writing the PPF'});
    // every run's source bytes, and the block, in one request
    if (read.prefetch) {
      await read.prefetch([[PPF.BLOCK_AT, PPF.BLOCK_AT + PPF.BLOCK_BYTES],
          ...runs.map(({lba, sectors}) => [lba * SECTOR, (lba + sectors.length) * SECTOR])]);
    }
    const regions = [];
    for (const {lba, sectors} of runs) {
      const target = joined(sectors);
      regions.push({base: lba * SECTOR, source: await read(lba * SECTOR, target.length), target});
    }
    const block = await read(PPF.BLOCK_AT, PPF.BLOCK_BYTES);
    const ppf = new Blob(PPF.fromRegions(block, regions, msg.description || ''),
                         {type: 'application/octet-stream'});
    postMessage({type: 'ppf-done', ppf});
    return;
  }

  if (msg.chd) throw new Error('Build disc needs the .bin, not a CHD');
  postMessage({type: 'progress', message: 'Preparing the download'});
  // the disc in order: a stretch of the source, or a run of changed sectors
  const pieces = [];
  let at = 0;
  for (const {lba, sectors} of runs) {
    const offset = lba * SECTOR;
    if (offset > at) pieces.push({from: at, to: Math.min(offset, size)});
    pieces.push({sectors});
    at = offset + sectors.length * SECTOR;
  }
  if (at < size) pieces.push({from: at, to: size});
  if (msg.target) {
    postMessage({type: 'done', bytes: await discIntoFile(msg.source, pieces, msg.target),
                 written: true});
    return;
  }
  if (msg.lowRam) {
    const file = await discInStorage(msg.source, pieces);
    if (file) {
      postMessage({type: 'done', blob: file, bytes: file.size, stored: true});
      return;
    }
    postMessage({type: 'progress', message: 'Browser storage is not available here; keeping the disc in memory'});
  }
  const blob = new Blob(pieces.flatMap(piece => piece.sectors
      || [msg.source.slice(piece.from, piece.to)]), {type: 'application/octet-stream'});
  postMessage({type: 'done', blob, bytes: blob.size});
}

/* The disc in order, each piece handed to `put`, each changed sector let go
 * once it is put. The source is read through one 16 MB window, so the many
 * small stretches between changed runs cost a read per window, not each. */
const COPY_BYTES = 16 << 20;

async function writeDisc(source, pieces, put, where) {
  let at = 0;
  let window = null, windowAt = 0;
  for (const piece of pieces) {
    if (!piece.sectors) {
      for (let pos = piece.from; pos < piece.to;) {
        if (!window || pos < windowAt || pos >= windowAt + window.length) {
          postMessage({type: 'progress', message:
              `Writing the disc ${where} (${Math.floor(at / (1 << 20))} MB)`});
          windowAt = pos;
          window = new Uint8Array(await source.slice(pos, Math.min(source.size, pos + COPY_BYTES))
              .arrayBuffer());
        }
        const take = Math.min(piece.to, windowAt + window.length) - pos;
        await put(window.slice(pos - windowAt, pos - windowAt + take), at);
        at += take;
        pos += take;
      }
    } else {
      while (piece.sectors.length) {
        const sector = piece.sectors.shift();
        await put(sector, at);
        at += sector.length;
      }
    }
  }
  return at;
}

/* Build disc with a disc folder: the disc written straight into the file the
 * page made beside the player's disc (msg.target), nothing held as a Blob. */
async function discIntoFile(source, pieces, handle) {
  const writable = await handle.createWritable();
  try {
    const bytes = await writeDisc(source, pieces, bytes => writable.write(bytes), 'into the folder');
    await writable.close();
    return bytes;
  } catch (err) {
    await writable.abort().catch(() => {});
    throw err;
  }
}

/* Low-RAM mode: the patched disc written to the origin's private storage
 * (OPFS) instead of being held as a Blob; the page hands over the stored
 * file. One disc is kept at a time (OUTPUT_DIR, emptied by the page when it
 * opens). null: no OPFS here. */
const OUTPUT_DIR = 'patcher-output';

async function discInStorage(source, pieces) {
  let handle, access;
  try {
    const root = await navigator.storage.getDirectory();
    const dir = await root.getDirectoryHandle(OUTPUT_DIR, {create: true});
    handle = await dir.getFileHandle('disc.bin', {create: true});
    access = await handle.createSyncAccessHandle();
  } catch (err) {
    return null;
  }
  try {
    access.truncate(0);
    await writeDisc(source, pieces, (bytes, at) => {
      for (let done = 0; done < bytes.length;) {
        done += access.write(bytes.subarray(done), {at: at + done});
      }
    }, 'to browser storage');
    access.flush();
  } finally {
    access.close();
  }
  return handle.getFile();
}

self.onmessage = async event => {
  const msg = event.data;
  if (!msg || msg.type !== 'run') return;
  try {
    try {
      await run(msg);
    } catch (err) {
      // kept CHD parts that fail the base layer's source check are stale or
      // damaged: drop them and unpack the disc again, once
      if (!(msg.chd && msg.keepChd && err instanceof SourceMismatch)) throw err;
      postMessage({type: 'progress', message: 'The kept CHD parts were out of date; unpacking again'});
      await dropParts(err.chdSha1);
      await run(msg);
    }
  } catch (err) {
    postMessage({type: 'error', message: String((err && err.message) || err)});
  }
};
