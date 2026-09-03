import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { identityDb } from './helpers/identity-db.mjs';
import { runIdentityMaintenance } from '../worker/identity-retention.js';
import worker from '../worker/index.js';

const now = 1_800_000_000;
function setup() {
  const db = identityDb();
  return { db, env: { IDENTITY_DB: db, IDENTITY_RETENTION_ENABLED: 'true' } };
}
function user(db, id, disabled = null) {
  db.sqlite.prepare('INSERT INTO identity_users VALUES (?,?,?,?)').run(id, `${id}@example.com`, now - 86400, disabled);
}
function session(db, id, uid, expires, revoked = null) {
  db.sqlite.prepare('INSERT INTO identity_sessions VALUES (?,?,?,?,?)').run(id, uid, now - 100, expires, revoked);
}
test('maintenance is explicitly configured and does not need delivery secrets', async () => {
  assert.deepEqual(await runIdentityMaintenance({}, now), { state: 'disabled' });
  await assert.rejects(runIdentityMaintenance({ IDENTITY_RETENTION_ENABLED: 'true' }, now), /identity_maintenance_unavailable/);
  const config = JSON.parse(readFileSync(new URL('../wrangler.jsonc', import.meta.url)));
  assert.equal(config.vars.IDENTITY_RETENTION_ENABLED, 'true');
  assert.equal(config.vars.EMAIL_LOGIN_ENABLED, 'true');
  assert.deepEqual(config.triggers.crons, ['17 * * * *']);
});
test('expiry cleanup preserves active sessions, challenges and all non-requested profiles', async () => {
  const {db,env} = setup(); user(db, 'active'); user(db, 'disabled', now - 10);
  session(db, 'active-token', 'active', now + 1);
  session(db, 'expired-token', 'active', now);
  session(db, 'revoked-token', 'active', now + 500, now - 1);
  session(db, 'disabled-token', 'disabled', now + 500);
  for (const [id, expiry] of [['old', now], ['current', now + 1]]) {
    db.sqlite.prepare('INSERT INTO identity_challenges VALUES (?,?,?,?,?,0,1,NULL)').run(id, id, `${id}@example.com`, 'hash', expiry);
    db.sqlite.prepare('INSERT INTO identity_rate_buckets VALUES (?,1,?)').run(id, expiry);
    db.sqlite.prepare('INSERT INTO identity_send_cooldowns VALUES (?,?)').run(id, expiry);
  }
  const result = await runIdentityMaintenance(env, now);
  assert.equal(result.state, 'complete');
  assert.equal(result.deleted.sessions, 3);
  assert.equal(result.deleted.challenges, 1);
  assert.equal(db.sqlite.prepare('SELECT count(*) n FROM identity_users').get().n, 2);
  assert.equal(db.sqlite.prepare('SELECT token_hash FROM identity_sessions').get().token_hash, 'active-token');
  assert.equal(db.sqlite.prepare('SELECT id FROM identity_challenges').get().id, 'current');
  assert.equal((await runIdentityMaintenance(env, now)).deleted.sessions, 0);
});
test('only explicitly requested disabled profiles are purged with their sessions and challenges', async () => {
  const {db,env} = setup(); user(db, 'remove', now); user(db, 'keep'); user(db, 'suspended', now);
  session(db, 'remove-token', 'remove', now + 500);
  session(db, 'keep-token', 'keep', now + 500);
  db.sqlite.prepare('INSERT INTO identity_deletion_requests VALUES (?,?)').run('remove', now);
  db.sqlite.prepare('INSERT INTO identity_challenges VALUES (?,?,?,?,?,0,1,NULL)').run('hash', 'id', 'remove@example.com', 'code-hash', now + 100);
  const result = await runIdentityMaintenance(env, now);
  assert.equal(result.deleted.profiles, 1);
  assert.equal(db.sqlite.prepare('SELECT count(*) n FROM identity_deletion_requests').get().n, 0);
  assert.equal(db.sqlite.prepare('SELECT count(*) n FROM identity_challenges').get().n, 0);
  assert.deepEqual(db.sqlite.prepare('SELECT id FROM identity_users ORDER BY id').all().map(row => row.id), ['keep', 'suspended']);
  assert.equal((await runIdentityMaintenance(env, now)).deleted.profiles, 0);
});
test('bounded cleanup reports backlog instead of claiming completion', async () => {
  const {db,env} = setup();
  const insert = db.sqlite.prepare('INSERT INTO identity_rate_buckets VALUES (?,1,?)');
  for(let i=0;i<8001;i++) insert.run(`expired-${i}`, now - 1);
  const result = await runIdentityMaintenance(env, now);
  assert.equal(result.state, 'backlog');
  assert.equal(result.deleted.rate_buckets, 8000);
  assert.equal(result.pending.rate_buckets, true);
  assert.equal((await runIdentityMaintenance(env, now)).state, 'complete');
});
test('a failed profile purge is atomic and can be retried', async () => {
  const {db,env} = setup(); user(db, 'retry', now); session(db, 'retry-token', 'retry', now+100);
  db.sqlite.prepare('INSERT INTO identity_deletion_requests VALUES (?,?)').run('retry', now);
  db.sqlite.exec("CREATE TRIGGER reject_purge BEFORE DELETE ON identity_users BEGIN SELECT RAISE(ABORT,'fixture failure'); END;");
  await assert.rejects(runIdentityMaintenance(env, now));
  assert.equal(db.sqlite.prepare('SELECT count(*) n FROM identity_users').get().n, 1);
  assert.equal(db.sqlite.prepare('SELECT count(*) n FROM identity_deletion_requests').get().n, 1);
  // Session may already be pruned as invalid, but the durable deletion request survives.
  db.sqlite.exec('DROP TRIGGER reject_purge');
  assert.equal((await runIdentityMaintenance(env, now)).deleted.profiles, 1);
});

test('additive migration is repeatable and missing migration fails closed', async () => {
  const {db,env} = setup(); user(db, 'keep');
  db.sqlite.exec(readFileSync(new URL('../worker/identity-retention-schema.sql', import.meta.url), 'utf8'));
  assert.equal(db.sqlite.prepare('SELECT count(*) n FROM identity_users').get().n, 1);
  db.sqlite.exec('DROP TABLE identity_deletion_requests');
  await assert.rejects(runIdentityMaintenance(env, now));
  assert.equal(db.sqlite.prepare('SELECT count(*) n FROM identity_users').get().n, 1);
});

test('scheduled handler awaits maintenance and never exposes database errors', async (t) => {
  const log = t.mock.method(console, 'log', () => {});
  await worker.scheduled({}, {});
  assert.deepEqual(JSON.parse(log.mock.calls[0].arguments[0]), { event: 'identity_retention', state: 'disabled' });
  await assert.rejects(worker.scheduled({}, { IDENTITY_RETENTION_ENABLED: 'true', IDENTITY_DB: { prepare() { throw new Error('private fixture detail'); } } }), { message: 'identity_retention_incomplete' });
  assert.equal(log.mock.callCount(), 1);
});
