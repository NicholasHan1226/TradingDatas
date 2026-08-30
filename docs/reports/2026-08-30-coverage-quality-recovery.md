# 2026-08-30 coverage and quality recovery

## Scope and evidence

Observed on 2026-08-30, Asia/Shanghai. This report separates an installed-release
recovery from a source candidate. It does not declare all datasets stable.
No database migration, existing-row quality rewrite, token change, new timer,
provider activation, or trading operation is part of this change.

Production A-share release during the inspection:
`385a4fa4fb461fd1e276e5cfd6577dbcb0758b3d`; Crypto remained on
`15f463eee602e919244678985622adfedfea1189`. The source candidate starts from
`bec87b7fae9f8efbb9b48e224bd61a35d8cd9c20`. Local source, PR, main, immutable
release, receipt, HTTP readback, and consumer readiness are separate gates.

The 13:34 catalog contained 192 A-share datasets: 80 success, 57 paused,
43 empty, 10 unobserved, 1 stale, and 1 failed. These counts are a timestamped
projection, not proof of universe/history coverage. Read-only coverage inspection
used `open_verified_read_model_snapshot` as the service account and
`validated_receipt_history_for_dataset` for each resumable dataset. Only matching
provider/config/window/frozen-universe/batch identity and success/empty variants
counted toward an observed batch. No full payload scan or database integrity
scan was run.

## Coverage baseline at 13:36

| Dataset group | Exact window | Completed batches | Implication |
|---|---|---:|---|
| balancesheet, cashflow, express, fina_audit, fina_indicator, income | ann_date=20260830 | 10 / 5,971 each | The date resets before a serial one-batch sweep can finish. |
| cb_share | ann_date=20260830 | 10 / 1,162 | The same daily-window limitation applies. |
| pledge_stat | empty request window | 7 / 5,971 | Can resume across days, but current evidence suggests about one batch per 15 minutes. |
| cyq_chips, cyq_perf | trade_date=20260828, current universe hash | 289 / 598 each | About 48.3% of the current batch universe; earlier universe hashes are not interchangeable. |
| rt_min | latest eligible Friday bar, 14:55 | 20 / 20 | One exact bar/universe observed; not a historical-completeness declaration. |
| rt_min_daily | recent Friday bar windows | 20 / 1,194 each | Each new bar repeats the first 100 codes instead of continuing the day sweep. |

Success/empty batch coverage is not row coverage. An empty provider partition
can be legitimate; accumulated catalog row counts include old windows and schema
majors and cannot substitute for current-batch completeness.

No reliable completion ETA exists for the ann_date cohorts under the current
window reset. Even an optimistic five-minute single-batch interval allows only
288 daily batches; raising to four per tick still cannot finish 5,971. For the
windowless pledge_stat backlog, 5,964 remaining batches at an uninterrupted
15-minute pace would take about 62.1 days; this is a conditional capacity estimate,
not an SLA. Provider quotas, failures, shared budgets, changing security masters,
and runtime durations may extend it. No rate increase or automatic historical
backfill is authorized by this estimate. A future financial-report coverage
change needs a verified bulk request contract or an explicitly bounded persistent
window backlog; neither can be fabricated from official Tushare limits.

## Installed-release recovery

The existing collector dispatcher ran a five-item on-demand manifest for
trade_date=20260828. Its SHA-256 was
`612c6fb4a1ecbcd96cf3bfd53bd8eea543b88e30a92420bb231b4bdb7ecb53ac`.
The deployed-release dry-run selected exactly five datasets without provider
calls or writes. The timer was paused, the existing run was allowed to drain,
and the same installed service and lock executed the batch at 13:46:40–13:46:44.
Invocation: `14ab4814c0da446d828bad8dc22996ce`. Exit status 0; selector files
consumed and removed; timer restored active. The old receipt history was retained.

| Dataset | Inserted rows | Fresh receipt |
|---|---:|---|
| fut_mapping | 202 | `3a2a17aae13f821fae1f422a3e66c3174cbf8c883cd0168a7c881c96bf61572f` |
| fut_settle | 911 | `c0f96f7f88ef11fd1814a05b902c9307dc50b292bdda6bf50da546a20c60e8f7` |
| limit_cpt_list | 20 | `345392f4177c3db2120c41287a017aab24046055636d65deaef4b410e155e722` |
| moneyflow_hsgt | 1 | `e04c8af0056fa24cb7f2d30b51f969d347c67fa8a8018f2b9a4171a67d5580c7` |
| sz_daily_info | 14 | `a9cde9c57b9ea09776182033ccbc564f685338f8b2c80ee9c96495113000e9bb` |

