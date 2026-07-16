# SQLite Ingest Receipts

## Purpose

An ingest receipt is the immutable, versioned evidence for one provider attempt
or one real SQLite data transaction. Together, SQLite facts and transaction-
scoped receipts are the runtime authority for SharedSignals. These
**transaction-scoped receipts** are inseparable from the fact transaction they
prove.

Flat JSON, logs, dashboards, HTTP status and collector summaries are rebuildable
observations. They cannot establish successful ingestion.

## Atomicity contract

- successful non-empty facts and their success receipt commit in the same SQLite
  transaction;
- receipt insertion failure rolls back that transaction's fact changes;
- each committed chunk has its own receipt and transaction index;
- a later chunk failure does not invent success for that chunk or roll back
  already committed earlier chunks;
- receipt writers never use replace/upsert semantics that rewrite history;
- callers own transaction boundaries; receipt serialization never commits alone.

## Attempt and receipt identity

Each provider call/window receives a unique `attempt_id`. Receipt identity binds:

- dataset ID and provider binding;
- provider API and adapter version;
- request/window and target table;
- attempt ID and transaction index;
- receipt schema version and canonical payload hash.

Same-day reruns use different attempt IDs. Duplicate receipt IDs fail closed.
Secrets, credentials, auth headers and raw SQL are prohibited from receipt data.

## Count semantics

Receipts preserve, without guessing:

- provider returned rows;
- validated/admitted rows;
- inserted, updated and verified-unchanged rows when the adapter can prove them;
- rejected rows and reasons;
- committed rows/transactions;
- target table and data-through boundary.

When a generic writer cannot distinguish insert/update/unchanged honestly, it
uses explicit unknown/null count semantics rather than fabricating zeroes.

## Terminal receipts

When SQLite is available, every attempt ends with evidence:

- legitimate empty;
- provider error;
- permission/entitlement denied;
- rate limited;
- validation failed;
- resource budget exceeded;
- unmapped dataset/adapter;
- storage failed.

Provider errors never become empty. Missing registry, adapter version, trusted
config bytes or target mapping cannot create success.

## Runtime projection and query

The runtime projector reads only recognized receipt schema versions and validates
dataset/binding/adapter/table/count identity before a receipt influences state.
Unknown or inconsistent receipt-like data fails closed.

Public query reads runtime evidence and facts from one SQLite read snapshot. Old
facts may remain queryable after a failed collection, but metadata must report the
latest failed/stale state. When no receipt exists, evidence fields remain null;
the service must not invent IDs or timestamps for consumer compatibility.

## Recovery and cache rebuild

Deleting the optional interface-runtime JSON cache must not change projected
state; it is rebuilt from registry + SQLite receipts + read clock. Recovery must
restore a verified SQLite authority or rebuild from providers with new receipts.
DuckDB and consumer copies are not promoted to authority.

See [sqlite_recovery_runbook.md](sqlite_recovery_runbook.md) for controlled
recovery and [dataset_registry.md](dataset_registry.md) for registry semantics.
