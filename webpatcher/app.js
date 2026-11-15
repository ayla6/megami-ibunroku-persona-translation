'use strict';
/* Persona translation web patcher - page logic.
 *
 * The release output (dist/patches/) is served next to this page as
 * patches/ (manifest.tsv + the .xdelta files): the Pages workflow unpacks
 * it from the release zip, and local testing copies or symlinks it. The
 * manifest drives everything: which options exist, which patch file each
 * option needs for the current size-changer anchors, the chain order, and
 * how each step is verified. plan.js derives that graph; this file only
 * renders it and names the result. Nothing here is hardcoded per release.
 */

const PATCHES = 'patches/';
const RELEASE_REPO = 'ayla6/megami-ibunroku-persona-translation';  // 'owner/repo'; tools/publish_patches.py uploads here too
/* The downloaded image is named from the release, never from the file the
 * user picked (which may be a dump name, a hash, or just wrong). The
 * manifest's release stamp names the release, so results from two releases
 * never share a filename. A Rev 1 source is converted to Rev 0 on the way
 * in, so the result carries no source-revision suffix. */
const OUTPUT_NAME = 'Persona-TL';
/* Same cue convention as src/injection_tools/build_disc.py. */
const CUE_BODY = '  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n';

/* What each manifest option is called and what it does: generated into
 * features.js by tools/generate_features.py from tools/release_options.json
 * (the single place option wording lives - the release README reads the
 * same file). Edit the JSON, never this table; the Pages workflow and
 * tools/publish_patches.py run the generator for you. An option missing
 * from the JSON still works; it just shows its internal label. */
const FEATURES = globalThis.FEATURES || {};

const {BASE_PATCH, REV1_PATCH} = PatchPlan;
const REV_LABEL = ['Rev 0', 'Rev 1'];

const $ = id => document.getElementById(id);

const state = {
  rows: [],
  graph: null,           // PatchPlan.index(rows)
  labels: [],            // option labels, in apply order
  patches: null,         // {manifestText}
  source: null,
  fromFolder: false,     // the source was chosen from the disc folder's list
  folder: null,          // the disc folder (File System Access API)
  rev: null,             // detected revision (0 or 1), null until checked
  identifying: false,
  identifyRun: 0,
  identifyWork: null,    // promise for the run in flight
  identifySource: null,  // file that run is about
  identifyError: null,   // why the last run failed, if it did
  running: false,
};

function status(message, isError) {
  const element = $('status');
  element.textContent = message;
  element.className = isError ? 'error' : '';
}

const stepOf = (row, source) => ({patch: row.patch,
                                  adds: row.adds || '',
                                  source,
                                  expectBytes: Number(row.target_bytes),
                                  patchHash: row.patch_sha256});

/* Patches come from patches/ next to the page, which is the only way a
 * static page can read them: github.com serves release downloads without
 * CORS headers, so fetching an asset URL from this origin is blocked by the
 * browser. .github/workflows/pages.yml mirrors the latest release into that
 * directory, so the public site serves the files itself. */

async function loadPatches() {
  // cached like any file: a stale copy from another release is caught by
  // checkRelease, which tells the user to reload
  const response = await fetch(PATCHES + 'manifest.tsv');
  if (!response.ok) {
    throw new Error(`no ${PATCHES}manifest.tsv (${response.status}) - copy the`
        + ' release files from dist/patches/ into webpatcher/patches/');
  }
  return {manifestText: await response.text()};
}

/* The release is only a few MB in total and the base patch is reused for
 * every disc, so keep each fetched patch for this visit: identifying a disc,
 * applying it, and applying again never download the same file twice. The
 * page also starts the base patch as soon as it loads, before the user has
 * picked anything. */
const patchCache = new Map();  // name -> Promise<File>

/* A patch, from its gzipped copy when the site has one (the Pages deploy
 * writes <patch>.gz; Pages sends .xdelta uncompressed), else the file itself
 * (a local copy of dist/patches). A host that already decoded the .gz in
 * transit hands over the patch itself, so the gzip magic decides. The
 * manifest's SHA-256 is checked on the unpacked bytes either way. */
async function fetchPatch(name, version) {
  if (typeof DecompressionStream === 'function') {
    try {
      const packed = await fetch(PATCHES + name + '.gz' + version);
      if (packed.ok) {
        const blob = await packed.blob();
        const magic = new Uint8Array(await blob.slice(0, 2).arrayBuffer());
        if (magic[0] !== 0x1f || magic[1] !== 0x8b) return blob;
        return await new Response(blob.stream().pipeThrough(new DecompressionStream('gzip'))).blob();
      }
    } catch (err) { /* fall back to the plain file */ }
  }
  const response = await fetch(PATCHES + name + version);
  if (!response.ok) throw new Error(`cannot load ${name} (${response.status})`);
  return response.blob();
}

function loadPatch(name) {
  let file = patchCache.get(name);
  if (!file) {
    // the manifest's hash in the URL: a new release never gets an old
    // cached copy of a patch that kept its name
    const row = state.rows.find(item => item.patch === name);
    const version = row && row.patch_sha256 ? `?sha=${row.patch_sha256.slice(0, 16)}` : '';
    file = fetchPatch(name, version).then(blob => new File([blob], name)).catch(err => {
      patchCache.delete(name);  // a later attempt can retry
      throw err;
    });
    patchCache.set(name, file);
  }
  return file;
}

function prefetchBase() {
  loadPatch(BASE_PATCH).catch(() => {});  // identify/apply reports the error
}