All five authenticated `/v1/query` checks at 13:47:27–13:47:29 returned a real
row, `ready`, `quality=valid`, `lineage=complete`, and matching SQLite receipt
authority. Total inserted: 1,148; rejected: zero. These on-demand contracts remain
on-demand: this is observed recovery, not continuous scheduled stability.

The second bounded manifest preserved all six `fut_basic` exchange variants.
Its SHA-256 was `ec5a7f4dc134aa463c24f64bb113046e689bdaa765d292d51bdd11b88632704b`.
Invocation `183190cfdc3a4ae3817791953a493f49` ran 13:53:07–13:53:37, exit 0,
inserted 11,196 rows with six receipts and zero rejects. Selector cleanup and
timer restoration succeeded. Authenticated query at 13:54:46 showed successful
collection and complete lineage **but degraded quality**: the payload lacks
`trade_time_desc`. This is not counted as quality-ready recovery.

A dataset-bounded read-only grouping of these fresh rows (not a database-wide
scan) confirmed that all six receipt cohorts retained exactly that issue:

| Receipt digest | Rows missing trade_time_desc |
|---|---:|
| `12f7238ce647b918c7a8be7d06f3fd77e5942d790a87f7be7ad4bab3e5cb89a0` | 2,926 |
| `72e95d2b53e6856b16741778d56ed8f55a5a1ad4644f17ad838243a4c466d4f1` | 483 |
| `83e274760501e605869fb9ada786c635ce4f6563a79f364e9d8d4eaae3f87f3f` | 3,612 |
| `985ee15dbde9e863d4faa8f329e18584dd0f266277b652142958013231e7f94f` | 3,309 |
| `e13e9ec3c36b065783b57a4b58ae0714461ca9df717ac1ac1491f49c1f7e098e` | 146 |
| `eaadcf00ba840286f388f32b7e614811ec8da77234ee76d1f3ebd430b2922e29` | 720 |

Five bounded raw-key samples from the last cohort confirmed field absence;
example payload hash `b1d2889014defaacd10a469623f68f1b51fb01dedd7e2202516b2913aede2a1f`.
The same existing response-override mechanism removes only this field and
increments `fut_basic` to schema 2.0.0 in the candidate. Its `[ts_code]` identity,
six variants, on-demand semantics and budgets are unchanged. Old records stay
untouched; another real six-variant collection and API readback are required
after release. There is no dataset-specific Python addition.

Across both installed-release batches: 12,344 inserted rows, 11 receipts,
zero rejects; five datasets query quality-ready, one still quality-degraded.

## Source candidate: truthful response quality

### rt_min_daily

Five bounded production samples under schema major 1 all contained exactly
`amount, close, high, low, open, time, ts_code, vol`; none contained `freq`.
They were marked `missing_field:freq`, linked to receipt
`6acff9ff6369cba8408beb572191855cefcbd82c82fcaba4f6c51db7eb411a6f`.
Example original payload SHA-256:
`87df4ee06469e5feef5f509d8a8613673e7439591222244d9ddca0208f07aabe`.
The existing official-document snapshot remains unchanged; it declares a field
and is not evidence that this QuickSync response actually returned it.

The candidate uses the existing observed-response override mechanism to remove
only the absent **response** field and publish schema 2.0.0. The request remains
`freq: 1MIN`. No value is synthesized, and old major-1 facts/receipts remain
untouched. A new schema alone is not observed production evidence.

### broker_recommend

Five bounded samples for partition 202608 contained month `202608`, but retained
`time_format_mismatch:month:yyyymm` from the historical validator. Receipt:
`c871394579325d9621c1595363585813434ce5168dbd2a093a6b691ba129803f`;
example payload SHA-256:
`eef972eec2e5d21f4cdd6c42fe1f3841127a6d98315b1dd6a878843f08589990`.
The current strict YYYYMM validator accepts that representation. Repeating an
identical append-only row deliberately preserves its first quality decision.

The reviewed contract moves to major 2 without changing fields, identity,
monthly cadence, or request parameters. After an accepted release, bounded real
recollection of months 202607 and 202608 can create new facts with current
validation while keeping old facts and receipts. SQL quality updates, a minor
version workaround, and manufactured provider rows are forbidden.

The fixed query API serves the current registry major only: existing major-1
history remains stored but is not silently offered as a fallback. Until real
major-2 collection/readback and required consumer validation, the candidate must
not be described as a production quality fix.

## Day-scoped cursor proposal withdrawn after P1 reproduction

