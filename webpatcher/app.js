'use strict';
/* Persona translation web patcher - page logic.
 *
 * The release output (dist/patches/) is served next to this page as
 * patches/ (manifest.tsv + the .xdelta files): the Pages workflow mirrors
 * it from the latest release, and local testing copies or symlinks it. The
 * manifest drives everything: which options exist, which patch file each
 * combination maps to, and the chain between them. xdelta checksums every
 * step while applying it. Nothing here is hardcoded per release.
 */

const PATCHES = 'patches/';
const RELEASE_REPO = 'ayla6/megami-ibunroku-persona-translation';  // 'owner/repo'; tools/publish_patches.py uploads here too
/* The downloaded image is named from the release, never from the file the
 * user picked (which may be a dump name, a hash, or just wrong). A Rev 1
 * source is converted to Rev 0 on the way in, so the result carries no
 * source-revision suffix. */
const OUTPUT_NAME = 'Persona-TL';
/* Same cue convention as src/injection_tools/build_disc.py. */
const CUE_BODY = '  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n';

/* What each manifest option is called and what it does, keyed by the
 * manifest's `choices` labels. An option with no entry still works; it just
 * shows its internal label. This block is JSON (tools/tests/test_webpatcher
 * reads it to prove every release choice is described), so keep the keys and
 * strings double-quoted. */
const FEATURES = {
  "saves": {
    "name": "Save menu",
    "description": "Merges the slot 1 and slot 2 menus into one, so that you don't have to worry about which one to select. Requires \"speed up on memory card access\" to not feel like a slog."
  },
  "mark": {
    "name": "Black Mark",
    "description": "Makes Masao Inaba black. It uses a custom sprite I made for him so that he's both black and still wears his original outfit. Doesn't change the script."
  },
  "battlespeed": {
    "name": "Battle speedup",
    "description": "Doubles the speed of summons and skill effects in battle."
  },
  "60fps": {
    "name": "60 FPS",
    "description": "Interpolates frames to get the dungeons to 60fps and the map to 30fps. Only does it when you're actively moving around. Needs overclocking."
  },
  "rewards-encounters": {
    "name": "Easy mode",
    "description": "Halves random encounters and doubles EXP, Persona points and money after battles."
  }
};

const BASE_PATCH = 'rev0-to-base.xdelta';
const REV1_PATCH = 'rev1-to-rev0.xdelta';
const REV_LABEL = ['Rev 0', 'Rev 1'];

const $ = id => document.getElementById(id);

const state = {
  rows: [],
  byChoices: new Map(),  // sorted-choice key -> manifest row
  labels: [],            // option labels, in manifest order
  patches: null,         // {manifestText, urlFor}
  source: null,
  rev: null,             // detected revision (0 or 1), null until checked
  identifying: false,
  identifyRun: 0,
  running: false,
};

function status(message, isError) {
  const element = $('status');
  element.textContent = message;
  element.className = isError ? 'error' : '';
}

const choiceKey = row => row.choices.split(',').sort().join(',');
const stepOf = row => ({patch: row.patch,
                        expectBytes: Number(row.target_bytes)});

/* Patches come from patches/ next to the page, which is the only way a
 * static page can read them: github.com serves release downloads without
 * CORS headers, so fetching an asset URL from this origin is blocked by the
 * browser. .github/workflows/pages.yml mirrors the latest release into that
 * directory, so the public site serves the files itself. */

async function loadPatches() {
  const response = await fetch(PATCHES + 'manifest.tsv');
  if (!response.ok) {
    throw new Error(`no ${PATCHES}manifest.tsv (${response.status}) - copy the`
        + ' release files from dist/patches/ into webpatcher/patches/');
  }
  return {manifestText: await response.text(),
          urlFor: name => PATCHES + name};
}

async function loadManifest() {
  const source = await loadPatches();
  state.patches = source;
  const lines = source.manifestText.split('\n').filter(line => line);
  const header = lines.shift().split('\t');
  for (const name of ['patch', 'choices', 'source_bytes', 'source_sha256',
                      'target_bytes', 'target_sha256']) {
    if (!header.includes(name)) throw new Error('unrecognized release manifest');
  }
  state.rows = lines.map(line => {
    const cells = line.split('\t');
    const row = {};
    header.forEach((name, index) => { row[name] = cells[index]; });
    return row;
  });
  if (!state.rows.some(row => row.patch === BASE_PATCH)) {
    throw new Error('release manifest is missing ' + BASE_PATCH);
  }
  state.byChoices.clear();
  state.labels = [];
  const seen = new Set();
  for (const row of state.rows) {
    if (!row.choices) continue;
    state.byChoices.set(choiceKey(row), row);
    for (const label of row.choices.split(',')) {
      if (!seen.has(label)) { seen.add(label); state.labels.push(label); }
    }
  }
}

const featureOf = label => FEATURES[label] || {name: label, description: ''};
const displayName = label => featureOf(label).name;

function selectedRow() {
  const chosen = [...document.querySelectorAll('#choices input:checked')]
      .map(box => box.value).sort();
  if (!chosen.length) return null;
  const row = state.byChoices.get(chosen.join(','));
  if (!row) {
    throw new Error(`this combination of options has no patch in the release`
        + ` manifest (${chosen.map(displayName).join(', ')}) - is the release`
        + ' complete?');
  }
  return row;
}

/* The chain to a combination, derived from the manifest alone: each
 * patch's source_sha256 is the target_sha256 of the one before it, so the
 * path from the base translation to any combination is walkable by those
 * recorded hashes - the builder's layer layout is never hardcoded here.
 * The hashes only identify rows; xdelta does the verification. */
