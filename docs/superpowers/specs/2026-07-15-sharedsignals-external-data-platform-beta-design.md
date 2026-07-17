# SharedSignals External Multi-source Financial Data Platform Beta Design

**Date:** 2026-07-15

**Status:** binding and approved for local implementation; production schema migration remains separately gated

**Owner:** SharedSignals

**Initial upstream:** Tushare

**Initial access model:** invite-only external-account Beta

## 1. Product definition

SharedSignals is an independent, externally consumable, multi-source financial data service. It is not an internal Tushare mirror and it is not a TradingAgent or MarketGraph submodule.

Tushare is the first major upstream and a compatibility benchmark. SharedSignals owns the external contract, dataset identifiers, provider-native schema versions, technical validation, quality controls, storage, service metadata, account isolation, and long-term provider expansion. Every provider-native key/value is preserved losslessly, including fields not yet declared in the registry; business interpretation and feature engineering belong to consumers. Future providers may add exchange data, announcements, news, research, policy, interaction, and factual sentiment or public-opinion data without creating new public API routes.

The first release is an invite-only Beta for external accounts. It is designed as an external commercial service from day one, but it does not include public registration, automated billing, self-service privilege escalation, or an open marketplace.

## 2. Goals

1. Catalog all in-scope domestic-market Tushare datasets and activate every dataset the current account is actually entitled to use.
2. Download data into SharedSignals-owned SQLite storage according to each dataset's update schedule, permission limits, freshness SLA, and backfill policy.
3. Expose data through two stable, provider-neutral public endpoints:
   - `GET /v1/catalog`
   - `POST /v1/query`
4. Preserve source truth in every response through `freshness`, `quality`, `lineage`, `degraded`, `data_through`, and runtime state.
5. Support invite-only external tenants with isolated API credentials, dataset/field/lookback scopes, rate and concurrency limits, quotas, revocation, and usage auditing.
6. Let future sources and datasets extend the catalog without adding public routes or leaking provider-specific storage details.
7. Remove or migrate SharedSignals documentation, code, systems, and schedules that belong to research, readiness, strategy, or trading control rather than factual data service operation.

## 3. Non-goals

- No opening gate, candidate selection, prediction, strategy score, alpha, portfolio weight, account capital authority, position state, risk decision, order, fill, execution receipt, or trading recommendation.
- No cross-system database sharing, callback into TradingAgent or MarketGraph, or direct import of their business code.
- No prediction-market, cryptocurrency, Hong Kong, or United States market ingestion in the first release.
- No public signup, automated payment, automatic plan upgrade, or self-service scope expansion in Beta.
- No request-time provider fallback. Public queries never call Tushare or another upstream live.
- No destructive production database migration, data deletion, or historical evidence deletion as part of documentation and schedule retirement.
- No claim that a configured or allowlisted provider interface is entitled, active, fresh, or externally usable without runtime evidence.
- No conversion of provider-native rows into factor/value pairs, trading features, research conclusions, or other consumer-specific semantic models inside SharedSignals.
- No dataset-specific collector, storage writer, query compiler, or public route for an ordinary Tushare dataset that can be described by registry metadata.

## 4. Selected architecture

Three approaches were considered:

1. Continue extending the current hard-coded Tushare allowlist and dedicated endpoints. Rejected because every dataset would continue to require coordinated edits across configuration, table mappings, routes, authorization, readers, tests, and documentation.
2. Introduce one provider-neutral dataset registry, one generic provider-row SQLite authority, and one query service while retaining existing typed SQLite tables and endpoints only as compatibility surfaces during migration. Selected because it provides a stable external contract, supports gradual rollout, and avoids a clean-room rewrite.
3. Rebuild the service in a new repository and database. Rejected for the initial release because it duplicates proven ingestion, authentication, and read-model components and creates unnecessary migration risk.

The selected data flow is:

```text
Upstream providers
  -> provider adapters
  -> technical validation / lossless provider-native rows / deduplication
  -> generic SQLite dataset rows + transaction-scoped ingest receipt
  -> dataset registry + metadata projector
  -> query service
  -> GET /v1/catalog and POST /v1/query
  -> invite-only external tenants and internal consumers
```

