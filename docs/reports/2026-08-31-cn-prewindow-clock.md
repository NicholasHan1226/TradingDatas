# CN freshness clock before configured availability

Candidate base: `0f5f0daf01ebde3d978e302d4f605b940779beb3`.
Scope: read-clock projection only; no registry, provider, scheduler, database, SLA,
credentials, service or timer changes. This report is candidate evidence, not a
production fix or a statement of continuous health.

## Reproduced problem

The production `c714dc9f3b5a48268818dee67c5b2bb8c832cc99` weekend clock stopped
clamping at Monday 00:00. A fixed Friday success receipt therefore changed from
success to stale between Sunday 23:59:59 and Monday 00:00, even though the next
configured collection window had not opened. The 2026-08-31 00:20:39 CST local
readback showed nine `postclose_daily` datasets with `data_through=20260828` and
`cn.dataset.rt_min` with Friday 15:00. Their timestamp transition is reproducible
without changing any receipt. This does not establish complete historical or
symbol coverage.

The separate `stk_holdernumber` latest-empty observation was approximately
1,028 seconds old against its 900-second SLA. That event observation remains
stale; this patch does not hide it.

## Frozen behavior

Only success freshness for market `CN`, timezone `Asia/Shanghai`, and cadence
`session_minute` or `postclose_daily` uses this clock. Before the configured
`availability_after_local`, or on a day outside configured `weekdays`, the
clock is the preceding configured weekday's existing close: 15:00 for minute
cadence, or the following midnight for postclose cadence. The existing
end-of-date reference and strict `age > SLA` comparison remain unchanged,
including the microsecond distinction that rejects a missing preceding daily
partition. Existing date-only and monthly watermark interpretation is unchanged.

At availability on a configured weekday, the ordinary clock resumes immediately;
there is no new grace period. The current schedule specifies 09:30 and 16:30.
Those availability times are read from the existing schedule, not duplicated
in runtime code. Weekdays may be a nonempty subset of Monday through Friday;
weekend entries are unsupported and fail closed. This is a configured-weekday
rule, not a holiday calendar. No new holiday correctness claim is made.

Missing Friday/minute 14:30/Thursday receipts remain stale as applicable.
Missing or mismatched receipts, failed and empty receipts, event/reference/
on-demand data, other markets/timezones, and the existing intraday lunch-break
rule are unchanged. Empty freshness continues to use receipt completion time.

## Configuration and dependency boundary

The projection lazily imports the existing pure
`tools.provider_native_cadence_planner.load_schedule_bytes` parser after the
receipt module is initialized. The planner already imports receipt projection;
a top-level reverse import would create an initialization cycle. No planner
execution, registry activation, provider access, calendar lookup or new YAML
parser is introduced.

Only the physical release's `config/provider_native_schedule.yaml`, located
relative to the resolved receipt module path, is accepted. No environment or
working-directory schedule selector is consulted. Symlink/non-regular files,
missing/unreadable files, invalid YAML/contract, missing availability and
unsupported weekday policies raise the existing `RuntimeProjectionError`.
There is no fallback to a healthy result or the unadjusted clock. As with other
read-model failures, the API error boundary can fail the affected request closed.

After successful validation, only immutable availability/weekday tuples are
cached in an immutable mapping for that process. Release files must remain
immutable; modifying an installed schedule in place is not a supported update
mechanism. An API runtime now requires its own valid packaged schedule when it
projects applicable CN success receipts. A bad shared schedule can therefore
fail a catalog containing those datasets; unrelated markets and cadence paths
do not load that policy. Production manifest verification and independent
release/readback remain required.

## Verification

TDD against the unmodified base: 29 selected cases produced 11 expected failures
and 18 passes. Failures cover four Monday prewindow cases, six invalid-schedule
cases, and the configured availability/weekday/cache case. A separate symlink
negative also failed on the base. After implementation, 30 new cases plus 11
existing weekend/lunch/month cases passed (41 total, 38.09 seconds).

Reproduction command (Python 3.12, local SQLite fixtures only):

```sh
uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/test_receipt_projection.py -k 'cn_prewindow or weekend or lunch_break or month_watermark'
```

The first full receipt/catalog/provider-native-query run returned 328 passes and
seven failures (364.10 seconds). All seven were existing stale fixtures evaluated
inside the newly protected prewindow, not receipt-integrity failures. Assertions
were retained:

- Two global-tripwire tests and the three run-id/source-tamper variants now read
  at 18:00 CST instead of 10:00, after daily availability; receipt/anomaly/stale
  assertions are unchanged.
- The timezone/SLA boundary test moves the watermark from 12:00 to 16:00 and
  the exact one-hour boundary from 13:00 to 17:00; its one-microsecond-over-SLA
  rejection remains unchanged. Receipt timestamps move by the same four hours.
- The catalog six-state fixture moves only `f_stale`'s watermark back one day,
  keeping it older than the preceding due close and SLA. All six state and
  queryability assertions remain unchanged.

All seven repaired cases passed in 23.72 seconds. The 30 new cases plus the
six repaired receipt cases also passed together (36 total, 36.79 seconds).
The final full regression on frozen runtime/tests passed: **335 passed in
349.19 seconds**, using:

```sh
uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/test_receipt_projection.py tests/test_catalog_service.py tests/test_provider_native_query.py -n 2
```

`git diff --check` passed and config diff is empty. Ruff reports only the two
pre-existing unused-local findings (`first_receipt` in receipt tests and
`response` in catalog tests); there are no new findings. Independent review,
CI, integration and production readback remain outside this author-side result.
No production or upstream requests were executed for this change.
