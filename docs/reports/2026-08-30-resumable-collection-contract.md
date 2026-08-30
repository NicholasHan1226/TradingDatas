# Bounded collection progress and truthful time contract

Design baseline: `4ef956544fc9eb50584b0bfa00fcf83e5e12711c` (2026-08-30).
Status: design frozen before implementation; not a production or provider observation.
Scope: existing active current-day cumulative minute binding and seven existing
single-code announcement-date bindings. No new activation, route, service,
timer, storage object, transport quota or history rewrite.

## Reproduced configuration gap

A synthetic reproduction against the unmodified baseline uses the existing
planner and selector with three codes and two variants. A trusted first-code
receipt leaves code B next for the old date; the next day generates only the
new date and selects code A again. A new bar likewise selects A again. Command:
`uv run --python 3.12 --with-requirements requirements.txt python work/collection-progress/reproduce_gap.py`.
It completed successfully with old-window next `[B]`, next-day first `[A]`,
next-bar first `[A]`, and only `period=20260721` automatically planned. This is
synthetic code evidence, not an upstream observation.

`_resumable_batch_state` matches complete exact windows and config/universe/batch
identity correctly; removing those checks is not a repair. Session planning
creates a new bar window each tick. Current-only event planning abandons an
unfinished prior date. Neither behavior has an existing binding-level opt-in
for bounded continuation/rotation. The already merged dataset-scoped receipt
history loader remains unchanged and must not regress to whole-registry scans.

Configuration-only alternatives were checked. Official snapshot income doc 33
requires ts_code and documents optional ann_date/start_date/end_date; cb_share
doc 247 requires ts_code and ann_date, with optional range keys. Existing request
observations freeze single-code plus ann_date; STATUS records real rejection of
income ann_date alone and silent-empty multi-code requests. No evidence permits
removing code fanout or replacing the exact-date request with a range. A range
might reduce calls, but changes provider semantics and needs its own bounded
upstream validation. A manual older exact-date plan works today, but cannot make
the timer preserve unfinished windows. Current-only timer semantics remain the
default for all bindings that do not opt in below.

## Frozen general contract

Extend existing resumable_fanout with optional strict `progress_mode` enum:
`complete_window` (unchanged default), `session_day_rotation`,
`partition_continuation`; and `continuation_max_age_days` (default 0, required
positive bounded value only for partition_continuation), plus binding-only
`partition_date_field` required only for partition_continuation. New values participate
in config identity; absent defaults preserve every old binding hash. Compiler,
registry loader and dataclass must enforce the same applicability. No API name
or dataset ID controls Python behavior.

### Current-session cumulative observations

`session_day_rotation` requires session_minute cadence, v2 fanout, an exact
local-calendar-day datetime window, and existing windowed_unique_primary_key
response completeness. The window is fixed local midnight through 23:59:59,
using the declared start/end keys, not a changing request timestamp. These keys
are validation/cursor metadata only and are not sent as unsupported historical
provider arguments. Calendar and existing morning/afternoon gates remain active.

For current-day responses, validate the local date against the collection start
and completion clocks, and each provider timestamp against the actual completion
clock before any fact can be persisted, including partial-success failure paths.
Prior-day, mixed-date, malformed/missing-time, future and cross-midnight late
responses fail admission as a whole. Non-null [ts_code,time] identity is required;
no row is silently dropped or rewritten. `data_through` is the actual maximum
validated provider time, never the collection clock. A successful old prefix can
therefore not make a new day fresh. Empty calls retain empty receipts and no
watermark; they do not establish current-day completion.

Within this exact day/config/universe, select never-attempted then least-recently
attempted batches. Failed and empty observations count only for fair rotation,
not successful coverage. The existing per-call retry and per-round batch caps
remain unchanged. A persistently bad batch cannot pin every later code; it is
visited again only as bounded rotation reaches it. Success is not permanently
complete: after a sweep, oldest observations are refreshed. The planner never
suppresses this mode on whole-day completion. New day/config/universe starts a
new identity and cannot borrow old successful coverage.

Closing/late semantic: rotation continues only during the existing eligible
windows, including their configured publication buffer. It does not add an
after-close run or a special all-code closing pass. A code observed early may
never be revisited that day at the existing capacity. 5971 codes / 5 = 1195
batches (the separately observed 1194 count depends on that frozen universe);
even the generous 52 ticks x 20 = 1040 batch upper bound cannot finish that
universe. This is breadth progress plus truthful snapshots, not full-market,
all-minute, historical-Friday or close-complete coverage.