Existing `/tushare` and dedicated data endpoints remain temporary compatibility adapters. They must call the same query service and must not retain independent provider or storage logic.

### 4.1 Binding anti-drift decision (2026-07-16)

The earlier implementation effort drifted in three ways: SharedSignals absorbed
trading-readiness/control concerns, a flat JSON runtime ledger was treated as an
authority, and review requirements expanded after candidates were frozen. Those
directions are rejected. This section is binding for every later phase.

The only approved authority chain is:

```text
provider-neutral dataset registry
→ SQLite facts + transaction-scoped ingest receipts
→ runtime metadata derived from registry + receipts + read clock
→ fixed catalog/query API
```

JSON, email, dashboards, HTTP status, compatibility endpoints, consumer state,
and configured-interface counts are observations or caches. They cannot become
data authority and cannot add trading/control semantics to SharedSignals.

#### Acceptance Freeze

Before implementation, each task freezes its product boundary, authoritative
inputs, public/internal interfaces, exact write scope, threat model, P0/P1
acceptance cases, stop condition, and rollback. After candidate freeze:

- reviewers test only that approved contract;
- a new finding blocks only when it is in scope, deterministically reproducible,
  materially affects data correctness, tenant isolation, or service availability,
  and is P0/P1;
- contract-external hardening is recorded as P2/backlog rather than silently
  expanding the release gate;
- two successive rounds of new structural P1 findings stop patch accumulation
  and require an architecture decision;
- the invite-only Beta assumes cooperative service processes and accidental
  races; a **same-UID malicious** process is outside this release threat model
  unless a later security specification explicitly adds it.

The implementation sequence is fixed: approved specification → one provider-to-
API vertical slice → acceptance freeze → TDD → candidate freeze → fresh clean-
overlay review → exact integration → safe release and production readback.
Parallel work begins only after shared contracts are frozen and only across
non-overlapping write domains.

### 4.2 Provider-native storage decision (2026-07-17)

The previous mapping model compressed 114 datasets into a small set of research-
shaped tables and, for many datasets, decomposed provider fields into
`factor_name/value`. That model forced per-interface schema, key, mapping, and
review work and made SharedSignals a semantic processing layer. It is rejected.

The default Beta storage contract is one generic, lossless provider-row path:

```text
provider response fields/items
-> generic provider adapter
-> canonical JSON row (all provider-native fields preserved)
-> registry-declared technical identity/time metadata
-> generic SQLite dataset-row fact + same-transaction ingest receipt
-> registry-compiled JSON-field query
-> flat provider-native row returned by POST /v1/query
```

The additive generic fact table is designed around technical identity rather
than research semantics. `payload_json` preserves every provider-native
key/value, including unknown fields added upstream after the registry was
published. Its minimum logical columns are `dataset_id`, `provider`,
`schema_major`, `ingested_schema_version`, `row_key`, `observed_at`,
`partition_value`, `payload_json`, `payload_hash`, `quality_state`,
`quality_issues_json`, `collected_at`, `receipt_id`, and `revision`. Technical metadata is stored beside the payload,
may be null when the provider does not supply a reliable value, and never
overwrites, renames, drops, coerces, or timezone-normalizes a provider payload
field. The exact DDL, indexes, migration, backfill, parity, cutover, and rollback
require a separate safe migration review before any production database change.

Physical identity is isolated by schema major, not the full schema version, so
a backward-compatible optional-field minor release does not hide older rows.
`ingested_schema_version` preserves row lineage and the API reports the current
registry contract version. `current_snapshot` datasets use declared stable keys
and may update across attempts; `append_only` datasets use payload identity and
never update. A missing/unusable snapshot key falls back to tagged payload
identity with degraded quality. Conflicting payloads for one stable key within a
single attempt are rejected as a damaged envelope rather than silently
last-write-winning.

Registry metadata supplies the provider API name, request template, native
field manifest, time/partition field, row-key fields or canonical-row-hash
fallback, cadence, entitlement, budgets, and query policy. The field manifest
controls discovery, query allowlisting, and quality annotations; it is not an
ingest projection and cannot discard an unknown provider field. A provider
field/schema/type mismatch or an unknown field is stored unchanged and marks
the row/dataset quality or degraded metadata; it is not a row-admission
failure. Only an invalid or oversized JSON representation, an approved resource
budget breach, a damaged technical envelope, or a response matching the existing
credential/provider-token leakage contract may reject admission, and none
may rewrite the payload. Ordinary
Tushare datasets do not add Python branches, target tables, public routes,
custom fixtures, or custom query code. Provider-level adapters are allowed only
for a genuinely different transport protocol, not for dataset business
semantics.

