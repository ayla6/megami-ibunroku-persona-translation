'use strict';
/* Node harness for the web patcher: runs webpatcher/worker.js exactly as the
 * page does (the player's disc as a Blob read in slices, layers checked
 * against their SHA-1, merged, laid out) and writes what the page would
 * hand over, so it can be compared with modpack.py apply / build_disc.py.
 *
 *   node webpatcher_modpack.js <webpatcher/modpack.js> <source.bin|.chd> <out.bin> [--ppf out.ppf] [--choose 'LABEL(TOKEN,...)'] <layer.p1mod> ...
 *
 * With --compare, out.bin is an existing expected disc; the worker's complete
 * Blob is compared while streaming, without writing a second disc image.
 * Otherwise out.bin is the worker's Build disc result (its Blob of the source's slices
 * and the changed sectors); with --ppf the worker's Build PPF result is
 * written too. A .chd source takes only --ppf (the page's Build disc needs
 * the .bin), and out.bin is then not written.
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const site = path.dirname(path.resolve(process.argv[2]));
global.self = global;
global.importScripts = (...files) => files.forEach(file => require(path.join(site, file)));

function runWorker(msg) {
  return new Promise((resolve, reject) => {
    global.postMessage = reply => {
      if (reply.type === 'progress') return;
      if (reply.type === 'error') reject(new Error(reply.message));
      else resolve(reply);
    };
    self.onmessage({data: msg});
  });
}

async function main() {
  const args = process.argv.slice(3);
  const sourcePath = args.shift();
  const outPath = args.shift();
  let ppfPath = null;
  let compare = false;
  const selection = {};
  const chooses = [];
  while (args[0] === '--ppf' || args[0] === '--choose' || args[0] === '--compare') {
    const flag = args.shift();
    if (flag === '--compare') compare = true;
    else if (flag === '--ppf') ppfPath = args.shift();
    else chooses.push(args.shift());
  }
  require(path.join(site, 'worker.js'));
  for (const text of chooses) {
    for (const [label, tokens] of MODPACK.parseMods(text)) selection[label] = tokens;
  }
  const source = await fs.openAsBlob(sourcePath);
  const chd = /\.chd$/i.test(sourcePath);
  const layers = [];
  for (const file of args) {
    layers.push({name: path.basename(file), file: await fs.openAsBlob(file),
                 hash: crypto.createHash('sha1').update(fs.readFileSync(file)).digest('hex')});
  }
  const started = Date.now();
  const base = {type: 'run', source, chd, keepChd: false, layers, selection, description: 'harness'};
  if (!chd) {
    const done = await runWorker({...base, output: 'disc'});
    const out = fs.openSync(outPath, compare ? 'r' : 'w');
    try {
      if (compare && fs.fstatSync(out).size !== done.blob.size)
        throw Error('webpatcher: disc length differs from ' + outPath);
      const reader = done.blob.stream().getReader();
      let offset = 0;
      for (let chunk; !(chunk = await reader.read()).done;) {
        const bytes = chunk.value;
        if (compare) {
          const expected = Buffer.allocUnsafe(bytes.length);
          let read = 0;
          while (read < expected.length) {
            const count = fs.readSync(out, expected, read, expected.length - read, null);
            if (!count) throw Error('webpatcher: expected disc ended at ' + (offset + read));
            read += count;
          }
          if (!expected.equals(Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength)))
            throw Error('webpatcher: disc differs near offset ' + offset);
        } else fs.writeSync(out, bytes);
        offset += bytes.length;
      }
      if (offset !== done.blob.size) throw Error('webpatcher: incomplete disc stream');
    } finally { fs.closeSync(out); }
    console.log(`webpatcher: disc ${done.blob.size} bytes${compare ? ' verified' : ''}`);
  }
  if (ppfPath) {
    const done = await runWorker({...base, output: 'ppf'});
    fs.writeFileSync(ppfPath, Buffer.from(await done.ppf.arrayBuffer()));
    console.log(`webpatcher: ppf ${done.ppf.size} bytes`);
  }
  console.log(`webpatcher: ${layers.length} layer(s) in ${((Date.now() - started) / 1000).toFixed(1)} s`);
}

main().catch(err => { console.error(err); process.exit(1); });