Minute schema is a new major 3, preserving merged major-2 meaning and old rows.
Fields remain ts_code/time as text, non-null/selectable/sortable; time becomes
filterable for bounded consumption. Price/volume/amount fields retain their
current float/nullability. Response freq remains absent; request freq=1MIN is
unchanged. PK [ts_code,time]; payload-hash append-only storage preserves distinct
provider revisions. It does not claim that revisions never occur. Consumer
contracts must explicitly negotiate major 3 before production use.

### Already-started date partitions

`partition_continuation` requires an event binding, a single exact YYYYMMDD
request key and a declared text response `partition_date_field`. Non-null and
strict YYYYMMDD are enforced at admission, without changing public field
nullability, identity, as-of/range/partition metadata or schema major. The
response date field may differ from the request key (e.g. publish_date); every
returned row must equal the actual requested date and belong to the requested
fanout code. All failure/partial paths use the same checks. Financial public schemas remain unchanged; payload-hash revisions remain intact
without inventing a financial business key. The binding-only date field drives
the actual row watermark; empty has no watermark.

Only prior windows evidenced as already started by matching validated receipts
may continue. New config hashes intentionally cannot resume pre-change receipts;
only windows started under this new config participate. Do not fabricate dates between the earliest receipt and now. A
binding opts into a finite maximum age (candidate 31 days); dates beyond that
age stop consuming automatic budget but their debt/evidence is retained and is
not relabeled complete. This cap is limited catch-up, not a retention deletion.
Current and oldest unfinished eligible prior window alternate from trustworthy
recent receipts, with current first on a new day. At most one window is planned
for that binding per round; this does not increase calls. A failed oldest window
still counts as an attempt for lane fairness so it cannot starve current work.

Within current date rotate observations, including empty/success, so a morning
empty cannot permanently suppress a later announcement. For a prior date,
completed success/empty batch observations can retire only those exact
batch/variant/config/universe identities; remaining batches are attempted fairly.
No single row, last execution, or run clock proves a whole date covered.
Old-window completion is bounded observed query coverage, not provider finality
or completeness against future revisions. Newly published historical revisions
still require explicitly scoped re-observation.

Capacity is intentionally not called convergent: one single-code call per
five-minute round yields at most 288 calls/day before other budgets/latency.
Half allocated to current and half to debt cannot service 5971 new code-date
pairs/day. Dates can age out with substantial debt. Improving full coverage
requires separate verified provider request-shape/capacity work, not raising
quotas or silently broadening date queries here.

## Required verification and stop lines

Before candidate freeze, SQLite tests must exercise real collect -> receipt
validation -> planner/selector chains for same-day progression, next-day reset,
old/mixed/future/late data, empty, permanent and transient failures, revisions,
config/universe mismatches, completed versus incomplete historical partitions,
age expiry and no starvation between current and old lanes. Test all new parser
closed enums/applicability and stable old hashes. Compile both source layers,
check activation set and budgets unchanged, and produce nonzero bounded plans.
Synthetic tests never become upstream permission or production receipt evidence.

No persistence/API changes are authorized. If truthful timestamp/identity rules
cannot be expressed within these bounds, stop the affected candidate rather than
weakening admission or publishing a premature contract_ready claim. Production
requires parent-owned exact release preflight and real provider/SQLite/API
readback; candidate tests do not authorize deployment.

## Candidate implementation and local evidence

The implementation now keeps financial schema major/fields/nullability/PK and
all as-of/range/partition metadata unchanged. Its binding-only
`partition_date_field` is `ann_date` for the six report families and
`publish_date` for cb_share. New financial binding hashes do not adopt old
configuration or old-universe debt. Current-seen, started-window and last-attempt
lane decisions use current expected universe/index/count/batch-values identities
and registered variants, not merely the presence of a v2 receipt. The current
source-universe derivation is shared with the existing completion checker; it
does not bypass source authority or weaken default complete-window behavior.

New behavior was tested with real temporary SQLite transactions and the existing
receipt authority loader, planner and QueryService. An old-binding row followed
by same-payload new-binding observation remains byte-for-byte unchanged with
its original quality and receipt. Actual `row_receipt_proofs` still identifies
the old receipt; the fresh observation cannot certify that old row retroactively.
A prior-date continuation can conservatively make the latest projection show an
old watermark/stale until the next current round. Release readback must inspect
request windows and row proofs separately; this patch does not change API
projection or substitute the current clock for an old announcement date.

Local checks as of the candidate review handoff:

- Two normal source compilation layers completed successfully. Compiled registry
  SHA256: `319fcd20fd7ab6b46698929e39996a1833166d31b21698debe6cf7683b246c4e`;
  request-source provenance and activation-wave registry hash agree.
- All 184 non-target binding hashes match baseline exactly. Only eight target
  bindings change; activation/entitlement, row/byte/depth budgets, per-round batch
  caps and the schedule document remain unchanged. Seven financial public
  contracts are unchanged; only the minute dataset advances to public major 3.
