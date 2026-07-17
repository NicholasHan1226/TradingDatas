# Provider-native SQLite additive migration

`provider_dataset_rows` is the single provider-neutral SQLite fact table for
ordinary Tushare and future provider datasets. Fresh databases receive the
canonical 14-column table, composite primary key, JSON/CHECK constraints and
four query indexes through `storage.schema.SCHEMA_SQL`.

Existing databases must **not** receive this table through
`storage/migrate.py`. That legacy runner intentionally excludes the table
because it cannot provide the required atomic postflight. Use only the
dedicated migration after an approved safe-release preflight:

```bash
python3 -m storage.provider_dataset_rows_migration \
  --db /absolute/path/to/existing.sqlite \
  --apply
```

The command refuses a missing database path, a non-regular file, a leaf
symlink, or any symlink/non-directory in the parent chain. It binds the
absolute path to the parent and database device/inode identities, holds a
no-follow descriptor, asks SQLite for a read-write no-follow open, and
revalidates the binding before and after SQLite open, after `BEGIN IMMEDIATE`,
and immediately before commit. An accidental path replacement therefore
fails closed before commit; a replacement detected after transaction start
also rolls the transaction back.

Within that bound path, the command executes `CREATE TABLE IF NOT EXISTS`, the
four `CREATE INDEX IF NOT EXISTS` statements and the complete postflight inside
one `BEGIN IMMEDIATE` transaction. The postflight verifies `table_xinfo`, the
composite primary key, exact index columns, valid JSON object and array
behavior, quality-state checks, and positive schema/revision checks. Any DDL,
binding, or postflight failure rolls the transaction back and exits non-zero.

The migration does not rename, copy, update or delete typed-v1 tables or rows.
After a successful commit, a code rollback can safely leave an unused empty
generic table in place. Dropping the table is a separate destructive operation
and is not part of this migration or its rollback path.

Before production execution, validate the command against a fresh SQLite
backup/canary, capture the production database identity and rollback evidence,
stop if the target has a malformed pre-existing table, and obtain the separate
database-migration authorization required by `AGENTS.md`.
