# 2026-09-05 next-wave onboarding (fina_mainbz / pledge_detail / top10_cb_holders)

Weekend contract cut on `marketgraph-main`. This is an Evidence Plane
onboarding report. It does not declare the universe stable, restore
Scale500, enable email/payment, merge #395, or change the ann_date family.

## Chosen datasets (frozen in writing before activation)

| Dataset | Prior catalog | This wave |
|---|---|---|
| `cn.dataset.fina_mainbz` | active / unobserved (`on_demand`, #349 seed/window miss) | `event` + ts_code-only `entity_fanout` `batch_size=1` / `max_batches_per_run=1` |
| `cn.dataset.top10_cb_holders` | active / unobserved (`on_demand`) | `event` + existing `cb_basic` fanout, `batch_size=1` / `max_batches_per_run=1` |
| `cn.dataset.pledge_detail` | paused / entitled | activate + `event`; first cut used `ann_date` snapshot; GZ proved that shape wrong |

**Not chosen:** ann_date family (`income` / `balancesheet` / `cashflow` /
`express` / `fina_indicator` / `fina_audit`) — identity and
`max_batches_per_run` unchanged. `stk_nineturn` stays paused
(`postclose_daily`; official 21:00 publish + datetime-window completeness
gap). `stk_mins` / `top10_floatholders` stay `on_demand`. fund/fut/opt
later. #395 stays draft.

Dry-run at `2026-09-05 10:40 Asia/Shanghai` planned all three as event
windows before activation (`fina_mainbz` / `top10_cb_holders` `{}`; first
`pledge_detail` `{ann_date: 20260905}`). After the shape fix, all three
plan `{}`.

## Surfaces (separate)

| Surface | Fact |
|---|---|
| Local feature tips | `651880c3` (#475), `8e94dbd6` (#476) |
| GitHub `main` | `edef9a56f5f4233188d95d9694bac253fea0b840` (merge #476) |
| GZ A-share `current` | `edef9a56f5f4233188d95d9694bac253fea0b840` |
| GZ crypto `current` | same |
| `verify-current` both | `verified=true`, `file_count=1051`, `tree=46e09caba9379d3e3b5eff6d2bf6c1c3eb12cb4f` |
| Rollback for this pointer | `f1ab528ae64d9d1b85ca71ce2105ab13435acdc6` |
| Source checkout | not production |

GitHub merge ≠ GZ. #475 (`f1ab528a`) was cut first; #476 was the
`pledge_detail` shape repair cut onto `edef9a56`.

## Auth and dual catalog (edef9a56 restart pair)

- Anonymous `18082` / `18083` → **401**
- A-share token on `18083` → **401** (isolation)
- Authenticated cold pair after the `edef9a56` switch: A-share **200**
  `7.80s` (880291 B), crypto **200** `12.54s` (572652 B). Both <15s.

## Catalog / query / receipts (12:05 CST, `edef9a56`)

Authenticated A-share catalog **200**, 192 datasets:
success 86 / empty 44 / paused 55 / unobserved 2
(`stk_mins`, `top10_floatholders`) / stale 3 / failed 2.

| Dataset | Catalog | Query | Receipt |
|---|---|---|---|
| `fina_mainbz` | success, coverage 337 | HTTP 200, 5 rows, lineage complete | `receipt:a193ff87…` / `data_through=2026-09-05T03:47:07.579724Z` |
| `pledge_detail` | empty | HTTP 200, 0 rows, lineage complete | `receipt:9dc76e5f…` / `provider_returned_no_rows` |
| `top10_cb_holders` | empty | HTTP 200, 0 rows, lineage complete | `receipt:4fc2a64a…` / `provider_returned_no_rows` |

`fina_mainbz` is non-empty SUCCESS (vendor returned rows). Quality stays
degraded on `response_completeness_unverified`.

## Internal vs external

- **Internal, closed:** `pledge_detail` on `f1ab528a` used `ann_date` only.
  QuickSync `provider_error` 20002: 须提供必选参数 `ts_code`. Official table
  marks `ts_code` optional (文档≠现实). #476 switched to ts_code-only
  fanout matching `pledge_stat`. First `edef9a56` cycle no longer returns
  20002.
- **External, not slip:** `pledge_detail` and `top10_cb_holders` first
  fanout batches are legal empty (`provider_returned_no_rows`). Weekend
  / that `ts_code` has no rows. Contract is correct; do not rewrite
  completeness or raise `max_batches_per_run`.
- **Pre-existing, not this wave:** `global.news.flash` firecrawl
  `provider_error`; `major_news` transport 502 on the 11:47 cycle;
  weekend `margin*` stale; ann_date family still converging.

## What this slice did not do

- No `max_batches_per_run` change on the ann_date family.
- No #395 merge. No new collector, business table, or public route.
- No Product Plane / payment / email / Scale500. No TA ten-symbol pins.
- No catalog timeout or worker change. Tokens were not printed.
- Production SQLite / releases / rollback artifacts were not deleted.
