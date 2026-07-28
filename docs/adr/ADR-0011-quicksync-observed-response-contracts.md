# ADR-0011: QuickSync observed response contracts

## Status

Accepted — 2026-07-28.

## Decision

Tushare official documents remain the source declaration for dataset identity,
request shape and cadence reference.  When the approved QuickSync transport
returns a stable but incompatible response schema, TradingDatas records the
smallest evidence-bound response delta in
`config/quicksync_interface_observations.v1.yaml` and applies it in the
existing registry compiler.

The delta is limited to all of the following, and cannot change any other
dataset behavior:

- remove a consistently absent non-structural response field;
- correct an observed JSON field type without coercing stored payload values;
- add a consistently observed response field; and
- advance that dataset's public schema version.

It cannot alter a dataset's identity, request mapping, cadence, primary key,
partition, completeness declaration, provider adapter, SQLite schema,
collector, scheduler or public API route.  Unknown future fields remain in the
raw provider payload and cause degraded metadata until separately reviewed.

## Evidence

The first production batch used the existing generic on-demand runner and the
approved `tradingdatas` service identity.  It completed successful,
transaction-scoped receipts for these affected datasets on 2026-07-28 UTC:

| Dataset | Receipt |
| --- | --- |
| `cn.dataset.anns_d` | `receipt:fa6fe189aa34e01192dde8477079a5a69494b1cd28970e90e3c22d4c6ab298d2` |
| `cn.dataset.bak_basic` | `receipt:4c72eb35629a4efa9ab90aee6c0fb3c6b1417b7d835df6ad532c8a99633c5ed4` |
| `cn.dataset.cb_daily` | `receipt:9a81ea4f559547f350131f261c23d768e272b7180884cc32b9cc7b77c9c29437` |
| `cn.dataset.cb_issue` | `receipt:999030aed71789c373e7a75888d60b9eca62e0523c54a20c98dab93f768c1155` |
| `cn.dataset.dc_daily` | `receipt:325e5bd78ebc6d2b89a4bff21fe7d1f1c701be5db2e5c5593d9907882d364723` |
| `cn.dataset.disclosure_date` | `receipt:f0098de6efeb9390ce7e119d32b1e1dabd691dbd880d8d59919587b6f5dd8c04` |
| `cn.dataset.fut_settle` | `receipt:96a7c460b8bb46178a8829abd03205364906904f0d4bef32b914fdaeb2e74501` |
| `cn.dataset.moneyflow` | `receipt:f9a8834232ff0c7e9d2a8c3718518a5d0d1bf62adec58e63126e760fdb753129` |
| `cn.dataset.stk_holdertrade` | `receipt:c6e51ff93f76cd5dfb4d3980957b63bbdc4c6bc34ae01651801f530d42cbc905` |
| `cn.dataset.stk_managers` | `receipt:a3d046e7cf682698476321da816e490e1d41cf01f964c7c1553fa0375c4a764e` |
| `cn.dataset.ths_daily` | `receipt:8e68da9914d5590b9a2b108abbc5ec2ee0a9f6bc1f44c51a227dab7322114edc` |
| `cn.dataset.top_inst` | `receipt:a53345b50014597916fab6cabbd18eeeed6740c42cdbda42ac46d0ec9f26378b` |

The receipts establish that data and receipt committed together.  They do not
by themselves establish data completeness, a business-time watermark or a
freshness SLA.  `POST /v1/query` must therefore continue to report those
metadata dimensions honestly; a successful receipt or HTTP 200 is not a
ready-for-consumption assertion.

## Consequences

No per-interface Python collector, database table, scheduler branch or public
route is introduced.  After a fresh re-collection under the revised contract,
the affected payloads can be queried using the same `GET /v1/catalog` and
`POST /v1/query` data plane.  Consumers must use the returned schema major and
metadata, and fail closed for `partial` or `degraded` states.
