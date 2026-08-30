import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';

// Real in-memory SQLite, exposing only the D1 calls used by the identity slice.
export function identityDb() {
  const sqlite = new DatabaseSync(':memory:');
  sqlite.exec(readFileSync(new URL('../../worker/identity-schema.sql', import.meta.url), 'utf8'));
  const db = {
    sqlite,
    prepare(sql) {
      let args = [];
      const statement = {
        bind(...values) { args = values; return statement; },
        async first() { return sqlite.prepare(sql).get(...args) ?? null; },
        async run() { return { success: true, meta: sqlite.prepare(sql).run(...args) }; },
        async all() { return { success: true, results: sqlite.prepare(sql).all(...args) }; },
        execute() { return { success: true, results: sqlite.prepare(sql).all(...args) }; },
      };
      return statement;
    },
    async batch(statements) {
      sqlite.exec('BEGIN');
      try { const results = statements.map((statement) => statement.execute()); sqlite.exec('COMMIT'); return results; }
      catch (error) { sqlite.exec('ROLLBACK'); throw error; }
    },
  };
  return db;
}
