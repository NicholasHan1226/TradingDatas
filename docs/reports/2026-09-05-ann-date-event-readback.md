# 2026-09-05 authenticated catalog/query readback and ann_date event freeze

Observed 2026-09-05 00:28–00:35 Asia/Shanghai on `marketgraph-main`.
This report is a timestamped Evidence Plane readback. It does not declare the
universe stable, restore Scale500, enable email/payment, or authorize a new
GZ cut.

## Surfaces (separate)

| Surface | Fact |
|---|---|
| GitHub / local `main` at write-up | `d6e90fe6e423df4f149e76182d2d4db23ba204b6` (#471) |
| GZ A-share immutable `current` | `d6e90fe6e423df4f149e76182d2d4db23ba204b6` |
| `verify-current` | `verified=true`, `file_count=1050`, `tree=215f9fe634d0c57ea261f7496701aa13bd0659d0` |
| Units | `tradingdatas-v1-internal`, `tradingdatas-crypto-v1-internal`, `provider-native-collect.timer`, `tradingdatas-admin` = active |
| Source checkout | `/opt/investment/TradingDatasSource` at `d6e90fe6` is not production |

#454–#463 collection/query contracts are already on this `current`. The previous
STATUS line that they still needed a GZ publish is false as of this pointer.

## Auth walls

- Anonymous `GET http://127.0.0.1:18082/v1/catalog` → **401**
  `error.code=unauthenticated`.
- Authenticated catalog → **200**, 192 datasets.
- Crypto loopback `18083` anonymous **401**; the A-share internal token is also
  **401** there (isolated runtime, not a second A-share catalog).

## Catalog distribution (00:28 CST)

`runtime.state` counts from the authenticated catalog projection:

- success 81
- empty 47
- paused 56
- unobserved 4 (`fina_mainbz`, `stk_mins`, `top10_cb_holders`, `top10_floatholders`)
- stale 3 (`margin`, `margin_detail`, `margin_secs`; `freshness_sla_exceeded`, watermark `20260903`)
- failed 1 (`global.news.flash`, `provider_error`; prior success watermark `2026-09-01T14:27:31.489578Z` retained)

These counts are a clocked projection, not historical completeness.

## Frozen family

**Chosen:** A-share `ann_date` event cohort already on `partition_continuation`
(`continuation_max_age_days=31`, fanout `ts_code` `batch_size=1`,
`max_batches_per_run=1`, `batch_count=5976`):

- `cn.dataset.income`
- `cn.dataset.balancesheet`
- `cn.dataset.cashflow`
- `cn.dataset.express`
- `cn.dataset.fina_indicator`
- `cn.dataset.fina_audit`

**Not chosen:** `cn.dataset.rt_min_daily`. It is `success` / quality `valid` /
freshness `fresh`, `data_through=2026-09-04 15:00`, coverage 1,178,968 rows.
Validated success/empty unique `batch_index` on the session-day window
`2026-09-04 00:00:00`–`23:59:59` is **380 / 1195** (2026-09-03 was 460 / 1195).
That is session-day rotation, not the 2026-08-30 “first 20 batches / first 100
codes every bar” failure. It is not this slice’s gap.

**Budget stop-line:** keep the existing event timer. Do not raise
`max_batches_per_run` or issue a full-universe one-shot. A config-hash change
would drop `partition_continuation` identity for already-started dates.

**Acceptance (this slice):**

1. Authenticated catalog + at least one family query (anonymous 401).
2. Unique success/empty `batch_index` on a dated window far above the 2026-08-30
   report of **10 / 5,971**.
3. A later timer cycle advances receipt count and/or flips current vs
   continuation window.
4. At least one family member returns query rows with complete lineage and a
   receipt id.
5. Do **not** claim 5,976 complete, income default-query non-empty, Scale500
   recovery, or firecrawl health.

## Receipt progress vs 2026-08-30

Read-only `validated_receipt_history_for_dataset` as `tradingdatas` through
`open_verified_read_model_snapshot` (same snapshot path as catalog/query).
Unique success/empty `batch_index` by `ann_date`:

| Dataset | 20260830 | 20260904 | 20260905 | receipts | latest at T0 |
|---|---:|---:|---:|---:|---|
| income | 297 | 75 | 3 | 5850 | `ann_date=20260905` empty @ 16:28:15Z |
| balancesheet | 296 | 73 | 3 | 1136 | `ann_date=20260905` empty |
| cashflow | 297 | 39 | 0 | 1089 | windowless success |
| express | 297 | 39 | 0 | 2279 | windowless empty |
| fina_indicator | 296 | 75 | 3 | 2325 | `ann_date=20260905` empty |
| fina_audit | 297 | 40 | 0 | 1086 | windowless success |

8/30 coverage report had **10 / 5,971** completed batches for the same dated
window. 297 unique indexes on `20260830` is cross-cycle accumulation under the
already-installed contract, not a new collector.

`pledge_stat` stays windowless (`request_window={}`) with 318 unique batch
indexes and 399,430 stored rows; it is related event cadence but not this
dated-window freeze.

## Live timer cycle (T0 → T1)

- T0 ≈ 00:30 CST: income `n_receipts=5850`, latest window `20260905`.
- T1 = 00:34:48 CST: income `n_receipts=5851`, latest window flipped to
  continuation `ann_date=20260904`, new empty receipt
  `receipt:e4df98f402ee01327844451479110173a40e90a4ebf26bd6feb89e1c3f28b931`
  finished `2026-09-04T16:34:06.087666Z`.
- cashflow authenticated query watermark moved from
  `2026-09-04T16:23:33.188128Z` /
  `receipt:e01eb7ae1193ed9831366f84dd14182a083720d40e3df676d9143613e85bed7b`
  to `2026-09-04T16:29:04.997081Z` /
  `receipt:5ec92630671aa9cc8d0344b608fc7a2ff12bdbe3644264b9b9a28e0ff9eca6ff`.

That is current-vs-debt alternation from `partition_continuation`, not a
window reset that abandons unfinished dates.

## Authenticated query

Request shape: `dataset_id` + `schema_major` + empty `fields`/`filters` +
`limit=5`. Omitting `schema_major` is HTTP 400 `invalid_request`.

| Dataset | HTTP | n | runtime_state | lineage | quality | receipt / through |
|---|---:|---:|---|---|---|---|
| cashflow | 200 | 5 | success | complete | degraded (`response_completeness_unverified`) | `5ec92630…` / `2026-09-04T16:29:04.997081Z` |
| fina_audit | 200 | 5 | success | complete | degraded (same reason) | `0a438733…` / same through |
| income | 200 | 0 | empty | complete | degraded | latest empty window; `provider_returned_no_rows` |
| balancesheet | 200 | 0 | empty | complete | degraded | same legal empty |
| rt_min_daily | 200 | 5 | success | complete | valid | `4e99c87c…` / `2026-09-04T15:00:00+08:00` |
| rt_min | 200 | 5 | success | complete | valid | `cad3e3dc…` / same close print |

Default income/balancesheet query follows the **latest** empty receipt, so
`filters.ann_date=20260830` still returned 0 rows. Coverage `row_count` for
income is 389; those facts are not this latest empty window. That is not
treated as a collection failure and was not “fixed” by a new query contract
in this slice.

`include_receipt_proofs=true` on cashflow returned HTTP 503 (row-receipt
fail-closed). Default query without proofs is the accepted consumer path here.

## What this slice did not change

- No registry/cadence/Python edit.
- No exact-main / `switch-current`.
- No timer restart, no QuickSync budget expansion, no one-shot manifest.
- No Feature/Recipe/Product Plane, payment, or email login claim.

## Residual (not this freeze)

- `global.news.flash` failed / firecrawl `#354`.
- `fina_mainbz` still `unobserved` (`#349`).
- Weekend `margin*` stale is SLA vs last prior-open watermark, not this family.
- Remaining ann_date debt: ~5,976 − 297 on `20260830`, and smaller unique
  indexes on later dates because current and 31-day continuation share the
  one-batch-per-tick budget.
