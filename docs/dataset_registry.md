# Dataset Registry Authority

## Purpose

The provider-native contract set is the authority for target dataset identity,
schema, provider binding, cadence, freshness and query policy. The
provider-neutral dataset registry is materialized from that contract set. During migration
that authority is assembled from the reviewed upstream-contract bundle,
`config/provider_native_activation.yaml`, and the deterministically generated
`config/provider_native_dataset_registry.yaml`. The default
`config/dataset_registry.yaml` is legacy compatibility input only; it cannot
activate or define a target provider-native dataset. This split lets
SharedSignals add providers and datasets without adding public routes or
duplicating policy across collectors, readers, auth and documentation.

Neither registry is proof of runtime success. Target runtime state comes from
the process-selected provider-native registry policy plus authoritative SQLite
ingest receipts and the read clock.

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

`tools/compile_provider_native_registry.py` combines the current provider-neutral
identity registry with a versioned, reviewed Tushare upstream-contract bundle.
The old capability plan and collector configuration are migration diagnostics;
they are not provider-native schema authority. The compiler does not call
Tushare, change the default registry, migrate SQLite or activate any dataset. By
default it writes a deterministic candidate/report bundle only to stdout:

```bash
python tools/compile_provider_native_registry.py
python tools/compile_provider_native_registry.py --kind report
python tools/compile_provider_native_registry.py \
  --kind candidate \
  --output /private/tmp/provider-native-registry.yaml
```

The upstream-contract bundle freezes official-document provenance, provider-native
fields, approved logical query types, stable keys/time fields, request-window
strategy, completeness policy, cadence and resource budgets. The compiler must
replace an inherited legacy schema with this reviewed inline contract. It must
never infer provider-native fields, keys or freshness from an old typed table or
from one live response.

Response completeness is a registry contract, not dataset-specific Python. A
strategy such as `one_row_per_calendar_date` declares the response date field,
the request start/end keys, and any row fields that must equal resolved request
parameters. The loader and compiler must reject undeclared fields, missing
request parameters, unsupported strategies, or incompatible date formats. The
generic ingest path validates the entire returned set before the SQLite writer:
missing, duplicate, out-of-window, malformed-date, or fixed-value-mismatch rows
produce one failed validation receipt and zero facts/success receipts. Future
cardinality strategies require a separately reviewed registry contract; they do
not justify an `api_name` or `dataset_id` branch.

The current reviewed generic strategies additionally include
`unique_primary_key_snapshot` for a current reference snapshot and
`single_partition_unique_primary_key` for one requested `yyyymmdd` partition.
They verify usable provider-native primary-key uniqueness, requested partition
agreement where applicable, and reject a response that reaches a contract's
declared row cap when `reject_at_row_limit` is enabled. This is structural
completeness evidence only: it does not independently prove that a response
below the cap contains every security in the market. A missing, blank,
non-scalar, or type-drifted native identity key continues through the generic
payload-hash fallback and is recorded as degraded rather than silently dropping
the provider payload. Legitimate empties still follow `empty_data_policy` and
produce an explicit `empty` receipt; provider and validation failures remain
`failed` receipts.

An ordinary Tushare binding freezes `requested_fields` from the reviewed upstream
contract whenever the provider's default response omits any officially declared
field. The list must follow the contract `fields` order, and the generic adapter
sends it as the exact comma-separated provider request. `requested_fields: []`
is allowed only when reviewed evidence proves that the default response includes
every declared field. The actual returned `fields/items` envelope remains
lossless, including unknown keys, but those keys do not enter the public query
allowlist automatically. A newly declared upstream field is added through a
reviewed contract/registry refresh, never a dataset-specific Python branch or
public route. A legacy collector `fields` value is only a diagnostic hint.

`stock_basic` and `daily` are ordinary config-only Tushare extensions under
this rule. Their onboarding adds neither a public route, a table, nor a
dataset-specific collector/query branch: the fixed data surface remains
`GET /v1/catalog` and `POST /v1/query`, backed by the generic provider-native
fact and receipt path. Industry fan-out/membership work remains separate.
Activation is controlled only by `config/provider_native_activation.yaml` and
the deterministic generated target registry. An active checked-in binding is
still not evidence of deployment, a provider call, SQLite facts, a success
receipt, API freshness, or consumer readiness; each layer requires fresh
runtime evidence.

Missing or incomplete contracts are listed as deterministic `unresolved + paused`
records and are absent from the provider-native target candidate. Structurally
invalid or duplicate bundle contracts fail strict bundle loading; ownership
conflicts prevent candidate rendering. None of these cases can enter the target.
They remain available only through the unchanged legacy compatibility registry
until a reviewed native contract exists; V1 must not expose a legacy schema as if
it were provider-native. The compiler never guesses parameters, keys, windows or
pagination and never adds dataset-specific branches. A generated candidate is only
an input to the separate provider-native target registry and isolated canary. A
fresh compiler review cannot authorize a default-registry or production switch;
that switch still requires all backfill, parity, consumer-migration, no-use and
rollback evidence in
[AGENTS.md](../AGENTS.md#注册表迁移门禁).

## Dual-registry runtime migration

The default `config/dataset_registry.yaml` remains the legacy compatibility
contract during migration. The deterministic compiler output is committed as
`config/provider_native_dataset_registry.yaml`; it is the target contract for
the generic runner, `GET /v1/catalog`, `POST /v1/query`, and isolated canaries.
It does not replace or mutate the default registry.

An unset `SHAREDSIGNALS_DATASET_REGISTRY_PATH` keeps the complete legacy
behavior. A trusted process may set that variable only to the absolute,
canonical repository path of `config/provider_native_dataset_registry.yaml`.
Relative paths, missing files, links, non-regular files, and any other path fail
closed. HTTP requests, tenants, external accounts, dataset parameters, and the
ordinary collection CLI have no registry-path selector.

The legacy `/tushare` adapter, canonical
`/reference?table=stock_master` adapter, and their in-process reader helpers
always resolve the default registry and execute through a separate QueryService
bound to that same default registry. They never reuse the V1 target
QueryService, even when the trusted process selector activates the target
registry for V1 catalog/query and the generic runner.

The target artifact is generated from the separately reviewed activation
manifest. A binding may be checked in as active only with an exact entitlement
and evidence reference, but repository state alone cannot call the provider or
write SQLite. Only the trusted scheduler in the isolated provider-native runtime
may act on that state. The internal V1 candidate activates exactly three resolved
bindings (`cn.market.trade_calendar`, `cn.equity.security_master`, and
`cn.equity.daily`) through this manifest; that is not evidence of a live
provider call, SQLite fact, receipt, API readiness, merge, or deployment.
`paused` is only a scheduling state and is never evidence that legacy readers
ignore a contract. Replacing the default registry therefore remains blocked until
generic schema/receipts, backfill, query parity, consumer migration, no-use
observation, and rollback evidence are independently complete.