async function loadManifest() {
  const source = await loadPatches();
  const rows = PatchPlan.rowsFrom(source.manifestText);
  checkRelease(rows);          // before anything is kept: no buttons for a mismatch
  state.patches = source;
  state.rows = rows;
  state.graph = PatchPlan.index(state.rows);
  state.labels = state.graph.labels;
}

/* The page and its patches must be one release. The deployed page carries
 * its release in <html data-release> (stamped with the title by
 * tools/stamp_webpatcher.py); the manifest names it in its release column.
 * A browser that kept an old copy of either gets told to reload instead of
 * patching with a mismatched pair. An unstamped (local) page or manifest
 * has nothing to compare. */
function checkRelease(rows) {
  const page = document.documentElement.dataset.release || '';
  const patches = PatchPlan.releaseStamp(rows);
  if (!page || page.startsWith('$') || page === 'local' || !patches || page === patches) return;
  throw new Error(`This page (${page}) and its patches (${patches}) are from different`
      + ' releases - your browser kept an old copy. Reload the page with Ctrl+Shift+R'
      + ' (or clear this site\'s cache) before patching.');
}

const featureOf = label => FEATURES[label] || {name: label, description: ''};
const displayName = label => featureOf(label).name;

function selectedLabels() {
  return PatchPlan.ordered(state.graph, [...document.querySelectorAll(
      '#choices input:checked')].map(box => box.value));
}

/* The chain: rev1 -> rev0 if the user has a Rev 1 disc (obligatory), then
 * rev0-to-base, then one add- patch per selected option in apply order.
 * PatchPlan picks the file each option needs from `anchor`; nothing about
 * the options themselves is hardcoded here. */
function buildPlan(rev, labels = selectedLabels()) {
  const plan = PatchPlan.plan(state.graph, rev, labels);
  return {
    steps: plan.steps.map(step => stepOf(step.row, step.source)),
    patchNames: plan.patchNames,
    sourceExpect: plan.sourceExpect,
  };
}

/* `ppf` set: the worker builds a PPF instead of a disc and answers
 * {ppf, blob} (blob: the Rev 0 disc it patches, for a Rev 1 source). */
async function apply(source, rev, scratchName, useScratch, ppf, ppfDescription,
                     labels = selectedLabels(), rev0Handle = null) {
  const plan = buildPlan(rev, labels);
  const patchFiles = [];
  for (const name of plan.patchNames) {
    status(`Fetching ${name}`);
    patchFiles.push({name, file: await loadPatch(name)});
  }
  status('working...');
  const worker = new Worker('worker.js');
  try {
    return await new Promise((resolve, reject) => {
      worker.onmessage = event => {
        const msg = event.data;
        if (msg.type === 'progress') status(msg.message + '...');
        else if (msg.type === 'done') resolve(msg);
        else if (msg.type === 'ppf-done') {
          resolve({ppf: msg.ppf, blob: msg.rev0, scratchDir: null, onDisk: false});
        } else if (msg.type === 'error') reject(new Error(msg.message));
      };
      worker.onerror = event => {
        reject(new Error(event.message || 'patch worker failed to start'));
      };
      worker.postMessage(ppf
          ? {type: 'ppf', source, patchFiles, steps: plan.steps,
             sourceExpect: plan.sourceExpect, description: ppfDescription,
             chd: isChd(source), keepChd: $('keep-chd').checked, rev0Handle}
          : {type: 'apply', source, patchFiles, steps: plan.steps,
             sourceExpect: plan.sourceExpect, keepScratch: resultScratch,
             scratchName, useScratch});
    });
  } finally {
    worker.terminate();
  }
}

function outputBase(labels) {
  const stamp = PatchPlan.releaseStamp(state.rows);
  return [OUTPUT_NAME, ...(stamp ? [stamp] : []), ...labels].join('-');
}

function downloadLink(url, name, isDisc) {
  const p = document.createElement('p');
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.textContent = name;
  if (isDisc) {
    anchor.addEventListener('click', () => {
      downloadClickedAt = Date.now();
      resultDownloaded = true;
    });
  }
  p.appendChild(anchor);
  return p;
}

/* Object URLs keep their Blob alive until revoked. Revoke the previous
 * run's result when the new one replaces it, so patching a second disc does
 * not leave the first patched disc in memory. When the result came from
 * OPFS, drop its scratch directory too - but only after the new result is
 * installed, because the File is backed by that directory. */
let resultUrls = [];
let resultScratch = null;
let resultLock = null;
let resultDownloaded = false;
let downloadClickedAt = 0;

/* A page showing a result holds a Web Lock named after its scratch
 * directory. The page sweep and the worker both remove only unlocked
 * directories, so a closed or crashed tab is cleaned up on the next visit or
 * run without touching a second tab's download. The timestamp in the name
 * lets the cleanup age it first. */

/* null when Web Locks are unavailable (the worker then ages directories
 * instead), false when this page could not take the lock, or a handle. */
async function holdScratch(name) {
  if (!navigator.locks || !navigator.locks.request) return null;
  let release;
  const held = new Promise(resolve => { release = resolve; });
  let markReady;
  const ready = new Promise(resolve => { markReady = resolve; });
  let granted = false;
  try {
    navigator.locks.request(name, () => {
      granted = true;
      markReady();
      return held;
    }).catch(() => markReady());
    await ready;
  } catch (err) {
    granted = false;
  }
  if (!granted) {
    release();
    return false;
  }
  return {name, release};
}

function releaseScratch(lock) {
  if (lock) lock.release();
}

async function dropScratch(name) {
  if (!name || !navigator.storage || !navigator.storage.getDirectory) return;
  try {
    const root = await navigator.storage.getDirectory();
    await root.removeEntry(name, {recursive: true});
  } catch (err) {}
}

