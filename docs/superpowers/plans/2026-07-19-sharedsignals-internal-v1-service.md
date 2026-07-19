# SharedSignals Internal V1 Service Implementation Plan

> Status: reviewed GitHub code and execution/release plan for the internal-first
> data service lane. The code chain is based on `0be6f83` and integrates
> `7f5e20a -> 43af5c2 -> 976ad6b -> 2468f80`; `2468f80` has local, origin, and
> live GitHub readback, but it is not deployed and is not evidence that a
> service is running.

## Outcome

Run a stable, authenticated, loopback-only SharedSignals provider-native data
service for TradingAgent, MarketGraph, and internal research consumers.

The internal service exposes only:

- `GET /v1/catalog`
- `POST /v1/query`

The first internal slice contains:

- `cn.market.trade_calendar`
- `cn.equity.security_master`
- `cn.equity.daily`

All three datasets have bounded real-provider canary evidence. New ordinary
Tushare datasets must remain config-only additions to the same registry,
transport, SQLite facts/receipts, query service, scheduler, and public routes.

## Non-goals and protected production state

This plan does not:

- replace or restart the legacy `127.0.0.1:8082` service;
- migrate, modify, copy, or delete the legacy approximately 23 GB SQLite
  database;
- change nginx, cloudflared, or public ingress;
- add provider- or dataset-specific collectors, tables, query handlers, cron
  entries, or public API routes;
- add opening gates, research, prediction, strategy, capital, position, risk,
  or execution semantics;
- enable real trading, broker integration, real email, Tonghuashun, or any
  automatic authority expansion;
- delete legacy code, data, evidence, or worktrees during the pilot.

The provider-native lane uses `127.0.0.1:18082` and the new SQLite database
`/opt/investment-data/sharedsignals-v1/read_model/provider_native.sqlite`.
Creating that database from the repository's canonical `SCHEMA_SQL` is a
fresh-store bootstrap, not a migration of the legacy database. The API unit is
`sharedsignals-v1-internal.service`; its Git-owned non-secret profile is loaded
from the active release, while secrets are supplied separately by the mode-
restricted `/etc/sharedsignals/provider-native-internal.secrets` file.

Runtime credentials are split by least privilege and are never committed:

- API: `/etc/sharedsignals/provider-native-internal.secrets` contains only the
  token-hash file path, token salt, and cursor signing key;
- collector: `/etc/sharedsignals/provider-native-collector.secrets` contains
  only the upstream collection endpoint and credential needed for collection;
- probe: `/etc/sharedsignals/provider-native-probe.secrets` contains only the
  raw internal bearer token used for authenticated HTTP readback.

All three files are root-owned mode `0600` systemd `EnvironmentFile`s. The API,
collector, and probe must not load one another's credential file. Creating or
copying these credentials is a separately confirmed production action; tests
and release evidence may validate names, ownership, modes, and successful use,
but must never print their values.

## Frozen authority chain

The authority order is:

```text
provider_native_activation.yaml
        +
tushare_upstream_contracts.v1.yaml
        +
provider-neutral registry compiler
        |
        v
provider_native_dataset_registry.yaml (generated, checked in)
        |
        +--> generic collection scheduler
        +--> SQLite facts + transaction-scoped receipts
        +--> GET /v1/catalog and POST /v1/query
```

Activation is never inherited from the legacy registry. Missing activation
entries compile to `unknown` and `paused`. The generated registry is never
hand-edited.

## Workstream A: activation authority

Files:

- add `config/provider_native_activation.yaml`;
- modify `tools/compile_provider_native_registry.py`;
- regenerate `config/provider_native_dataset_registry.yaml`;
- add or modify compiler tests only.

Acceptance:

- exact `dataset_id + provider` activation records;
- `active` requires both active entitlement and a non-secret evidence
  reference;
- duplicate, unknown, or invalid records fail closed;
- a missing record deterministically compiles to `unknown/paused`;
- changing legacy activation state does not change provider-native output;
- compiler output matches the checked-in target byte for byte;
- the legacy registry remains byte-identical.

## Workstream B: isolated runtime and release control

Files:

- add a non-secret Git-owned internal runtime profile;
- add a new loopback-only systemd service;
- add a fresh-store bootstrap tool;
- add a dedicated provider-native internal release/readback/rollback tool;
- add dedicated tests.

Acceptance:

- the new service has a distinct name, release root, database, and port;
- authentication remains required on localhost;
- the Git-owned profile contains no credential, token, salt, or signing key;
- the separate secret file is checked only for path, owner, mode, required key
  names, and successful service use; its values are never printed or copied
  into evidence;
- the registry path is the canonical target inside the active release;
- bootstrap builds the complete new root only in a random sibling staging
  directory under the approved runtime parent, including the SQLite file,
  coordination locks, ownership/mode, schema and indexes;
- after directory/file `fsync`, Linux `renameat2(RENAME_NOREPLACE)` publishes
  that sibling staging root as the final runtime root atomically;