Credential leakage protection takes precedence over lossless storage: a matched
response is treated as a damaged security envelope and cannot enter facts,
logs, or the public API. A future provider with a legitimate business field that
resembles a credential requires a separately reviewed security contract rather
than a dataset-specific bypass.

For a generic Tushare binding the registry also owns the provider request
template, requested provider fields, allowed request-window substitutions, and
row/byte/depth budgets. Collection starts from `dataset_id + request_window`;
dataset-specific code cannot supply API parameters or receipt lineage behind
the registry. The generic ingest path constructs dataset/provider/API/adapter,
config-hash, request-window, and data-through receipt fields from trusted
registry/config; callers supply only attempt identity and start time. Successful
non-empty `data_through` is derived generically from the maximum validated
provider `as_of_field`, otherwise `partition_field`, otherwise collection time
when no provider data-time field exists; it is never guessed from API names or
request parameter names. Tests
inject raw `fields/items` transport envelopes below the existing strict parser,
not prebuilt provider outcomes.

Existing typed fact tables and their read-model adapters are compatibility
surfaces during migration. They are not the target authority for newly onboarded
datasets. Consumers may continue to use them until semantic parity and rollback
are proven, but the generic path cannot write provider rows into those tables or
derive research features for them.

## 5. Initial dataset scope

The first release covers domestic-market factual datasets:

- A-share security master data, trading calendar, daily/weekly/monthly/intraday/realtime bars, adjustment factors, valuation and trading statistics, limit and suspension data, auction data, financial statements, disclosure schedules, corporate actions, shareholders, pledges, repurchases, margin, market money flow, block trades, concepts, and factual hot-list data.
- Domestic ETF and public-fund master data, bars, realtime data where entitled, NAV, share size, portfolio, dividends, managers, PCF baskets, and IOPV where available.
- Exchange, Shenwan, and CITIC index taxonomy, constituents, weights, bars, realtime data where entitled, and market statistics.
- Domestic futures, options, convertible bonds, bonds, repo, and Shanghai gold reference and market data.
- Domestic macroeconomic releases including GDP, CPI, PPI, PMI, money supply, social financing, Shibor, and LPR.
- Announcements, factual news, policy, research reports, central-bank reports, exchange interaction, and other licensed text corpora.

Domestic ETF filters exclude QDII products in this release. Cross-border interfaces are cataloged as excluded or paused rather than treated as successful domestic coverage.

The official Tushare catalog and entitlement documentation are upstream references, not the SharedSignals public contract:

- <https://tushare.pro/document/2?doc_id=371>
- <https://tushare.pro/document/1?doc_id=290>
- <https://tushare.pro/document/1?doc_id=40>
- <https://tushare.pro/document/1?doc_id=9>

## 6. Dataset registry

The registry is the single authority for dataset discovery, provider bindings, schema, query policy, cadence, SLA, and Beta access policy. It replaces duplicated hard-coded lists over time.

Each registry entry contains:

- stable provider-neutral dataset ID, for example `cn.equity.daily`;
- aliases, including compatibility names such as `tushare.daily`;
- domain, market, entity type, and objective-data classification;
- provider bindings and internal adapter version;
- provider-native dataset schema version, declared field types for catalog/query validation without ingest coercion, technical row-key fields or row-hash fallback, and default projection;
- filterable, sortable, and selectable fields;
- maximum page size and lookback;
- point-in-time capability: `append_only`, `current_snapshot`, or `unsupported`;
- cadence class, timezone, freshness SLA, and backfill policy;
- empty-data policy;
- entitlement state: `active`, `locked`, `unknown`, `excluded`, or `retired`;
- runtime state: `success`, `empty`, `unobserved`, `paused`, `failed`, or `stale`;
- generic provider-row read adapter; legacy typed read-model adapters are compatibility-only;
- required tenant scope and Beta quota class.