/* Build PPF on a Rev 1 disc hands back the Rev 0 disc the PPF patches. It
 * carries the Redump name of the Rev 0 dump, so it is the same disc a Rev 0
 * owner has, and every later PPF is built from it. */
const REV0_NAME = 'Megami Ibunroku Persona - Be Your True Mind (Japan)';
const REV0_NOTE = "PPF patches don't work on differently sized discs, please"
    + ' use this disc instead for now and future repatches.';

/* An emulator finds a PPF by the disc's own file name, so the PPF is named
 * after the disc it patches; which release and options it holds goes in
 * its description field and in the manifest beside it. */
const stem = name => name.replace(/\.[^./\\]*$/, '');

/* Beside the PPF: the release, then one option label per line. A local
 * release has no stamp yet; its first line says so, so the first line is
 * always the release and never an option. */
const UNSTAMPED = 'unstamped';

function ppfNote(info) {
  const lines = [PatchPlan.releaseStamp(state.rows) || UNSTAMPED, ...info.labels];
  return new Blob([lines.join('\n') + '\n'], {type: 'text/plain'});
}

/* `done.blob` is the disc to download (the patched disc, or for a PPF built
 * from Rev 1 the Rev 0 disc it patches); `done.ppf` the PPF, if one was
 * built, named after the disc it patches, with a note of what it holds. */
function showResult(base, done, lock, info) {
  const files = [];   // [blob, name]
  if (done.ppf) {
    const disc = done.blob ? REV0_NAME : stem(info.sourceName);
    const ppfName = disc + '.ppf';
    files.push([done.ppf, ppfName]);
    files.push([ppfNote(info), ppfName + '.txt']);
    if (done.blob) files.push([done.blob, disc + '.bin']);
  } else {
    files.push([done.blob, base + '.bin']);
  }
  const disc = files.find(([, name]) => name.endsWith('.bin'));
  if (disc) {
    files.push([new Blob([`FILE "${disc[1].replace(/"/g, '')}" BINARY\n` + CUE_BODY],
                         {type: 'application/octet-stream'}),
                stem(disc[1]) + '.cue']);
  }

  for (const url of resultUrls) URL.revokeObjectURL(url);
  const previousScratch = resultScratch;
  const previousLock = resultLock;
  resultScratch = done.scratchDir || null;
  resultLock = resultScratch ? lock : null;
  resultDownloaded = false;
  downloadClickedAt = 0;  // a new result has not been downloaded yet
  resultUrls = [];
  const entry = {at: new Date().toISOString(),
                 release: PatchPlan.releaseStamp(state.rows),
                 options: info.labels, kind: done.ppf ? 'ppf' : 'disc',
                 source: REV_LABEL[info.rev], file: files[0][1]};
  let recorded = false;
  const record = () => {   // once per result, however it is saved
    if (!recorded) addHistory(entry);
    recorded = true;
  };
  // the disc is the download the leave-page warning protects
  const tracked = disc ? disc[1] : files[0][1];
  const links = files.map(([blob, name]) => {
    const url = URL.createObjectURL(blob);
    resultUrls.push(url);
    const link = downloadLink(url, name, name === tracked);
    link.querySelector('a').addEventListener('click', record);
    return link;
  });
  $('results').replaceChildren(...links);
  $('scratch-warning').hidden = !done.scratchDir;
  if (previousScratch) dropScratch(previousScratch);
  releaseScratch(previousLock);
  status(done.ppf && done.blob ? REV0_NOTE : 'Here it is :D');
}

/* A PPF this patcher wrote: PPF 3.0 whose description (bytes 6..56) is a
 * release name, which always starts with OUTPUT_NAME. */
function ownPpf(head) {
  const magic = String.fromCharCode(...head.subarray(0, 5));
  const description = String.fromCharCode(...head.subarray(6, 56));
  return magic === 'PPF30' && description.startsWith(OUTPUT_NAME + '-');
}

/* Build PPF with a disc from the disc folder (Chrome, Edge): the PPF and
 * its note are written next to the disc - nothing to download. From a Rev
 * 1 disc the PPF patches the Rev 0 copy: the copy already in the folder,
 * or a new one written there with it. A PPF this patcher did not write is
 * never overwritten, and one that already holds this release and these
 * options is left alone. */
const PPF_DISC_KEY = 'patcher.ppf-disc';

function rememberPpfDisc(name) {
  try { localStorage.setItem(PPF_DISC_KEY, name); } catch (err) {}
}

function rememberedPpfDisc() {
  try { return localStorage.getItem(PPF_DISC_KEY); } catch (err) { return null; }
}

async function fileIn(folder, name) {
  try {
    return await (await folder.getFileHandle(name)).getFile();
  } catch (err) {
    return null;
  }
}


const cueFor = binName =>
    new Blob([`FILE "${binName.replace(/"/g, '')}" BINARY\n` + CUE_BODY],
             {type: 'application/octet-stream'});

async function writeInFolder(folder, files) {
  for (const [blob, name] of files) {
    status(`Saving ${name}`);
    const writable = await (await folder.getFileHandle(name, {create: true})).createWritable();
    await writable.write(blob);
    await writable.close();
  }
}

