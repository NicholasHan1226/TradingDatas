-- Candidate ACCOUNT-ONLY schema. Never apply to financial facts SQLite.
-- No production binding/migration is enabled by this file.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS identity_users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL,
  disabled_at INTEGER
);
CREATE TABLE IF NOT EXISTS identity_challenges (
  email_hash TEXT PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,
  email TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  accepted INTEGER NOT NULL DEFAULT 0,
  consumed_at INTEGER
);
CREATE INDEX IF NOT EXISTS identity_challenge_expiry ON identity_challenges(expires_at);
CREATE TABLE IF NOT EXISTS identity_sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES identity_users(id),
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  revoked_at INTEGER
);
CREATE INDEX IF NOT EXISTS identity_session_expiry ON identity_sessions(expires_at);
CREATE TABLE IF NOT EXISTS identity_rate_buckets (
  bucket_key TEXT PRIMARY KEY,
  hits INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS identity_rate_expiry ON identity_rate_buckets(expires_at);
CREATE TABLE IF NOT EXISTS identity_send_cooldowns (
  email_hash TEXT PRIMARY KEY,
  next_send_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS identity_cooldown_expiry ON identity_send_cooldowns(next_send_at);
