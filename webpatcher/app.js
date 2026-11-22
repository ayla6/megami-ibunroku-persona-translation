'use strict';
/* Persona translation web patcher - page logic.
 *
 * The release output (dist/patches/) is served next to this page as
 * patches/ (manifest.tsv + the .p1mod layers): the Pages workflow unpacks
 * it from the release zip, and local testing copies or symlinks it. The
 * manifest drives everything: the base layer, which options exist (its
 * option rows, in apply order) and every layer's SHA-1. worker.js applies
 * the layers (modpack.js). Nothing here is hardcoded per release.
 */

const PATCHES = 'patches/';
const RELEASE_REPO = 'ayla6/megami-ibunroku-persona-translation';  // 'owner/repo'; tools/publish_patches.py uploads here too
/* The downloaded image is named from the release, never from the file the
 * user picked (which may be a dump name, a hash, or just wrong). The
 * manifest's release stamp names the release, so results from two releases
 * never share a filename. */
const OUTPUT_NAME = 'Persona-TL';
/* Same cue convention as src/pipeline/build_disc.py. */
const CUE_BODY = '  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n';

/* What each manifest option is called and what it does: generated into
 * features.js by tools/generate_features.py from each mod's
 * src/mods/<mod>/mod.tsv (the single place mod wording lives - the release
 * README and the layers carry the same). Edit the mod.tsv, never this table;
 * the Pages workflow and tools/publish_patches.py run the generator for you.
 * An option missing from it still works; it just shows its internal label. */
const FEATURES = globalThis.FEATURES || {};
/* Mods were once known by short labels (`saves`); remembered selections and
 * history from then are read through this map (generated with FEATURES). */
const RENAMES = globalThis.FEATURE_RENAMES || {};
const renamed = label => RENAMES[label] || label;

/* Only the Rev 0 disc is patched. A Rev 1 .bin is recognised by its size
 * so the page can say what is wrong instead of just "not the original". */
const REV1_BYTES = 699672960;

/* The manifest: one row per layer (layer, kind, label, choices, requires,
 * version, bytes, sha1, ...; the base row also has the original disc's
 * source_bytes and source_chd_sha1). requires is the labels of the mods the
 * layer needs, comma-separated; version is the release (mods have no version
 * of their own). */
function rowsFrom(text) {
  const lines = text.split(/\r?\n/).filter(line => line.trim());
  const header = (lines.shift() || '').split('\t');
  if (!header.includes('layer') || !header.includes('choices')) {
    throw new Error('this release manifest is from an older patcher - reload the page'
        + ' with Ctrl+Shift+R');
  }
  return lines.map(line => {
    const cells = line.split('\t');
    return Object.fromEntries(header.map((name, k) => [name, cells[k] || '']));
  });
}

const requirementsOf = row => (row.requires || '').split(',').filter(Boolean);

/* The option labels an option needs, directly or through another option
 * (the base layer is always applied, so it is never one of them). */
function neededOptions(label, seen = new Set()) {
  const row = state.rows.find(item => item.kind === 'option' && item.label === label);
  const own = state.ownMods.find(mod => mod.name === label);
  for (const need of row ? requirementsOf(row) : own ? own.requires : []) {
    if ((state.labels.includes(need) || state.ownMods.some(mod => mod.name === need))
        && !seen.has(need)) {
      seen.add(need);
      neededOptions(need, seen);
    }
  }
  return seen;
}

/* Dependencies stay blue regardless of selection. Ticking a mod enables
 * and locks what it needs until its dependents are off; automatically
 * enabled dependencies then go off again. */
function followRequirements(changed) {
  const boxes = [...document.querySelectorAll('#choices input.mod')];
  if (changed && changed.classList.contains('mod')) {
    delete changed.dataset.auto;          // a click makes it the user's own
  }
  const manual = boxes.filter(item => item.checked && !item.dataset.auto);
  const ownManual = state.ownMods.filter(mod => mod.on && !mod.auto);
  const dependencies = new Set([
    ...state.rows.flatMap(requirementsOf),
    ...state.ownMods.flatMap(mod => mod.requires),
  ]);
  const needed = new Set([
    ...manual.flatMap(item => [...neededOptions(item.value)]),
    ...ownManual.flatMap(mod => [...neededOptions(mod.name)]),
  ]);
  for (const mod of state.ownMods) {
    if (!ownManual.includes(mod)) {
      mod.on = needed.has(mod.name);
      mod.auto = mod.on;
    }
    mod.required = needed.has(mod.name);
  }
  for (const control of document.querySelectorAll('#own-mods [data-mod]')) {
    const mod = state.ownMods.find(item => item.name === control.dataset.mod);
    if (mod) {
      control.disabled = mod.required;
      if (control.type === 'checkbox') {
        control.checked = mod.on;
        control.closest('label').classList.toggle('auto', dependencies.has(mod.name));
      }
    }
  }
  for (const item of boxes.filter(box => !manual.includes(box))) {
    item.checked = needed.has(item.value);
    if (item.checked) item.dataset.auto = '1'; else delete item.dataset.auto;
  }
  for (const item of boxes) {
    item.disabled = needed.has(item.value);
  }
  for (const item of document.querySelectorAll('#choices input')) {
    item.closest('.chip').classList.toggle('auto', dependencies.has(item.value));
  }
  refreshSettings();
}

const releaseStamp = rows => (rows.find(row => row.release) || {}).release || '';
/* A release the build has not verified yet (building: layers still being
 * made; testing: its checks running) - only ever served locally. */
const unverified = rows => [...new Set(rows.map(row => row.state || 'verified'))]
    .filter(state => state !== 'verified');
const baseRow = () => state.rows.find(row => row.kind === 'base');

const $ = id => document.getElementById(id);

const state = {
  rows: [],
  labels: [],            // option labels, in apply order
  ranges: {},            // numeric settings declared by the actual layer headers
  source: null,
  fromFolder: false,     // the source was chosen from the disc folder's list
  folder: null,          // the disc folder (File System Access API)
  rev: null,             // 0 once the disc is recognised as Rev 0, null until checked
  identifying: false,
  identifyRun: 0,
  identifyWork: null,    // promise for the run in flight
  identifySource: null,  // file that run is about
  identifyError: null,   // why the last run failed, if it did
  running: false,
  ownMods: [],           // [{file, blob, on, name, title, version, requires}]
};

function status(message, isError) {
  const element = $('status');
  element.textContent = message;
  element.className = isError ? 'error' : '';
}

