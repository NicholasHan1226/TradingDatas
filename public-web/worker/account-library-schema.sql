-- Additive account-only schema. Apply separately after review; never a data-plane DB.
CREATE TABLE IF NOT EXISTS account_bookmarks (
  user_id TEXT NOT NULL REFERENCES identity_users(id) ON DELETE CASCADE,
  resource_key TEXT NOT NULL CHECK(length(resource_key) BETWEEN 3 AND 180),
  created_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, resource_key)
);
CREATE TRIGGER IF NOT EXISTS account_bookmark_limit
BEFORE INSERT ON account_bookmarks
WHEN NOT EXISTS (SELECT 1 FROM account_bookmarks WHERE user_id=NEW.user_id AND resource_key=NEW.resource_key)
 AND (SELECT COUNT(*) FROM account_bookmarks WHERE user_id=NEW.user_id)>=500
BEGIN SELECT RAISE(ABORT, 'library_full'); END;

CREATE TABLE IF NOT EXISTS account_connections (
  user_id TEXT PRIMARY KEY REFERENCES identity_users(id) ON DELETE CASCADE,
  credential_box TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
-- Revocation survives feature-flag changes and rollback to the identity-only code.
CREATE TRIGGER IF NOT EXISTS account_connection_revoke_on_disable
AFTER UPDATE OF disabled_at ON identity_users WHEN NEW.disabled_at IS NOT NULL
BEGIN DELETE FROM account_connections WHERE user_id=NEW.id; END;