The first candidate `16e9dd84a00d2e50a533ada2942a17bbcc4756eb` attempted an
opt-in daily cursor. Initial unit and SQLite round-trip tests passed, but two
independent bounded SQLite reproductions then found a P1: the first batch
returned previous-day rows with a valid success receipt; another batch returned
current-day rows; the cursor regarded both as completed for the current day and
never revisited the first batch. The aggregate projection was successful. The
old per-bar cursor would revisit that prefix on the following bar.

This is a correctness regression, not a permissible full-market coverage gap.
The generic runtime/compiler changes, scope field, activation configuration and
scope tests were therefore removed from this PR before any production release.
The original candidate remains in Git history for traceability, but is not a
contract-ready or approved daily-cursor capability. Only the three schema-quality
changes and their regression tests remain. The existing bar behavior and its
known prefix/coverage limitation remain unchanged.

The inspection also found that the current minute contract lacks a response
time/completeness declaration: `_data_through` can fall back to run start time.
Accordingly, a fresh collection timestamp is not proof that its rows are from
today. The schema-quality changes alone do not fix this older timing limitation.

Before revisiting day accumulation, freeze a provider-time contract using the
existing `windowed_unique_primary_key` mechanism, non-null `[ts_code,time]`
identity, `date_field=time` and bounded cursor-only day start/end values. Test
previous-day, mixed-day, empty and late-updating responses, including whether a
failed early batch can be retried without starving other batches or expanding
budgets. Do not filter old rows into an empty-success receipt or infer current
coverage from the collector clock. This design remains unimplemented/unapproved.

Capacity is an independent gap: 1,194 batches at 20/run require at least 60
successful opportunities. Even a generous 52 five-minute opportunities across
the configured buffers yields at most 1,040 batches (5,200 codes). Early samples
also do not contain later bars. No full-market/close-completeness or next-session
stability is established.

## Consumer and release boundaries

The TradingAgent `CNFutures/fut_basic_contract_units` adapter also fixes major 1;
its fields do not include the removed description, but its schema gate will
reject major 2. That market is paused and must not be activated for this fix.

The TradingAgent `rt_min_daily_pit` adapter currently hard-codes major 1 and
requires `freq`. Its domain adapter will reject the new raw response. The broker
consumer obtains a major from catalog but freezes a contract fingerprint;
its event-time parser does not accept YYYYMM. Its default as-of request must
be checked against the live catalog; an as-of omission is required if the
consumer-visible contract is a current snapshot without an as-of field. Existing fixture tests do not establish
compatibility. These issues must be fixed and checked with bounded real consumer
reads before a corresponding consumer-ready/stable claim. Generic authenticated
HTTP readiness is a different layer. No observation worker, strategy, trading
state or consumer files were changed in this task.

The session's supplied merge rule still requires exact-head Controller
acceptance; newer repository text says that mechanism is retired in favor of
Datas PM. The old Controller task is archived. This candidate must not manufacture
an acceptance or use a conflicting automatic merge label. Prepare and verify the
PR first; resolve the applicable owner gate before any merge/deployment.

## Continued runtime observation

At 13:57, authenticated catalog readback showed A-share 192 datasets:
87 success, 43 empty, 57 paused, 4 unobserved and 1 stale (`rt_min_daily`).
The earlier transient failure was absent in that snapshot. `fut_basic` still
has degraded query quality despite its successful collection state. Crypto
showed 240 success and no stale datasets. Neither count certifies history
completeness or consumer compatibility.

After 13:15, seven completed natural funding runs each reported 40 successful
funding datasets, 40 receipt identifiers and zero retries; the latest catalog
readback independently remained successful. These are bounded post-renewal
observations, not a long-term availability guarantee. The isolated prediction
snapshot unit completed its natural 13:37–13:38:20 run with exit 0; that service
result alone is not dataset activation, fixed-API or consumer validation.

## Validation and next evidence

Both existing compilers completed successfully. All four source-provenance
hashes and the activation-wave registry hash match the compiled inputs. Pure
plans select the monthly broker and unchanged six-variant futures requests
without calling a provider or writing a database. Focused tests, independent review and
exact-candidate CI results are recorded in the PR; an unfinished test run is
not a passing result. Production source remains on the inspected immutable
release until the applicable gates and release preflight pass. Release validation must include
nonzero plans, bounded major-2 July/August broker collection, a next-session
minute observation, authenticated catalog/query and consumer readback, plus a new six-variant fut_basic cohort, with the
old immutable release available for rollback and all facts/receipts preserved.