async function ppfIntoFolder(rev, labels) {
  const folder = await writableFolder();
  let source = state.source;
  let sourceRev = rev;
  if (rev === 1) {
    // the Rev 0 copy made before, when it is there, is what the PPF patches
    const copy = await fileIn(folder, REV0_NAME + '.bin');
    if (copy) {
      status(`Checking ${copy.name}`);
      if ((await identify(copy)).rev === 0) {
        source = copy;
        sourceRev = 0;
      }
    }
  }
  const discName = sourceRev === 1 ? REV0_NAME + '.bin' : source.name;
  const ppfName = stem(discName) + '.ppf';
  const noteName = ppfName + '.txt';
  const existing = await fileIn(folder, ppfName);
  if (existing && !ownPpf(new Uint8Array(await existing.slice(0, 56).arrayBuffer()))) {
    throw new Error(`${ppfName} in ${folder.name} is not a Persona translation PPF;`
        + ' it was left alone');
  }
  const stamp = PatchPlan.releaseStamp(state.rows);
  const note = await fileIn(folder, noteName);
  if (note && existing && stamp) {
    // the first line is the release; options follow, one per line
    const [first = '', ...rest] = (await note.text()).split(/\r?\n/);
    if (first.trim() === stamp
        && sameOptions(labels, rest.map(line => line.trim()).filter(Boolean))) {
      $('results').replaceChildren();
      status(`${ppfName} is already ${stamp} with these options`);
      return;
    }
  }
  // from Rev 1 the Rev 0 disc is written by the worker straight into its
  // file, its .cue first (a tiny file, so it is there whatever happens)
  let rev0Handle = null;
  if (sourceRev === 1) {
    await writeInFolder(folder, [[cueFor(REV0_NAME + '.bin'), REV0_NAME + '.cue']]);
    rev0Handle = await folder.getFileHandle(REV0_NAME + '.bin', {create: true});
  }
  const done = await apply(source, sourceRev, null, false, true, outputBase(labels), labels,
                           rev0Handle);
  await writeInFolder(folder, [[done.ppf, ppfName], [ppfNote({labels}), noteName]]);
  rememberPpfDisc(discName);       // the disc chosen from now on
  addHistory({at: new Date().toISOString(), release: stamp, options: labels,
              kind: 'ppf', source: REV_LABEL[rev], file: ppfName});
  $('results').replaceChildren();
  status(rev0Handle
      ? `The PPF was placed alongside the selected disc, together with the Rev 0 disc`
        + ` it patches (${REV0_NAME}.bin). ${REV0_NOTE}`
      : `The PPF was placed alongside the selected disc (${discName}).`);
}

/* The disc folder (Chrome, Edge). Picked once and kept as a handle in
 * IndexedDB, so a later visit only re-confirms write permission (one click
 * on the browser's prompt) instead of picking again; Change folder picks a
 * different one. Blocked storage just means picking every time. */
const FOLDER_STORE = 'handles';
const FOLDER_KEY = 'ppf-folder';

function folderDb(mode, use) {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open('patcher', 1);
    open.onupgradeneeded = () => open.result.createObjectStore(FOLDER_STORE);
    open.onerror = () => reject(open.error);
    open.onsuccess = () => {
      const db = open.result;
      const request = use(db.transaction(FOLDER_STORE, mode).objectStore(FOLDER_STORE));
      request.onsuccess = () => { resolve(request.result); db.close(); };
      request.onerror = () => { reject(request.error); db.close(); };
    };
  });
}

async function storedFolder() {
  try {
    return await folderDb('readonly', store => store.get(FOLDER_KEY)) || null;
  } catch (err) {
    return null;
  }
}

async function pickFolder() {
  const previous = state.folder || await storedFolder();
  const folder = await window.showDirectoryPicker(
      {id: FOLDER_KEY, mode: 'readwrite', ...(previous ? {startIn: previous} : {})});
  try {
    await folderDb('readwrite', store => store.put(folder, FOLDER_KEY));
  } catch (err) { /* not remembered: the next save asks again */ }
  state.folder = folder;
  showFolder(folder);
  return folder;
}

/* The remembered folder with write permission, or a newly picked one. */
async function writableFolder() {
  const folder = state.folder || await storedFolder();
  if (folder) {
    let permission = await folder.queryPermission({mode: 'readwrite'});
    if (permission !== 'granted') permission = await folder.requestPermission({mode: 'readwrite'});
    if (permission === 'granted') return folder;
  }
  return pickFolder();
}

function showFolder(folder) {
  $('folder-line').hidden = !window.showDirectoryPicker;
  $('folder-or').hidden = !window.showDirectoryPicker;   // folder OR file picker
  $('folder-name').textContent = folder ? folder.name : 'not chosen yet';
  $('change-folder').textContent = folder ? 'Change folder' : 'Choose folder';
}

/* The disc folder (Chrome, Edge) comes first: the page lists the Megami
 * Ibunroku Persona discs in it - a .bin by its size, a .chd by the raw
 * SHA-1 in its 124-byte header, so other games never show up - and picks
 * the one used last. A PPF built from a disc chosen here is saved next to
 * it at once. */
async function discsIn(folder) {
  const sizes = new Map(state.rows.filter(row => row.patch === BASE_PATCH || row.patch === REV1_PATCH)
      .map(row => [Number(row.source_bytes), row.patch === BASE_PATCH ? 0 : 1]));
  const hashes = new Map(state.rows.filter(row => row.source_chd_sha1)
      .map(row => [row.source_chd_sha1, row.patch === BASE_PATCH ? 0 : 1]));
  const found = [];
  const all = [];              // every .bin and .chd, for the search
  for await (const [name, handle] of folder.entries()) {
    if (handle.kind !== 'file' || !/\.(bin|chd)$/i.test(name)) continue;
    all.push({name, handle});
    const file = await handle.getFile();
    let rev;
    if (/\.bin$/i.test(name)) {
      rev = sizes.get(file.size);
    } else {
      const sha1 = await CHD.headerSha1(async (offset, length) =>
          new Uint8Array(await file.slice(offset, offset + length).arrayBuffer()));
      rev = hashes.get(sha1);
    }
    if (rev !== undefined) found.push({name, rev, handle});
  }
  const byName = (a, b) => a.name.localeCompare(b.name);
  return {discs: found.sort(byName), all: all.sort(byName)};
}