/* Patches come from patches/ next to the page, which is the only way a
 * static page can read them: github.com serves release downloads without
 * CORS headers, so fetching an asset URL from this origin is blocked by the
 * browser. .github/workflows/pages.yml mirrors the latest release into that
 * directory, so the public site serves the files itself. */

async function loadPatches() {
  // always revalidated, so checkRelease compares the page against the
  // release the site serves now, not a copy the browser kept
  const response = await fetch(PATCHES + 'manifest.tsv', {cache: 'no-cache'});
  if (!response.ok) {
    throw new Error(`no ${PATCHES}manifest.tsv (${response.status}) - copy the`
        + ' release files from dist/patches/ into webpatcher/patches/');
  }
  return {manifestText: await response.text()};
}

/* The release is a few MB and the base layer is used for every disc, so
 * each fetched layer is kept for this visit, and the base starts loading as
 * soon as the page does. A layer is already gzip; the worker checks its
 * SHA-1 against the manifest. */
const layerCache = new Map();  // name -> Promise<Blob>

function loadLayer(name) {
  let file = layerCache.get(name);
  if (!file) {
    // the manifest's hash in the URL: a new release never gets an old
    // cached copy of a layer that kept its name
    const row = state.rows.find(item => item.layer === name);
    const checksum = row && row.sha1;
    const version = checksum ? `?sha=${checksum.slice(0, 16)}` : '';
    file = fetch(PATCHES + name + version).then(response => {
      if (!response.ok) throw new Error(`cannot load ${name} (${response.status})`);
      return response.blob();
    }).catch(err => {
      layerCache.delete(name);  // a later attempt can retry
      throw err;
    });
    layerCache.set(name, file);
  }
  return file;
}

function prefetchBase() {
  const base = baseRow();
  if (base) loadLayer(base.layer).catch(() => {});  // a run reports the error
}

async function loadManifest() {
  const source = await loadPatches();
  const rows = rowsFrom(source.manifestText);
  checkRelease(rows);          // before anything is kept: no buttons for a mismatch
  if (!rows.some(row => row.kind === 'base')) throw new Error('the release has no base layer');
  state.rows = rows;
  state.labels = rows.filter(row => row.kind === 'option').map(row => row.label);
  state.ranges = {};
  await Promise.all(rows.filter(row => (FEATURES[renamed(row.label)]?.ranges || []).length)
    .map(async row => {
      const file = await loadLayer(row.layer);
      const head = layerHeader(new TextDecoder().decode(await file.slice(0, 65536).arrayBuffer()));
      state.ranges[row.label] = head.ranges;
    }));
}

/* The page and its patches must be one release. The deployed page carries
 * its release in <html data-release> (stamped with the title by
 * tools/stamp_webpatcher.py); the manifest names it in its release column.
 * A browser that kept an old copy of the page refreshes the site once on
 * its own (refreshSite); if the pair still differs after that, it is told
 * so instead of patching with a mismatched pair. An unstamped (local) page
 * or manifest has nothing to compare. */
const REFRESHED_KEY = 'patcher.refreshed';

function checkRelease(rows) {
  const page = document.documentElement.dataset.release || '';
  const patches = releaseStamp(rows);
  if (!page || page.startsWith('$') || page === 'local' || !patches || page === patches) return;
  let tried = null;
  try { tried = sessionStorage.getItem(REFRESHED_KEY); } catch (err) {}
  if (tried !== patches) {
    try { sessionStorage.setItem(REFRESHED_KEY, patches); } catch (err) {}
    refreshSite();
    throw new Error(`Updating the page to ${patches}...`);
  }
  throw new Error(`This page (${page}) and its patches (${patches}) are from different`
      + ' releases - your browser kept an old copy. Press "Reload the patcher" below'
      + ' (or clear this site\'s cache) before patching.');
}

/* A browser's own reload may answer from its cache, and a phone has no
 * hard reload. This fetches the page and every script it and its workers
 * load past the cache, which stores the fresh copies, then opens the page
 * under a one-off query so the document itself cannot come from the cache
 * either; init drops the query again. */
const WORKER_SCRIPTS = ['worker.js', 'chdblocks.js', 'modpack.js', 'ppf.js', 'lzma.js',
                        'inflate.js', 'chd.js'];
const FRESH_PARAM = 'fresh';

async function refreshSite() {
  status('reloading the patcher...');
  const page = new URL(location.href);
  page.searchParams.delete(FRESH_PARAM);
  const files = new Set([page.href, ...[...document.scripts].map(script => script.src)
    .filter(Boolean), ...WORKER_SCRIPTS.map(name => new URL(name, page).href)]);
  await Promise.all([...files].map(url => fetch(url, {cache: 'reload'}).catch(() => {})));
  page.searchParams.set(FRESH_PARAM, Date.now().toString(36));
  location.replace(page.href);
}

function dropFreshParam() {
  const page = new URL(location.href);
  if (!page.searchParams.has(FRESH_PARAM)) return;
  page.searchParams.delete(FRESH_PARAM);
  history.replaceState(history.state, '', page.href);
}

const featureOf = label => {
  const feature = FEATURES[renamed(label)] || {name: label, description: ''};
  if (!Object.hasOwn(state.ranges, label)) return feature;
  // the layer's own bounds; which range follows which is the page's (features.js)
  const ranges = state.ranges[label].map(range => ({
    ...(feature.ranges || []).find(known => known.key === range.key), ...range}));
  return {...feature, ranges};
};
const displayName = label => featureOf(label).name;

/* Each mod's choices in the manifest: its tokens, each option group's
 * first being its default. */
const choicesOf = label => ((state.rows.find(row => row.label === label) || {}).choices || '')
    .split(',').filter(Boolean);

function defaultTokens(label) {
  const first = new Map();
  for (const token of choicesOf(label)) {
    if (token.includes('=') && !first.has(token.split('=')[0])) first.set(token.split('=')[0], token);
  }
  return [...first.values(), ...(featureOf(label).ranges || []).map(r => `${r.key}=${r.default}`)];
}

/* The tokens picked under a mod's entry (its radios, toggles and extra
 * boxes). A toggle names its group either way: `GROUP=on` or `GROUP=off`. */
