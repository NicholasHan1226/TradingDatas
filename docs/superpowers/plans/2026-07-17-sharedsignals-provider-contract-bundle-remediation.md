# SharedSignals Tushare Upstream Contract Bundle Remediation

**Date:** 2026-07-17
**Status:** binding for isolated local TDD and canary; production and external Beta remain blocked
**Base:** `de30b97cbfd5772e8329486984240f365582233f`
**Pilot dataset:** `cn.market.trade_calendar` / Tushare `trade_cal`

## 1. Direct goal

Replace the unsafe legacy-schema inheritance in the provider-native compiler with
one versioned, provider-level upstream contract bundle. The pilot must prove this
single path without adding a dataset-specific collector, table, query branch, API
route, or trading semantic:

```text
official Tushare contract provenance
-> reviewed provider-native contract bundle
-> deterministic target registry
-> generic Tushare adapter
-> provider_dataset_rows + same-transaction receipt
-> GET /v1/catalog + POST /v1/query
```

The current target registry is not an accepted data contract. In particular,
`cn.market.trade_calendar` incorrectly inherits `market_factors.v1`; this plan
removes that inheritance rather than adding a `trade_cal` code path.

## 2. Authority and provenance

The bundle is derived from, but does not dynamically trust, upstream documentation.
Its provenance is frozen as follows:

- official index repository: `https://github.com/waditu-tushare/skills.git`;
- pinned commit: `5e12b31d09123e262c5fb38564e80c26d05cb830`;
- index path: `tushare/references/数据接口.md`;
- index SHA-256:
  `0df85aa1265a59b963fca6660eb3f58bec232aa2347c9c44d763d0d55a1b9cb2`;
- `trade_cal` source document: `https://tushare.pro/wctapi/documents/26.md`;
- source-document SHA-256:
  `bb615ca96bf9995d70c9ba90b0e3744e2d452553c116aa6ca94a9f487e77fb22`.

The official input/output tables are machine-readable evidence for names, declared
types, required flags, and default visibility. Prose is not automatically promoted
to an execution policy. Primary keys, point-in-time behavior, request windows,
pagination, completeness, cadence, budgets, and provider-type overrides require a
reviewed entry in this repository.

Neither live provider responses nor documentation changes may silently rewrite the
approved catalog. They produce a deterministic conflict/semver proposal and leave
the dataset paused until reviewed.

## 3. Commercial launch gate

The current public Tushare service agreement describes the paid license as personal,
non-transferable, revocable, time-limited, and non-commercial, and prohibits opening
the service for profit or transferring service qualification. Therefore:

- local development, internal storage, and isolated server canaries may continue;
- no invited external tenant may receive Tushare-derived rows until Nicholas has
  obtained written redistribution/API-service authorization from Tushare or a
  separately licensed upstream;
- the gateway/Beta access plane must enforce this as a launch prerequisite and may
  not infer redistribution rights from points, token validity, HTTP 200, or payment;
- the legal gate does not authorize or require any trading feature.

Source: `https://tushare.pro/document/1?doc_id=405`.

## 4. Frozen product boundary

SharedSignals remains a provider-neutral data service. This remediation owns only:

- upstream contract provenance and deterministic compilation;
- provider-native fields and query policy;
- generic request-window policy and technical budgets;
- generic ingest, SQLite fact/receipt, catalog/query metadata, and canary evidence.

It does not own opening readiness, candidates, predictions, strategy scores, alpha,
capital, positions, risk, orders, fills, execution, or TradingAgent/MarketGraph state.
It must not import those systems, share their databases, or callback into them.

The public surface remains exactly `GET /v1/catalog` and `POST /v1/query`.

## 5. Bundle contract

Add one versioned YAML bundle. A contract entry is keyed by stable `dataset_id` and
contains:

- provider and provider API identity;
- source repository/commit/index/document/hash provenance;
- provider-native schema version;
- fields with declared source type, approved logical query type, nullability, and
  selectable/filterable/sortable policy;
- primary key, default projection, as-of/range/partition fields and date format;
- point-in-time, empty-data, backfill, scope, quota and cadence policy;
- provider request template and upstream field request policy;
- one generic window strategy with exact keys, formats, maximum span, and
  completeness assertion;
- row/row-byte/batch-byte/depth limits;
- reviewed type overrides with reason and real-observation evidence when the
  provider transport differs from the documentation.

The compiler must reject unknown bundle keys, duplicate dataset/API ownership,
missing source hashes, unsupported window strategies, undeclared key/time/requested
fields, invalid versions, and missing execution policy.

`requested_fields: []` continues to mean “request the complete upstream
`fields/items` payload”. It is not permission to publish undeclared fields through
explicit query operations. Unknown returned fields remain losslessly stored and
truthfully degraded until reviewed.

## 6. Compiler behavior

The compiler receives four authorities:

1. legacy registry for identity and compatibility metadata only;
2. capability plan for migration diagnostics only;
3. collector config for migration diagnostics only;
4. the approved upstream contract bundle for provider-native schema and execution
   policy.

For a resolved contract it must:

- remove the legacy `schema_profile` reference;
- write an inline provider-native field/query contract;
- generate the generic binding, request template, budgets, cadence, and
  `provider_dataset_rows` read adapter;
- preserve stable provider-neutral ID, aliases, domain, market, classification,
  entitlement and activation state unless the contract requires fail-closed pause;
- include source hashes and reviewed overrides in the compilation report;
- produce byte-identical output on repeated runs.

