/* Local adapter: runs the production Worker against a SQLite database.
 * Reads one base64 event body per stdin line, writes one status per line. */
import {DatabaseSync} from 'node:sqlite';
import {randomBytes} from 'node:crypto';
import {readFileSync, writeFileSync} from 'node:fs';
import {createInterface} from 'node:readline';
import worker from './worker.mjs';

const database = process.argv[2];
const keyPath = database + '.key';
try { writeFileSync(keyPath, randomBytes(32).toString('hex'), {flag: 'wx', mode: 0o600}); }
catch (error) { if (error.code !== 'EEXIST') throw error; }
const db = new DatabaseSync(database);
const origin = 'http://local-patcher';
const env = {
  ALLOWED_ORIGIN: origin,
  IDENTITY_SECRET: readFileSync(keyPath, 'utf8'),
  DB: {
    prepare: sql => ({bind: (...values) => ({sql, values})}),
    batch: async statements => {
      db.exec('BEGIN');
      try { for (const {sql, values} of statements) db.prepare(sql).run(...values); db.exec('COMMIT'); }
      catch (error) { db.exec('ROLLBACK'); throw error; }
    },
  },
};
for await (const line of createInterface({input: process.stdin})) {
  const response = await worker.fetch(new Request(origin + '/event', {
    method: 'POST', headers: {Origin: origin, 'Content-Type': 'text/plain'},
    body: Buffer.from(line, 'base64'),
  }), env);
  process.stdout.write(response.status + '\n');
}
db.close();
