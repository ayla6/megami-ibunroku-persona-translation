import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import worker, {rows} from './worker.mjs';
const id = () => crypto.randomUUID();
const build = () => ({t: 'build', b: id(), v: id(), id: id(), rel: 'patches-2026-11-25', prev: '2026-11-24',
  out: 'ppf', src: 'chd', dir: true, mods: {kept: 'b=2,a=1', added: ''}, was: {kept: 'a=1', gone: ''},
  chg: {kept: 'b', added: ''}});
const NOW = '2026-11-25T12:34:56Z';

test('a build becomes visit, build and one row per mod on either side', () => {
  const s = rows(build(), 'h', NOW);
  assert.equal(s.length, 5);
  assert.equal(s[0][3], '2026-11-25');
  assert.deepEqual(s[1].slice(-2), [1, NOW]);
  const mods = Object.fromEntries(s.slice(2).map(r => [r[2], r.slice(3)]));
  assert.deepEqual(mods, {kept: ['a=1,b=2', 'a=1', 'b'], added: ['', null, ''], gone: [null, '', null]});
  assert.equal(rows({...build(), was: null}, 'h', NOW)[1].at(-2), 0);
  assert.equal(rows({...build(), chg: undefined}, 'h', NOW)[2].at(-1), null);  // older pages: unknown
});
test('invalid fields are rejected', () => {
  for (const bad of [{mods: {'x y': ''}}, {mods: {x: 'private file'}}, {out: 'zip'}, {prev: 'nope'}, {v: 'x'}])
    assert.equal(rows({...build(), ...bad}, 'h', NOW), null);
});
test('referrer keeps only the origin', () => {
  assert.equal(rows({t: 'visit', v: id(), r: 'https://a.example/x?token=1'}, 'h', NOW)[0][4], 'https://a.example');
  assert.equal(rows({t: 'visit', v: id(), r: 'file:///x'}, 'h', NOW), null);
});
test('origin, size and identity hashing', async () => {
  let saved;
  const env = {ALLOWED_ORIGIN: 'https://o.example', IDENTITY_SECRET: 's'.repeat(32),
    DB: {prepare: sql => ({bind: (...v) => [sql, ...v]}), batch: async s => { saved = s; }}};
  const req = (body, origin = env.ALLOWED_ORIGIN) => new Request('https://c/event', {method: 'POST',
    headers: {Origin: origin, 'Content-Type': 'text/plain'}, body});
  const data = build();
  assert.equal((await worker.fetch(req(JSON.stringify(data)), env)).status, 204);
  assert.match(saved[0][2], /^[0-9a-f]{16}$/);
  assert.ok(!JSON.stringify(saved).includes(data.b));
  assert.equal((await worker.fetch(req('{}', 'https://x.example'), env)).status, 403);
  assert.equal((await worker.fetch(req(JSON.stringify(build())), {...env, IDENTITY_SECRET: ''})).status, 500);
  assert.equal((await worker.fetch(req('a'.repeat(9000)), env)).status, 413);
  let left = 1;
  const limited = {...env, LIMITER: {limit: async () => ({success: left-- > 0})}};
  saved = null;
  assert.equal((await worker.fetch(req(JSON.stringify(build())), limited)).status, 204);
  assert.ok(saved);
  saved = null;
  assert.equal((await worker.fetch(req(JSON.stringify(build())), limited)).status, 204);
  assert.equal(saved, null); // over the limit: same answer, nothing written
});

function client(store = new Map(), referrer = '') {
  const on = {}, sent = [];
  const toggle = {addEventListener: (n, f) => { on[n] = f; }};
  const context = {crypto, URL, window: {addEventListener: (n, f) => { on[n] = f; }},
    document: {referrer, querySelector: () => ({content: 'https://c/event'}), getElementById: () => toggle},
    localStorage: {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: k => store.delete(k)},
    fetch: async (_, o) => { sent.push(JSON.parse(o.body)); }};
  vm.runInNewContext(readFileSync(new URL('../../webpatcher/analytics.js', import.meta.url), 'utf8'), context);
  return {api: context.PatcherAnalytics, toggle, on, sent, store};
}
test('opt-out persists and stops builds; the payload passes the worker', () => {
  const c = client(new Map(), 'https://a.example/p');
  assert.equal(c.sent[0].r, 'https://a.example');
  const base = {release: '2026-11-25', output: 'ppf', source: 'bin', folder: true,
    selection: {kept: ['b=2', 'c=on'], mine: []}, labels: ['kept', 'gone'], defaults: () => ['b=1', 'c=on']};
  c.api.complete({...base, note: '2026-11-24\nkept(b=1)\ngone\nown x.p1mod\ncheck 0123abcd\n'});
  c.api.complete({...base, note: ''});  // unsigned or edited: app.js passes ''
  assert.equal(c.sent[2].was, null); assert.equal(c.sent[2].prev, '');
  const b = c.sent[1];
  assert.deepEqual({...b.mods}, {kept: 'b=2,c=on'});
  assert.deepEqual({...b.chg}, {kept: 'b'});
  assert.deepEqual({...b.was}, {kept: 'b=1', gone: ''});
  assert.equal(b.prev, '2026-11-24');
  assert.ok(rows(b, 'h', NOW));
  c.toggle.checked = false; c.on.change();
  const count = c.sent.length;
  c.api.complete({release: 'x', output: 'disc', source: 'bin', folder: false, selection: {}, labels: [], defaults: () => []});
  assert.equal(c.sent.length, count);
  assert.equal(c.store.has('patcher.analytics.browser'), false);
  assert.equal(client(c.store).sent.length, 0);
});