/* The disc picker: a search over the folder's .bin and .chd files, every
 * word of the query somewhere in the name, starting with the game's name.
 * Recognised discs carry their revision and come first; the picked one is
 * highlighted and always heads the list, whatever the search (an empty
 * search shows it alone). */
const SEARCH_DEFAULT = 'Megami Ibunroku Persona';
const SEARCH_SHOWN = 200;

function discPicker(all, discs) {
  const revOf = new Map(discs.map(disc => [disc.name, disc.rev]));
  const files = all.slice().sort((a, b) =>
      (revOf.has(b.name) - revOf.has(a.name)) || a.name.localeCompare(b.name));
  const wrap = document.createElement('div');
  const search = document.createElement('input');
  search.type = 'search';
  search.className = 'disc-search';
  search.placeholder = 'Search the folder for the disc';
  search.value = SEARCH_DEFAULT;
  const list = document.createElement('div');
  const button = (file, current) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'file-choice' + (file.name === current ? ' picked' : '');
    item.setAttribute('aria-pressed', file.name === current);
    item.textContent = file.name + (revOf.has(file.name) ? ` - ${REV_LABEL[revOf.get(file.name)]}` : '');
    item.addEventListener('click', async () => setSource(await file.handle.getFile(), true));
    return item;
  };
  const render = () => {
    // the picked disc heads the list whatever the search says
    const current = state.fromFolder && state.source ? state.source.name : null;
    const head = files.find(file => file.name === current);
    const items = head ? [button(head, current)] : [];
    const words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
    if (words.length) {
      const matches = files.filter(file => file !== head && words.every(word =>
          file.name.toLowerCase().includes(word)));
      items.push(...matches.slice(0, SEARCH_SHOWN).map(file => button(file, current)));
      if (matches.length > SEARCH_SHOWN) {
        const more = document.createElement('p');
        more.textContent = `and ${matches.length - SEARCH_SHOWN} more - narrow the search`;
        items.push(more);
      } else if (!matches.length && !head) {
        const none = document.createElement('p');
        none.textContent = 'No .bin or .chd matches.';
        items.push(none);
      }
    }
    list.replaceChildren(...items);
  };
  search.addEventListener('input', render);
  state.renderPicker = render;
  render();
  wrap.append(search, list);
  return wrap;
}

/* `fresh`: the user just chose this folder, so its best disc is selected
 * even when one from another folder was. */
async function loadFolder(folder, fresh = false) {
  state.folder = folder;
  showFolder(folder);
  const box = $('folder-discs');
  box.hidden = false;
  box.textContent = 'Looking for the disc...';
  let discs, all;
  try {
    ({discs, all} = await discsIn(folder));
  } catch (err) {
    box.textContent = err.message;
    return;
  }
  const remembered = rememberedPpfDisc();
  const note = remembered && await fileIn(folder, stem(remembered) + '.ppf.txt');
  if (note) {
    noteRelease = (await note.text()).split(/\r?\n/)[0].trim() || UNSTAMPED;
    updateBanner();
  }
  box.replaceChildren(discPicker(all, discs));
  if (!discs.length) {
    status(`No Megami Ibunroku Persona disc this page recognises in ${folder.name} -`
        + ' search for it below, choose the folder that has it, or pick the file.', true);
    return;
  }
  // the best disc here: the one used last, the file picked with the file
  // input, one that already has a PPF note, a Rev 0 disc (the PPF patches
  // Rev 0), else the first
  const notes = new Set();
  for (const disc of discs) {
    if (await fileIn(folder, stem(disc.name) + '.ppf.txt')) notes.add(disc.name);
  }
  const rank = disc => [disc.name === remembered, !!state.source && disc.name === state.source.name,
                        notes.has(disc.name), disc.rev === 0];
  const pick = discs.slice().sort((a, b) => {
    const ra = rank(a), rb = rank(b);
    for (let k = 0; k < ra.length; k++) if (ra[k] !== rb[k]) return ra[k] ? -1 : 1;
    return 0;
  })[0];
  if (fresh || !state.source) {
    setSource(await pick.handle.getFile(), true);
  } else if (state.renderPicker) {
    state.renderPicker();
  }
}

/* The disc to patch: from the folder list (`fromFolder`), or from the file
 * picker. */
function setSource(file, fromFolder) {
  state.source = file;
  state.fromFolder = !!(file && fromFolder);
  state.rev = null;
  state.identifyError = null;
  if (state.fromFolder) rememberPpfDisc(file.name);
  if (state.renderPicker) state.renderPicker();
  status(file ? file.name : '');
  refreshApply();
  maybeIdentify();
}

/* The remembered disc folder: listed at once when permission survived,
 * otherwise its button asks for it back (that needs a click). */
async function restoreFolder() {
  const folder = await storedFolder();
  if (!folder) {
    $('folder-discs').hidden = false;
    $('folder-discs').textContent = 'Choose the folder with your disc, then pick it here.';
    return;
  }
  state.folder = folder;
  showFolder(folder);
  if (await folder.queryPermission({mode: 'readwrite'}) === 'granted') return loadFolder(folder);
  $('change-folder').textContent = 'Allow access';
  $('change-folder').dataset.allow = '1';
  $('folder-discs').hidden = false;
  $('folder-discs').textContent = `Click Allow access to use ${folder.name} again.`;
}

/* A file from the picker: when the disc folder holds the same file, it is
 * that one (so its PPF can be saved beside it); otherwise say so. */
