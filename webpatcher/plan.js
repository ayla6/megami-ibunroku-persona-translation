'use strict';
/* Persona translation web patcher - release graph.
 *
 * manifest.tsv has one row per patch file (not one per combination). A row
 * names the option it adds (`adds`), the size-changers it was encoded
 * against (`anchor`), its fixed apply position (`order`) and the canonical
 * state it produces (`choices`). This module turns a selection into the
 * ordered chain of rows to apply:
 *
 * - options are applied in `order`;
 * - a step whose source is exactly the canonical state of its row uses
 *   xdelta's own checksums; anything else is a decorated source (other
 *   in-place options riding along) and is decoded with -n;
 * - `rev1-to-rev0` comes first on a Rev 1 disc, then `rev0-to-base`, then
 *   one add- patch per selected option.
 *
 * Nothing here knows an option name: the manifest is the whole graph.
 */
const PatchPlan = (() => {
  const BASE_PATCH = 'rev0-to-base.xdelta';
  const REV1_PATCH = 'rev1-to-rev0.xdelta';
  const REQUIRED = ['patch', 'adds', 'anchor', 'order', 'choices', 'verify',
                    'source_bytes', 'source_sha256', 'target_bytes',
                    'target_sha256', 'patch_sha256'];

  function rowsFrom(text) {
    const lines = text.split('\n').filter(line => line);
    if (!lines.length) throw new Error('the release manifest is empty');
    const header = lines.shift().split('\t');
    for (const name of REQUIRED) {
      if (!header.includes(name)) {
        throw new Error(`unrecognized release manifest (no ${name} column)`);
      }
    }
    return lines.map(line => {
      const cells = line.split('\t');
      const row = {};
      header.forEach((name, index) => { row[name] = cells[index] || ''; });
      return row;
    });
  }

  function index(rows) {
    const base = rows.find(row => row.patch === BASE_PATCH);
    if (!base) throw new Error('release manifest is missing ' + BASE_PATCH);
    const rev1 = rows.find(row => row.patch === REV1_PATCH) || null;
    const byAdds = new Map();
    const order = new Map();
    for (const row of rows) {
      if (!row.adds) continue;
      if (!byAdds.has(row.adds)) byAdds.set(row.adds, []);
      byAdds.get(row.adds).push(row);
      const position = Number(row.order);
      if (!Number.isInteger(position) || position < 0) {
        throw new Error(`release manifest has no apply order for ${row.adds}`);
      }
      if (order.has(row.adds) && order.get(row.adds) !== position) {
        throw new Error(`release manifest disagrees on the apply order of ${row.adds}`);
      }
      order.set(row.adds, position);
    }
    /* The grid shows the options the release actually has patches for. */
    const labels = [...order.keys()].sort((a, b) => order.get(a) - order.get(b));
    return { rows, base, rev1, byAdds, order, labels };
  }

  function anchors(row) {
    return row.anchor ? row.anchor.split(',') : [];
  }

  /* The canonical source state of a row: the state it was encoded from.
   * `choices` is the canonical target, so removing the option it adds
   * leaves the source. */
  function sourceOf(row) {
    return row.choices ? row.choices.split(',').filter(item => item !== row.adds) : [];
  }

  function ordered(index, labels) {
    const unique = [...new Set(labels)];
    for (const label of unique) {
      if (!index.order.has(label)) {
        throw new Error(`the manifest has no patch for ${label}`);
      }
    }
    return unique.sort((a, b) => index.order.get(a) - index.order.get(b));
  }

  /* The add- rows for a selection, in apply order. The anchor decides which
   * file an option needs: the most specific row whose size-changers are all
   * already applied. */
  function chain(index, labels) {
    const applied = new Set();
    const steps = [];
    for (const label of ordered(index, labels)) {
      const candidates = (index.byAdds.get(label) || [])
          .filter(row => anchors(row).every(item => applied.has(item)));
      if (!candidates.length) {
        throw new Error(`this combination has no patch for ${label} - is the`
            + ' release complete?');
      }
      candidates.sort((a, b) => anchors(b).length - anchors(a).length);
      const row = candidates[0];
      steps.push({ row, source: sourceOf(row) });
      applied.add(label);
    }
    return steps;
  }

  /* Whether the options applied so far are exactly the row's canonical
   * source. In-place decorations never change the image size, but they do
   * change its bytes, so the patch's window checksums only describe the
   * canonical source. */
  function canonicalSource(step, applied) {
    return step.source.length === applied.size
        && step.source.every(label => applied.has(label));
  }

  /* xdelta arguments for one step. `-n` only when the source carries
   * decorations the patch was not encoded from; the release build verified
   * sampled decorated chains byte for byte (manifest `verified`). */
  function decodeArgs(step, applied) {
    const args = ['-d', '-f', '-q'];
    if (!canonicalSource(step, applied)) args.push('-n');
    return args;
  }

  function plan(index, rev, labels) {
    const steps = [];
    let bytes;
    if (rev === 1) {
      if (!index.rev1) {
        throw new Error('release manifest is missing ' + REV1_PATCH);
      }
      steps.push({ row: index.rev1, source: sourceOf(index.rev1) });
      bytes = Number(index.rev1.source_bytes);
    } else {
      bytes = Number(index.base.source_bytes);
    }
    steps.push({ row: index.base, source: sourceOf(index.base) });
    for (const step of chain(index, labels)) steps.push(step);
    return {
      steps,
      patchNames: steps.map(step => step.row.patch),
      sourceExpect: { bytes },
    };
  }

  return { rowsFrom, index, anchors, sourceOf, ordered, chain,
           canonicalSource, decodeArgs, plan, BASE_PATCH, REV1_PATCH };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = PatchPlan;
