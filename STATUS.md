# TradingDatas current status

Observed at: 2026-08-22T18:32:42+08:00

This file is a current, replaceable status summary. Durable product and contract
rules live in `README.md`, `docs/ARCHITECTURE.md`, `docs/API.md`, and
`docs/OPERATIONS.md`. Older status text remains available in Git history and must
not be used as current runtime evidence.

## Layered delivery state

| Layer | Current observation | Claim boundary |
|---|---|---|
| GitHub `main` | `71ab452d7fd893361e4441170d745737dbaea8a2`; main CI and scheduled CI succeeded | accepted source only |
| Local canonical checkout | `cbde095b4080264e71e037ff95d60f024c2a7d4a`, ahead 1 / behind 7 and deliberately preserved | divergent, non-authoritative; do not reset or clean until its owner hands off |
| Ordinary server source | no canonical checkout was found under the standard `/opt/investment` source paths in this readback | not claimed synchronized and not required to prove an immutable release |
| Effective release | `/opt/investment/releases/tradingdatas/f085075e98f5de9199482e8aac0281d4f1ec529e` | immutable runtime source |
| Internal API service | `tradingdatas-v1-internal.service` active/running | process health only; not a query or consumer receipt |
| Collector schedule | timer enabled/active; the applicable service completed successfully | scheduling/process evidence only |
| API and consumer | no authenticated catalog/query plus consumer readback was taken in this same observation batch | open evidence layer |

The source difference from effective release `f085075` through GitHub `71ab452`
is limited to CI workflow, repository rule, and CI-contract-test paths. No runtime
code delta was found, so this status does not manufacture a deployment merely to
make source SHAs numerically equal.

## Same-batch collector result

The collector completed at the observed time with `Result=success`, exit status
zero, `failed=0`, `planned=0`, `skipped=187`, and `terminal=5`. These values belong
to this one readback and must not be combined with a later slot or receipt count.

| Dataset | Result | Use |
|---|---|---|
| `cn_schedule` | success | persisted increment/receipt subject to API readback |
| `cyq_chips` | success | persisted increment/receipt subject to API readback |
| `cyq_perf` | success | persisted increment/receipt subject to API readback |
| `daily_basic` | valid empty | retain as dataset-local valid-empty evidence |
| `global.news.flash` | success | persisted increment/receipt subject to API readback |

The skipped set included `cn.news.flash` with a receipt-authority rejection
(`data_through_in_future`). That exact capability remains unusable until corrected;
it does not invalidate the five terminal sibling results or block independent
datasets.

## Product maturity by boundary

- Provider contracts, persistence, receipts, catalog/query, consumer acceptance,
  and long-run stability are independent claims.
- A valid row or valid-empty receipt is retained immediately. Dataset-local empty,
  partial, throttled, transient provider failure, or optional-field loss is
  classified locally when identity, time, key, unit, lineage, and PIT safety remain
  explainable.
- TD supplies data only. Factor/strategy evaluation, simulation, promotion, risk,
  capital, and orders belong to TradingAgent.
- A-share exact500 and Crypto full-40 coverage constrain their named coverage
  claims. They do not block safe per-symbol/per-shard simulation consumers.
- Prediction markets and CNFutures remain paused. No real-trading, account,
  capital, execution, or order authority is created by this status.

## Next evidence

1. Read back authenticated `catalog/query` for one of the latest valid receipts and
   bind the result to the same receipt identity and observation time.
2. Obtain the applicable TA consumer readback separately; a healthy TD service or
   timer is not consumer proof.
3. Preserve the divergent local canonical checkout behind a recovery ref. Perform
   any future acceptance from a clean current-main checkout; never reset it merely
   to make local and GitHub labels match.
4. Replace this file on the next material observation. Do not append incident
   chronology or copy its SHA/count/timer values into durable documentation.
