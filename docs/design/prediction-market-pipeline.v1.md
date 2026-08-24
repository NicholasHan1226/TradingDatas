# Prediction-market public snapshot pipeline (Polymarket provider)

> Status: reviewed TD public-read-only data draft, 2026-08-24. Nicholas has resumed this TD data scope only; this document still creates no registry, timer, API or TA runtime capability. The two contracts remain intentionally unregistered, `paused`, and `blocked` until the stated integrity gates close.

## 1. Goals and non-goals

Goal: collect a small, versioned selection of public Polymarket markets as provider-native facts for later analytics. Each capture retains question id, slug, question, selection category, end date, outcomes, outcome prices/probabilities, volume, liquidity, active/closed flags, and an available resolution field.

Non-goals: market making, trading, wallets, accounts, signatures, orders, positions, simulation, alpha, recommendation, or a new public API. Consumers can only be considered later through the existing `GET /v1/catalog` and `POST /v1/query` data plane.

## 2. Source and transport contract

The only allowlisted source is Gamma `GET https://gamma-api.polymarket.com/markets`, constrained to `slug`, `limit`, and `offset`. Candidate slugs live in `config/polymarket_starter_markets.v1.yaml`; every one is explicitly unverified and must be confirmed during the first bounded live run.

Production cannot reach Polymarket directly. `SshRelayTransport` invokes, without any shell on either side, `ssh -o BatchMode=yes -o ConnectTimeout=10 <user@host> '<allowlisted-url>'` — the bare URL is the SSH remote command. The relay account's `authorized_keys` carries `restrict`, a forced-command wrapper that re-validates the URL against its own host allowlist and runs curl itself (`-m 20`, so effective per-call latency is capped remotely), and a source-IP pin to the collector host; arbitrary commands and non-allowlisted destinations are rejected server-side (exit 111). Host/user arrive only through arguments or environment (`POLYMARKET_RELAY_HOST`, `POLYMARKET_RELAY_USER`); no credential or relay configuration belongs in the repository. `DirectHttpTransport` exists only for local development/tests.

Pagination is offset-based and bounded (`page_size <= 100`, `max_pages <= 5`); an over-size page, an unexpected response shape, or a response whose slug differs from the request fails the complete capture.

## 3. Dataset contracts

| Dataset | Point in time | Key | Intended contents |
| --- | --- | --- | --- |
| `pm.dataset.polymarket_market` | current snapshot | `question_id` | question metadata, selection category, end date, outcomes, lifecycle and resolution |
| `pm.dataset.polymarket_snapshot` | append-only | `question_id`, `captured_at` | probability vector, volume, liquidity, lifecycle and resolution at capture time |

Both contracts use `provider_data`, `objective_factual`, `market: PREDICTION_MARKET`, `on_demand`, `paused`, and `blocked`. They deliberately are not added to `provider_native_dataset_registry.yaml`: activating them, compiling a valid registry binding, or exposing them through catalog/query needs a separate reviewed change.

## 4. Normalization and receipts

The adapter preserves every raw Gamma object key, then validates and adds the frozen projection: `question_id`, normalized array `outcomes`, numeric `[0,1]` `outcome_prices`, numeric `volume`/`liquidity`, exact bool lifecycle flags, UTC `captured_at`, and deterministic `snapshot_id = sha256(question_id|captured_at)`. The selection-file category is treated as a reviewed candidate label, not provider truth.

`collect_outcome()` follows the existing provider-adapter convention and returns `ProviderCallOutcome`. A reviewed integration must use the existing `provider_dataset_rows` plus transaction-scoped `storage/ingest_receipts`: facts and a success receipt in one transaction; empty/failed terminal receipt otherwise. The draft CLI therefore writes one atomic success envelope (`receipt`, `market_records`, `snapshot_records`) or one atomic failed receipt, never a partial capture file.

## 5. Fail-closed matrix

| Condition | Result |
| --- | --- |
| SSH failure, curl nonzero, direct HTTP failure, timeout | failed receipt, `transport_error`, nonzero CLI exit |
| Malformed JSON, non-array response, bad/mismatched slug, missing required field, invalid numeric/flag | failed receipt, `provider_error`, nonzero exit |
| Valid empty Gamma array | core returns terminal `empty`; the multi-market CLI turns it into a failed batch receipt so it never silently stores a partial requested selection |
| Any page failure after earlier page success | discard all buffered rows; failed receipt only |
| Response exceeds byte/page bounds | failed receipt; no partial write |

## 6. Cadence and backfill proposal

Phase 0 remains `on_demand`: run one bounded 14-market capture through the relay after first-live slug/schema verification. The draft CLI accepts `--lookback` as a bounded capture-intent argument; Gamma's current-market endpoint does not make it historical data, so it never fabricates or claims historical snapshots. No registry/catalog/query exposure, timer, alert or consumer is enabled until official contract hashes, the one-api-name/two-dataset mapping, Yes/No semantic direction, persistence/receipt integration and authenticated API readback are separately proven. If observed, propose a separate `event` cadence of 15 minutes for active markets and 6 hours for closed/unresolved markets; do not install a timer in this draft. Historical backfill is provider-limited: snapshots begin at first observed capture, and no reconstruction of past probabilities is claimed.

## 7. Monitoring hooks

Monitor receipt state/error code, per-capture requested/returned/normalized market count, age of last successful capture, active-to-closed transitions, outcomes/price-vector cardinality changes, and unknown raw fields/schema drift. Alerting consumes receipts and catalog projection only after separately approved registry/runtime integration; it must not scrape Gamma directly.

## 8. Rollout plan and rollback

1. Human review source terms, market scope, exact Gamma schema, and relay ownership; freeze verified slugs and document hashes.
2. Register the two contracts through the existing compiler, keep activation `paused`, and run all local/CI contract tests.
3. Run a single relay bounded canary; independently read back SQLite receipt and authenticated catalog/query before calling it `observed`.
4. Propose cadence, isolation, budget and consumer readback only after multiple successful captures.

Rollback is to set both bindings `paused`, stop only their future timer (if one is later approved), retain facts/receipts under the documented retention policy, and preserve a last known-good immutable release. No rollback writes external market state because the provider surface is read-only.

## 9. Reviewer decisions required

- Verify the current Gamma endpoint fields and whether market resolution has a single authoritative field.
- Replace all starter candidates with live verified slugs/questions and decide whether category comes from Gamma, a reviewed taxonomy, or both.
- Approve legal/terms review, relay trust boundary, service identity, rate budget, storage isolation, and retention.
- Decide whether the real compiled registry supports `PREDICTION_MARKET`, the 20-slug literal fanout, `offset` pagination and list-typed projections without code changes; the draft intentionally does not claim that it does.
- Resolve the existing one-`provider.api_name`-to-one-dataset authority before registering both projected datasets from one Gamma response; this draft keeps both contracts unregistered rather than disguising that incompatibility.
