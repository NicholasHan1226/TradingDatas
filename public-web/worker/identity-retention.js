// Account-only maintenance. No outbound network, financial tables or credentials.
const BATCH = 1000;
const MAX_BATCHES = 8;
const PROFILE_BATCH = 100;
const TABLES = [
  ['challenges', 'identity_challenges', 'id', 'expires_at<=?'],
  ['sessions', 'identity_sessions', 'token_hash', '(expires_at<=? OR revoked_at IS NOT NULL OR user_id IN (SELECT id FROM identity_users WHERE disabled_at IS NOT NULL))'],
  ['rate_buckets', 'identity_rate_buckets', 'bucket_key', 'expires_at<=?'],
  ['cooldowns', 'identity_send_cooldowns', 'email_hash', 'next_send_at<=?'],
];
// Identifiers/predicates above are private constants, never HTTP input.
export async function runIdentityMaintenance(env, now = Math.floor(Date.now() / 1000)) {
  if (env.IDENTITY_RETENTION_ENABLED !== 'true') return { state: 'disabled' };
  if (!env.IDENTITY_DB || !Number.isSafeInteger(now) || now <= 0) throw new Error('identity_maintenance_unavailable');
  const db = env.IDENTITY_DB;
  const deleted = { profiles: 0 };
  const pending = {};
  for (const [key, table, pk, predicate] of TABLES) {
    deleted[key] = 0;
    for (let i = 0; i < MAX_BATCHES; i++) {
      const result = await db.prepare(`DELETE FROM ${table} WHERE ${pk} IN (SELECT ${pk} FROM ${table} WHERE ${predicate} LIMIT ?)`)
        .bind(now, BATCH).run();
      const count = result.meta?.changes;
      if (!Number.isSafeInteger(count) || count < 0) throw new Error('identity_maintenance_unavailable');
      deleted[key] += count;
      if (count < BATCH) break;
    }
    pending[key] = Boolean(await db.prepare(`SELECT 1 FROM ${table} WHERE ${predicate} LIMIT 1`).bind(now).first());
  }
  const profiles = await db.prepare(`SELECT u.id FROM identity_deletion_requests r JOIN identity_users u ON u.id=r.user_id
    WHERE u.disabled_at IS NOT NULL AND r.requested_at<=? ORDER BY r.requested_at LIMIT ?`).bind(now, PROFILE_BATCH).all();
  for (const {id} of profiles.results) {
    // The durable request is removed only in the same transaction as the profile.
    const results = await db.batch([
      db.prepare('DELETE FROM identity_challenges WHERE email=(SELECT email FROM identity_users WHERE id=? AND disabled_at IS NOT NULL)').bind(id),
      db.prepare('DELETE FROM identity_sessions WHERE user_id IN (SELECT id FROM identity_users WHERE id=? AND disabled_at IS NOT NULL)').bind(id),
      db.prepare('DELETE FROM identity_deletion_requests WHERE user_id IN (SELECT id FROM identity_users WHERE id=? AND disabled_at IS NOT NULL)').bind(id),
      db.prepare('DELETE FROM identity_users WHERE id=? AND disabled_at IS NOT NULL RETURNING id').bind(id),
    ]);
    deleted.profiles += results[3].results.length;
  }
  // Even an inconsistent non-disabled request must be visible, never silently lost.
  pending.profiles = Boolean(await db.prepare('SELECT 1 FROM identity_deletion_requests WHERE requested_at<=? LIMIT 1').bind(now).first());
  return { state: Object.values(pending).some(Boolean) ? 'backlog' : 'complete', deleted, pending };
}