Adding an ordinary Tushare dataset must change only registry/config metadata. It must not add a public route, dataset-specific collector, storage writer, query compiler, fixture, or business-table mapping. Generic conformance tests enumerate the registry and prove that a synthetic registry-only dataset traverses the provider-to-SQLite-to-query path unchanged; onboarding does not add a per-dataset test branch.

## 7. Storage and ingest authority

SQLite remains the authoritative store for the first release. DuckDB is not required for Beta availability and must not be part of the critical read path.

Every true database write transaction records an immutable ingest receipt in the same SQLite transaction as its successful data rows. A successful receipt must never survive a rolled-back data transaction, and successful rows must never be committed without the matching receipt.

Receipts distinguish:

- provider success with inserted, updated, unchanged, rejected, and returned row counts;
- legitimate empty response;
- provider failure, permission denial, throttling, hard admission failure for invalid/oversized JSON or damaged technical envelopes, storage failure, and resource-budget rejection;
- paused and never-observed datasets;
- attempt ID, provider API, dataset ID, request window, config hash, adapter version, collection time, data-through time, and error classification.

Provider errors must not be converted into empty datasets. The latest failed receipt keeps the dataset degraded even when older rows remain queryable.

The generic provider-row table is the target authority for newly onboarded datasets. Existing typed fact tables may temporarily serve compatibility consumers where they already preserve full provider payload and stable keys, but they do not define the new public storage model. Production activation remains blocked until the additive generic table, indexes, isolated backfill, parity, cutover, and rollback pass a separate migration preflight.

## 8. Collection scheduling

Cadence is a registry attribute, not a growing collection of handwritten cron tiers.

Initial cadence classes are:

- `intraday_5m`: entitled realtime or intraday A-share, ETF, index, futures, and option datasets;
- `event_15m` or `event_30m`: news, announcements, policy, research, and interaction datasets according to provider limits;
- `preopen`: limits, adjustment factors, premarket reference data, and other morning publications;
- `postclose`: daily bars, valuation, money flow, indexes, funds, and derivatives;
- `evening`: historical minute archives, financial disclosures, company actions, ownership, announcements, and provider reconciliation;
- `next_morning`: delayed margin, ETF-share, and similar datasets;
- `weekly` and `monthly`: low-frequency summaries and macro releases;
- `backfill`: separately throttled historical recovery that cannot starve current-session collection.

The scheduler resolves active datasets from the registry, respects provider-specific rate limits and independent permissions, prevents overlapping work for the same dataset/window, and records every attempt in SQLite.

Configured but non-entitled datasets remain visible as `locked`; they are not retried continuously as failures. Excluded markets remain `excluded` and their existing historical data is not deleted.

## 9. Public API

### 9.1 `GET /v1/catalog`

Returns the tenant-visible dataset catalog. Supported filters are bounded and fixed: `market`, `domain`, `cadence`, `state`, `q`, `cursor`, and `limit`.

The public catalog exposes schema, query capabilities, cadence, SLA, availability, and data-through status. It never exposes database paths, SQL, credentials, provider tokens, internal hostnames, or excluded datasets the tenant is not allowed to discover.

### 9.2 `POST /v1/query`

The request contains:

- dataset ID and compatible schema major;
- selected fields;
- registry-allowed filters and operators;
- registry-allowed ordering;
- optional supported `as_of` value;
- bounded page limit and opaque cursor.

The query compiler accepts only registry-declared fields and the operators `eq`, `in`, `gte`, `lte`, and `between`. It never accepts SQL, table names, arbitrary expressions, provider tokens, or unbounded offset queries.

For generic provider rows, registry-declared fields compile to bounded,
type-guarded SQLite JSON expressions only for filtering and ordering. Response
projection reads the internal canonical `payload_json` and parses it strictly
in the service so large integers remain exact and a missing key remains distinct
from an explicit JSON null. The raw storage JSON and technical columns are never
exposed. Queries never accept arbitrary JSON paths and every statement is
isolated by qualified technical `dataset_id`, provider, and schema-major
predicates even when the provider payload contains identically named keys.

