/* Public write-only collector. Stores no IP, user agent, URL query or file data. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TOKEN = /^[a-zA-Z0-9_.-]{1,64}$/;
const OPTIONS = /^(?:[a-zA-Z0-9_=.-]{1,64}(?:,[a-zA-Z0-9_=.-]{1,64}){0,49})?$/;
export const RELEASE = /^(?:patches-)?[0-9]{4}-[0-9]{2}-[0-9]{2}(?:-[0-9]+)?$/;
export const MAX_BYTES = 8000;

function modMap(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const entries = Object.entries(value);
  if (entries.length > 100) return null;
  for (const [mod, options] of entries)
    if (!TOKEN.test(mod) || typeof options !== 'string' || !OPTIONS.test(options)) return null;
  return new Map(entries.map(([mod, options]) => [mod, options.split(',').filter(Boolean).sort().join(',')]));
}

/* Returns the statements to run, as [sql, ...values] lists, or null if invalid. */
export function rows(data, visitor, now) {
  const day = now.slice(0, 10);
  if (!data || !UUID.test(data.v)) return null;
  const visit = ['INSERT OR IGNORE INTO visits (visit, visitor, day, referrer) VALUES (?, ?, ?, ?)',
    data.v, visitor, day];
  if (data.t === 'visit') {
    let referrer = '';
    if (data.r) {
      try {
        const url = new URL(String(data.r).slice(0, 2000));
        if (!['http:', 'https:'].includes(url.protocol)) return null;
        referrer = url.origin;
      } catch (_) { return null; }
    }
    return [[...visit, referrer]];
  }
  if (data.t !== 'build' || !UUID.test(data.id) || !TOKEN.test(data.rel ?? '')
      || !(data.prev === '' || RELEASE.test(data.prev ?? ''))
      || !['ppf', 'disc'].includes(data.out) || !['bin', 'chd'].includes(data.src)
      || typeof data.dir !== 'boolean') return null;
  const mods = modMap(data.mods);
  const was = data.was == null ? null : modMap(data.was);
  const changed = data.chg == null ? new Map() : modMap(data.chg);
  if (!mods || (data.was != null && !was) || !changed) return null;
  const statements = [[...visit, ''],
    ['INSERT OR IGNORE INTO builds (build, visit, release, previous, output, source, folder, known, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
     data.id, data.v, data.rel, data.prev, data.out, data.src, data.dir ? 1 : 0, was ? 1 : 0, now]];
  for (const mod of new Set([...mods.keys(), ...(was?.keys() ?? [])]))
    statements.push(['INSERT OR IGNORE INTO build_mods (build, mod, options, was, changed) VALUES (?, ?, ?, ?, ?)',
      data.id, mod, mods.get(mod) ?? null, was?.get(mod) ?? null,
      mods.has(mod) ? changed.get(mod) ?? null : null]);
  return statements;
}

async function readBody(request) {
  const reader = request.body?.getReader();
  if (!reader) return null;
  const chunks = [];
  let size = 0;
  for (;;) {
    const {value, done} = await reader.read();
    if (done) break;
    size += value.length;
    if (size > MAX_BYTES) { await reader.cancel(); return undefined; }
    chunks.push(value);
  }
  return new Blob(chunks).text();
}

let hmac = null; // imported once per isolate, not per request
async function visitorOf(browser, secret) {
  hmac ??= crypto.subtle.importKey('raw', new TextEncoder().encode(secret),
    {name: 'HMAC', hash: 'SHA-256'}, false, ['sign']).catch(error => { hmac = null; throw error; });
  const digest = new Uint8Array(await crypto.subtle.sign('HMAC', await hmac, new TextEncoder().encode(browser)));
  return Array.from(digest.slice(0, 8), b => b.toString(16).padStart(2, '0')).join('');
}

export default {
  async fetch(request, env) {
    // A deploy without its secret would hash every visitor with the same
    // missing key; refuse loudly instead of collecting unusable counts.
    if (!env.IDENTITY_SECRET || env.IDENTITY_SECRET.length < 32) return new Response(null, {status: 500});
    const origin = request.headers.get('Origin');
    if (origin !== env.ALLOWED_ORIGIN) return new Response(null, {status: 403});
    const reply = status => new Response(null, {status, headers: {
      'Access-Control-Allow-Origin': origin, 'Vary': 'Origin', 'Cache-Control': 'no-store'}});
    if (new URL(request.url).pathname !== '/event') return reply(404);
    if (request.method !== 'POST') return reply(405);
    if (!request.headers.get('Content-Type')?.startsWith('text/plain')) return reply(415);
    // Per-IP budget, invisible to the visitor, counted in Cloudflare's memory only; the IP is never stored.
    if (env.LIMITER) {
      const {success} = await env.LIMITER.limit({key: request.headers.get('CF-Connecting-IP') || ''});
      if (!success) return reply(204); // dropped silently: looks like any other report
    }
    const body = await readBody(request);
    if (body === undefined) return reply(413);
    let data;
    try { data = JSON.parse(body); } catch (_) { return reply(400); }
    if (!UUID.test(data?.b)) return reply(400);
    const visitor = await visitorOf(data.b, env.IDENTITY_SECRET);
    const statements = rows(data, visitor, new Date().toISOString().slice(0, 19) + 'Z');
    if (!statements) return reply(400);
    try {
      await env.DB.batch(statements.map(([sql, ...values]) => env.DB.prepare(sql).bind(...values)));
    } catch (_) { return reply(204); } // a full or failing database also answers like success
    return reply(204);
  },
};
