'use strict';
/* Debug log for the web patcher, served only by
 * `python tools/serve_webpatcher.py --debug` (never part of the Pages site).
 *
 * The server loads this file in every scope: a <script> before app.js on the
 * page, and an importScripts at the end of worker.js and chdblocks.js. Each
 * scope reports what it sees; the reports climb worker by worker to the page
 * as {__debug} messages (filtered out before the patcher's own handlers see
 * them), which shows them in a panel and posts them to the server, so a
 * phone without dev tools leaves its log on the machine serving it
 * (build/webpatcher-debug.log).
 */

(function () {
  const start = Date.now();
  const inPage = typeof window !== 'undefined';
  const scope = inPage ? 'page' : (self.name || String(self.location.pathname).split('/').pop());

  /* ---- reporting: the page owns the log, workers send theirs up ---- */
  let sink;
  if (inPage) {
    const lines = [];
    let unsent = [];
    let panel = null;
    sink = (from, text) => {
      const line = `${((Date.now() - start) / 1000).toFixed(2).padStart(8)}s ${from}: ${text}`;
      lines.push(line);
      unsent.push(line);
      if (panel) {
        panel.log.textContent += line + '\n';
        panel.log.scrollTop = panel.log.scrollHeight;
      }
    };
    const flush = () => {
      if (!unsent.length) return;
      const body = unsent.join('\n') + '\n';
      unsent = [];
      fetch('__debug/log', {method: 'POST', body, keepalive: true}).catch(() => {});
    };
    setInterval(flush, 1000);
    addEventListener('pagehide', flush);
    addEventListener('DOMContentLoaded', () => {
      const box = document.createElement('div');
      box.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:99;'
          + 'background:#000e;color:#0f0;font:12px monospace;text-shadow:none;';
      const bar = document.createElement('div');
      bar.style.cssText = 'display:flex;gap:0.5rem;padding:0.25rem;';
      const toggle = document.createElement('button');
      toggle.textContent = 'Debug log';
      const copy = document.createElement('button');
      copy.textContent = 'Copy';
      const log = document.createElement('pre');
      log.style.cssText = 'margin:0;padding:0.25rem;max-height:40vh;overflow:auto;'
          + 'white-space:pre-wrap;overflow-wrap:anywhere;';
      log.hidden = true;
      log.textContent = lines.join('\n') + (lines.length ? '\n' : '');
      toggle.onclick = () => { log.hidden = !log.hidden; log.scrollTop = log.scrollHeight; };
      copy.onclick = () => navigator.clipboard.writeText(lines.join('\n')).catch(() => {});
      bar.append(toggle, copy);
      box.append(bar, log);
      document.body.append(box);
      panel = {log};
      const status = document.getElementById('status');
      if (status) {
        new MutationObserver(() => sink('status', (status.className ? '[error] ' : '')
            + status.textContent)).observe(status, {childList: true, characterData: true, subtree: true});
      }
    });
  } else {
    sink = (from, text) => postMessage({__debug: {from, text}});
  }
  const log = text => sink(scope, text);

  const describe = err => (err && (err.stack || err.message)) || String(err);
  addEventListener('error', event => log('uncaught error: '
      + (event.error ? describe(event.error) : `${event.message} at ${event.filename}:${event.lineno}`)));
  addEventListener('unhandledrejection', event => log('unhandled rejection: ' + describe(event.reason)));

  /* ---- what this scope can do ---- */
  const nav = self.navigator || {};
  const facts = [`cores ${nav.hardwareConcurrency}`];
  if (nav.deviceMemory) facts.push(`memory ${nav.deviceMemory} GB`);
  facts.push(`nested Worker ${typeof Worker}`, `FileReaderSync ${typeof FileReaderSync}`,
             `DecompressionStream ${typeof DecompressionStream}`, `indexedDB ${typeof indexedDB}`);
  if (inPage) {
    facts.unshift(nav.userAgent);
    facts.push(`showDirectoryPicker ${typeof window.showDirectoryPicker}`);
    if (nav.storage && nav.storage.estimate) {
      nav.storage.estimate().then(({usage, quota}) =>
          log(`storage ${(usage / 1e6).toFixed(1)} MB used of ${(quota / 1e6).toFixed(0)} MB`), () => {});
    }
  }
  log('loaded; ' + facts.join(', '));

  /* ---- workers: log their life, pass their reports up, hide them from the
   * patcher's handlers ---- */
  if (typeof Worker !== 'undefined') {
    const Native = Worker;
    let made = 0;
    const summary = data => {
      if (!data || typeof data !== 'object') return String(data);
      if (data.type) return data.type + (data.message ? ` "${data.message}"` : '');
      if (data.blocks) return `${data.blocks.length} blocks`;
      if (data.error) return `error "${data.error}"`;
      return Object.keys(data).join(',');
    };
    self.Worker = class extends Native {
      constructor(url, options) {
        const name = `${String(url).split('/').pop()}#${++made}`;
        super(url, Object.assign({}, options, {name}));
        this.debugName = name;
        const born = Date.now();
        let heard = false;
        log(`started ${name}`);
        super.addEventListener('message', event => {
          const data = event.data;
          if (data && data.__debug) {
            event.stopImmediatePropagation();
            sink(data.__debug.from, data.__debug.text);
            return;
          }
          if (!heard) log(`${name} first message after ${Date.now() - born} ms`);
          heard = true;
          if (!(data && data.type === 'progress')) log(`${name} -> ${summary(data)}`);
        });
        super.addEventListener('error', event => log(`${name} error event: `
            + `${event.message || '(no message)'} ${event.filename || ''}:${event.lineno || ''}`));
        super.addEventListener('messageerror', () => log(`${name} messageerror (could not clone)`));
      }
      set onmessage(handler) {
        // stopImmediatePropagation above cannot reach an onmessage handler
        // registered before ours, so wrap it instead
        super.onmessage = handler && (event => {
          if (!(event.data && event.data.__debug)) handler.call(this, event);
        });
      }
      get onmessage() { return super.onmessage; }
      postMessage(data, transfer) {
        log(`-> ${this.debugName} ${summary(data)}`);
        return super.postMessage(data, transfer);
      }
      terminate() {
        log(`terminated ${this.debugName}`);
        return super.terminate();
      }
    };
  }

  /* ---- workers: every file read, timed, with where in the file it starts
   * (a read whose time grows with its offset means the file cannot seek) */
  if (!inPage && typeof Blob !== 'undefined') {
    const origin = new WeakMap();
    const slice = Blob.prototype.slice;
    Blob.prototype.slice = function (start = 0, end, ...rest) {
      const piece = slice.call(this, start, end, ...rest);
      if (this instanceof File || origin.has(this)) {
        origin.set(piece, (origin.get(this) || 0) + Math.max(0, start));
      }
      return piece;
    };
    const arrayBuffer = Blob.prototype.arrayBuffer;
    let reads = 0, readBytes = 0, readMs = 0;
    Blob.prototype.arrayBuffer = async function () {
      if (!origin.has(this)) return arrayBuffer.call(this);
      const began = Date.now();
      const out = await arrayBuffer.call(this);
      const took = Date.now() - began;
      reads++;
      readBytes += this.size;
      readMs += took;
      if (this.size >= 65536 || took >= 100 || reads <= 3) {
        log(`read ${(this.size / 1024).toFixed(0)} KB at ${(origin.get(this) / 1048576).toFixed(1)} MB`
            + ` in ${took} ms (${(this.size / 1048.576 / Math.max(took, 1)).toFixed(2)} MB/s);`
            + ` ${reads} reads, ${(readBytes / 1048576).toFixed(1)} MB, ${(readMs / 1000).toFixed(1)} s so far`);
      }
      return out;
    };
  }

  /* ---- workers: what arrives, and how CHD blocks unpack ---- */
  if (!inPage) {
    if (typeof self.onmessage === 'function') {
      const handler = self.onmessage;
      self.onmessage = event => {
        const data = event.data || {};
        log(`received ${data.type || Object.keys(data).join(',')}`
            + (data.indices ? ` (${data.indices.length} blocks from ${data.indices[0]})` : ''));
        return handler.call(self, event);
      };
    }
    if (self.CHD && self.CHD.hunk) {
      const hunk = self.CHD.hunk;
      let done = 0, slowest = 0, busy = null, since = 0;
      setInterval(() => {
        if (busy !== null && Date.now() - since > 3000) {
          log(`block ${busy} unpacking for ${((Date.now() - since) / 1000).toFixed(0)} s (${done} done)`);
        }
      }, 3000);
      self.CHD.hunk = async (...args) => {
        const index = args[1];
        busy = index;
        since = Date.now();
        try {
          const out = await hunk(...args);
          const took = Date.now() - since;
          done++;
          if (done === 1 || took > slowest * 2) {
            log(`block ${index} unpacked in ${took} ms (${done} done)`);
            slowest = Math.max(slowest, took);
          }
          return out;
        } catch (err) {
          log(`block ${index} failed: ${describe(err)}`);
          throw err;
        } finally {
          busy = null;
        }
      };
    }
  }
})();
