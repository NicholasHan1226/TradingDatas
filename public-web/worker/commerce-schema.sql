-- ISOLATED SANDBOX ONLY. Never apply to IDENTITY_DB or financial facts SQLite.
-- Opaque owner references intentionally have no identity-table FK: this test store
-- cannot change production identity deletion or retain production payment records.
CREATE TABLE IF NOT EXISTS commerce_orders (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
 offer_id TEXT NOT NULL, offer_version TEXT NOT NULL, tier TEXT NOT NULL,
 period TEXT NOT NULL, currency TEXT NOT NULL, amount_minor INTEGER NOT NULL,
 term_days INTEGER NOT NULL, terms_version TEXT NOT NULL, requests_per_minute INTEGER NOT NULL,
 payment_state TEXT NOT NULL DEFAULT 'pending',
 provisioning_state TEXT NOT NULL DEFAULT 'not_provisioned', created_at INTEGER NOT NULL,
 UNIQUE(owner_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS commerce_events (
 event_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES commerce_orders(id),
 currency TEXT NOT NULL, amount_minor INTEGER NOT NULL, verified_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS commerce_subscriptions (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL UNIQUE, tier TEXT NOT NULL,
 period TEXT NOT NULL, starts_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
 terms_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS commerce_provisions (
 order_id TEXT PRIMARY KEY REFERENCES commerce_orders(id), state TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, completed_at INTEGER
);