function pickedTokens(label) {
  const sub = `.sub-choices[data-label="${label}"]`;
  const inputs = [...document.querySelectorAll(`${sub} input:checked:not([data-toggle])`)];
  const toggles = [...document.querySelectorAll(`${sub} input[data-toggle]`)];
  const ranges = [...document.querySelectorAll(`${sub} input[data-parameter]`)];
  const tokens = [...inputs.map(input => input.value),
                  ...toggles.map(input => `${input.dataset.toggle}=${input.checked ? 'on' : 'off'}`),
                  ...ranges.map(input => `${input.dataset.parameter}=${input.value}`)];
  return tokens.length ? tokens : defaultTokens(label);
}

/* The selection as a build names it: every ticked mod in the manifest's
 * order, `slug(tokens)` where its choices are not its defaults; the base
 * only when its choices are not the defaults. These strings are
 * what the PPF note, the history and the output name carry. */
function selectedLabels() {
  const picked = new Set([...document.querySelectorAll('#choices input.mod:checked')]
      .map(box => box.value));
  const item = label => {
    const tokens = pickedTokens(label);
    const plain = defaultTokens(label);
    const same = tokens.length === plain.length && tokens.every(t => plain.includes(t));
    return same ? label : `${label}(${tokens.join(',')})`;
  };
  const base = baseRow() ? item(baseRow().label) : '';
  return [...(base && base !== baseRow().label ? [base] : []),
          ...state.labels.filter(label => picked.has(label)).map(item)];
}

/* {label: tokens} for a selection's strings, every layer it applies at its
 * defaults unless named (MODPACK.selected). */
function selectionOf(items) {
  const out = {};
  if (baseRow()) out[baseRow().label] = defaultTokens(baseRow().label);
  for (const [label, tokens] of MODPACK.parseMods(items.join(','))) {
    out[label] = tokens.length ? tokens : defaultTokens(label);
  }
  return out;
}

/* The layers for a selection: base, then the selected alphabet, translation and mods
 * in the manifest's order. Which parts of each apply - an option, what one
 * mod carries for another - the worker picks from the selection. */
function planLayers(items = selectedLabels()) {
  const base = baseRow();
  if (base && modBox(base.label) && !isOn(base.label)) {
    throw new Error(`${displayName(base.label)} is off: every layer of this release is`
        + ' built on top of it, so there is no disc without it');
  }
  const selection = selectionOf(items);
  const rows = [baseRow(), ...state.rows.filter(row => row.kind === 'option'
                                                && row.label in selection)];
  for (const row of rows) {
    for (const need of requirementsOf(row)) {
      if (!(need in selection)) {
        throw new Error(`${displayName(row.label)} needs ${displayName(need)}, which this`
            + ' selection leaves out');
      }
    }
  }
  return {layers: rows.map(row => ({name: row.layer, hash: row.sha1})), selection};
}

/* `ppf` set: the worker builds a PPF instead of a disc. */
async function apply(source, ppf, ppfDescription, labels = selectedLabels(), target = null) {
  const layers = [];
  const plan = planLayers(labels);
  for (const layer of plan.layers) {
    status(`Fetching ${layer.name}`);
    layers.push({...layer, file: await loadLayer(layer.name)});
  }
  for (const mod of state.ownMods.filter(mod => mod.on)) {
    for (const need of mod.requires) {
      if (!(need in plan.selection) && !state.ownMods.some(o => o.on && o.name === need)) {
        throw new Error(`${mod.title || mod.name} needs ${displayName(need)}, which this`
            + ' selection leaves out');
      }
    }
    layers.push({name: mod.file, file: mod.blob, hash: null, own: true});
  }
  status('working...');
  const worker = new Worker('worker.js');
  try {
    return await new Promise((resolve, reject) => {
      worker.onmessage = event => {
        const msg = event.data;
        if (msg.type === 'progress') status(msg.message + '...');
        else if (msg.type === 'done') resolve({blob: msg.blob, stored: !!msg.stored});
        else if (msg.type === 'ppf-done') resolve({ppf: msg.ppf});
        else if (msg.type === 'error') reject(new Error(msg.message));
      };
      worker.onerror = event => {
        reject(new Error(event.message || 'patch worker failed to start'));
      };
      worker.postMessage({type: 'run', output: ppf ? 'ppf' : 'disc', source, layers,
                          selection: plan.selection,
                          chd: isChd(source), keepChd: $('keep-chd').checked,
                          lowRam: $('low-ram').checked, target,
                          description: ppfDescription});
    });
  } finally {
    worker.terminate();
  }
}

function outputBase(labels) {
  const stamp = releaseStamp(state.rows);
  // `english-translation(font=small)` names the file as english-small
  const named = labels.map(item => item.replace(/\((.*)\)$/, (_all, tokens) =>
      '-' + tokens.split(',').map(token => token.split('=').pop()).join('-')));
  return [OUTPUT_NAME, ...(stamp ? [stamp] : []), ...named].join('-');
}

function downloadLink(url, name, isDisc) {
  const p = document.createElement('p');
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.textContent = name;
  if (isDisc) {
    anchor.addEventListener('click', () => { resultDownloaded = true; });
  }
  p.appendChild(anchor);
  return p;
}

/* Object URLs keep their Blob alive until revoked. Revoke the previous
 * run's result when the new one replaces it, so patching a second disc does
 * not keep the first result alive. */
let resultUrls = [];
let resultDownloaded = false;

/* An emulator finds a PPF by the disc's own file name, so the PPF is named
 * after the disc it patches; which release and options it holds goes in
 * its description field and in the manifest beside it. */
const stem = name => name.replace(/\.[^./\\]*$/, '');

/* What a result holds, written beside it (the PPF's note, the disc's cue):
 * the release, then every layer it applies, one per line, with every one
 * of its settings - defaults too, so the note still says what was built
 * when a later release changes a default - then each mod of your own as
 * `own <file>`. A local release has no stamp yet; its first line says so,
 * so the first line is always the release and never an option. */
const UNSTAMPED = 'unstamped';

function settingLines(labels) {
  return [...Object.entries(selectionOf(labels)).map(([label, tokens]) =>
              (tokens.length ? `${label}(${tokens.join(',')})` : label)),
          ...state.ownMods.filter(mod => mod.on).map(mod => `own ${mod.file}`)];
}

function ppfNote(info) {
  const lines = [releaseStamp(state.rows) || UNSTAMPED, ...settingLines(info.labels)];
  return new Blob([lines.join('\n') + '\n'], {type: 'text/plain'});
}

/* The same lines as REM comments at the top of the cue, which emulators
 * skip. */