async function pickedFile(file) {
  if (!file || !state.folder) return setSource(file, false);
  const inFolder = await fileIn(state.folder, file.name);
  if (inFolder && inFolder.size === file.size) return setSource(inFolder, true);
  setSource(file, false);
  status(`${file.name} is not in ${state.folder.name}, so a PPF cannot be saved next to`
      + ' it - pick it from the list above, or choose its folder', true);
}


/* Everything patched in this browser (Patched before): when, which release, which
 * options, a disc or a PPF. It lives only in this browser's localStorage;
 * blocked storage just means no history. */
const HISTORY_KEY = 'patcher.history';
const HISTORY_MAX = 200;

function readHistory() {
  try {
    const saved = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    return Array.isArray(saved) ? saved : [];
  } catch (err) {
    return [];
  }
}

function addHistory(entry) {
  noteRelease = null;         // what was just patched is the latest now
  try {
    const history = readHistory();
    history.unshift(entry);
    localStorage.setItem(HISTORY_KEY,
                         JSON.stringify(history.slice(0, HISTORY_MAX)));
  } catch (err) { /* storage blocked or full: nothing is remembered */ }
  renderHistory();
}

function clearHistory() {
  try { localStorage.removeItem(HISTORY_KEY); } catch (err) {}
  renderHistory();
}

/* "There's a new update" under the title: the release this browser last
 * patched with (the newest Patched before entry, or the remembered disc's
 * .ppf.txt once the disc folder is open) against this release. An
 * unstamped (local) release cannot be compared, so it never shows. */
let noteRelease = null;

function updateBanner() {
  const stamp = PatchPlan.releaseStamp(state.rows);
  const last = noteRelease || (readHistory()[0] || {}).release || '';
  const old = stamp && last && last !== UNSTAMPED && last !== stamp;
  $('update-banner').hidden = !old;
  if (old) {
    $('update-banner').textContent = `There's a new update (${stamp})! You're on ${last} -`
        + ' press Build PPF, or build your disc again.';
  }
}

function renderHistory() {
  const history = readHistory();
  if (state.rows.length) updateBanner();
  $('history-box').hidden = !history.length;
  $('history').replaceChildren(...history.map(item => {
    const row = document.createElement('li');
    const when = new Date(item.at);
    const date = isNaN(when) ? '' : when.toLocaleString();
    const options = (item.options || []).length
        ? item.options.map(label => featureOf(label).name)
            .join(', ')
        : 'no options';
    row.textContent = `${date} - ${item.release || 'unstamped release'} - `
        + `${item.kind === 'ppf' ? 'PPF' : 'disc'} from ${item.source || '?'}`
        + ` - ${options} (${item.file})`;
    return row;
  }));
}

async function deleteResult() {
  const scratch = resultScratch;
  const lock = resultLock;
  for (const url of resultUrls) URL.revokeObjectURL(url);
  resultUrls = [];
  resultScratch = null;
  resultLock = null;
  resultDownloaded = false;
  downloadClickedAt = 0;
  $('results').replaceChildren();
  $('scratch-warning').hidden = true;
  if (scratch) await dropScratch(scratch);
  releaseScratch(lock);
  status('Patched disc deleted from browser storage.');
}

/* Ask before leaving while there is something to lose: a patch run still in
 * flight, a finished disc that has not been downloaded, or an OPFS copy that
 * the user may still want to delete. The browser shows its own wording. */
window.addEventListener('beforeunload', event => {
  const pending = state.running
      || (resultUrls.length && (!resultDownloaded || resultScratch));
  if (!pending) return;
  event.preventDefault();
  event.returnValue = '';
});

/* A tab that goes away for good should not leave its scratch file behind.
 * If a download started less than a minute ago it may still be reading that
 * file, so leave it: the next visit or run removes the orphan once the lock
 * is gone. */
window.addEventListener('pagehide', event => {
  if (event.persisted || !resultScratch) return;
  if (downloadClickedAt && Date.now() - downloadClickedAt < 60 * 1000) return;
  dropScratch(resultScratch);
});

const SAVED_KEY = 'patcher.selected';

function saveSelection() {
  try {
    const checked = [...document.querySelectorAll('#choices input:checked')]
        .map(box => box.value);
    localStorage.setItem(SAVED_KEY, JSON.stringify(checked));
  } catch (err) { /* storage blocked: the choice just isn't remembered */ }
}

const sameOptions = (a, b) => a.length === b.length && a.every(label => b.includes(label));

/* Tick the options remembered from the last patch run; labels that no
 * longer exist are ignored. */
function restoreSelection() {
  try {
    const saved = JSON.parse(localStorage.getItem(SAVED_KEY) || '[]');
    if (!Array.isArray(saved)) return;
    for (const box of document.querySelectorAll('#choices input')) {
      box.checked = saved.includes(box.value);
    }
  } catch (err) { /* nothing saved, or storage blocked */ }
}

function renderGrid() {
  const grid = $('choices');
  // FEATURES order, so the checkboxes stay where they are regardless of how
  // the manifest's patch names happen to sort; anything unlisted follows.
  const shown = [...Object.keys(FEATURES).filter(label => state.labels.includes(label)),
                ...state.labels.filter(label => !FEATURES[label])];
  grid.replaceChildren(...shown.map(label => {
    const info = featureOf(label);
    const item = document.createElement('label');
    item.className = 'choice';
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.value = label;
    const text = document.createElement('span');
    text.className = 'choice-text';
    const name = document.createElement('span');
    name.className = 'choice-name';
    name.textContent = info.name;
    text.append(name);
    if (info.description) {
      const note = document.createElement('span');
      note.className = 'choice-description';
      note.textContent = info.description;
      text.append(document.createElement('br'), note);
    }
    item.append(box, text);
    return item;
  }));
  restoreSelection();
  $('choices-box').hidden = false;
}