- an existing final root is accepted only after complete-store validation;
  partial finals, existing files, symlinks, the legacy database path, schema
  drift, unsafe parents, or unavailable no-replace rename fail closed;
- stale sibling staging roots are counted/reported and retained for manual
  investigation; bootstrap never guesses at or automatically cleans them up;
- `PRAGMA quick_check`, facts table, receipt table, and indexes pass before the
  service starts;
- apply and rollback never invoke a schema migration, touch the legacy service,
  alter ingress, or delete data/evidence;
- rollback stops the new lane and preserves its database and logs.

## Workstream C: generic scheduler and internal probe

Files:

- add cadence-class schedule configuration;
- add one registry-driven scheduler;
- add one collection service/timer;
- add one authenticated V1 probe and probe service/timer;
- add dedicated tests.

Acceptance:

- the scheduler enumerates all active and entitled provider-native bindings;
- no dataset ID, API name, target table, or per-dataset command branch is
  embedded in Python or units;
- request windows are derived from cadence configuration and each registry
  binding's request-window policy;
- a global non-overlap lock prevents concurrent scheduler runs;
- paused or locked bindings cause zero provider calls and zero writes;
- provider error, validation failure, empty result, and success remain distinct
  terminal results and receipts;
- the probe derives the expected active-and-entitled dataset set only from the
  canonical checked-in registry, then uses authenticated catalog/query HTTP for
  all runtime data and state checks; it never reads SQLite, a provider route,
  or a legacy cache;
- HTTP 200 with stale, failed, unobserved-after-grace, missing receipt, invalid
  quality, incomplete coverage, or degraded metadata fails the probe;
- tokens are never logged or written to evidence.

## Integration order

1. Fresh independent review of all frozen candidates.
2. Integrate activation authority (`7f5e20a`).
3. Rebase and integrate scheduler/probe against the generated active target
   (`43af5c2`).
4. Rebase and integrate runtime/release controls (`976ad6b`), then apply the
   atomic store-initialization correction (`2468f80`).
5. Update README, STATUS, registry documentation, and infrastructure/runbook
   documentation from the final integrated bytes.
6. Run the relevant focused suites, full Python suite, static checks, compiler
   byte comparison, secret scan, and boundary checks.
7. Commit and push exact reviewed files; verify local, origin, and GitHub heads.

## Internal production release sequence

1. Fresh read-only preflight records both repository heads, legacy service PID
   and listener, legacy database device/inode/size/mtime, units, cron/timers,
   runtime paths, permissions, and rollback prerequisites.
2. Create and validate a detached immutable release from the reviewed Git
   commit.
3. Through that exact release control plane, build the complete runtime tree in
   a random sibling staging root and atomically publish it with
   `renameat2(RENAME_NOREPLACE)`. A clean first installation must not require
   the database to exist before bootstrap; an existing final root is validated
   as complete or fails closed rather than migrate or overwrite it. Stale staging
   roots are reported and retained, never automatically cleaned.
4. Install only the new internal service and timer units.
5. Start the API service with no public route and verify authenticated catalog
   state before collection.
6. Execute one bounded generic collection pass for every active dataset. The
   manual bootstrap may supply an explicit reviewed request window (for
   example, the last completed exchange session on a weekend); it must still
   use the same generic registry-driven collector and may not add a dataset-
   specific code path.
7. Verify per-dataset facts/latest-success-receipt conservation and
   catalog/query metadata, then run the strict authenticated probe.
8. Enable the collection and probe timers only after the manual pass and strict
   probe succeed. The regular scheduler may subsequently skip datasets that
   are outside their configured weekday/window without invalidating the
   already-verified bootstrap.
9. Re-run production readback and prove the legacy service/database identities
   are unchanged.

Any unknown dirty production state, missing credential, unsafe path, failed
schema/readback, provider blocking error, or legacy identity drift stops the
release before mutation or triggers rollback of the new lane only.

## Internal completion stop line

Internal service is complete only when all of the following are fresh facts:

- reviewed Git commit is identical locally, at `origin/main`, and on GitHub;
- new provider-native API service is active on loopback and authentication is
  enforced;
- all three first datasets have current SQLite facts and matching success or
  truthful terminal receipts;
- catalog/query return provider-native data with objective freshness, quality,
  lineage, degraded, receipt, observed-at, and data-through metadata;
- pagination and same-as-of reads are reproducible;
- scheduler and probe timers run without overlap or secret leakage;
- TradingAgent and MarketGraph can use the frozen HTTP contract without DB or
  legacy fallback;
- rollback is exercised or dry-run proven from the exact deployed release;
- legacy `8082`, legacy database, external ingress, and `REAL_TRADING_ENABLED`
  remain unchanged.

External Beta, billing, external tenant onboarding, public ingress, broader
dataset expansion, DuckDB, and any trading-production work remain later phases.
