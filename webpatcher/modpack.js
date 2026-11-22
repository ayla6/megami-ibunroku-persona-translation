'use strict';
/* Patch layers (P1MOD 1) applied in the browser: the files every selected
 * layer touches are merged in memory, then laid out on the player's disc
 * once - the JavaScript twin of src/pipeline/modpack.py (merge) and
 * build_disc.build_to (layout). Every rule here mirrors those two files; a
 * change to one is a change to both (docs/MOD_ENGINE.md).
 *
 *   const pack = MODPACK.parseLayer(bytes)    // needs lzma.js loaded
 *   const layers = MODPACK.selected([pack, ...], {english: ['font=small'], ...})
 *   const disc = MODPACK.source(read, size)   // read(offset, length) -> Promise<Uint8Array>
 *   const {files, clashes} = await MODPACK.merge(disc, layers)
 *   const plan = await MODPACK.layout(disc, files)
 *   // plan.sectors: Map lba -> Uint8Array(2352), in ascending lba order, every
 *   // sector that differs from the source disc or lies past its end;
 *   // plan.total: the image's sector count afterwards.
 *
 * A layer is one mod: "P1MOD\t1\n", the readable UTF-8 TSV manifest (kind
 * path before after: the name, title, description, version - the release,
 * stamped when published - and commit rows, a "requires LABEL" row per mod it
 * needs, an "option GROUP=KEY NAME" or "extra KEY NAME" row per choice, then a
 * "part COND" row per part
 * followed by its file / raw rows, each file's length before and after), a
 * line "--\t<rows bytes>\t<payload bytes>", then one raw LZMA1 stream (lc 3,
 * lp 0, pb 2) of TSV rows - "part N" switching to part N, "check PATH SHA1",
 * the SHA-1 the file must have before it is edited, and "bytes PATH OFFSET
 * LENGTH" - followed by the bytes rows' payload. COND is "-" (always) or
 * mods written as a build names them: LABEL, LABEL(TOKEN,...) (holds). Growth is
 * not an edit: a layer extends a file only when it is shorter, and only a
 * shrinking layer truncates one. FNAME / FSECT / FSIZE.DAT belong to the
 * layout and are refused in a layer.
 */