/* Identifying the disc (which may still be downloading its patch) does not
 * disable Apply: a click waits for that run to finish. */
function refreshApply() {
  const disabled = state.running || !state.source || !state.rows.length;
  // a CHD is compressed: xdelta cannot patch it, only a PPF can be made
  $('apply').disabled = disabled || isChd(state.source);
  $('build-ppf').disabled = disabled;
}

/* The release patches that prove which original disc this is: applying
 * rev1-to-rev0 in check-only mode succeeds only on Rev 1, and rev0-to-base
 * only on Rev 0. The manifest records each patch's source size; the worker
 * runs the matching one and reads the exit status. */
function revisionExpectations() {
  const expect = [];
  const baseRow = state.rows.find(row => row.patch === BASE_PATCH);
  const revRow = state.rows.find(row => row.patch === REV1_PATCH);
  if (baseRow) {
    expect.push({rev: 0, bytes: Number(baseRow.source_bytes),
                 patch: BASE_PATCH, label: REV_LABEL[0]});
  }
  if (revRow) {
    expect.push({rev: 1, bytes: Number(revRow.source_bytes),
                 patch: REV1_PATCH, label: REV_LABEL[1]});
  }
  return expect;
}

const isChd = file => !!file && /\.chd$/i.test(file.name);

/* A CHD is identified by its header alone: the raw SHA-1 chdman records for
 * the disc inside, against the one the release computed from each original
 * disc (`source_chd_sha1`). Only a Rev 0 CHD can take a PPF: from Rev 1 the
 * PPF patches a converted Rev 0 disc, which is a .bin. */
async function identifyChd(source) {
  const readAt = async (offset, length) =>
      new Uint8Array(await source.slice(offset, offset + length).arrayBuffer());
  const chd = await CHD.open(readAt);
  const known = state.rows.filter(row => row.source_chd_sha1);
  if (!known.length) {
    throw new Error('this release cannot recognise CHD files yet - use the .bin');
  }
  const row = known.find(item => item.source_chd_sha1 === chd.rawSha1);
  if (!row) {
    throw new Error("this CHD's disc is not the original Megami Ibunroku Persona"
        + ' (Rev 0 or Rev 1) - it may be a different or modified dump');
  }
  if (row.patch === REV1_PATCH) {
    throw new Error('this is a Rev 1 CHD; a PPF needs the Rev 0 disc - pick the'
        + ' Rev 1 .bin to get a Rev 0 copy, or a Rev 0 CHD');
  }
  return {rev: 0};
}

async function identify(source) {
  if (isChd(source)) return identifyChd(source);
  const expect = revisionExpectations();
  /* Only the patch for the candidate with this file's size can apply, so
   * don't download the other revision's patch. */
  for (const entry of expect.filter(entry => entry.bytes === source.size)) {
    status(`Fetching ${entry.patch} to identify the disc`);
    entry.file = await loadPatch(entry.patch);
  }
  const worker = new Worker('worker.js');
  return new Promise((resolve, reject) => {
    worker.onmessage = event => {
      const msg = event.data;
      if (msg.type === 'identified') resolve(msg);
      else if (msg.type === 'error') reject(new Error(msg.message));
    };
    worker.onerror = event => {
      reject(new Error(event.message || 'Patch worker failed to start'));
    };
    worker.postMessage({type: 'identify', source, expect});
  }).finally(() => worker.terminate());
}

/* Start (or join) the identification run for the current file. Apply awaits
 * the returned promise, so a click while the patch is still downloading just
 * waits instead of being refused. A new file starts a new run; an older run
 * that finishes later is ignored by its run number. */
async function maybeIdentify() {
  if (!state.source || !state.rows.length) return;
  if (state.identifying && state.identifySource === state.source) {
    return state.identifyWork;
  }
  const run = ++state.identifyRun;
  const source = state.source;
  state.identifying = true;
  state.identifySource = source;
  state.identifyError = null;
  refreshApply();
  status('identifying the disc...');
  const work = (async () => {
    try {
      const found = await identify(source);
      if (run === state.identifyRun) {
        state.rev = found.rev;
        status(`${REV_LABEL[found.rev]} disc detected`);
      }
    } catch (err) {
      if (run === state.identifyRun) {
        state.identifyError = err.message;
        status(err.message, true);
      }
    } finally {
      if (run === state.identifyRun) {
        state.identifying = false;
        state.identifySource = null;
        refreshApply();
      }
    }
  })();
  state.identifyWork = work;
  return work;
}

async function ensureRevision() {
  while (state.identifying) {
    const work = state.identifyWork;
    if (!work) break;
    await work;
  }
  return state.rev;
}

/* MEMFS is the default: a computer can hold the chain in its tab and never
 * writes a disc image to browser storage. Low-RAM mode moves the output to
 * OPFS instead; it is opt-in, and turned on automatically only where memory
 * is likely tight (Android, or a device that reports under 4 GB). */
const LOW_RAM_GB = 4;

function lowMemoryHint() {
  const data = navigator.userAgentData;
  if ((data && data.platform === 'Android')
      || /Android/i.test(navigator.userAgent || '')) {
    return 'this is an Android device';
  }
  const reported = navigator.deviceMemory;
  if (typeof reported === 'number' && reported < LOW_RAM_GB) {
    return `this browser reports about ${reported} GB of memory`;
  }
  return null;
}

let autoMemoryHint = null;

const MEMORY_KEY = 'patcher.memory';

function savedMemory() {
  try {
    const saved = JSON.parse(localStorage.getItem(MEMORY_KEY) || 'null');
    return saved && typeof saved === 'object' ? saved : null;
  } catch (err) {
    return null;
  }
}

