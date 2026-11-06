'use strict';
/* Node harness for webpatcher/plan.js: the manifest is the whole release
 * graph, so this proves the chain, canonical sources and decode arguments
 * are derived from its columns only. Called by test_webpatcher.py with a
 * synthetic one-row-per-patch manifest.
 *
 *   node webpatcher_plan.js <webpatcher/plan.js>
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const Plan = require(path.resolve(process.argv[2]));

const HEADER = ['patch', 'adds', 'anchor', 'order', 'choices', 'verify',
                'source_bytes', 'source_sha256', 'target_bytes',
                'target_sha256', 'patch_sha256', 'proof_choices',
                'proof_sha256'];

function row(patch, adds, anchor, order, choices) {
  const cells = {
    patch, adds, anchor, order, choices, verify: 'xdelta',
    source_bytes: '100', source_sha256: `src-${patch}`,
    target_bytes: String(100 + (adds === 'saves' ? 10 : 0)),
    target_sha256: `dst-${patch}`, patch_sha256: `file-${patch}`,
    proof_choices: '', proof_sha256: '',
  };
  cells.proof_choices = choices ? [choices, 'decorated'].join(',') : '';
  cells.proof_sha256 = adds ? `proof-${patch}` : '';
  return HEADER.map(name => cells[name]).join('\t');
}

/* The same shape the release emits: one row per patch file. The order
 * column puts in-place options first and the size-changers last. */
const manifest = [
  HEADER.join('\t'),
  row('rev1-to-rev0.xdelta', '', '', '', ''),
  row('rev0-to-base.xdelta', '', '', '', ''),
  row('add-a.xdelta', 'a', '', '0', 'a'),
  row('add-b.xdelta', 'b', '', '1', 'b'),
  row('add-saves.xdelta', 'saves', '', '2', 'saves'),
  row('add-60fps.xdelta', '60fps', '', '3', '60fps'),
  row('add-60fps-saves.xdelta', '60fps', 'saves', '3', 'saves,60fps'),
].join('\n') + '\n';

const rows = Plan.rowsFrom(manifest);
const graph = Plan.index(rows);

assert.deepStrictEqual(graph.labels, ['a', 'b', 'saves', '60fps'],
                       'the grid lists each option once, in apply order');

assert.deepStrictEqual(Plan.sourceOf(graph.base), [],
                       'the base translation is encoded from the retail disc');
assert.deepStrictEqual(Plan.sourceOf(graph.byAdds.get('60fps')[1]),
                       ['saves'],
                       'an anchored row is encoded from the anchor state');
assert.deepStrictEqual(Plan.sourceOf(graph.byAdds.get('a')[0]), [],
                       'an in-place row is encoded from the base state');

function names(steps) {
  return steps.map(step => step.row.patch);
}

/* A selection is applied in order; each option picks the most specific
 * file whose anchor is already applied. */
assert.deepStrictEqual(
    names(Plan.chain(graph, ['60fps', 'a', 'saves'])),
    ['add-a.xdelta', 'add-saves.xdelta', 'add-60fps-saves.xdelta']);
assert.deepStrictEqual(names(Plan.chain(graph, ['60fps', 'a'])),
                       ['add-a.xdelta', 'add-60fps.xdelta'],
                       'without saves, 60 fps uses its base-anchored file');
assert.deepStrictEqual(names(Plan.chain(graph, [])), [],
                       'an empty selection has no add- steps');
assert.deepStrictEqual(names(Plan.chain(graph, ['a', 'b', 'a'])),
                       ['add-a.xdelta', 'add-b.xdelta'],
                       'a duplicate selection applies once');

assert.throws(() => Plan.chain(graph, ['nope']), /no patch for nope/);

/* Canonical-source and decode-argument decisions: the worker uses these
 * exact functions to choose xdelta checksums or -n. */
const inPlace = graph.byAdds.get('a')[0];
assert.strictEqual(
    Plan.canonicalSource({row: inPlace, source: []}, new Set()), true);
assert.strictEqual(
    Plan.canonicalSource({row: inPlace, source: ['a']}, new Set(['a'])), true);
assert.strictEqual(
    Plan.canonicalSource({row: inPlace, source: ['a']}, new Set(['a', 'b'])),
    false, 'extra in-place decorations are not the canonical source');
assert.strictEqual(
    Plan.canonicalSource({row: inPlace, source: ['a']}, new Set(['b'])),
    false, 'same size but different options is not the canonical source');

assert.deepStrictEqual(Plan.decodeArgs({row: inPlace, source: []}, new Set()),
                       ['-d', '-f', '-q']);
assert.deepStrictEqual(
    Plan.decodeArgs({row: inPlace, source: ['a']}, new Set(['a', 'b'])),
    ['-d', '-f', '-q', '-n'],
    'a decorated source decodes without the patch window checksums');

/* The full plan: Rev 1 conversion, then the base translation, then the
 * selected add- rows. sourceExpect is the size of the disc xdelta reads. */
const rev0 = Plan.plan(graph, 0, ['60fps', 'saves']);
assert.deepStrictEqual(rev0.patchNames,
                       ['rev0-to-base.xdelta', 'add-saves.xdelta',
                        'add-60fps-saves.xdelta']);
assert.deepStrictEqual(rev0.sourceExpect, {bytes: 100});
const rev1 = Plan.plan(graph, 1, []);
assert.deepStrictEqual(rev1.patchNames,
                       ['rev1-to-rev0.xdelta', 'rev0-to-base.xdelta']);
assert.deepStrictEqual(rev1.sourceExpect, {bytes: 100},
                       'Rev 1 is identified and converted before the base');

assert.throws(() => Plan.rowsFrom('patch\tchoices\nbase.xdelta\t\n'),
              /unrecognized release manifest/);
assert.throws(() => Plan.rowsFrom(''), /manifest is empty/);

console.log('PLAN_OK');