function cueText(discName, labels) {
  const rems = [`REM PATCHER https://ayla6.github.io/megami-ibunroku-persona-translation/`,
                `REM VERSION ${releaseStamp(state.rows) || UNSTAMPED}`,
                ...settingLines(labels).map(line => `REM MOD ${line}`)];
  return rems.join('\n') + `\nFILE "${discName.replace(/"/g, '')}" BINARY\n` + CUE_BODY;
}

/* `done.blob` is the patched disc, `<disc> (Modded).bin` with its cue;
 * `done.ppf` the PPF, named after the disc it patches, with a note of what
 * it holds. */
function showResult(done, info) {
  const files = [];   // [blob, name]
  if (done.ppf) {
    const ppfName = stem(info.sourceName) + '.ppf';
    files.push([done.ppf, ppfName]);
    files.push([ppfNote(info), ppfName + '.txt']);
  } else {
    // the release and the settings are in its cue: the name stays the disc's
    files.push([done.blob, stem(info.sourceName) + ' (Modded).bin']);
  }
  const disc = files.find(([, name]) => name.endsWith('.bin'));
  if (disc) {
    files.push([new Blob([cueText(disc[1], info.labels)], {type: 'application/octet-stream'}),
                stem(disc[1]) + '.cue']);
  }

  for (const url of resultUrls) URL.revokeObjectURL(url);
  resultDownloaded = false;
  resultUrls = [];
  const entry = {at: new Date().toISOString(),
                 release: releaseStamp(state.rows),
                 options: info.labels, kind: done.ppf ? 'ppf' : 'disc',
                 source: 'Rev 0', file: files[0][1]};
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
  status('Here it is :D');
}

/* A PPF this patcher wrote: PPF 3.0 whose description (bytes 6..56) is a
 * release name, which always starts with OUTPUT_NAME. */
function ownPpf(head) {
  const magic = String.fromCharCode(...head.subarray(0, 5));
  const description = String.fromCharCode(...head.subarray(6, 56));
  return magic === 'PPF30' && description.startsWith(OUTPUT_NAME + '-');
}

/* Build PPF with a disc from the disc folder (Chrome, Edge): the PPF and
 * its note are written next to the disc - nothing to download. A PPF this
 * patcher did not write is never overwritten, and one that already holds
 * this release and these options is left alone. */
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


async function writeInFolder(folder, files) {
  for (const [blob, name] of files) {
    status(`Saving ${name}`);
    const writable = await (await folder.getFileHandle(name, {create: true})).createWritable();
    await writable.write(blob);
    await writable.close();
  }
}

async function ppfIntoFolder(labels) {
  const folder = await writableFolder();
  const source = state.source;
  const discName = source.name;
  const ppfName = stem(discName) + '.ppf';
  const noteName = ppfName + '.txt';
  const existing = await fileIn(folder, ppfName);
  if (existing && !ownPpf(new Uint8Array(await existing.slice(0, 56).arrayBuffer()))) {
    throw new Error(`${ppfName} in ${folder.name} is not a Persona translation PPF;`
        + ' it was left alone');
  }
  const stamp = releaseStamp(state.rows);
  const note = await fileIn(folder, noteName);
  if (note && existing && stamp) {
    // the first line is the release; options follow, one per line
    const [first = '', ...rest] = (await note.text()).split(/\r?\n/);
    if (first.trim() === stamp
        && sameOptions(settingLines(labels), rest.map(line => line.trim()).filter(Boolean))) {
      $('results').replaceChildren();
      status(`${ppfName} is already ${stamp} with these options`);
      return;
    }
  }
  const done = await apply(source, true, outputBase(labels), labels);
  await writeInFolder(folder, [[done.ppf, ppfName], [ppfNote({labels}), noteName]]);
  rememberPpfDisc(discName);       // the disc chosen from now on
  addHistory({at: new Date().toISOString(), release: stamp, options: labels,
              kind: 'ppf', source: 'Rev 0', file: ppfName});
  $('results').replaceChildren();
  status(`The PPF was placed alongside the selected disc (${discName}).`);
}

/* Build disc with a disc from the disc folder: `<disc> (Modded).bin` and its
 * cue are written next to it by the worker as it goes, so the disc is never
 * held in memory or in browser storage, and nothing is downloaded. */
async function discIntoFolder(labels) {
  const folder = await writableFolder();
  const discName = state.source.name;
  const name = stem(discName) + ' (Modded).bin';
  if (isChd(state.source)) throw new Error('Build disc needs the .bin, not a CHD');
  const target = await folder.getFileHandle(name, {create: true});
  try {
    await apply(state.source, false, outputBase(labels), labels, target);
  } catch (err) {
    // a disc that did not finish is not left looking like one
    await folder.removeEntry(name).catch(() => {});
    throw err;
  }
  await writeInFolder(folder, [[new Blob([cueText(name, labels)]), stem(name) + '.cue']]);
  addHistory({at: new Date().toISOString(), release: releaseStamp(state.rows), options: labels,
              kind: 'disc', source: 'Rev 0', file: name});
  $('results').replaceChildren();
  status(`${name} was placed alongside the selected disc (${discName}).`);
}

/* The disc folder (Chrome, Edge). Picked once and kept as a handle in
 * IndexedDB, so a later visit only re-confirms write permission (one click
 * on the browser's prompt) instead of picking again; Change folder picks a
 * different one. Blocked storage just means picking every time. */
const FOLDER_STORE = 'handles';
const FOLDER_KEY = 'ppf-folder';
const MOD_STORE = 'mods';