function saveMemory() {
  try {
    localStorage.setItem(MEMORY_KEY, JSON.stringify(
        {lowRam: $('low-ram').checked, keepChd: $('keep-chd').checked}));
  } catch (err) { /* storage blocked: the boxes just aren't remembered */ }
}

/* The CHD parts the worker keeps (worker.js, PART_DB) - the whole store. */
function dropChdParts() {
  try { indexedDB.deleteDatabase('patcher-chd'); } catch (err) {}
}

function setMemoryNote(text) {
  const note = $('low-ram-note');
  note.hidden = !text;
  note.textContent = text || '';
}

/* The automatic reason only applies to the checkbox the page set; a manual
 * change clears it. A run that asked for browser storage and did not get it
 * says so, because that run stayed in memory. */
function refreshMemoryNote(fellBack) {
  if (fellBack) {
    setMemoryNote(
        'Browser storage is not available here, so this run used memory instead.');
  } else {
    setMemoryNote(autoMemoryHint
        ? `Turned on automatically because ${autoMemoryHint}.` : '');
  }
}

window.patcher = {loadManifest, FEATURES, buildPlan, apply, selectedLabels,
                  state, lowMemoryHint};  // tests

async function init() {
  ScratchSpace.clean();  // a closed tab could not finish deleting its output
  // the memory and storage options are remembered from the first visit:
  // low-RAM mode starts from the device hint and CHD parts start kept
  const memory = savedMemory();
  autoMemoryHint = memory ? null : lowMemoryHint();
  $('low-ram').checked = memory ? !!memory.lowRam : !!autoMemoryHint;
  $('keep-chd').checked = memory ? memory.keepChd !== false : true;
  if (!memory) saveMemory();     // the starting choices, written at once
  refreshMemoryNote(false);
  // kept parts should survive storage pressure: ask for persistent storage
  // (Chrome decides without a prompt, by how the site is used)
  const persist = () => {
    if ($('keep-chd').checked && navigator.storage && navigator.storage.persist) {
      navigator.storage.persist().catch(() => {});
    }
  };
  persist();
  $('keep-chd').addEventListener('change', () => {
    saveMemory();
    if (!$('keep-chd').checked) dropChdParts();
    persist();
  });
  $('low-ram').addEventListener('change', () => {
    autoMemoryHint = null;
    saveMemory();
    refreshMemoryNote(false);
  });
  $('source').addEventListener('change', () => pickedFile($('source').files[0] || null));
  $('delete-scratch').addEventListener('click', deleteResult);
  $('clear-history').addEventListener('click', clearHistory);
  renderHistory();
  $('apply').addEventListener('click', () => run(false));
  $('build-ppf').addEventListener('click', () => run(true));
  if (window.showDirectoryPicker) {
    showFolder(null);
    $('change-folder').addEventListener('click', async () => {
      try {
        // a remembered folder only needs its permission back (a click is
        // the user gesture that asks); Change folder picks another
        const folder = state.folder;
        if (folder && $('change-folder').dataset.allow) {
          if (await folder.requestPermission({mode: 'readwrite'}) === 'granted') {
            delete $('change-folder').dataset.allow;
            return loadFolder(folder);
          }
        }
        await loadFolder(await pickFolder(), true);
      } catch (err) {
        if (!err || err.name !== 'AbortError') status(err.message, true);
      }
    });
  }
  async function run(ppf) {
    if (!state.source || state.running) return;
    saveSelection();
    state.running = true;
    refreshApply();
    let lock = null;
    try {
      // The disc may still be identified (its patch may still be
      // downloading). Wait for that run instead of refusing the click.
      const rev = await ensureRevision();
      if (rev === null) {
        throw new Error(state.identifyError
            || 'this disc is neither Rev 0 nor Rev 1, so it cannot be patched');
      }
      // Name the download from the selection this run applied, not from
      // whatever the boxes say by the time the worker finishes.
      const labels = selectedLabels();
      // a disc from the disc folder: the PPF goes next to it, no downloads
      if (ppf && state.fromFolder && state.folder) return await ppfIntoFolder(rev, labels);
      // a PPF never holds a disc image, so it needs no scratch space
      const lowRam = !ppf && $('low-ram').checked;
      let scratch = lowRam ? ScratchSpace.name(Date.now()) : null;
      if (lowRam) lock = await holdScratch(scratch);
      const useScratch = lowRam && lock !== false;
      if (!useScratch) {
        // Either memory is fine (the default) or the page could not hold the
        // lock that protects an OPFS directory from another tab's orphan
        // cleanup; both run in memory.
        scratch = null;
        lock = null;
      }
      const done = await apply(state.source, rev, scratch, useScratch, ppf,
                               outputBase(labels));
      const keep = done.scratchDir ? lock : null;
      if (!keep) releaseScratch(lock);
      lock = null;  // showResult owns the lock from here
      if (!ppf) refreshMemoryNote(lowRam && !done.onDisk);
      showResult(outputBase(labels), done, keep,
                       {labels, rev, sourceName: state.source.name});
    } catch (err) {
      releaseScratch(lock);
      status(err.message, true);
    } finally {
      state.running = false;
      refreshApply();
    }
  }
  try {
    await loadManifest();
    prefetchBase();        // the largest patch; ready before a disc is picked
    renderGrid();
    updateBanner();
    if (window.showDirectoryPicker) restoreFolder();
    status(`Hello :D - there are ${state.labels.length} options`);
  } catch (err) {
    status(err.message, true);
  }
  refreshApply();
  if (state.source) maybeIdentify();  // picked before the manifest arrived
}

init();
