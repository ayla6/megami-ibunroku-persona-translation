'use strict';
/* Node harness for webpatcher/plan.js: the manifest is the whole release
 * graph, so this proves the chain, canonical sources and decode arguments
 * are derived from its columns only. Called by test_webpatcher.py with a
 * synthetic manifest shaped like the release: size-changers first, then
 * in-place options, each in-place option with one row per size-changer
 * layout.
 *
 *   node webpatcher_plan.js <webpatcher/plan.js>
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const Plan = require(path.resolve(process.argv[2]));

const HEADER = ['patch', 'adds', 'anchor', 'order', 'choices', 'verify',
                'source_bytes', 'source_sha256', 'target_bytes',
                'target_sha256', 'patch_sha256', 'verified'];

function row(patch, adds, anchor, order, choices) {
  const cells = {
    patch, adds, anchor, order, choices, verify: 'xdelta',
    source_bytes: '100', source_sha256: `src-${patch}`,
    target_bytes: String(100 + (adds === 'saves' ? 10 : 0)),
    target_sha256: `dst-${patch}`, patch_sha256: `file-${patch}`,
    verified: '',
  };
  return HEADER.map(name => cells[name]).join('\t');
}

/* The same shape the release emits: one row per patch file. The order
 * column puts the size-changers first and the in-place options last; an
 * in-place row exists for every size-changer layout it can be added to. */
const manifest = [
  HEADER.join('\t'),
  row('rev1-to-rev0.xdelta', '', '', '', ''),
  row('rev0-to-base.xdelta', '', '', '', ''),
  row('add-saves.xdelta', 'saves', '', '0', 'saves'),
  row('add-60fps.xdelta', '60fps', '', '1', '60fps'),
  row('add-60fps-saves.xdelta', '60fps', 'saves', '1', 'saves,60fps'),
  row('add-a.xdelta', 'a', '', '2', 'a'),
  row('add-a-saves.xdelta', 'a', 'saves', '2', 'saves,a'),
  row('add-a-60fps.xdelta', 'a', '60fps', '2', '60fps,a'),
  row('add-a-60fps-saves.xdelta', 'a', 'saves,60fps', '2', 'saves,60fps,a'),
  row('add-b.xdelta', 'b', '', '3', 'b'),
  row('add-b-saves.xdelta', 'b', 'saves', '3', 'saves,b'),
  row('add-b-60fps.xdelta', 'b', '60fps', '3', '60fps,b'),
  row('add-b-60fps-saves.xdelta', 'b', 'saves,60fps', '3', 'saves,60fps,b'),
].join('\n') + '\n';

const rows = Plan.rowsFrom(manifest);
const graph = Plan.index(rows);

assert.deepStrictEqual(graph.labels, ['saves', '60fps', 'a', 'b'],
                       'the grid lists each option once, in apply order');

assert.deepStrictEqual(Plan.sourceOf(graph.base), [],
                       'the base translation is encoded from the retail disc');
assert.deepStrictEqual(Plan.sourceOf(graph.byAdds.get('60fps')[1]),
                       ['saves'],
                       'an anchored size-changer is encoded from the anchor');
assert.deepStrictEqual(Plan.sourceOf(graph.byAdds.get('a')[3]),
                       ['saves', '60fps'],
                       'an in-place row is encoded from its size-changer layout');

function names(steps) {
  return steps.map(step => step.row.patch);
}

/* A selection is applied in order; each option picks the most specific
 * file whose anchor is already applied. Size-changers always precede the
 * in-place options, whatever order the user picked them in. */
assert.deepStrictEqual(
    names(Plan.chain(graph, ['60fps', 'a', 'saves'])),
    ['add-saves.xdelta', 'add-60fps-saves.xdelta',
     'add-a-60fps-saves.xdelta']);
assert.deepStrictEqual(
    names(Plan.chain(graph, ['a', 'saves', '60fps'])),
    ['add-saves.xdelta', 'add-60fps-saves.xdelta',
     'add-a-60fps-saves.xdelta'],
    'the apply order is fixed by the manifest, not the selection');
assert.deepStrictEqual(names(Plan.chain(graph, ['60fps', 'a'])),
                       ['add-60fps.xdelta', 'add-a-60fps.xdelta'],
                       'without saves, both use their base-anchored files');
assert.deepStrictEqual(names(Plan.chain(graph, ['saves', 'b'])),
                       ['add-saves.xdelta', 'add-b-saves.xdelta'],
                       'an in-place row follows the size-changer it was'
                       + ' encoded against');
assert.deepStrictEqual(names(Plan.chain(graph, [])), [],
                       'an empty selection has no add- steps');
assert.deepStrictEqual(names(Plan.chain(graph, ['a', 'b', 'a'])),
                       ['add-a.xdelta', 'add-b.xdelta'],
                       'a duplicate selection applies once');

assert.throws(() => Plan.chain(graph, ['nope']), /no patch for nope/);

/* Canonical-source and decode-argument decisions: the worker uses these
 * exact functions to choose xdelta checksums or -n. */
const inPlace = graph.byAdds.get('a')[0];
const anchoredInPlace = graph.byAdds.get('a')[1];
assert.strictEqual(
    Plan.canonicalSource({row: inPlace, source: []}, new Set()), true);
assert.strictEqual(
    Plan.canonicalSource({row: anchoredInPlace, source: ['saves']},
                         new Set(['saves'])), true,
    'the size-changer layout is this row\'s canonical source');
assert.strictEqual(
    Plan.canonicalSource({row: anchoredInPlace, source: ['saves']},
                         new Set(['saves', 'b'])), false,
    'extra in-place decorations are not the canonical source');
assert.strictEqual(
    Plan.canonicalSource({row: anchoredInPlace, source: ['saves']},
                         new Set(['60fps'])), false,
    'same size but a different layout is not the canonical source');

assert.deepStrictEqual(Plan.decodeArgs(
    {row: anchoredInPlace, source: ['saves']}, new Set(['saves'])),
    ['-d', '-f', '-q']);
assert.deepStrictEqual(
    Plan.decodeArgs({row: anchoredInPlace, source: ['saves']},
                    new Set(['saves', 'b'])),
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
