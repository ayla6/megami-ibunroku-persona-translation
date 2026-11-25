'use strict';
/* Anonymous usage counts. No cookies, file names or disc contents. The
 * collector URL comes from the page's patcher-analytics meta (empty in source). */
globalThis.PatcherAnalytics = (() => {
  const endpoint = document.querySelector('meta[name="patcher-analytics"]')?.content || '';
  const toggle = document.getElementById('analytics-enabled');
  const PREFERENCE = 'patcher.analytics.enabled';
  const IDENTITY = 'patcher.analytics.browser';
  const RELEASE = /^(?:patches-)?[0-9]{4}-[0-9]{2}-[0-9]{2}(?:-[0-9]+)?$/;
  const visit = crypto.randomUUID();
  let browser = null;
  let enabled = false;
  let visited = false;
  try {
    enabled = localStorage.getItem(PREFERENCE) !== 'no';
    browser = localStorage.getItem(IDENTITY);
  } catch (_) { /* No storage: report nothing rather than inflate uniques. */ }

  function send(event) {
    if (!enabled || !endpoint) return;
    try {
      if (!browser) localStorage.setItem(IDENTITY, browser = crypto.randomUUID());
      void fetch(endpoint, {
        method: 'POST', mode: 'cors', credentials: 'omit', referrerPolicy: 'no-referrer',
        headers: {'Content-Type': 'text/plain'}, keepalive: true,
        body: JSON.stringify({b: browser, v: visit, ...event}),
      }).catch(() => {});
    } catch (_) { /* Never interrupts a patch. */ }
  }
  function pageView() {
    if (!enabled || !endpoint || visited) return;
    visited = true;
    let r = '';
    try {
      const source = new URL(document.referrer);
      if (['http:', 'https:'].includes(source.protocol)) r = source.origin;
    } catch (_) { /* direct */ }
    send({t: 'visit', r});
  }
  toggle.checked = enabled;
  toggle.addEventListener('change', () => {
    enabled = toggle.checked;
    try {
      localStorage.setItem(PREFERENCE, enabled ? 'yes' : 'no');
      if (!enabled) { localStorage.removeItem(IDENTITY); browser = null; }
    } catch (_) { enabled = false; toggle.checked = false; }
    pageView();
  });
  window.addEventListener('storage', event => {
    if (event.key === PREFERENCE || event.key === null) {
      enabled = event.newValue !== 'no'; // cleared storage = the default, on
      toggle.checked = enabled;
      if (!enabled) browser = null;
    }
  });
  pageView();

  /* The settings of the PPF a build replaces, as {label: 'a=1,b=2'}, from
   * its note; app.js passes only a note it signed itself (unedited), so
   * every mod line in it counts, even one not in this release. */
  function noteSettings(note) {
    const lines = (note || '').split(/\r?\n/);
    if (!RELEASE.test(lines[0].trim())) return null;
    const out = {};
    for (const raw of lines.slice(1)) {
      const match = /^([a-zA-Z0-9_.-]+)(?:\(([a-zA-Z0-9_=.,-]*)\))?$/.exec(raw.trim());
      if (match) out[match[1]] = match[2] || '';  // `own <file>` and the check line never match
    }
    return out;
  }
  /* The option keys of `tokens` not at their default (`speed` of `speed=3`):
   * a default token missing, or a picked token that is no default. */
  function changedKeys(tokens, defaults) {
    const keyOf = token => token.split('=')[0];
    const keys = new Set([...defaults.filter(token => !tokens.includes(token)),
                          ...tokens.filter(token => !defaults.includes(token))].map(keyOf));
    return [...keys].sort().join(',');
  }
  /* build: {release, output, source, folder, selection: {label: [tokens]},
   * labels, defaults(label) -> [tokens], note} */
  function complete({release, output, source, folder, selection, labels, defaults, note = ''}) {
    const was = noteSettings(note);
    const mods = {}, chg = {};
    for (const [label, tokens] of Object.entries(selection)) {
      if (!labels.includes(label)) continue;
      mods[label] = tokens.join(',');
      chg[label] = changedKeys(tokens, defaults(label));
    }
    send({t: 'build', id: crypto.randomUUID(), rel: release,
      prev: was ? note.split(/\r?\n/)[0].trim() : '', out: output, src: source, dir: folder, mods, was, chg});
  }
  return {complete};
})();