function chainFor(row) {
  const steps = [row];
  while (steps[0].patch !== BASE_PATCH) {
    if (steps.length > state.rows.length) {
      throw new Error('circular patch chain in the release manifest');
    }
    const parent = state.rows.find(
        candidate => candidate.target_sha256 === steps[0].source_sha256);
    if (!parent) {
      throw new Error(`broken patch chain in the release manifest at ${steps[0].patch}`);
    }
    steps.unshift(parent);
  }
  return steps;
}

/* The chain: rev1 -> rev0 if the user has a Rev 1 disc (obligatory), then
 * the manifest's chain from rev0-to-base to the chosen combination. */
function buildPlan(rev) {
  const baseRow = state.rows.find(row => row.patch === BASE_PATCH);
  const revRow = state.rows.find(row => row.patch === REV1_PATCH);
  const variant = selectedRow();
  const steps = [];
  if (rev === 1) {
    if (!revRow) throw new Error('release manifest is missing ' + REV1_PATCH);
    steps.push(stepOf(revRow));
  }
  steps.push(...chainFor(variant || baseRow).map(stepOf));
  const sourceRow = rev === 1 ? revRow : baseRow;
  return {
    steps,
    patchNames: steps.map(step => step.patch),
    sourceExpect: {bytes: Number(sourceRow.source_bytes)},
  };
}

async function apply(source, rev) {
  const plan = buildPlan(rev);
  const patchFiles = [];
  for (const name of plan.patchNames) {
    status(`Fetching ${name}`);
    const response = await fetch(state.patches.urlFor(name));
    if (!response.ok) {
      throw new Error(`cannot load ${name} (${response.status})`);
    }
    patchFiles.push({name, file: new File([await response.blob()], name)});
  }
  status('working...');
  const worker = new Worker('worker.js');
  try {
    return await new Promise((resolve, reject) => {
      worker.onmessage = event => {
        const msg = event.data;
        if (msg.type === 'progress') status(msg.message + '...');
        else if (msg.type === 'done') resolve(msg);
        else if (msg.type === 'error') reject(new Error(msg.message));
      };
      worker.onerror = event => {
        reject(new Error(event.message || 'patch worker failed to start'));
      };
      worker.postMessage({type: 'apply', source, patchFiles,
                          steps: plan.steps, sourceExpect: plan.sourceExpect});
    });
  } finally {
    worker.terminate();
  }
}

function outputBase(labels) {
  return [OUTPUT_NAME, ...labels].join('-');
}

function downloadLink(url, name) {
  const p = document.createElement('p');
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.textContent = name;
  p.appendChild(anchor);
  return p;
}

function showResult(base, done) {
  const binName = base + '.bin';
  const cueName = base + '.cue';
  const cue = `FILE "${binName.replace(/"/g, '')}" BINARY\n` + CUE_BODY;
  $('results').replaceChildren(
      downloadLink(URL.createObjectURL(done.blob), binName),
      downloadLink(URL.createObjectURL(
          new Blob([cue], {type: 'application/octet-stream'})), cueName));
  status(`Here it is :D`);
}

function renderGrid() {
  const grid = $('choices');
  grid.replaceChildren(...state.labels.map(label => {
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
  $('choices-box').hidden = false;
}

function refreshApply() {
  $('apply').disabled = state.running || !state.source
      || state.rev === null || !state.rows.length;
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

async function identify(source) {
  const expect = revisionExpectations();
  /* Only the patch for the candidate with this file's size can apply, so
   * don't download the other revision's patch. */
  for (const entry of expect.filter(entry => entry.bytes === source.size)) {
    status(`Fetching ${entry.patch} to identify the disc`);
    const response = await fetch(state.patches.urlFor(entry.patch));
    if (!response.ok) {
      throw new Error(`Cannot load ${entry.patch} (${response.status})`);
    }
    entry.file = new File([await response.blob()], entry.patch);
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

async function maybeIdentify() {
  if (!state.source || !state.rows.length || state.identifying) return;
  const run = ++state.identifyRun;
  const source = state.source;
  state.identifying = true;
  refreshApply();
  status('identifying the disc...');
  try {
    const found = await identify(source);
    if (run === state.identifyRun) {
      state.rev = found.rev;
      status(`${REV_LABEL[found.rev]} disc detected`);
    }
  } catch (err) {
    if (run === state.identifyRun) status(err.message, true);
  } finally {
    if (run === state.identifyRun) {
      state.identifying = false;
      refreshApply();
    }
  }
}

window.patcher = {loadManifest, FEATURES, buildPlan, apply, selectedRow, state};  // tests

async function init() {
  $('source').addEventListener('change', () => {
    state.source = $('source').files[0] || null;
    state.rev = null;
    status(state.source ? state.source.name : '');
    refreshApply();
    maybeIdentify();
  });
  $('apply').addEventListener('click', async () => {
    if (!state.source || state.rev === null || state.running) return;
    const rev = state.rev;
    state.running = true;
    refreshApply();
    try {
      // Name the download from the selection this run applied, not from
      // whatever the boxes say by the time the worker finishes.
      const row = selectedRow();
      const done = await apply(state.source, rev);
      showResult(outputBase(row ? row.choices.split(',') : []), done);
    } catch (err) {
      status(err.message, true);
    } finally {
      state.running = false;
      refreshApply();
    }
  });
  try {
    await loadManifest();
    renderGrid();
    status(`Patches loaded from ${PATCHES} - ${state.labels.length} options`);
  } catch (err) {
    status(err.message, true);
  }
  refreshApply();
}

init();