function folderDb(mode, use, storeName = FOLDER_STORE) {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open('patcher', 2);
    open.onupgradeneeded = () => {
      for (const name of [FOLDER_STORE, MOD_STORE]) {
        if (!open.result.objectStoreNames.contains(name)) open.result.createObjectStore(name);
      }
    };
    open.onerror = () => reject(open.error);
    open.onsuccess = () => {
      const db = open.result;
      const request = use(db.transaction(storeName, mode).objectStore(storeName));
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
  delete $('change-folder').dataset.allow;
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

function folderNeedsPermission(folder) {
  showFolder(folder);
  $('folder-name').textContent = `${folder.name} (permission required)`;
  $('change-folder').textContent = 'Allow access';
  $('change-folder').dataset.allow = '1';
  $('folder-discs').hidden = false;
  $('folder-discs').textContent = `Click Allow access to use ${folder.name} again.`;
}

/* The browser may drop the permission while the page stays open: checked
 * whenever the page is shown again, so the folder shows Allow access. A
 * permission prompt needs a click, and only Allow access and the build
 * buttons ask for it. */
async function recheckFolder() {
  const folder = state.folder;
  if (!folder || $('change-folder').dataset.allow || state.running) return;
  try {
    if (await folder.queryPermission({mode: 'readwrite'}) !== 'granted') folderNeedsPermission(folder);
  } catch (err) { /* the folder is gone: the next build says so */ }
}

/* The disc folder (Chrome, Edge) comes first: the page lists the Megami
 * Ibunroku Persona discs in it - a .bin by its size, a .chd by the raw
 * SHA-1 in its 124-byte header, so other games never show up - and picks
 * the one used last. A PPF built from a disc chosen here is saved next to
 * it at once. */
async function discsIn(folder) {
  const base = baseRow();
  const sizes = new Map([[Number(base.source_bytes), 0]]);
  const hashes = new Map(base.source_chd_sha1 ? [[base.source_chd_sha1, 0]] : []);
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
    item.textContent = file.name + (revOf.has(file.name) ? ' - Rev 0' : '');
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
    if (err.name === 'NotAllowedError' || err.name === 'SecurityError') {
      folderNeedsPermission(folder);
      return;
    }
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
  folderNeedsPermission(folder);
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
  const stamp = releaseStamp(state.rows);
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
        ? item.options.map(describeItem).join(', ')
        : 'no options';
    row.textContent = `${date} - ${item.release || 'unstamped release'} - `
        + `${item.kind === 'ppf' ? 'PPF' : 'disc'} from ${item.source || '?'}`
        + ` - ${options} (${item.file})`;
    return row;
  }));
}

/* Ask before leaving while there is something to lose: a patch run still in
 * flight, a finished disc that has not been downloaded, or an OPFS copy that
 * the user may still want to delete. The browser shows its own wording. */
window.addEventListener('beforeunload', event => {
  const pending = state.running || (resultUrls.length && !resultDownloaded);
  if (!pending) return;
  event.preventDefault();
  event.returnValue = '';
});

/* A selection string for people: the mod's name, then its picked choices'
 * names (`English translation (Small font)`). */
function describeItem(item) {
  const [[shortLabel, tokens] = [item, []]] = MODPACK.parseMods(item);
  const label = renamed(shortLabel);
  const named = (featureOf(label).choices || []);
  const parts = tokens.map(token => (named.find(c => c.token === token) || {name: token}).name);
  return displayName(label) + (parts.length ? ` (${parts.join(', ')})` : '');
}

const SAVED_KEY = 'patcher.selected';

/* Remembered: the ticked mods and every mod's picked tokens. */
function saveSelection() {
  try {
    // needed mods follow from the ticked ones, so only those are kept
    const checked = [...document.querySelectorAll('#choices input.mod:checked')]
        .filter(box => !box.dataset.auto).map(box => box.value);
    const choices = {};
    for (const sub of document.querySelectorAll('.sub-choices')) {
      choices[sub.dataset.label] = pickedTokens(sub.dataset.label);
    }
    localStorage.setItem(SAVED_KEY, JSON.stringify({mods: checked, choices, layers: 3}));
  } catch (err) { /* storage blocked: the choice just isn't remembered */ }
}

const sameOptions = (a, b) => a.length === b.length && a.every(label => b.includes(label));

/* Tick the options remembered from the last patch run; labels that no
 * longer exist are ignored. With nothing remembered, the options marked
 * `default` in their mod.tsv start ticked, each at its default choices. */
function restoreSelection() {
  let saved = null;
  try {
    const raw = localStorage.getItem(SAVED_KEY);
    saved = raw === null ? null : JSON.parse(raw);
  } catch (err) { /* storage blocked: the defaults apply */ }
  if (Array.isArray(saved)) saved = {mods: saved, choices: {}};   // before choices
  if (saved && saved.layers !== 3 && baseRow()?.label === 'base') {
    saved.mods = [...(saved.mods || []), 'english-translation'];
  }
  if (saved) {
    saved = {mods: (saved.mods || []).map(renamed),
             choices: Object.fromEntries(Object.entries(saved.choices || {})
                 .map(([label, tokens]) => [renamed(label), tokens]))};
  }
  for (const box of document.querySelectorAll('#choices input.mod')) {
    box.checked = saved ? saved.mods.includes(box.value) : !!featureOf(box.value).default;
  }
  for (const sub of document.querySelectorAll('.sub-choices')) {
    const label = sub.dataset.label;
    const remembered = saved && saved.choices && saved.choices[label];
    const want = new Set(remembered && remembered.length ? remembered : defaultTokens(label));
    const inputs = [...sub.querySelectorAll('input')];
    for (const input of inputs) input.checked = want.has(input.value);
    for (const input of inputs.filter(i => i.dataset.parameter)) {
      // a remembered value that is no number (an option this range replaced,
      // such as `entry=off`) is not this range's: it keeps its default
      const token = [...want].find(t => t.startsWith(input.dataset.parameter + '=')
                                       && /^\d+$/.test(t.split('=')[1]));
      if (token) { input.value = token.split('=')[1]; input.dispatchEvent(new Event('change')); }
    }
    // a remembered option that no longer exists: its group falls back to its default
    for (const group of new Set(inputs.filter(i => i.type === 'radio').map(i => i.name))) {
      const radios = inputs.filter(i => i.name === group);
      if (!radios.some(i => i.checked)) radios[0].checked = true;
    }
  }
  followRequirements(null);
}

/* A mod's choices under it: a radio per option of each group, one toggle
 * for a group that is exactly `on` / `off` (named after its `on` choice), a
 * box per extra, named from features.js (the manifest's tokens decide which
 * exist). */
