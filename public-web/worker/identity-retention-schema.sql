-- Additive ACCOUNT-ONLY migration; never run against financial facts SQLite.
-- Explicitly apply to the dedicated identity store before retention activation.
CREATE TABLE IF NOT EXISTS identity_deletion_requests (
  user_id TEXT PRIMARY KEY REFERENCES identity_users(id),
  requested_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS identity_deletion_requested ON identity_deletion_requests(requested_at);
