# Bounded catalog reads and response-contract diagnosis

Candidate based on main `878567a253c00c2fe26973efb80d35c9b4392c22`.
No release, production write, migration, provider call or configuration change is
part of this candidate. Production observations below are dated 2026-09-05 CST.

## Catalog latency

The initial authenticated A-share/crypto catalogs took16.647/8.441 seconds. Exactly
three additional rounds with15 seconds between rounds took16.839/11.121,
15.645/9.543 and5.851/11.295 seconds; all HTTP200. Three of four A-share reads
exceeded the unchanged15-second gate. A final passing sample does not erase those
failures or demonstrate stable tail latency. Both process PIDs and working
directories stayed on the target SHA. The preceding383591aa→878567a diff changed
only three documentation files, excluding an application-code change there.

The original recent-receipt SQL applies ROW_NUMBER over the entire append-only
journal, carrying notes payloads through the window before selecting100 rows per
source. Its output is bounded; its historical payload work is not. This is a
reproducible structural cost, not proof that it alone caused each production
spike. Concurrent natural collectors and high observed I/O wait23–27% also
coincided with the earlier samples; later I/O wait was0%. No schedules were changed.

The candidate enumerates source keys via the existing covering index and reads
the same ordered suffix per source. Unknown sources remain included. Original
ordering, total budget, schema/identity/snapshot validation and execution-sibling
completion remain intact. Legacy databases without the optional index use the
old query. No schema/index migration or payload cache is introduced.

A synthetic10,000-receipt test compares every selected raw field with the old SQL,
including foreign sources and cutoff timestamp ties, and requires less than half
its SQLite VM work. It also checks the no-index fallback. Existing projection
fail-closed and cohort tests remain required. This is an offline cost reduction;
production latency acceptance requires a separately authorized exact-release
readback and remains unproven by the synthetic benchmark.

## fina_mainbz: concrete drift, no silent v1 rewrite

The13:03 query was HTTP200/one row, runtime success but partial/degraded with
`missing_field:update_flag`, `unknown_field:bz_code` and
`response_completeness_unverified`. Freshness was fresh and lineage complete.
A shape-only synthetic reproduction confirms the two field quality errors without
copying any provider/customer values.

The current upstream contract and hashed official document snapshot declare both
fields. However `config/quicksync_interface_observations.v1.yaml` records bz_code
as missing under schema_subset; `_apply_observed_schema_subset` in the registry
compiler consequently removes it from the generated v1 registry. Today's response
shape contradicts that older observation and omits update_flag instead. Nullable
means a present null is allowed; it does not make an absent field valid.
Additionally the binding has response_completeness=null, so query metadata
correctly refuses to claim response completeness. None of these reasons can be
removed by relabeling success or changing latency limits.

The existing response-contract override mechanism requires a higher schema major.
The minimal next contract decision is a reviewed transport-shape override retaining
bz_code and explicitly addressing update_flag, with source/evidence and historical
query compatibility. It must decide how old v1 facts/config-hash receipts remain
queryable and what future evidence establishes completeness. This candidate does
not edit generated registry bytes, rewrite historical quality or invent a
completeness guarantee. A major-version/transition choice remains with the owner.

## Draft PR395

Fresh GitHub inspection finds draft head
`65df6af79b7e1806afa2cc7645dc750d0a344a86`; four PR CI shards succeeded. It only adds a
decision handoff. The current code still drops funding markPrice and snaps the end
window to an eight-hour boundary; a fractional-second settlement can fall
outside that bound. Adding mark price changes payload-hash identity for the same
logical settlement, requiring an approved schema-major/identity/transition plan.
The draft also leaves actual perpetual/mark OHLCV source contracts (B) and an
independent historical funding schedule source (C) unapproved. These are contract
choices, not a failing CI repair. No migration path or new dataset is selected here.

## Independently reviewable funding-window correction

The local candidate also isolates a smaller correction from PR395: the existing
48-hour request window ends at the observed UTC millisecond, rather than at an
assumed eight-hour settlement boundary. It retains the same dataset IDs, four
payload fields, append-only identity, provider request count and overlap/dedup
behavior. It does not add markPrice, OHLCV or schedule datasets and does not resolve
PR395's identity decisions. A mocked collector test retains a settlement at
16:00:00.002 and excludes one after the inclusive observed end. The full existing
USD-M module passes31 tests offline; no provider request or activation occurred.

Final catalog synthetic comparison: the original window used approximately745,200
SQLite VM steps and the seek plan77,200 for the same200 selected rows (10,000-row
fixture). Measured local wall times0.009227/0.001225 seconds are illustrative only,
not a production SLA claim. Source enumeration remains proportional to index
history, and timestamp ties may require key sorting; only the selected payloads
are fetched. This does not eliminate coverage aggregation, snapshot verification,
execution-sibling reads or external load as additional costs.

Funding endpoint semantics were checked against the [official Binance USD-M market-data documentation](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#get-funding-rate-history): funding history bounds use inclusive millisecond timestamps. This source check does not establish collected historical completeness.