Generic keyset cursors use provider plus stable row key as their final signed
tie-breaker; SQLite `rowid` is not a public pagination identity. Dataset-wide
indexed quality state and page-level row issues feed response quality evidence.
Runtime state remains receipt-derived, while top-level `degraded` also reflects
dataset data-quality degradation. Filtering or ordering a field with incompatible
stored types fails closed rather than coercing or silently omitting rows.
Rows whose declared provider time is invalid remain selectable as raw factual
values with `failed/degraded`, null `data_through`, and truthful receipt/quality
lineage; any filter, order, as-of, or latest-partition operation touching that
field fails closed. Dataset-wide and operation-specific quality checks use the
bounded degraded-row index and cannot fall back to scanning the full dataset
partition when that index is missing.
Explicit-null filters use JSON type `null` and never match a missing key. Values
outside SQLite's exact signed-64-bit integer domain remain lossless in response
projection, but any filter/order/as-of/partition operation on such a field fails
closed using stored field-specific quality evidence.

Responses contain data, signed keyset pagination, dataset and schema versions, request ID, and metadata:

- runtime state;
- requested and resolved `as_of`;
- data-through value;
- freshness state, observed time, and SLA;
- quality state and validation evidence;
- provider and receipt lineage;
- degraded flag and structured reasons.

Old data may be returned as last-known data only with explicit failed or stale metadata. HTTP 200 never implies source health.

### 9.3 Compatibility

`/tushare?api_name=daily` resolves the alias `tushare.daily` to `cn.equity.daily` and calls the query service. Other legacy data endpoints follow the same migration path.

Compatibility endpoints receive deprecation metadata only after representative consumers pass semantic parity tests. They are deleted only after an observed no-use window and rollback evidence.

## 10. Invite-only Beta access plane

Beta accounts are created manually through an operator-reviewed process. There is no public registration endpoint.

Each account has:

- stable tenant ID;
- one or more individually revocable API keys whose cleartext is shown once and never stored;
- server-side key hashes;
- status and expiry;
- dataset-pattern scopes;
- optional field restrictions;
- maximum lookback and page size;
- hourly request limit, concurrent-request limit, and quota class;
- allowed network or gateway policy when required.

Middleware order is fixed:

```text
authenticate
-> authorize dataset / field / lookback
-> enforce rate and concurrency
-> reserve quota
-> execute or read safe cache
-> append usage event
-> release reservation
```

Usage events contain request ID, tenant, dataset, rows, bytes, latency, cache hit, result state, cost units, and normalized query hash. They do not contain tokens, provider credentials, SQL, or unnecessary raw query values.

Administrative mutation routes, cache invalidation, account creation, and scope changes are not granted to Beta data-read credentials. Revocation and quota exhaustion fail closed.

## 11. Error and degraded model

Protocol and authorization failures use explicit HTTP errors:

- `400`: invalid request, filter, cursor, or unsupported `as_of`;
- `401`: unauthenticated;
- `403`: dataset, field, or lookback forbidden;
- `404`: dataset not found for the current tenant;
- `409`: cursor/snapshot mismatch;
- `413`: query too large;
- `429`: rate, concurrency, or quota exhausted;
- `503`: read model unavailable or server capacity exhausted;
- `500`: internal error without internal-path or stack-trace disclosure.

Legitimate data states may return HTTP 200 with an empty data list, but the metadata must distinguish `empty`, `unobserved`, `paused`, `failed`, and `stale`. A missing receipt cannot be represented as healthy empty data.

## 12. Scope retirement and deletion

SharedSignals retirement is staged to avoid deleting live consumer contracts or evidence.

### 12.1 Keep and rewrite

Keep the minimum authoritative documentation and systems for:

- product boundary and repository rules;
- dataset registry and provider onboarding;
- API and schema contracts;
- authentication and Beta account operations;
- ingestion, storage, backup, recovery, rollback, and incident response;
- capability, entitlement, runtime, and freshness status;
- deployment and external-route operation.

These documents are rewritten to reflect the external data-platform Beta and fixed catalog/query API.

### 12.2 Migrate, deprecate, then delete

The following categories leave SharedSignals after their replacement owner and consumer migration are verified:

