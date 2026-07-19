# Retired Tushare Activation Backlog

Last updated: 2026-07-19

> **Retired migration inventory — not executable and not runtime authority.**
> This path remains temporarily only because legacy compatibility documents and
> consumers still link to it. The former hand-maintained `114/113 scheduled/0
> planned` instructions were removed because they were neither a complete
> Tushare capability catalog nor proof of entitlement, collection, freshness, or
> queryability. Do not use this file to activate a dataset, modify a collector,
> add a table/route, or install a schedule.

The active decisions are now:

- [ADR-0009](adr/ADR-0009-tushare-capability-cadence-retirement.md) for the
  pinned official capability baseline, generic request shapes, cadence/backfill,
  and retirement gates;
- [dataset_registry.md](dataset_registry.md) for provider-native registry
  authority and zero-code onboarding;
- [data_source_onboarding.md](data_source_onboarding.md) for dataset acceptance;
- [../STATUS.md](../STATUS.md) for current Git and production evidence.

The legacy 114-name list is only a compatibility input. At the pinned official
source commit used by ADR-0009, the reviewed upstream index contains 239 unique
API names. Every API needs an explicit scope/entitlement classification, while
ordinary read datasets continue through one generic Tushare transport, one
provider-row SQLite/receipt path, and the fixed `GET /v1/catalog` plus
`POST /v1/query` data plane.

This temporary tombstone is deleted only after all references have migrated and
the legacy lane has completed stop-write, no-use, and rollback verification.
Deleting this document never authorizes deleting databases, facts, receipts,
journals, audit evidence, or rollback artifacts.
