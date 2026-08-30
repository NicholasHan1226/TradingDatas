# Catalog latency and event refresh margin

Scope: generic receipt prefilter performance and an opt-in event refresh margin.
The fixed API, registry, schema, receipt validation, provider budgets, credentials
and activation states stay unchanged. Datas PM owns the feature PR and release;
Controller is not part of this workflow.

## Evidence and acceptance

The existing isolated Crypto API at release `15f463e` exceeded the 15-second
consumer timeout on 2026-08-30. A first full c714 CatalogService preflight measured
18.724 seconds with a cold validation cache and 11.120 seconds warm. Profiling
showed repeated construction of 200 large literal regex alternatives contributed
significantly to receipt lookup overhead.

The candidate keeps the same raw SQL candidate semantics. On UTF-8 databases it
searches the common byte prefix and checks exact suffix membership grouped by
length; more than 16 distinct lengths or no shared prefix retain the prior regex
path. Non-UTF-8 databases retain the original SQLite `instr` predicate. Invalid
TEXT/BLOB, NUL, malformed JSON, duplicate keys and overlapping matches are not
parsed away. Exact execution parsing, corrupt-receipt detection, callback cleanup
and the shared 400,000 raw-row read budget are unchanged.

A bounded same-snapshot comparison at 21:48 CST used the actual Crypto service
account and the full CatalogService, including coverage. Main cold/warm took
13.319/6.496 seconds; candidate cold/warm took 9.661/6.089 seconds. All four passes
returned exactly identical 240-entry public responses and identical raw candidate
multisets across 200 groups / 20,000 rows. The four passes share a read clock and
database snapshot; timings include diagnostic capture and page-cache warming.
This proves neither cold storage-cache performance nor authenticated HTTP latency.
No provider calls or database writes occurred in these diagnostics.

`stk_holdernumber` has both a 900-second minimum re-observation interval and a
900-second freshness SLA. An empty receipt at 21:17:37 is suppressed at the 21:20,
21:25 and 21:30 ticks, becomes due at 21:32:37, and is already stale before the
21:35 tick, before queue time is added. `cn_schedule` has the same short-SLA
pattern. Empty is valid evidence of a completed zero-row observation, not success
or proof of source completeness. The source documentation says irregular updates;
the 900 seconds is a local service target, not an upstream publication promise.

The optional event refresh lead defaults to zero. A 600-second candidate lead can
give these short-SLA datasets time for the five-minute tick and bounded execution,
without shortening the repeat interval of long-SLA event datasets. It is **not
enabled** in the repository schedule. Existing per-run ceilings do not establish
daily quota headroom; current-account daily-limit evidence is still missing.
Production frequency must remain unchanged until that evidence and a bounded
runtime check support activation. See `../OPERATIONS.md` for the configuration
contract and rollback to the zero/default setting.

## Release boundary

The existing Crypto database uses journal mode `delete`. New mainline writers
request WAL, so switching the whole release also needs a bounded journal-mode
transition and proven rollback; it is not merely an API restart. No schema change,
index, data rewrite, historical deletion or provider call is needed for that
transition. All original writers must naturally drain before it, with both
collector locks accounted for. The existing independent public snapshot timer
also uses the Crypto release pointer and must be paused/restored consistently;
its external market list and capture directory remain unchanged. An earlier
mainline change permits partial empty market responses and records their slugs,
while all-empty and provider errors still fail. This may reach later markets in
the same existing bounded list; it adds no markets or retries.

Release acceptance requires exact-main CI, trusted immutable manifest checks,
authenticated catalog and six-family query readback below the existing 15-second
limit, unchanged authority on a paused-writer baseline, service/timer restoration,
and normal subsequent collector receipts. Rollback must restore journal mode
before starting the old reader, preserve facts/receipts, and separately verify the
old pointer and authenticated API. Failed rollback verification keeps writers
paused and reports the exact failed gate. This document records a candidate;
production results must be appended to the PR and external run report after the
actual maintenance window.