- opening-gate routes, collectors, schedules, documents, and tests;
- MarketGraph-style association and impact research projections;
- derived sentiment or trading interpretation rather than provider-native factual sentiment;
- sector or factor routes that exist only as research conclusions rather than objective datasets;
- compatibility endpoints and documents superseded by `/v1/catalog` and `/v1/query`;
- duplicated architecture, handoff, completed-candidate, and obsolete activation documents whose retained facts have been folded into the current contract and status history.

### 12.3 Disable, verify, then delete

The following schedules and systems are disabled first, observed for ownership and consumer impact, and then removed from repository and installation templates:

- prediction-market and cryptocurrency collection;
- Hong Kong and United States market collection for the initial domestic release;
- opening-gate generation;
- strategy/readiness control tasks;
- real-email green-gate or trading-operation notifications;
- obsolete tier wrappers replaced by the registry scheduler;
- optional DuckDB critical-path tasks after SQLite-only Beta parity and recovery are proven.

Historical data, SQLite databases, Journal/ledger/outbox/history, production handoff evidence, and rollback artifacts are not deleted by this retirement.

### 12.4 Safe-delete gate

A file, route, system, or schedule is safe to delete only when all of the following are true:

1. no current registry entry, import, test, documentation link, cron template, service unit, or known external consumer requires it;
2. the replacement path is implemented and verified where required;
3. live runtime and installed schedules have been inventoried separately from repository templates;
4. rollback evidence exists;
5. the deletion does not remove historical data, credentials, audit evidence, or another project's property;
6. focused and full regression tests pass after deletion.

## 13. Versioning and compatibility

The public API envelope is versioned by URI major. Each dataset schema has an independent semantic version. Provider-adapter and storage-schema versions remain internal.

- optional field addition: dataset minor version;
- compatible correction: patch version;
- removal, rename, type change, or semantic change: dataset major version;
- default field projection is versioned and cannot expand silently;
- signed cursors bind dataset, schema major, normalized query hash, access-policy hash, receipt watermark, last sort tuple, and expiry.

## 14. Security and operational boundaries

- External access terminates at an approved gateway. The local service port is not shared directly with external tenants.
- Credentials, provider tokens, account secrets, database paths, SQL, and internal stack traces never appear in API responses or logs.
- Tenant-specific field or row policy participates in cache keys. Cross-tenant cache sharing is permitted only for explicitly public, policy-identical datasets.
- The API process opens SQLite read-only for query traffic.
- Provider collection and API query capacity are separately budgeted.
- No Beta credential grants cache administration, deployment, collection control, or account administration.
- `REAL_TRADING_ENABLED=false` remains outside SharedSignals but is not changed by this project.

## 15. Implementation phases

### Phase 1: registry and ingest authority

- establish the provider-neutral registry;
- import the current 114-interface configuration as compatibility entries;
- catalog missing in-scope Tushare datasets;
- distinguish active, locked, unknown, excluded, and retired entitlement states;
- make data and successful ingest receipt atomic;
- preserve provider errors and validation results.

### Phase 2: query service

- implement catalog and query endpoints;
- bind metadata to receipts rather than row presence alone;
- add signed keyset cursors;
- adapt `/tushare` and representative legacy endpoints;
- prove no request-time provider or file fallback.

### Phase 3: entitlement and scheduling

- replace dataset-specific business-table writes with the one generic provider-row ingest path;
- prove zero-code onboarding with a synthetic registry/config-only dataset;
- probe the configured Tushare account without exposing tokens;
- activate every entitled domestic dataset at its registry cadence;
- create a separately throttled backfill queue;
- publish an honest runtime matrix and data-through status.

### Phase 4: invite-only Beta access

- implement tenant-scoped keys, authorization, rate and concurrency limits, quota reservation, revocation, and usage events;
- create an operator-reviewed onboarding and offboarding runbook;
- run external-route, tenant-isolation, abuse, pagination, load, and recovery tests.

### Phase 5: retirement and production rollout

- migrate consumers to the fixed query API;
- disable out-of-scope schedules and systems;
- observe and then delete approved obsolete repository surfaces;
- perform a fresh production inventory and safe-release preflight;
- release through a reversible shadow, pilot, and readback sequence.

## 16. Acceptance criteria

### Data platform