function subChoices(label) {
  const ranges = featureOf(label).ranges || [];
  const tokens = choicesOf(label).filter(t => !ranges.some(r => t.startsWith(r.key + '=')));
  if (!tokens.length && !ranges.length) return null;
  const named = featureOf(label).choices || [];
  const box = document.createElement('div');
  box.className = 'sub-choices';
  box.dataset.label = label;
  for (const setting of ranges) {
    const item = document.createElement('label');
    const title = document.createElement('span');
    title.textContent = setting.name;
    const slider = document.createElement('input');
    slider.type = 'range';
    const number = document.createElement('input');
    number.type = 'number';
    number.dataset.parameter = setting.key;
    number.id = `${label}-${setting.key}-number`;
    number.name = `${label}:${setting.key}`;
    slider.id = `${label}-${setting.key}-slider`;
    slider.name = `${label}:${setting.key}:slider`;
    for (const input of [slider, number]) {
      input.min = setting.minimum; input.max = setting.maximum; input.step = setting.step;
      input.value = setting.default;
      input.setAttribute('aria-label', setting.name);
      input.addEventListener('change', () => {
        const parsed = Number(input.value);
        const value = Number.isFinite(parsed) ? Math.min(setting.maximum, Math.max(setting.minimum,
          setting.minimum + Math.round((parsed - setting.minimum) / setting.step) * setting.step)) : setting.default;
        number.value = slider.value = value;
      });
    }
    slider.addEventListener('input', () => { number.value = slider.value; });
    item.append(title, slider, number);
    box.append(item);
  }
  followRanges(box, label, ranges);
  const groupOf = token => token.includes('=') ? token.split('=')[0] : '';
  const isToggle = group => {
    const keys = tokens.filter(t => groupOf(t) === group).map(t => t.split('=')[1]).sort();
    return group && keys.length === 2 && keys[0] === 'off' && keys[1] === 'on';
  };
  const shownGroup = new Set();
  for (const token of tokens) {
    const info = named.find(c => c.token === token) || {token, name: token, description: '',
                                                        group: groupOf(token)};
    const toggle = isToggle(info.group);
    if (toggle && token !== `${info.group}=on`) continue;   // the toggle is its `on` choice
    if (info.group && !toggle && !shownGroup.has(info.group)) {
      shownGroup.add(info.group);
      const head = document.createElement('p');
      head.className = 'group';
      head.textContent = info.group.replace(/-/g, ' ');
      box.append(head);
    }
    const item = document.createElement('label');
    const input = document.createElement('input');
    input.type = info.group && !toggle ? 'radio' : 'checkbox';
    if (info.group) input.name = `${label}:${info.group}`;
    if (toggle) input.dataset.toggle = info.group;
    input.value = token;
    const text = document.createElement('span');
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
    item.append(input, text);
    box.append(item);
  }
  return box;
}

/* A range that follows another (features.js `follows`) moves with it while
 * the two are equal; one set to a value of its own keeps it, until it is set
 * back to the other's. Saved choices restore in order, the followed range
 * first, so a saved value of its own comes back as it was. */
function followRanges(box, label, ranges) {
  const field = (key, kind) => box.querySelector(`#${label}-${key}-${kind}`);
  for (const leader of ranges) {
    const followers = ranges.filter(range => range.follows === leader.key);
    if (!followers.length) continue;
    let previous = Number(field(leader.key, 'number').value);
    const follow = () => {
      const value = Number(field(leader.key, 'number').value);
      for (const range of followers) {
        const number = field(range.key, 'number');
        if (Number(number.value) !== previous) continue;
        const near = Math.min(range.maximum, Math.max(range.minimum, value));
        number.value = field(range.key, 'slider').value = range.minimum
            + Math.round((near - range.minimum) / range.step) * range.step;
      }
      previous = value;
    };
    field(leader.key, 'slider').addEventListener('input', follow);
    field(leader.key, 'slider').addEventListener('change', follow);
    field(leader.key, 'number').addEventListener('change', follow);
  }
}

/* Mods: one toggle each, the translation first (on, with its warning when
 * turned off). Settings: a card per mod that is on and has choices; a card is built once and hidden while its mod is off. */
function renderGrid() {
  // Foundation components follow dependency order; ordinary mods follow
  // FEATURES order, with unlisted mods last.
  const components = state.rows.filter(row => state.labels.includes(row.label)
      && featureOf(row.label).always).map(row => row.label);
  const shown = [...components,
                ...Object.keys(FEATURES).filter(label => state.labels.includes(label)
                    && !components.includes(label)),
                ...state.labels.filter(label => !FEATURES[label] && !components.includes(label))];
  const chip = (label, className) => {
    const info = featureOf(label);
    const item = document.createElement('label');
    item.className = 'chip';
    const description = [info.description, info.author ? `Author: ${info.author}` : ''].filter(Boolean).join('\n');
    if (description) item.title = description;
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.className = className;
    box.value = label;
    item.append(box, info.name);
    if (!description) return item;
    // phones have no hover: the info button shows the description under the toggles
    const about = document.createElement('button');
    about.type = 'button';
    about.className = 'info';
    about.textContent = 'i';
    about.setAttribute('aria-label', `About ${info.name}`);
    about.addEventListener('click', event => {
      event.preventDefault();          // inside the label: never toggles the mod
      const shown = $('chip-about');
      const same = !shown.hidden && shown.dataset.label === label;
      shown.hidden = same;
      shown.dataset.label = label;
      shown.textContent = `${info.name}: ${description}`;
      for (const integration of info.integrates || []) {
        const note = document.createElement('p');
        note.textContent = `Dependency: ${describeItem(integration.with)}. ${integration.text}`;
        if (!itemOn(integration.with)) {
          const enable = document.createElement('button');
          enable.type = 'button';
          enable.textContent = 'Enable';
          enable.addEventListener('click', () => {
            enableItem(integration.with);
            enable.remove();
          });
          note.append(' ', enable);
        }
        shown.append(note);
      }
    });
    const wrap = document.createElement('span');
    wrap.className = 'chip-wrap';
    wrap.append(item, about);
    return wrap;
  };
  const base = baseRow();
  const baseChip = base && chip(base.label, 'base');
  if (baseChip) {
    (baseChip.querySelector('.chip') || baseChip).classList.add('must');
    baseChip.querySelector('input').checked = true;
    baseChip.querySelector('input').disabled = true;
  }
  $('choices').replaceChildren(...(baseChip ? [baseChip] : []),
                               ...shown.map(label => chip(label, 'mod')));
  $('settings').replaceChildren(...[...(base ? [base.label] : []), ...shown]
      .map(settingCard).filter(Boolean));
  restoreSelection();
  $('choices').onchange = event => {
    if (event.target.classList.contains('base')) refreshSettings();
    else followRequirements(event.target);
  };
  $('settings').onchange = () => refreshSettings();
  $('choices-box').hidden = false;
}

/* Settings cards contain the mod's choices. Dependency notes live in its info panel. */
function settingCard(label) {
  const info = featureOf(label);
  const sub = subChoices(label);
  if (!sub) return null;
  const card = document.createElement('div');
  card.className = 'setting';
  card.dataset.label = label;
  const title = document.createElement('h3');
  title.textContent = info.name;
  card.append(title);
  if (sub) card.append(sub);
  return card;
}