- There are 35 new regression cases. A combined new-regression/related-planner
  run passed 63 tests in 44.66 seconds. It includes same-hash universe change,
  old-config debt exclusion and failed sibling-variant revisit.
- The initial six-file compiler/registry/regression combination ran 325 tests:
  322 passed and three old expectation/message checks failed. Expectations were
  updated for the intentional progress declarations and minute major; the old
  compiler unknown-key error wording was retained. The affected rerun passed
  101 tests in 72.19 seconds. The subsequent six-file combination passed
  328 tests in 187.79 seconds. It collected the then-current 31 new cases before
  the final four malformed-code regressions were added; it is not reported as
  a 332-case run or as verification of the later code guard by itself.
- Independent review reproduced a malformed provider code (JSON list/dict)
  raising TypeError before a failed receipt could be written. Admission now
  requires a nonempty string before fanout membership. Four real SQLite cases
  (list, dict, null, empty string) passed in 8.45 seconds, each proving a failed
  receipt, no admitted facts and next-batch progress. The independent final
  review reran all 35 new cases against the frozen files: 35 passed in
  52.68 seconds, with no remaining P0/P1 findings. It independently confirmed
  the 184 unchanged hashes, eight changed bindings and unchanged budgets and
  activation. This review is code/synthetic evidence, not production evidence.
- Adjacent ingest resumable/partial/future tests passed 7 cases in 0.95 seconds
  (145 deselected). No tests remain running at this handoff. Full repository,
  external-service and production checks were not run by this task; exact-head
  CI and release readback remain separate parent-owned gates.
- Ruff on all changed Python and `git diff --check` passed. No whole-file
  formatting was applied to existing runtime files.

These checks contain synthetic responses only. No production call, commit,
push, deployment, server mutation or fact rewrite was performed by this task.
The fixed day range is a cursor/admission envelope; the provider payload time is
also bounded by the actual clock immediately before persistence, so a future
row cannot become valid merely because the day-envelope end is 23:59:59.

## Frozen verification and release handoff

Frozen runtime SHA256 values:

- `collectors/tushare/provider_native_ingest.py`:
  `a2c0bf803c42d6b2fda941142228aa55e9d45fa5bb806cf00e3460316db9fd77`
- `tools/provider_native_cadence_planner.py`:
  `f1ba924d5da6b1d667ce0037c2ab531b29d0d5f9c14e605958d2470030a37c58`
- `tests/test_resumable_collection_progress.py`:
  `1b13627a070ab47d1f369669a674f65a5f33bddfed0d63ee49875e30d700f115`

| Binding | Progress mode | Admission date | Public schema |
| --- | --- | --- | --- |
| cn.dataset.rt_min_daily | session_day_rotation | time, exact current local day and completion clock | 3.0.0; PK ts_code,time |
| cn.dataset.balancesheet | partition_continuation | ann_date, exact queried date | unchanged |
| cn.dataset.cashflow | partition_continuation | ann_date, exact queried date | unchanged |
| cn.dataset.express | partition_continuation | ann_date, exact queried date | unchanged |
| cn.dataset.fina_audit | partition_continuation | ann_date, exact queried date | unchanged |
| cn.dataset.fina_indicator | partition_continuation | ann_date, exact queried date | unchanged |
| cn.dataset.income | partition_continuation | ann_date, exact queried date | unchanged |
| cn.dataset.cb_share | partition_continuation | publish_date, exact queried date | unchanged |

All seven continuation bindings use a 31-day maximum age. Only new-contract,
current-universe already-started windows are eligible. The historical production
prefix is not automatically imported as new-contract progress.

The normal source build used these two commands, in order, after synchronizing
reviewed/transport source hashes and then the compiled upstream provenance pin:

```sh
uv run --python 3.12 --with-requirements requirements.txt python tools/compile_tushare_runtime_contracts.py
uv run --python 3.12 --with-requirements requirements.txt python tools/compile_provider_native_registry.py
```

For immutable-candidate preflight, resolve `TD_PYTHON` to the existing dependency
environment and `TD_CHECK_DIR` to an existing writable directory outside the
release. Run from the candidate root; write neither bytecode nor build output
into the release:

```sh
PYTHONDONTWRITEBYTECODE=1 "$TD_PYTHON" -m tools.compile_tushare_runtime_contracts --output "$TD_CHECK_DIR/tushare_upstream_contracts.v1.yaml"
PYTHONDONTWRITEBYTECODE=1 "$TD_PYTHON" -m tools.compile_provider_native_registry --upstream-contracts "$TD_CHECK_DIR/tushare_upstream_contracts.v1.yaml" --output "$TD_CHECK_DIR/provider_native_dataset_registry.yaml"
cmp config/tushare_upstream_contracts.v1.yaml "$TD_CHECK_DIR/tushare_upstream_contracts.v1.yaml"
cmp config/provider_native_dataset_registry.yaml "$TD_CHECK_DIR/provider_native_dataset_registry.yaml"
```