- Every in-scope Tushare dataset is cataloged with a provider binding or an explicit locked/unknown state.
- Every entitled dataset is activated at a documented cadence and is queryable from SQLite.
- Adding a synthetic ordinary Tushare dataset through registry/config alone completes provider-to-SQLite-to-query without changing collector, storage writer, query service, or API routes.
- Query results preserve provider-native field names and values; SharedSignals does not decompose them into factor/value or consumer features.
- Data and successful receipt commit atomically; rollback leaves no success receipt.
- Provider failure, permission denial, throttle, empty, unobserved, paused, and stale states are independently reproducible.
- Deleting optional cache artifacts does not destroy data or service-state authority.
- No request path calls a provider or reads sibling databases/files.

### API

- Adding a provider binding or dataset does not add public routes.
- Registry is the sole authority for schema, query policy, cadence, SLA, and tenant dataset scope.
- Query fields, operators, ordering, lookback, row count, and cursor use are bounded.
- Responses preserve freshness, quality, lineage, degraded reasons, and data-through values.
- Pagination has no duplicate or missing rows and rejects cross-dataset, cross-query, cross-policy, or cross-snapshot cursor reuse.

### Invite-only Beta

- Two tenants cannot access each other's restricted datasets, fields, quotas, cursors, or usage events.
- Revoked, expired, rate-limited, concurrent-limit, and quota-exhausted credentials fail closed.
- Administrative routes remain forbidden to data-read keys.
- Usage accounting is durable and idempotent for retried request IDs.
- External-route tests separately prove gateway, authentication, service runtime, database read, and dataset freshness.

### Scope cleanup

- SharedSignals diff contains no opening, candidate, prediction, strategy, account-capital, position, risk, order, fill, or trading-control logic.
- Out-of-scope systems and schedules are absent from repository installation templates after retirement.
- Obsolete documentation is deleted only after its retained facts are migrated to the authoritative documents.
- Historical databases, collected facts, audit evidence, and rollback artifacts remain intact.

## 17. Rollback

Rollback is additive and non-destructive:

- disable new registry scheduler activation without deleting registry or receipts;
- keep existing compatibility endpoints during the rollback window;
- revert code through normal commits;
- preserve existing SQLite data and ingest history;
- revoke Beta credentials or disable the external route without affecting local collection;
- restore the last verified API release and registry version;
- retain retirement inventories and deletion evidence so removed schedules or compatibility layers can be reconstructed if necessary.

## 18. Documentation set after retirement

The intended active documentation set is small and authoritative:

1. repository rules and product boundary;
2. current status and production truth;
3. public API and dataset-schema contract;
4. dataset catalog and entitlement/runtime matrix;
5. provider onboarding and validation contract;
6. Beta account/security/usage contract;
7. ingestion, backup, recovery, deployment, rollback, and incident runbooks;
8. historical status archive.

All other handoff, candidate, duplicated capability, retired subsystem, and superseded planning documents are either folded into this set and deleted or retained only in version history.

## 19. Initial repository retirement inventory

This inventory records the read-only repository audit performed after design approval. It classifies repository content only. Production crontab, installed service state, running processes, and external consumers require a fresh production inventory before any live retirement claim.

### 19.1 Keep as evidence or current authority

- `CLAUDE.md` as a rule-discovery entry;
- `docs/resource_pressure_2026-07-13.md` as production incident and rollback evidence;
- `docs/status_history_2026-07.md` as explicitly historical status;
- this approved external-data-platform Beta design.

### 19.2 Rewrite as the authoritative active set

- `AGENTS.md`;
- `README.md`;
- `STATUS.md`;
- `API_CONTRACT.md`;
- `collectors/AGENTS.md`;
- `cron/AGENTS.md`;
- `cron/crontab.txt`, retained as the sole repository schedule template until registry scheduling replaces it;
- `docs/AGENTS.md`;
- `docs/INFRASTRUCTURE.md`;
- `docs/data_source_onboarding.md`;
- `docs/external_agent_api_prompt.md`;
- `docs/market_capability_matrix.md`;
- `docs/sqlite_recovery_runbook.md`.

### 19.3 Safe first-wave document deletion candidates

These files have no active repository references and contain obsolete candidate, handoff, plan, or report material. Git history remains the rollback source:

- `docs/opening_gate_5min_gate_v2_handoff.md`;
- `docs/sector_flow_v2_handoff.md`;
- `docs/sector_flow_v2_implementation_plan.md`;
- `docs/superpowers/plans/2026-07-11-capital-growth-data-foundation.md`;
- `docs/superpowers/reports/2026-07-11-sw2021-task4-fix-report.md`.

Deleting these documents does not authorize deletion of the corresponding code, data, schema, schedules, or production services.

### 19.4 Defer until replacement and consumer migration

- root `crontab.txt`, after every reader and test uses one canonical generated schedule;
- generated `docs/API_CONTRACT.md`, after capability generation is registry-driven;
- `docs/duckdb_sync_runbook.md`, after DuckDB is removed from recovery and critical paths;
- `docs/event_lane.md`, after news, announcements, and factual sentiment become registry datasets;
- `docs/repo_structure.md`, after retained system boundaries are folded into root rules and README;
- `docs/sector_flow_v2_contract.md`, after objective sector-flow datasets and consumers use the unified query service;
- `docs/singapore_proxy_relay.md`, after the external API tunnel is separated from crypto/prediction-market proxying;
- the prior SW2021 dedicated design, after SW2021 is represented by registry datasets and compatibility consumers migrate;
- `docs/tushare_activation_backlog.md`, after catalog entitlement/runtime states replace the hand-maintained backlog.

### 19.5 Keep core runtime surfaces

- `deploy/systemd/sharedsignals-api.service`;
- `deploy/systemd/sharedsignals-cloudflared.service`;
- `deploy/nginx/sharedsignals-origin.conf` during Beta compatibility;
- code release and rollback framework after separate safety review;
- deployment/collection coordination lock;
- domestic Tushare, domestic futures, news/announcement, and SW2021 collection until the registry scheduler replaces their wrappers;
- external API probe, rewritten for `/v1/catalog`, `/v1/query`, authentication, and tenant isolation;
- SQLite maintenance as an operator-reviewed maintenance action rather than an unbounded automatic job.

### 19.6 Disable first in production, then remove from templates

After a fresh production inventory and exact rollback capture, disable one schedule at a time:

- Hong Kong and United States P5 collection;
- cryptocurrency and prediction-market collection;
- opening-gate generation;
- real green-gate email;
- automatic heal, restart, and HALT mutation, while retaining read-only data-service health metrics;
- crypto/prediction-market proxy relay health;
- already-disabled DuckDB sync.

`cron/collectors.sh` must also stop including excluded markets in its no-argument and `--all` modes; deleting only explicit P5 cron lines would leave a manual reactivation path.

### 19.7 Migrate before code deletion

The following code surfaces are out of scope but still have active dependency chains:

- opening gate in `tools/opening_gate.py`, API routing, authorization, source governance, health checks, cron, tests, and contracts;
- real email and self-healing in `tools/green_gate_report.py`, `tools/email_sender.py`, `heal.py`, `tools/watchdog.py`, `tools/auto_restart.sh`, wrappers, tests, and configuration;
- cryptocurrency, prediction-market, and excluded-market collectors, routes, scopes, configuration, and tests;
- old source governance, health SLA, and capability scanning that mix objective data health with trading readiness;
- proxy installation and relay-health tooling after the public API tunnel is isolated;
- DuckDB sync, schema, snapshots, scheduler, dependency, and recovery code after SQLite-only recovery is proven;
- dedicated `/sentiment`, `/associations`, `/impacts`, sector-flow, and industry routes after consumers migrate to factual datasets through the unified query service.

One dead helper, `filter_impact_relations()` in `collectors/tushare/tushare_common.py`, has no repository caller and is a first-wave code deletion candidate once focused tests confirm the call graph.

### 19.8 Production retirement proof

Before production retirement, capture read-only evidence for:

- live `crontab -l`;
- installed systemd services and active timers/processes;
- current production commit and dirty-file hashes;
- collection locks and in-flight SQLite transactions;
- external tenant, TradingAgent, and MarketGraph calls to compatibility routes;
- current API tunnel and relay ownership;
- database, backup, and rollback artifact locations.

Live tasks are disabled by exact line or service unit, never by replacing the whole crontab. Repository deletion follows observed inactivity and consumer migration. Production retirement is complete only after fresh API, domestic-ingestion, receipt, catalog/query, authentication, and rollback readback.