const modBox = label => document.querySelector(`#choices input[value="${label}"]`);
const isOn = label => !!(modBox(label) && modBox(label).checked);

/* `slug` or `slug(token,...)` already on. */
function itemOn(item) {
  const [[label, tokens] = [item, []]] = MODPACK.parseMods(item);
  return isOn(label) && tokens.every(token => pickedTokens(label).includes(token));
}

function enableItem(item) {
  const [[label, tokens] = [item, []]] = MODPACK.parseMods(item);
  const box = modBox(label);
  if (!box) return;
  box.checked = true;
  for (const token of tokens) {
    const input = document.querySelector(
        `.sub-choices[data-label="${label}"] input[value="${token}"]`);
    const toggle = document.querySelector(
        `.sub-choices[data-label="${label}"] input[data-toggle="${token.split('=')[0]}"]`);
    if (input) input.checked = true;
    else if (toggle) toggle.checked = token.endsWith('=on');
  }
  followRequirements(box);
}

function refreshSettings() {
  for (const card of document.querySelectorAll('#settings .setting')) {
    card.hidden = !isOn(card.dataset.label);
  }
  $('settings-box').hidden = ![...document.querySelectorAll('#settings .setting')]
      .some(card => !card.hidden);
  const warnings = state.rows.filter(row => !isOn(row.label) && featureOf(row.label).warning)
      .map(row => featureOf(row.label).warning);
  const base = baseRow();
  if (base && !isOn(base.label) && !featureOf(base.label).warning) {
    warnings.unshift(`${displayName(base.label)} cannot be turned off.`);
  }
  $('base-warning').hidden = !warnings.length;
  $('base-warning').textContent = warnings.join(' ');

}

/* Identifying the disc does not disable Apply: a click waits for that run
 * to finish. */
/* Build disc cannot take a CHD: the result is the player's .bin with the
 * changed sectors in between, and a CHD would have to be unpacked whole. The button stays clickable (a disabled
 * one gets no hover or click) but looks unavailable, and both hovering and
 * clicking say why. */
const CHD_DISC_WARNING = "Build disc can't use a CHD: it would have to unpack the"
    + ' whole disc. Use Build PPF with the CHD, or pick the .bin to build a disc.';

function refreshApply() {
  const disabled = state.running || !state.source || !state.rows.length;
  const chd = !disabled && isChd(state.source);
  $('apply').disabled = disabled;
  $('apply').classList.toggle('unavailable', chd);
  $('apply').setAttribute('aria-disabled', chd);
  $('apply').title = chd ? CHD_DISC_WARNING : '';
  $('build-ppf').disabled = disabled;
}

const isChd = file => !!file && /\.chd$/i.test(file.name);

/* Which disc this is, from what the manifest records about the original:
 * a .bin by its size, a CHD by the raw SHA-1 in its header. The base layer
 * checks every file it changes when a run applies it, so a dump of the
 * right size with the wrong contents is refused there. */
async function identify(source) {
  const base = baseRow();
  if (isChd(source)) {
    const sha1 = await CHD.headerSha1(async (offset, length) =>
        new Uint8Array(await source.slice(offset, offset + length).arrayBuffer()));
    if (!base.source_chd_sha1 || sha1 === base.source_chd_sha1) return {rev: 0};
    throw new Error("this CHD's disc is not the original Megami Ibunroku Persona"
        + ' Rev 0 - it may be Rev 1, or a different or modified dump');
  }
  if (source.size === Number(base.source_bytes)) return {rev: 0};
  if (source.size === REV1_BYTES) {
    throw new Error('this is the Rev 1 disc; the patch needs the Rev 0 disc'
        + ' (the first release of SLPS-00500)');
  }
  throw new Error(`the selected file is ${source.size.toLocaleString()} bytes but the`
      + ` original disc is ${Number(base.source_bytes).toLocaleString()} bytes - select`
      + ' the Rev 0 .bin image, not the .cue');
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
        status('Rev 0 disc detected');
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
    localStorage.setItem(MEMORY_KEY, JSON.stringify({keepChd: $('keep-chd').checked,
                                                     lowRam: $('low-ram').checked}));
  } catch (err) { /* storage blocked: the box just isn't remembered */ }
}

function lowMemoryHint() {
  const data = navigator.userAgentData;
  if ((data && data.platform === 'Android') || /Android/i.test(navigator.userAgent || '')) {
    return 'this is an Android device';
  }
  return null;
}

/* The disc low-RAM mode wrote (worker.js, OUTPUT_DIR): one at a time, gone
 * when the page opens again. */
async function dropStoredDisc() {
  try {
    await (await navigator.storage.getDirectory()).removeEntry('patcher-output', {recursive: true});
  } catch (err) { /* nothing stored, or no OPFS */ }
}

/* The CHD parts the worker keeps (worker.js, PART_DB) - the whole store. */
function dropChdParts() {
  try { indexedDB.deleteDatabase('patcher-chd'); } catch (err) {}
}

/* Your own mods: .p1mod layers loaded from a file, kept in IndexedDB (the
 * `mods` store, keyed by file name) and applied after the release's mods at
 * their default choices. A layer is built against one release's discs; one
 * whose version row names another release gets a warning, not a refusal
 * (the merge itself refuses a layer that does not fit). Blocked storage
 * keeps a loaded mod for this visit only. */
function layerHeader(text) {
  const head = {name: '', title: '', author: '', version: '', requires: [], ranges: []};
  if (!text.startsWith('P1MOD')) throw new Error('not a .p1mod layer');
  for (const line of text.split('\n').slice(1)) {
    if (line.startsWith('--\t')) break;
    const [kind, value] = line.split('\t');
    if (kind === 'range') {
      const [, , bounds, name] = line.split('\t');
      const [minimum, maximum, step, defaultValue] = bounds.split(',').map(Number);
      head.ranges.push({key: value, minimum, maximum, step, default: defaultValue, name});
    } else if (kind === 'requires') head.requires.push(value);
    else if (kind in head) head[kind] = value;
  }
  if (!head.name) throw new Error('the layer names no mod');
  return head;
}

async function readOwnMod(file, blob, on = true) {
  const head = layerHeader(new TextDecoder().decode(
      new Uint8Array(await blob.slice(0, 65536).arrayBuffer())));
  return {file, blob, on, ...head};
}