For a missing, invalid, conflicting, or incomplete contract it must emit an explicit
`unresolved + paused` report and must not expose a legacy schema as provider-native.
The target candidate contains only resolved provider-native contracts; unresolved
identities remain in the report and the unchanged legacy registry, not in the V1
target data plane.

## 7. `trade_cal` pilot contract

The reviewed minimum is:

- fields: `exchange`, `cal_date`, `is_open`, `pretrade_date`;
- schema version: `2.0.0`; the previously exposed legacy 1.x field meaning is
  incompatible and must not be treated as a minor/patch change;
- stable primary key: `exchange + cal_date`;
- default projection: all four fields;
- as-of/range/partition: `cal_date`, format `YYYYMMDD`;
- point-in-time: `current_snapshot`;
- request strategy: `date_range` with `start_date` and `end_date`;
- fixed provider parameter: `exchange=SSE` for this first canary;
- maximum span: 366 calendar days;
- completeness: one row per requested calendar date for the selected exchange;
- empty response: forbidden for a valid non-empty calendar window;
- provider call requests the complete payload;
- `is_open` public logical type is frozen only after the bounded real transport
  readback confirms the JSON type. Documentation says `str`; a conflicting real
  integer must be recorded as a reviewed override, never silently coerced.

The prior bounded smoke (`20260701` through `20260717`) returned 17 rows and the four
expected fields. It is evidence for the window shape, not a PASS for this candidate.

## 8. Exact local implementation boundary

Expected production-code/config files:

1. `config/tushare_upstream_contracts.v1.yaml` (new);
2. `tools/compile_provider_native_registry.py`;
3. `dataset_registry.py` only if a generic runtime window contract cannot be safely
   represented by existing trusted binding fields;
4. `collectors/tushare/provider_native_ingest.py` only for generic format/span
   enforcement, never an API-name branch;
5. `config/provider_native_dataset_registry.yaml` (deterministically generated).

Expected tests:

6. `tests/test_compile_provider_native_registry.py`;
7. `tests/test_provider_native_registry.py` if runtime window validation changes;
8. `tests/test_collect_provider_dataset.py` if generic runtime-window validation
   changes.
9. `tests/test_dual_dataset_registry_runtime.py` to replace the obsolete
   114-entry target assumption with resolved-only target behavior;
10. `tests/test_reader.py` only to prove missing unreviewed datasets in the V1
    target do not change the default legacy registry/reader contract.

Documents owned by this candidate:

11. this plan;
12. `docs/dataset_registry.md`;
13. `docs/data_source_onboarding.md`;
14. `STATUS.md` only after fresh evidence exists;
15. the Beta design specification only for the redistribution launch gate.

Any need for a dataset-specific collector/table/query route, production DDL, cron,
auth, gateway, TradingAgent, MarketGraph, or secret file stops this candidate.

## 9. Acceptance freeze

Local candidate acceptance requires all of the following:

1. repeated compiler runs are byte-identical;
2. all legacy/default registry bytes and behavior remain unchanged;
3. target catalog for `cn.market.trade_calendar` exposes only the four real fields,
   correct key/time semantics, and no `factor_hash/factor_name/value`;
4. missing/invalid/unreviewed contracts are absent from the target candidate and
   listed with deterministic unresolved reasons;
5. zero per-dataset Python branch/table/query/API route is added;
6. exact-window validation rejects missing/extra/malformed/reversed/oversized dates
   before provider call and SQLite write;
7. a raw four-field provider envelope preserves values, writes facts plus success
   receipt atomically, updates the same primary key by revision, and sets
   `data_through=max(cal_date)`;
8. unknown returned fields remain in `payload_json` and cause truthful degraded
   quality without silent schema mutation;
9. the generic response-completeness contract rejects a missing requested date,
   duplicate date, malformed/out-of-window date, or fixed-field/request-parameter
   mismatch before fact admission, leaving zero facts and zero success receipts;
10. response truncation, budget breach, damaged envelope, transport failure, empty
   forbidden window, and missing receipt all fail closed;
11. `/v1/catalog` and `/v1/query` preserve the frozen TA envelope fields and impaired
    states without any legacy/provider/file fallback;
12. same registry/catalog/as-of/receipt watermark yields the same ordered data and
    cursor semantics apart from `request_id`;
13. focused suites, Python 3.12 full suite, Ruff, compile, YAML, docs links, and
    `git diff --check` pass from final bytes;
14. a fresh clean-overlay reviewer reports P0=0/P1=0 and verifies exact hashes.

Reviewers may block only deterministic P0/P1 violations of this freeze. Additional
datasets, pagination strategies, gateway/auth, billing, and optional hardening are
later work.

## 10. Canary and release stop lines

After local PASS, rebuild an isolated server canary with detached code, a new SQLite
database, separate locks and port, no systemd/cron/nginx, and a bounded `trade_cal`
window. The canary must prove:

- real Tushare transport -> provider-native facts + same-transaction receipt;
- catalog/query schema and data match the provider envelope;
- impaired/no-legacy-fallback/same-as-of negatives;
- canary shutdown and production checkout/database/service/port conservation.

Production remains NO-GO after canary PASS. Production requires a separate fresh
safe-release preflight, rollback snapshot, writer quiesce, additive migration,
runtime readback, and explicit Nicholas authorization for any production database
change. External Beta additionally requires the written redistribution license.

## 11. Rollback

Local rollback is removal of the isolated branch/worktree candidate. Canary rollback
is process shutdown plus removal from service exposure while preserving evidence.
No production rollback is defined here because production mutation is out of scope.
No database, historical row, receipt, audit evidence, or unrelated worktree may be
deleted.
