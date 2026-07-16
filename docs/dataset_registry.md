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
- provider API names, SQLite tables and adapters are internal bindings; they are
  not public dataset identity.
- duplicate IDs/aliases, ambiguous bindings and active datasets without a valid
  storage/query mapping fail validation.

## Required contract

Each dataset records:

- domain, market and objective entity type;
- canonical schema version, fields, types, primary key and default projection;
- selectable/filterable/sortable fields and bounded operators;
- keyset ordering, page size, lookback and point-in-time capability;
- provider binding, adapter version and target fact table;
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
- adding a dataset changes the registry and internal adapters, not route count.

## Change workflow

1. add a registry contract test and make it fail;
2. add/update the canonical entry and adapter binding;
3. prove fact/receipt atomicity and runtime projection;
4. prove catalog/query behavior and tenant policy;
5. update onboarding/capability docs;
6. freeze exact files and receive fresh independent review;
7. release separately from registry implementation and verify real receipts.

Schema-major breaks require a new reviewed API/storage compatibility plan. A
dataset remains non-active when current storage cannot represent it losslessly.