(function () {
  const SECTOR = 2352;
  const SYNC = new Uint8Array([0, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 0]);
  const SUB_DATA = new Uint8Array([0, 0, 0x08, 0]);
  const SUB_LAST = new Uint8Array([0, 0, 0x89, 0]);   // data | EOR | EOF
  const POSTGAP = 150;
  const MAGIC = 'P1MOD\t1\n';
  const LZMA_PROPS = {lc: 3, lp: 0, pb: 2};
  const HEADER = 'kind\tpath\tbefore\tafter';
  const LAYOUT_FILES = new Set(['FNAME.DAT', 'FSECT.DAT', 'FSIZE.DAT']);

  // --- Form 1 EDC/ECC (src/pipeline/cdsector.py) -------------------
  const EDC = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let e = i;
    for (let k = 0; k < 8; k++) e = (e >>> 1) ^ (e & 1 ? 0xD8018001 : 0);
    EDC[i] = e >>> 0;
  }
  const ECC_F = new Uint8Array(256);
  const ECC_B = new Uint8Array(256);
  for (let i = 0; i < 256; i++) {
    const j = ((i << 1) ^ (i & 0x80 ? 0x11D : 0)) & 0xFF;
    ECC_F[i] = j;
    ECC_B[i ^ j] = i;
  }

  function eccPQ(buf, majorCount, minorCount, majorMult, minorInc, outOff) {
    const size = majorCount * minorCount;
    for (let major = 0; major < majorCount; major++) {
      let index = (major >> 1) * majorMult + (major & 1);
      let a = 0;
      let b = 0;
      for (let m = 0; m < minorCount; m++) {
        const t = buf[12 + index];
        index += minorInc;
        if (index >= size) index -= size;
        a ^= t;
        b ^= t;
        a = ECC_F[a];
      }
      a = ECC_B[ECC_F[a] ^ b];
      buf[outOff + major] = a;
      buf[outOff + major + majorCount] = a ^ b;
    }
  }

  const bcd = n => ((Math.floor(n / 10)) << 4) | (n % 10);

  function msf(lba) {
    const t = lba + 150;
    return [bcd(Math.floor(t / 4500)), bcd(Math.floor(t / 75) % 60), bcd(t % 75)];
  }

  function makeForm1(lba, sub, user) {
    const buf = new Uint8Array(SECTOR);
    buf.set(SYNC, 0);
    buf.set(msf(lba), 12);
    buf[15] = 2;
    buf.set(sub, 16);
    buf.set(sub, 20);
    buf.set(user.subarray(0, 2048), 24);
    let e = 0;
    for (let p = 16; p < 2072; p++) e = (e >>> 8) ^ EDC[(e ^ buf[p]) & 0xFF];
    new DataView(buf.buffer).setUint32(2072, e >>> 0, true);
    const header = buf.slice(12, 16);
    buf.fill(0, 12, 16);                  // Mode 2: ECC ignores the header
    eccPQ(buf, 86, 24, 2, 86, 2076);      // P
    eccPQ(buf, 52, 43, 86, 88, 2076 + 172);   // Q
    buf.set(header, 12);
    return buf;
  }

  function emptySector(lba) {
    const s = new Uint8Array(SECTOR);
    s.set(SYNC, 0);
    s.set(msf(lba), 12);
    s[15] = 2;
    return s;
  }

  // --- layers ----------------------------------------------------------------
  function indexOf(hay, needle, from) {
    outer: for (let i = from; i <= hay.length - needle.length; i++) {
      for (let k = 0; k < needle.length; k++) if (hay[i + k] !== needle[k]) continue outer;
      return i;
    }
    return -1;
  }

  /* {name, title, description, version, commit, requires: [label], choices:
   *  [{token, name}], twins, parts: [{when, files: [{path, raw, before, length,
   *  source, spans: [{offset, bytes}]}]}]} */
  function parseLayer(blob) {
    const magic = new TextEncoder().encode(MAGIC);
    const prefix = new TextDecoder().decode(blob.subarray(0, magic.length));
    if (prefix !== MAGIC) {
      throw new Error('not a P1MOD 1 layer - reload the page');
    }
    // the readable manifest runs up to the "--\t<runs>\t<payload>" line
    const dash = indexOf(blob, new TextEncoder().encode('\n--\t'), magic.length - 1);
    let end = dash + 1;
    while (end < blob.length && blob[end] !== 0x0a) end++;
    if (dash < 0 || end >= blob.length) throw new Error('P1MOD layer: no -- line');
    const text = new TextDecoder('utf-8');
    const [, runsSize, size] = text.decode(blob.subarray(dash + 1, end)).split('\t').map(Number);
    const both = LZMA.decode(blob.subarray(end + 1), runsSize + size, LZMA_PROPS);
    const lines = text.decode(blob.subarray(magic.length, dash)).split('\n');
    if (lines[0] !== HEADER) throw new Error(`P1MOD layer: unknown header ${lines[0]}`);
    let name = null;
    const about = {title: '', description: '', version: '', commit: '', author: ''};
    const requires = [];
    const choices = [];
    const ranges = [];
    const parts = [];
    const byPath = [];
    for (const line of lines.slice(1)) {
      const [kind, path, before, after] = line.split('\t');
      if (kind === 'name') {
        name = path;
      } else if (kind in about) {
        about[kind] = path;
      } else if (kind === 'requires') {
        requires.push(path);
      } else if (kind === 'option' || kind === 'extra') {
        choices.push({token: path, name: before});
      } else if (kind === 'range') {
        const [minimum, maximum, step, defaultValue] = before.split(',').map(Number);
        ranges.push({key: path, minimum, maximum, step, default: defaultValue, name: after});
      } else if (kind === 'part') {
        parts.push({when: path === '-' ? '' : path, files: []});
        byPath.push(new Map());
      } else if (kind === 'file' || kind === 'raw') {
        if (!parts.length) throw new Error('P1MOD layer: a file row before any part');
        if (LAYOUT_FILES.has(path)) throw new Error(`P1MOD layer: ${path} belongs to the layout`);
        const file = {path, raw: kind === 'raw', before: Number(before), length: Number(after),
                      source: null, spans: [], scales: [], entries: []};
        parts[parts.length - 1].files.push(file);
        byPath[byPath.length - 1].set(path, file);
      } else {
        throw new Error(`P1MOD layer: unknown row kind ${kind}`);
      }
    }
    const payload = both.subarray(runsSize);
    const twins = [];
    let current = null;
    let pos = 0;
    for (const line of text.decode(both.subarray(0, runsSize)).split('\n')) {
      if (!line) continue;
      const [kind, path, a, b] = line.split('\t');
      if (kind === 'twins') {
        twins.push(line.split('\t').slice(1));
        continue;
      }
      if (kind === 'part') {
        current = byPath[Number(path)];
        continue;
      }
      const file = current && current.get(path);
      if (!file) throw new Error(`P1MOD layer: a ${kind} row for ${path} has no file row in its part`);
      if (kind === 'check') {
        file.source = a;
      } else if (kind === 'scale') {
        file.scales.push({offset: Number(a), parameter: b, original: Number(line.split('\t')[4])});
      } else if (kind === 'mes-entry') {
        const n = Number(b);
        file.entries.push({index: Number(a), bytes: payload.subarray(pos, pos + n), source: line.split('\t')[4]});
        pos += n;
      } else if (kind === 'bytes') {
        const n = Number(b);
        file.spans.push({offset: Number(a), bytes: payload.subarray(pos, pos + n)});
        pos += n;
      } else {
        throw new Error(`P1MOD layer: unknown row kind ${kind}`);
      }
    }
    if (pos !== payload.length) throw new Error('P1MOD layer: payload bytes left over');
    return {name, ...about, requires, choices, parts, twins, ranges};
  }

  /* `a,b(font=small,x)` -> [[a, []], [b, ['font=small', 'x']]]: a part's
   * condition, written as a build names mods (mods.parse_mods). */
  function parseMods(text) {
    const out = [];
    const items = [];
    let depth = 0;
    let start = 0;
    for (let at = 0; at <= text.length; at++) {
      const char = at < text.length ? text[at] : ',';
      if (char === '(') depth++;
      else if (char === ')') depth--;
      else if (char === ',' && depth === 0) {
        items.push(text.slice(start, at));
        start = at + 1;
      }
      if (depth < 0 || depth > 1) break;
    }
    for (const item of items.map(i => i.trim()).filter(Boolean)) {
      const match = /^([^(),\s]+)\s*(?:\(([^()]*)\))?$/.exec(item);
      if (depth || !match) throw new Error(`cannot read the part condition ${text}`);
      out.push([match[1], (match[2] || '').split(',').map(t => t.trim()).filter(Boolean)]);
    }
    if (depth) throw new Error(`cannot read the part condition ${text}`);
    return out;
  }

  /* Whether a part's condition holds in `selection` ({label: [its picked
   * choice tokens]}; modpack.holds). */
  function holds(when, selection) {
    return parseMods(when).every(([label, tokens]) =>
        label in selection && tokens.every(token => selection[label].includes(token)));
  }

  /* Each option group's first token (modpack.Pack.defaults). */
  function defaults(pack) {
    const first = new Map();
    for (const {token} of pack.choices) {
      if (token.includes('=') && !first.has(token.split('=')[0])) first.set(token.split('=')[0], token);
    }
    return [...first.values(), ...(pack.ranges || []).map(r => `${r.key}=${r.default}`)];
  }

  function rangeValue(range, text) {
    const value = Number(text);
    if (!/^\d+$/.test(text) || !Number.isSafeInteger(value) || range.step <= 0 ||
        value < range.minimum || value > range.maximum || (value - range.minimum) % range.step) {
      throw new Error(`${range.key}: expected ${range.minimum}..${range.maximum}, step ${range.step}`);
    }
    return value;
  }

  function parameterFiles(pack, files, tokens) {
    const values = new Map((pack.ranges || []).map(r => [r.key, r.default]));
    for (const token of tokens) {
      const [key, text] = token.split('=');
      const range = (pack.ranges || []).find(r => r.key === key);
      if (range) values.set(key, rangeValue(range, text));
    }
    return files.map(file => ({...file, spans: [...file.spans, ...(file.scales || []).map(scale => {
      if (!values.has(scale.parameter)) throw new Error('unknown range parameter');
      const percent = values.get(scale.parameter);
      const value = percent && scale.original ? Math.max(1, Math.floor((scale.original * percent + 50) / 100)) : 0;
      return {offset: scale.offset, bytes: new Uint8Array([value])};
    })], scales: []}));   // resolved into spans, as modpack.selected does: the merge sees byte edits
  }

  /* The layers merge() applies: every part of each pack whose condition
   * holds, in order; a pack missing from `selection` is on at its defaults
   * (modpack.selected). */
  function selected(packs, selection = {}) {
    const chosen = {};
    for (const pack of packs) chosen[pack.name] = defaults(pack);
    Object.assign(chosen, selection);
    // a choice past the defaults needs a part that names it, or the layer
    // would patch the default and say nothing (modpack.selected)
    for (const pack of packs) {
      const named = new Set(pack.parts.flatMap(part => parseMods(part.when)
          .filter(([label]) => label === pack.name).flatMap(([, tokens]) => tokens)));
      for (const token of chosen[pack.name]) {
        const [key, value] = token.split('=');
        const range = (pack.ranges || []).find(r => r.key === key);
        if (range) { rangeValue(range, value); continue; }
        if (!defaults(pack).includes(token) && !named.has(token)) {
          throw new Error(`${pack.title || pack.name}: this release has no ${token} -`
              + ' its layer was built without it');
        }
      }
    }
    const layers = packs.flatMap(pack => pack.parts.filter(part => holds(part.when, chosen))
      .map((part, n) => ({name: pack.name + (part.when ? `[${part.when}]` : ''),
                          files: parameterFiles(pack, part.files, chosen[pack.name]), twins: n ? [] : pack.twins})));
    // A range's byte is the player's value whatever a later mod's part wrote
    // there: every setting is written again after all layers, as pure byte
    // edits that never resize a file (modpack.selected).
    const settings = packs.flatMap(pack => pack.parts.filter(part => holds(part.when, chosen))
      .map(part => parameterFiles(pack, part.files.filter(file => (file.scales || []).length)
                                    .map(file => ({...file, raw: false, before: 0, length: 0, source: null,
                                                   spans: [], entries: []})), chosen[pack.name]))
      .filter(files => files.length)
      .map(files => ({name: pack.name + ' settings', files, twins: []})));
    return [...layers, ...settings];
  }

  function mesTable(data) {
    if (data.length < 514) throw new Error('MES: truncated table');
    const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
    const table = Array.from({length: 257}, (_, i) => view.getUint16(i * 2, true));
    if (table[0] < 1 || table[256] * 2048 > data.length || table.some((v, i) => i && v < table[i-1]))
      throw new Error('MES: invalid entry extents');
    return table;
  }

  async function replaceMes(data, edits) {
    const table = mesTable(data), replacements = new Map();
    for (const edit of edits) {
      if (!Number.isInteger(edit.index) || edit.index < 0 || edit.index >= 256 || replacements.has(edit.index))
        throw new Error('MES: invalid or duplicate entry index');
      if (edit.bytes.length < 10 || edit.bytes.at(-2) !== 127 || edit.bytes.at(-1) !== 255)
        throw new Error('MES: prepared entry lacks header or end token');
      replacements.set(edit.index, edit.bytes);
    }
    await Promise.all(edits.map(async edit => {
      const original = data.subarray(table[edit.index] * 2048, table[edit.index + 1] * 2048);
      if (await hexDigest(original) !== edit.source) throw new Error(`MES: source entry ${edit.index} differs`);
    }));
    if (edits.every(e => e.bytes.length <= (table[e.index + 1] - table[e.index]) * 2048)) {
      const result = data.slice();
      for (const edit of edits) {
        result.fill(0, table[edit.index] * 2048, table[edit.index + 1] * 2048);
        result.set(edit.bytes, table[edit.index] * 2048);
      }
      return result;
    }
    const pieces = [], starts = [table[0]];
    for (let i = 0; i < 256; i++) {
      const bytes = replacements.get(i) || data.subarray(table[i] * 2048, table[i+1] * 2048);
      pieces.push(bytes); starts.push(starts.at(-1) + Math.ceil(bytes.length / 2048));
    }
    if (starts[256] > 65535) throw new Error('MES: sector table overflow');
    const result = new Uint8Array(starts[256] * 2048);
    result.set(data.subarray(0, table[0] * 2048));
    const view = new DataView(result.buffer);
    starts.forEach((value, i) => view.setUint16(i * 2, value, true));
    pieces.forEach((bytes, i) => result.set(bytes, starts[i] * 2048));
    return result;
  }

  // --- the disc ----------------------------------------------------------------
  /* A disc being laid out: reads come from `written` first (sectors this
   * layout produced, or queued file sectors), then from the source image. */
  class Disc {
    constructor(read, size) {
      this.read = read;
      this.sectors = Math.floor(size / SECTOR);
      this.sourceSectors = this.sectors;
      this.written = new Map();          // lba -> Uint8Array(2352)
      this.pending = new Map();          // lba -> {sub, data}
    }

    async raw(lba) {
      const queued = this.pending.get(lba);
      if (queued) return makeForm1(lba, queued.sub, queued.data);
      const done = this.written.get(lba);
      if (done) return done;
      if (lba >= this.sourceSectors) return new Uint8Array(SECTOR);
      return this.read(lba * SECTOR, SECTOR);
    }

    async rawRun(lba, count) {
      let clean = lba + count <= this.sourceSectors;
      for (let n = 0; clean && n < count; n++) {
        if (this.pending.has(lba + n) || this.written.has(lba + n)) clean = false;
      }
      if (clean) return this.read(lba * SECTOR, count * SECTOR);
      const out = new Uint8Array(count * SECTOR);
      for (let n = 0; n < count; n++) out.set(await this.raw(lba + n), n * SECTOR);
      return out;
    }

    async user(lba) {
      return (await this.raw(lba)).slice(24, 24 + 2048);
    }

    async userRun(lba, count) {
      const raw = await this.rawRun(lba, count);
      const out = new Uint8Array(count * 2048);
      for (let n = 0; n < count; n++) out.set(raw.subarray(n * SECTOR + 24, n * SECTOR + 2072), n * 2048);
      return out;
    }

    /* Have the source read the sectors these spans hold before they are
     * compared: a read costs a fixed fraction of a second on some devices
     * whatever its size (a CHD's reader unpacks one block per read), so what
     * a comparison is about to touch is asked for in a few requests. A source
     * that reads cheaply has no prefetch, and nothing happens. */
    async prefetch(spans) {
      if (this.read.prefetch) await this.read.prefetch(spans);
    }

    async writeUser(lba, data, sub) {
      if (!sub) sub = lba < this.sectors ? (await this.raw(lba)).slice(16, 20) : SUB_DATA;
      this.pending.delete(lba);
      const user = new Uint8Array(2048);
      user.set(data.subarray(0, 2048));
      this.written.set(lba, makeForm1(lba, sub, user));
      this.sectors = Math.max(this.sectors, lba + 1);
    }

    /* `original`: the extent's sectors on the source disc. A sector whose
     * body (subheader on) is unchanged stays the source's own - regenerating
     * it would give the same bytes (build_disc.write_raw). */
    writeRaw(lba, data, original = null) {
      for (let n = 0; n < data.length / SECTOR; n++) {
        const sec = data.subarray(n * SECTOR, (n + 1) * SECTOR);
        this.pending.delete(lba + n);
        if (original && lba + n < this.sourceSectors
            && sameBytes(sec.subarray(16), original.subarray(n * SECTOR + 16, (n + 1) * SECTOR))) {
          this.written.delete(lba + n);
          continue;
        }
        let out;
        if (sec[18] & 0x20) {
          out = new Uint8Array(SECTOR);
          out.set(SYNC, 0);
          out.set(msf(lba + n), 12);
          out[15] = 2;
          out.set(sec.subarray(16), 16);
        } else {
          out = makeForm1(lba + n, sec.slice(16, 20), sec.subarray(24, 24 + 2048));
        }
        this.written.set(lba + n, out);
      }
      this.sectors = Math.max(this.sectors, lba + data.length / SECTOR);
    }

    writeEmpty(lba) {
      this.written.set(lba, emptySector(lba));
      this.sectors = Math.max(this.sectors, lba + 1);
    }

    writeFile(lba, data) {
      const count = Math.max(1, Math.ceil(data.length / 2048));
      for (let n = 0; n < count; n++) {
        this.pending.set(lba + n, {sub: n === count - 1 ? SUB_LAST : SUB_DATA,
                                   data: data.subarray(n * 2048, (n + 1) * 2048)});
      }
      this.sectors = Math.max(this.sectors, lba + count);
      return count;
    }

    /* Generate the queued file sectors. One whose subheader and data equal
     * the source's own sector would regenerate into that same sector, so it
     * is left as the source has it (read in runs, not sector by sector). */
    async flush() {
      const runs = [];
      for (const lba of [...this.pending.keys()].sort((a, b) => a - b)) {
        const last = runs[runs.length - 1];
        if (last && lba === last[1] && last[1] - last[0] < 4096) last[1]++;
        else runs.push([lba, lba + 1]);
      }
      // every run's source before comparing it: read one block at a time, a
      // CHD would cost a read per block on some devices
      await this.prefetch(runs.map(([first, stop]) => [first * SECTOR, stop * SECTOR]));
      for (const [first, stop] of runs) {
        const inSource = Math.max(0, Math.min(stop - first, this.sourceSectors - first));
        const original = inSource ? await this.read(first * SECTOR, inSource * SECTOR) : null;
        for (let lba = first; lba < stop; lba++) {
          const {sub, data} = this.pending.get(lba);
          const n = lba - first;
          if (n < inSource) {
            const at = n * SECTOR;
            const user = new Uint8Array(2048);
            user.set(data.subarray(0, 2048));
            if (sameBytes(original.subarray(at + 16, at + 20), sub)
                && sameBytes(original.subarray(at + 20, at + 24), sub)
                && sameBytes(original.subarray(at + 24, at + 2072), user)) {
              this.written.delete(lba);
              continue;
            }
          }
          this.written.set(lba, makeForm1(lba, sub, data));
        }
      }
      this.pending.clear();
    }

    /* [path, extent, size, recordLba, recordOffset] for every file */
    async walk(lba, size) {
      // one depth of the tree at a time, every directory of it asked for in
      // one request (Disc.prefetch), then the files in the tree's order
      const records = new Map();     // directory lba -> [name, ext, size, isDir, recLba, recOff]
      for (let level = [[lba, size]]; level.length;) {
        await this.prefetch(level.map(([at, bytes]) =>
            [at * SECTOR, (at + Math.ceil(bytes / 2048)) * SECTOR]));
        const next = [];
        for (const [at, bytes] of level) {
          if (records.has(at)) continue;
          const own = [];
          records.set(at, own);
          for (let n = 0; n < Math.ceil(bytes / 2048); n++) {
            const sec = await this.user(at + n);
            const view = new DataView(sec.buffer, sec.byteOffset);
            let pos = 0;
            while (pos < 2048) {
              const recLen = sec[pos];
              if (recLen === 0) break;
              const ext = view.getUint32(pos + 2, true);
              const extSize = view.getUint32(pos + 10, true);
              const isDir = (sec[pos + 25] & 2) !== 0;
              const nameBytes = sec.subarray(pos + 33, pos + 33 + sec[pos + 32]);
              if (!(nameBytes.length === 1 && nameBytes[0] <= 1)) {
                const name = new TextDecoder('ascii').decode(nameBytes).split(';')[0];
                own.push([name, ext, extSize, isDir, at + n, pos]);
                if (isDir) next.push([ext, extSize]);
              }
              pos += recLen;
            }
          }
        }
        level = next;
      }
      const out = [];
      const emit = (at, prefix) => {
        for (const [name, ext, extSize, isDir, recLba, recOff] of records.get(at)) {
          if (isDir) emit(ext, prefix + name + '/');
          else out.push([prefix + name, ext, extSize, recLba, recOff]);
        }
      };
      emit(lba, '');
      return out;
    }

    async setRecord(recLba, recOff, ext, size) {
      const sec = await this.user(recLba);
      const view = new DataView(sec.buffer);
      view.setUint32(recOff + 2, ext, true);
      view.setUint32(recOff + 6, ext, false);
      view.setUint32(recOff + 10, size, true);
      view.setUint32(recOff + 14, size, false);
      await this.writeUser(recLba, sec);
    }

    async entries() {
      const pvd = await this.user(16);
      const view = new DataView(pvd.buffer);
      const files = await this.walk(view.getUint32(156 + 2, true), view.getUint32(156 + 10, true));
      const out = new Map();
      for (const [path, ext, size, recLba, recOff] of files) out.set(path.toUpperCase(), [ext, size, recLba, recOff]);
      return out;
    }

    async readFile(entries, path, raw = false) {
      const [ext, size] = entries.get(path);
      const sectors = Math.ceil(size / 2048);
      if (raw) return this.rawRun(ext, sectors);
      return (await this.userRun(ext, sectors)).slice(0, size);
    }
  }

  function source(read, size) {
    return new Disc(read, size);
  }

  const isRawFile = (path, data) => path.endsWith('.STR') && data.length % SECTOR === 0;
  const recordSize = length => Math.ceil(length / 2048) * 2048;   // FSIZE.DAT's whole sectors

  function sameBytes(a, b) {
    if (a.length !== b.length) return false;
    let i = 0;
    if (a.byteOffset % 4 === 0 && b.byteOffset % 4 === 0) {
      const words = a.length >> 2;
      const x = new Uint32Array(a.buffer, a.byteOffset, words);
      const y = new Uint32Array(b.buffer, b.byteOffset, words);
      for (let w = 0; w < words; w++) if (x[w] !== y[w]) return false;
      i = words << 2;
    }
    for (; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
  }

  function rawBody(data) {
    const out = new Uint8Array(data.length / SECTOR * (SECTOR - 16));
    for (let n = 0; n < data.length / SECTOR; n++) {
      out.set(data.subarray(n * SECTOR + 16, (n + 1) * SECTOR), n * (SECTOR - 16));
    }
    return out;
  }

  const sectorBody = raw => (raw[18] & 0x20 ? raw.subarray(16, 2348) : raw.subarray(16, 2072));
  // a Map key for bytes: latin1 decodes one byte to one character
  const LATIN1 = new TextDecoder('latin1');
  const key = bytes => LATIN1.decode(bytes);

  async function digest(bytes) {
    return key(new Uint8Array(await crypto.subtle.digest('SHA-1', bytes)));
  }

  async function hexDigest(bytes) {
    return [...new Uint8Array(await crypto.subtle.digest('SHA-1', bytes))]
      .map(b => b.toString(16).padStart(2, '0')).join('');
  }

  // --- merge (modpack.merge) ----------------------------------------------------
  /* A movie edited in place, held by the sectors the layers touch only: the
   * rest of the movie is never read (a CHD never unpacks it, and the kept
   * CHD parts never store it). The dub rewrites one sector in eight; this is
   * what keeps its movies from being loaded whole. `sectors`: index -> the
   * edited sector, `orig`: index -> the sector as the disc has it. */
  class SparseRaw {
    constructor(ext, count) {
      this.ext = ext;
      this.count = count;
      this.length = count * SECTOR;
      this.sectors = new Map();
      this.orig = new Map();
    }

    async sector(disc, n) {
      let sec = this.sectors.get(n);
      if (!sec) {
        const orig = await disc.raw(this.ext + n);
        this.orig.set(n, orig);
        sec = orig.slice();
        this.sectors.set(n, sec);
      }
      return sec;
    }

    /* The whole movie (for what needs every byte: a source check). */
    async full(disc) {
      const data = await disc.rawRun(this.ext, this.count);
      const out = data.slice();
      for (const [n, sec] of this.sectors) out.set(sec, n * SECTOR);
      return out;
    }

    /* A key equal for two movies with the same bytes: what each holds in its
     * edited sectors, on top of the retail movie `base` names. */
    async key(base) {
      const parts = [base, String(this.count)];
      for (const n of [...this.sectors.keys()].sort((a, b) => a - b)) {
        parts.push(`${n}:${await digest(this.sectors.get(n))}`);
      }
      return parts.join('|');
    }
  }

  /* Whether an edit of a movie can be held by sector: in place (the same
   * length, the extent's sectors) and with no source check to run. */
  let bySector = true;     // off only to compare against reading movies whole (setBySector)
  const sparseEdit = (edit, size) => bySector && edit.raw && !edit.source
      && edit.before === edit.length
      && edit.length === Math.ceil(size / 2048) * SECTOR;

  async function merge(disc, layers) {
    const entries = await disc.entries();
    const files = new Map();
    const owner = new Map();
    const clashes = new Map();
    for (let index = 0; index < layers.length; index++) {
      const {name, files: edits} = layers[index];
      for (const {path, raw, before, length, source, spans, scales = [], entries: memberEdits = []} of edits) {
        if (LAYOUT_FILES.has(path)) throw new Error(`${name}: ${path} belongs to the layout`);
        if (!entries.has(path)) throw new Error(`${name}: ${path} is not on the disc`);
        let data = files.get(path);
        const [ext, extSize] = entries.get(path);
        if (sparseEdit({raw, source, before, length}, extSize)
            && (!data || data instanceof SparseRaw)) {
          if (!data) data = new SparseRaw(ext, Math.ceil(extSize / 2048));
          let own = owner.get(path) || new Map();
          for (const {offset, bytes} of spans) {
            for (let at = offset; at < offset + bytes.length;) {
              const n = Math.floor(at / SECTOR);
              const end = Math.min(offset + bytes.length, (n + 1) * SECTOR);
              const sec = await data.sector(disc, n);
              if (!own.has(n)) own.set(n, new Uint8Array(SECTOR));
              const mine = own.get(n);
              for (let i = at; i < end; i++) {
                const prev = mine[i - n * SECTOR];
                if (prev && sec[i - n * SECTOR] !== bytes[i - offset]) {
                  const k = `${layers[prev - 1].name}\t${name}\t${path}`;
                  clashes.set(k, (clashes.get(k) || 0) + 1);
                }
              }
              sec.set(bytes.subarray(at - offset, end - offset), at - n * SECTOR);
              mine.fill(index + 1, at - n * SECTOR, end - n * SECTOR);
              at = end;
            }
          }
          files.set(path, data);
          owner.set(path, own);
          continue;
        }
        if (data instanceof SparseRaw) {        // a later edit needs the whole movie
          const own = new Uint8Array(data.length);
          for (const [n, mine] of owner.get(path)) own.set(mine, n * SECTOR);
          owner.set(path, own);
          data = await data.full(disc);
        }
        if (!data) data = await disc.readFile(entries, path, raw);
        if (source && await hexDigest(raw ? rawBody(data) : data) !== source) {
          throw new Error(`${path} is not the file the ${name} layer was made for -`
                          + ' this is not the original Rev 0 disc, or it is damaged');
        }
        if (memberEdits.length) {
          if (raw || spans.length || scales.length) throw new Error('MES entries cannot share a file edit with byte edits');
          data = await replaceMes(data, memberEdits);
          files.set(path, data);
          owner.set(path, new Uint8Array(data.length).fill(index + 1));
          continue;
        }
        let own = owner.get(path) || new Uint8Array(0);
        // An in-place edit whose bytes all land inside the file leaves its
        // length; one that writes past the end grows it to its whole recorded
        // length, trailing zero padding included (modpack.merge).
        const reach = spans.reduce((end, span) => Math.max(end, span.offset + span.bytes.length), 0);
        const minimum = length === before && !raw && !scales.length && reach <= data.length
          ? reach : length;
        const size = length < before ? length : Math.max(data.length, minimum);
        const sized = new Uint8Array(size);
        sized.set(data.subarray(0, size));
        data = sized;
        if (own.length !== size) {
          const ownSized = new Uint8Array(size);
          ownSized.set(own.subarray(0, size));
          own = ownSized;
        }
        for (const {offset, bytes} of spans) {
          for (let i = 0; i < bytes.length; i++) {
            const prev = own[offset + i];
            if (prev && data[offset + i] !== bytes[i]) {
              const k = `${layers[prev - 1].name}\t${name}\t${path}`;
              clashes.set(k, (clashes.get(k) || 0) + 1);
            }
          }
          data.set(bytes, offset);
          own.fill(index + 1, offset, offset + bytes.length);
        }
        files.set(path, data);
        owner.set(path, own);
      }
    }
    // the groups of identical files a layer made against this disc carries
    const twins = layers.flatMap(layer => layer.twins || []);
    return {files, clashes, entries, twins};
  }

  // --- layout (build_disc.build_to) -------------------------------------------
  /* build_disc.duplicate_files from the groups of identical files the base
   * layer carries (modpack.retail_twins): in each group, the files the layout
   * leaves alone point at the first of them (by extent), largest first -
   * nothing is read. */
  function duplicatesFrom(groups, entries, written) {
    const out = [];
    for (const group of groups) {
      const members = group.filter(path => entries.has(path) && !written.has(path))
        .map(path => [entries.get(path)[0], path, Math.ceil(entries.get(path)[1] / 2048)])
        .sort((a, b) => a[0] - b[0]);
      for (const [ext, path, sectors] of members.slice(1)) {
        out.push([sectors, ext, path, members[0][1]]);
      }
    }
    out.sort((a, b) => (b[0] - a[0]) || (a[1] - b[1]));
    return out.map(([, , path, twin]) => [path, twin]);
  }

  async function duplicateFiles(disc, entries, written) {
    const byLength = new Map();
    const sorted = [...entries].sort((a, b) => a[1][0] - b[1][0]);
    for (const [path, [ext, size]] of sorted) {
      if (size && !written.has(path)) {
        const s = Math.ceil(size / 2048);
        if (!byLength.has(s)) byLength.set(s, []);
        byLength.get(s).push([ext, path]);
      }
    }
    const out = [];
    for (const [sectors, group] of [...byLength].sort((a, b) => b[0] - a[0])) {
      const exts = new Map();
      for (const [ext, path] of group) if (!exts.has(ext)) exts.set(ext, path);
      if (exts.size < 2) continue;
      const firsts = new Map();
      for (const [ext, path] of [...exts].sort((a, b) => a[0] - b[0])) {
        const k = key(sectorBody(await disc.raw(ext)));
        if (!firsts.has(k)) firsts.set(k, []);
        firsts.get(k).push([ext, path]);
      }
      for (const candidates of firsts.values()) {
        const kept = [];
        for (const [ext, path] of candidates) {
          if (candidates.length < 2) break;    // a first sector of its own: no twin
          const raw = await disc.rawRun(ext, sectors);   // one read, not one per sector
          const body = [];
          for (let n = 0; n < sectors; n++) body.push(sectorBody(raw.subarray(n * SECTOR, (n + 1) * SECTOR)));
          const twin = kept.find(k => k[2].every((s, i) => sameBytes(s, body[i])));
          if (!twin) kept.push([ext, path, body]);
          else out.push([sectors, ext, path, twin[1]]);
        }
      }
    }
    out.sort((a, b) => (b[0] - a[0]) || (a[1] - b[1]));
    return out.map(([, , path, twin]) => [path, twin]);
  }


  async function layout(disc, files, entriesIn, groups = null) {
    const pvd = await disc.user(16);
    const pvdView = new DataView(pvd.buffer);
    let volume = pvdView.getUint32(80, true);
    const entries = entriesIn ? new Map([...entriesIn].map(([p, e]) => [p, e.slice()]))
                              : await disc.entries();
    const readFile = path => disc.readFile(entries, path);

    const fnames = new TextDecoder('ascii').decode(await readFile('FNAME.DAT'))
      .split('\0').filter(n => n);
    const fsect = (await readFile('FSECT.DAT')).slice();
    const fsize = (await readFile('FSIZE.DAT')).slice();
    const fsectView = new DataView(fsect.buffer);
    const fsizeView = new DataView(fsize.buffer);
    const gameIndex = new Map();
    fnames.forEach((n, i) => gameIndex.set(
      n.replace(/^\\+/, '').split(';')[0].replace(/\\/g, '/').toUpperCase(), i));
    let tablesDirty = false;

    const origEnd = disc.sectors;
    let appendAt = origEnd;
    let changed = 0;
    const work = [];
    let rawWork = [];
    for (const path of [...files.keys()].sort()) {
      if (!entries.has(path)) continue;
      const data = files.get(path);
      const [ext, size, recLba, recOff] = entries.get(path);
      const oldSectors = Math.ceil(size / 2048);
      if (data instanceof SparseRaw) {
        // only its edited sectors: one whose body is the disc's own stays
        const changedAny = [...data.sectors].some(([n, sec]) =>
            !sameBytes(sec.subarray(16), data.orig.get(n).subarray(16)));
        if (changedAny) rawWork.push([path, ext, size, data, null]);
        continue;
      }
      if (isRawFile(path, data)) {
        if (data.length / SECTOR !== oldSectors) {
          throw new Error(`${path}: ${data.length / SECTOR} raw sectors, the extent holds ${oldSectors}`);
        }
        const orig = await disc.rawRun(ext, oldSectors);
        if (!sameBytes(rawBody(orig), rawBody(data))) rawWork.push([path, ext, size, data, orig]);
        continue;
      }
      const sectors = Math.ceil(data.length / 2048);
      const orig = await disc.userRun(ext, oldSectors);
      const padded = new Uint8Array(sectors * 2048);
      padded.set(data);
      if (sectors === oldSectors && sameBytes(padded, orig) && data.length === size) continue;
      work.push({path, ext, oldSectors, sectors, data, size, recLba, recOff});
    }

    const written = new Set([...work.map(w => w.path), ...rawWork.map(w => w[0])]);
    const shared = new Map();
    for (const [path, [ext]] of entries) {
      if (!shared.has(ext)) shared.set(ext, []);
      shared.get(ext).push(path);
    }
    // A shared extent may be written only when every file on it is written
    // with the same sector bodies (build_disc.build_to).
    // files on one extent share their original, so two movies held by
    // sector there compare by what they hold in their edited sectors
    const extentKey = async (data, ext) => (data instanceof SparseRaw
        ? data.key(`extent ${ext}`) : digest(rawBody(data)));
    const rawBodies = new Map();
    for (const [p, ext, , d] of rawWork) rawBodies.set(p, await extentKey(d, ext));
    for (const path of written) {
      const sharers = shared.get(entries.get(path)[0]);
      if (sharers.length > 1 && !(sharers.every(p => rawBodies.has(p))
          && sharers.every(p => rawBodies.get(p) === rawBodies.get(sharers[0])))) {
        throw new Error(`${path} shares its extent with ${sharers}`);
      }
    }
    const growing = work.filter(w => w.sectors > w.oldSectors);
    const collapsed = new Map();
    let twins = null;
    const sameAs = new Map();
    const firstOf = new Map();
    // two movies can end up identical without being so on the disc (the dub
    // writes one audio into MV14 and MVFF): one of the same length as another
    // edited movie is compared whole; a movie of a length no other edited
    // movie has cannot be identical to one, and stays held by sector
    const lengths = new Map();
    for (const [, , size] of rawWork) lengths.set(size, (lengths.get(size) || 0) + 1);
    for (const item of [...rawWork]) {
      const [path, , size, data] = item;
      const k = lengths.get(size) < 2 ? `alone|${path}`
          : await digest(data instanceof SparseRaw ? await data.full(disc) : data);
      if (firstOf.has(k) && entries.get(firstOf.get(k))[1] === size) {
        sameAs.set(path, firstOf.get(k));
        collapsed.set(path, firstOf.get(k));
        rawWork = rawWork.filter(w => w !== item);
      } else {
        firstOf.set(k, path);
      }
    }

    const lexi = (a, b) => (a[0] - b[0]) || (a[1] - b[1]);
    function plan() {
      let free = growing.map(w => [w.ext, w.ext + w.oldSectors]).sort(lexi);
      for (const p of collapsed.keys()) {
        free.push([entries.get(p)[0], entries.get(p)[0] + Math.ceil(entries.get(p)[1] / 2048)]);
      }
      function take(lo, hi) {
        for (let k = 0; k < free.length; k++) {
          const [a, b] = free[k];
          if (a <= lo && hi <= b) {
            free.splice(k, 1, ...[[a, lo], [hi, b]].filter(x => x[0] < x[1]));
            return true;
          }
        }
        return false;
      }
      const merged = [];
      for (const [a, b] of free.slice().sort(lexi)) {
        if (merged.length && a <= merged[merged.length - 1][1]) {
          merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], b);
        } else {
          merged.push([a, b]);
        }
      }
      free = merged;
      const target = new Map();
      for (const w of growing.slice().sort((a, b) => a.ext - b.ext)) {
        if (take(w.ext, w.ext + w.sectors)) target.set(w.path, [w.ext, 'grown in place']);
      }
      for (const w of growing.filter(w => !target.has(w.path)).sort((a, b) => b.sectors - a.sectors)) {
        for (const [a, b] of free.map(x => x.slice())) {
          if (b - a >= w.sectors && take(a, a + w.sectors)) {
            target.set(w.path, [a, 'relocated into a freed extent']);
            break;
          }
        }
      }
      return target;
    }

    let target = plan();
    while (growing.some(w => !target.has(w.path))) {
      if (twins === null) {
        twins = groups ? duplicatesFrom(groups, entries, written)
                       : await duplicateFiles(disc, entries, written);
      }
      if (!twins.length) break;
      const [path, twin] = twins.shift();
      collapsed.set(path, twin);
      target = plan();
    }

    for (const [path, twin] of collapsed) {
      const [, size, recLba, recOff] = entries.get(path);
      await disc.setRecord(recLba, recOff, entries.get(twin)[0], size);
      if (gameIndex.has(path)) {
        fsectView.setUint32(gameIndex.get(path) * 4, entries.get(twin)[0], true);
        tablesDirty = true;
      }
    }

    for (const w of work) {
      changed++;
      let ext = w.ext;
      if (w.sectors <= w.oldSectors) {
        disc.writeFile(ext, w.data);
      } else if (target.has(w.path)) {
        ext = target.get(w.path)[0];
        disc.writeFile(ext, w.data);
      } else {
        ext = appendAt;
        appendAt += disc.writeFile(ext, w.data);
      }
      await disc.setRecord(w.recLba, w.recOff, ext, w.data.length);
      if (gameIndex.has(w.path)) {
        const i = gameIndex.get(w.path);
        fsectView.setUint32(i * 4, ext, true);
        fsizeView.setUint32(i * 4, recordSize(w.data.length), true);
        tablesDirty = true;
      }
    }

    for (const [, ext, , data, orig] of rawWork) {
      changed++;
      if (data instanceof SparseRaw) {
        for (const [n, sec] of data.sectors) disc.writeRaw(ext + n, sec, data.orig.get(n));
      } else {
        disc.writeRaw(ext, data, orig);
      }
    }

    if (tablesDirty) {
      for (const [name, table] of [['FSECT.DAT', fsect], ['FSIZE.DAT', fsize]]) {
        const [ext, , recLba, recOff] = entries.get(name);
        disc.writeFile(ext, table);
        await disc.setRecord(recLba, recOff, ext, table.length);
      }
    }

    if (appendAt > origEnd) {
      for (let lba = appendAt; lba < appendAt + POSTGAP; lba++) disc.writeEmpty(lba);
      volume = appendAt + POSTGAP;
      pvdView.setUint32(80, volume, true);
      pvdView.setUint32(84, volume, false);
      await disc.writeUser(16, pvd);
    }
    await disc.flush();

    // Only the sectors that differ from the source (or lie past its end),
    // compared against the source read in stretches: sectors up to READ_GAP
    // apart share one read (the dub's audio sectors sit between untouched
    // video sectors, so few written sectors are consecutive).
    const READ_GAP = 32;
    // a freed twin's extent now holds another file: never the same as the
    // source there, so it is not read (on a CHD, that would unpack a movie)
    const replaced = new Set();
    for (const path of collapsed.keys()) {
      const [ext, size] = entriesIn && entriesIn.has(path) ? entriesIn.get(path) : entries.get(path);
      for (let n = 0; n < Math.ceil(size / 2048); n++) replaced.add(ext + n);
    }
    const sectors = new Map();
    // a movie held by sector already holds the disc's own bytes for every
    // sector it writes: those are compared without reading the disc (on a
    // CHD, the stretches between them would unpack the whole movie)
    const known = new Map();
    for (const data of files.values()) {
      if (data instanceof SparseRaw) for (const [n, orig] of data.orig) known.set(data.ext + n, orig);
    }
    const lbas = [...disc.written.keys()].filter(lba => {
      if (known.has(lba) && !replaced.has(lba)) {
        if (!sameBytes(disc.written.get(lba), known.get(lba))) sectors.set(lba, disc.written.get(lba));
        return false;
      }
      if (!replaced.has(lba)) return true;
      sectors.set(lba, disc.written.get(lba));
      return false;
    }).sort((a, b) => a - b);
    for (let i = 0; i < lbas.length;) {
      let j = i + 1;
      while (j < lbas.length && lbas[j] - lbas[j - 1] <= READ_GAP && lbas[j] - lbas[i] < 4096) j++;
      const first = lbas[i];
      const span = Math.max(0, Math.min(lbas[j - 1] + 1, disc.sourceSectors) - first);
      const original = span ? await disc.read(first * SECTOR, span * SECTOR) : null;
      for (let k = i; k < j; k++) {
        const sector = disc.written.get(lbas[k]);
        const n = lbas[k] - first;
        if (n < span && sameBytes(sector, original.subarray(n * SECTOR, (n + 1) * SECTOR))) continue;
        sectors.set(lbas[k], sector);
      }
      i = j;
    }
    // in disc order: the callers write the result as ascending runs
    const ordered = new Map([...sectors].sort((a, b) => a[0] - b[0]));
    return {sectors: ordered, total: disc.sectors, volume, changed};
  }

  /* The disc paths a set of layers edits, and their extents' byte spans on
   * the disc ([start, end) in 2352-byte sectors) - what a CHD must unpack
   * before the merge and the layout read them. The layout also reads the
   * volume descriptor, its own tables and the directory sector each record it
   * writes lives in: small, and known here. */
  async function touched(disc, layers) {
    const entries = await disc.entries();
    const spans = [[16 * SECTOR, 17 * SECTOR]];       // the volume descriptor
    for (const path of LAYOUT_FILES) {
      const entry = entries.get(path);
      if (entry) spans.push([entry[0] * SECTOR, (entry[0] + Math.ceil(entry[1] / 2048)) * SECTOR]);
    }
    const edits = new Map();          // path -> its edits, every layer's
    for (const layer of layers) {
      for (const f of layer.files) {
        if (!edits.has(f.path)) edits.set(f.path, []);
        edits.get(f.path).push(f);
      }
    }
    // two edited movies of one length may end up identical, and the layout
    // then compares them whole (MV14 and MVFF under the dub): those are
    // unpacked whole up front, like any other file the layers edit
    const rawLengths = new Map();
    for (const [path, fileEdits] of edits) {
      const entry = entries.get(path);
      if (entry && fileEdits.some(f => f.raw)) rawLengths.set(entry[1], (rawLengths.get(entry[1]) || 0) + 1);
    }
    for (const [path, fileEdits] of edits) {
      const entry = entries.get(path);
      if (!entry) continue;
      const [ext, size, recLba] = entry;
      // the directory sector holding the record the layout rewrites
      spans.push([recLba * SECTOR, (recLba + 1) * SECTOR]);
      if (fileEdits.every(f => sparseEdit(f, size)) && rawLengths.get(size) < 2) {
        // a movie held by sector: only the sectors its edits land in
        const hit = new Set();
        for (const f of fileEdits) {
          for (const {offset, bytes} of f.spans) {
            for (let n = Math.floor(offset / SECTOR);
                 n <= Math.floor((offset + bytes.length - 1) / SECTOR); n++) hit.add(n);
          }
        }
        for (const n of hit) spans.push([(ext + n) * SECTOR, (ext + n + 1) * SECTOR]);
        continue;
      }
      spans.push([ext * SECTOR, (ext + Math.ceil(size / 2048)) * SECTOR]);
    }
    return spans;
  }

  globalThis.MODPACK = {replaceMes, parseLayer, parseMods, holds, selected, source, merge, layout, touched,
                       setBySector: on => { bySector = on; }, makeForm1, SECTOR, LAYOUT_FILES};
})();