async function loadOwnMods() {
  state.ownMods = [];
  try {
    const keys = await folderDb('readonly', store => store.getAllKeys(), MOD_STORE);
    const values = await folderDb('readonly', store => store.getAll(), MOD_STORE);
    for (let i = 0; i < keys.length; i++) {
      try {
        state.ownMods.push(await readOwnMod(keys[i], values[i].blob, values[i].on));
      } catch (err) {
        status(`${keys[i]}: ${err.message}`, true);
      }
    }
  } catch (err) { /* storage blocked: nothing kept */ }
  renderOwnMods();
}

async function keepOwnMod(mod) {
  try {
    await folderDb('readwrite', store => store.put({blob: mod.blob, on: mod.on && !mod.auto}, mod.file),
                   MOD_STORE);
  } catch (err) { /* kept for this visit only */ }
}

async function addOwnMods(files) {
  for (const file of files) {
    try {
      const mod = await readOwnMod(file.name, file);
      if (state.rows.some(row => row.label === mod.name)) {
        throw new Error(`${mod.name} is one of this release's own mods - tick it above`);
      }
      state.ownMods = state.ownMods.filter(other => other.file !== mod.file).concat(mod);
      await keepOwnMod(mod);
    } catch (err) {
      status(`${file.name}: ${err.message}`, true);
    }
  }
  renderOwnMods();
}

async function removeOwnMod(file) {
  state.ownMods = state.ownMods.filter(mod => mod.file !== file);
  try {
    await folderDb('readwrite', store => store.delete(file), MOD_STORE);
  } catch (err) {}
  renderOwnMods();
}

function renderOwnMods() {
  followRequirements(null);
  const release = baseRow() ? baseRow().version : '';
  $('own-mods').replaceChildren(...state.ownMods.map(mod => {
    const item = document.createElement('li');
    const label = document.createElement('label');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = mod.on;
    box.disabled = mod.required;
    box.dataset.mod = mod.name;
    box.addEventListener('change', () => {
      mod.on = box.checked;
      delete mod.auto;
      keepOwnMod(mod);
      followRequirements(null);
    });
    label.append(box, ` ${mod.title || mod.name} (${mod.file})`);
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = 'Remove';
    remove.disabled = mod.required;
    remove.dataset.mod = mod.name;
    remove.addEventListener('click', () => removeOwnMod(mod.file));
    item.append(label, ' ', remove);
    if (mod.author) {
      const credit = document.createElement('p');
      credit.textContent = `Author: ${mod.author}`;
      item.append(credit);
    }
    if (release && mod.version && mod.version !== release) {
      const warn = document.createElement('span');
      warn.className = 'warning';
      warn.textContent = ` made for ${mod.version}, this is ${release} - it may not apply`;
      item.append(warn);
    }
    return item;
  }));
}

window.patcher = {loadManifest, FEATURES, planLayers, apply, selectedLabels, state};  // tests

async function init() {
  dropFreshParam();     // a refreshSite reload leaves the address as it was
  // the storage options are remembered from the first visit: CHD parts start
  // kept, low-RAM mode starts on where memory is likely tight
  dropStoredDisc();
  const memory = savedMemory();
  $('keep-chd').checked = memory ? memory.keepChd !== false : true;
  const hint = lowMemoryHint();
  $('low-ram').checked = memory && 'lowRam' in memory ? !!memory.lowRam : !!hint;
  const note = $('low-ram-note');
  note.hidden = !(hint && $('low-ram').checked && !(memory && 'lowRam' in memory));
  note.textContent = note.hidden ? '' : `Turned on by itself because ${hint}.`;
  $('low-ram').addEventListener('change', () => {
    note.hidden = true;
    saveMemory();
  });
  if (!memory) saveMemory();     // the starting choice, written at once
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
  $('source').addEventListener('change', () => pickedFile($('source').files[0] || null));
  $('clear-history').addEventListener('click', clearHistory);
  $('refresh-site').addEventListener('click', refreshSite);
  $('own-mod-file').addEventListener('change', async () => {
    await addOwnMods([...$('own-mod-file').files]);
    $('own-mod-file').value = '';
  });
  renderHistory();
  $('apply').addEventListener('click', () => run(false));
  $('build-ppf').addEventListener('click', () => run(true));
  if (window.showDirectoryPicker) {
    showFolder(null);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') recheckFolder();
    });
    window.addEventListener('focus', recheckFolder);
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
    if (!ppf && isChd(state.source)) {
      status(CHD_DISC_WARNING, true);
      return;
    }
    saveSelection();
    state.running = true;
    refreshApply();
    try {
      if (state.fromFolder && state.folder) {
        const access = {mode: 'readwrite'};
        let permission = await state.folder.queryPermission(access);
        if (permission !== 'granted') permission = await state.folder.requestPermission(access);
        if (permission !== 'granted') {
          folderNeedsPermission(state.folder);
          throw new Error(`Allow access to ${state.folder.name}, then build again.`);
        }
        delete $('change-folder').dataset.allow;
        showFolder(state.folder);
      }
      // The disc may still be identified (its patch may still be
      // downloading). Wait for that run instead of refusing the click.
      const rev = await ensureRevision();
      if (rev === null) {
        throw new Error(state.identifyError || 'this is not the Rev 0 disc, so it cannot be patched');
      }
      // Name the download from the selection this run applied, not from
      // whatever the boxes say by the time the worker finishes.
      const labels = selectedLabels();
      // a disc from the disc folder: the PPF goes next to it, no downloads
      if (ppf && state.fromFolder && state.folder) return await ppfIntoFolder(labels);
      // and the disc too, written straight into the folder
      if (state.fromFolder && state.folder) return await discIntoFolder(labels);
      const done = await apply(state.source, ppf, outputBase(labels), labels);
      showResult(done, {labels, sourceName: state.source.name});
    } catch (err) {
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
    await loadOwnMods();
    updateBanner();
    if (window.showDirectoryPicker) restoreFolder();
    const pending = unverified(state.rows);
    const readyUntested = pending.length === 1 && pending[0] === 'untested';
    status(readyUntested ? `Hello :D - there are ${state.labels.length} options`
        : pending.length ? `Local test: this release is still ${pending.join('/')}`
        : `Hello :D - there are ${state.labels.length} options`, pending.length > 0 && !readyUntested);
  } catch (err) {
    status(err.message, true);
  }
  refreshApply();
  if (state.source) maybeIdentify();  // picked before the manifest arrived
}

init();
