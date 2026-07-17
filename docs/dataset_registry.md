# Dataset Registry Authority

## Purpose

`config/dataset_registry.yaml` is the **provider-neutral dataset registry** and authority for dataset
identity, schema, provider binding, entitlement, cadence, freshness and query
policy. It lets SharedSignals add providers and datasets without adding public
routes or duplicating policy across collectors, readers, auth and documentation.

The registry is not proof of runtime success. Runtime state comes from current
registry policy plus authoritative SQLite ingest receipts and the read clock.

## Identity and compatibility

- `dataset_id` is stable and provider-neutral, for example `cn.equity.daily`.
- aliases such as `tushare.daily` exist only for compatibility and resolve to one
  canonical dataset.
- provider API names and provider-level transport adapters are internal bindings;
  they are not public dataset identity. Ordinary datasets share one generic
  provider-row table and do not declare a business-table mapping.
- duplicate IDs/aliases, ambiguous bindings and active datasets without a valid
  storage/query mapping fail validation.

## Required contract

Each dataset records:

- domain, market and objective entity type;
- provider-native schema version, fields, declared query types, technical row-key
  fields or payload-hash fallback, and default projection;
- selectable/filterable/sortable fields and bounded operators;
- keyset ordering, page size, lookback and point-in-time capability;
- provider binding and provider-level adapter version;
- for generic bindings, request template, requested provider fields, allowed
  request-window substitutions, and row/byte/depth budgets;
- entitlement state: `active`, `locked`, `unknown`, `excluded`, `retired`;
- cadence class, timezone, freshness SLA, backfill and overlap policy;
- legitimate-empty policy;
- Beta discoverability, tenant scope and quota class.

Secrets, provider tokens, SQL, hostnames and database paths never appear in the
public catalog response.

## Runtime projection

For each registry dataset, the projector reads recognized receipts from the same
SQLite authority and derives exactly one state:

- `success`: latest valid attempt succeeded and remains fresh;
- `empty`: provider legitimately returned no data for the requested window;
- `unobserved`: no recognized receipt exists;
- `paused`: registry/entitlement policy prevents active collection;
- `failed`: latest authoritative attempt failed;
- `stale`: last valid data-through exceeds the registry SLA at read time.

A stored JSON summary cannot override per-dataset entries. Registry changes or
wall-clock transitions must be visible without waiting for a cache rewrite.

## Public API mapping

- `GET /v1/catalog` filters the tenant-visible registry and joins truthful
  runtime availability.
- `POST /v1/query` compiles only registry-declared fields, operators and ordering.
- `/tushare` resolves aliases and calls the same QueryService.
- adding an ordinary Tushare dataset changes only registry/config metadata, not
  Python, fixtures, storage code, query code, adapters, or route count.

## Change workflow

1. add/update only the provider-native registry/config entry;
2. let generic conformance tests enumerate and validate it;
3. prove zero-code provider → generic fact/receipt → catalog/query behavior;
4. update onboarding/capability docs;
5. freeze exact files and receive fresh independent review;
6. release separately from registry implementation and verify real receipts.

The field manifest is a catalog/query allowlist, never an ingest projection.
Unknown fields are still stored. Physical generic facts are isolated by schema
major so compatible minor additions do not hide old rows; each row retains its
ingested full version for lineage. `append_only` uses payload identity and never
updates; `current_snapshot` uses stable native keys with a quality-marked payload
fallback when the key is unusable. Schema-major breaks require a new reviewed
API compatibility plan; production generic-table migration remains separately gated.

## Offline provider-native compiler

`tools/compile_provider_native_registry.py` mechanically combines the current
dataset registry, Tushare capability plan and Tushare collector configuration.
It does not call Tushare, change the default registry, migrate SQLite or activate
any dataset. By default it writes a deterministic candidate/report bundle only
to stdout:

```bash
python tools/compile_provider_native_registry.py
python tools/compile_provider_native_registry.py --kind report
python tools/compile_provider_native_registry.py \
  --kind candidate \
  --output /private/tmp/provider-native-registry.yaml
```

The compiler preserves provider-neutral identity, schema, point-in-time and
query policy, converts exact legacy `{window_key}` parameter placeholders to
`${window.window_key}`, and keeps entitlement/activation unchanged for resolved
entries. Every ordinary Tushare binding emits `requested_fields: []`, so the
generic adapter omits `fields` and receives the complete upstream `fields/items`
envelope. A legacy collector `fields` value is only a diagnostic hint; it never
projects or blocks provider-native ingestion. Missing configuration, duplicate
ownership, non-canonical placeholders or additional provider bindings remain
paused and are listed in the unresolved/conflict report; the compiler never
guesses parameters or adds dataset-specific branches. A generated candidate is
only an input to the separate provider-native target registry and isolated
canary. The legacy default registry remains unchanged during migration. A fresh
compiler review cannot by itself authorize a default-registry or production
switch; that switch requires all backfill, query-parity, consumer-migration,
no-use-observation and rollback evidence listed in
[AGENTS.md](../AGENTS.md#注册表迁移门禁).