The broad local check command was:

```sh
uv run --python 3.12 --with-requirements requirements.txt pytest -q -n2 tests/test_compile_provider_native_registry.py tests/test_compile_tushare_runtime_contracts.py tests/test_tushare_request_observations.py tests/test_quicksync_interface_observations.py tests/test_provider_native_registry.py tests/test_resumable_collection_progress.py
```

For the parent-owned production dry-plan, resolve `TD_DB` from the actual service
inventory. The following reads planner state without provider execution and
keeps its lock/output outside the release; verify the process resolves the
candidate's canonical registry and the frozen registry hash above:

```sh
PYTHONDONTWRITEBYTECODE=1 "$TD_PYTHON" -m tools.run_provider_native_schedule --db-path "$TD_DB" --lock-path "$TD_CHECK_DIR/plan.lock" > "$TD_CHECK_DIR/plan.json"
```

Do not append `--execute`. Require nonzero plans for each target at its eligible
cadence; a nonzero unrelated dataset is not that target's gate. On Sunday
2026-08-30, a zero minute plan is expected and must not be bypassed. A bounded
planner-only scenario can add `--now 2026-08-31T10:00:00+08:00` to the command
above and use a separate output file, provided that date has trusted calendar
coverage. Such a result is explicitly a simulated clock against real stored
state, not current eligibility, provider success or deployment proof. Actual
minute observation still requires a real eligible session and authenticated
SQLite/receipt/API readback. This task did not run either command against the
production database.

The first candidate CI (`33299423804`) found one outdated scheduler expectation:
its fixture seeds only daily prices and a calendar, but expected all seven
continuation bindings to plan without a verified security-master universe.
The corrected test explicitly requires `dependency_unavailable` for those seven,
keeps the unchanged pledge binding planned, and preserves the not-on-demand
assertion. No runtime/config change was made for this failure. Parent reran the
corrected test plus all 35 new SQLite regressions: 36 passed in 42.47 seconds.
Independent review confirmed that this closes an obsolete expectation without
weakening the separate real-SQLite progress tests. The updated exact head still
requires fresh CI before merge.

## Runtime preflight correction after PR 396

The parent-owned read-only production preflight found two P1 execution-path
gaps before release switching. The merged tree is
`284b2f7a0d4a60aae564e097f918a86116422250`; the correction is isolated on
`codex/collection-progress-runtime-preflight-20260830`. This section supersedes
any implication that the earlier literal-universe regressions alone verified
the real dataset-field source path. Production was not changed by this task.

First, the real schedule runner supplies `calendar_dataset_ids` to
`load_planner_state`. That optimized path discarded every non-calendar payload,
including valid security-master and convertible-bond source facts. Their
`ts_code` therefore appeared absent to the new universe checker, producing
`dependency_unavailable` for all seven financial targets. This was not missing
upstream source data or a missing `list_date`. The correction derives active
resumable `dataset_field` dependencies from the registry and hydrates only those
source payloads in the existing verified snapshot, alongside calendars. Other
historical payloads remain unhydrated. Receipt/config/success filtering and the
missing-source dependency gate remain unchanged.

Second, `_load_completed_fanout_batches` reused its new `now: datetime` parameter
for an older local date cutoff variable. The dataset-field path consequently
passed a `date` to the continuation selector, raising `AttributeError` before
collection or a failed receipt. Renaming that local value to `local_today`
preserves the original source-age cutoff and the incoming datetime separately.
No request, quota, schema, config hash or registry artifact changes are needed.

Four new regressions use the actual immutable income/security-master and
cb_share/cb_basic definitions with synthetic provider responses and temporary
SQLite. They cover the production calendar-only loader, nonzero target plans,
real source collection, target collection/validated receipts, same-day 0-to-1
progress and next-day reset, actual date watermarks, and preservation of the
target facts' unhydrated fast path. Before the fix, the cb_share cases reproduced
both empty source payloads and `date.astimezone` failure. All four passed in
5.83 seconds after correction. Six adjacent dataset-field/resumable ingest
checks passed in 0.11 seconds; changed-file Ruff and diff checks passed.
The combined 39 progress regressions plus full scheduler test file passed
188 tests in 117.39 seconds with two workers. Against the unchanged registry,
the additional hydration set is exactly `cn.equity.security_master` and
`cn.dataset.cb_basic`, not a restoration of all historical payload loading.
No production provider call, commit or deployment was
performed by this task; the parent must repeat real-data preflight against the
new exact candidate before any switch.
