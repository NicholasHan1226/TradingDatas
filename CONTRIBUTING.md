# Autonomous Development Workflow

This repository uses an agent-first, machine-gated workflow. Routine human code review or approval is not a merge requirement.

## Normal workflow

1. Start from the latest `main` and check concurrent changes before integration.
2. Keep one task scoped to one branch and one pull request; do not overwrite unrelated work.
3. `main` is protected: use a pull request with all four named fast CI shards on the current base. Direct pushes, force-pushes, branch deletion, and unresolved review threads are blocked; routine human approval is not required.
4. Run relevant deterministic local validation before opening or updating the pull request. Data/runtime work must still obtain its provider/receipt/SQLite/catalog/query/consumer evidence where applicable.
5. Open a pull request to `main`. Human review is not required.
6. The pull-request CI is the routine Git merge gate. It runs four `pytest-shard` slices in parallel, each with `pytest-xdist -n auto`, and excludes only `slow` canary, local-HTTP, and timing suites. A failing, missing, cancelled, or stale CI result must not auto-merge.
7. A successful CI run is evidence only. A trusted same-repository PR may merge automatically only when Datas PM applies the `pm-merge` label, the author is `NicholasHan1226`, the PR is not a fork or draft, the base is `main`, and TradingDatas CI succeeded on the exact current head SHA. The repository label `pm-merge` (description: "Datas PM go-ahead for trusted auto-merge") is that go-ahead; create it on the repo if it is missing. It replaces `controller-accepted` and `automerge-m0`. `AUTODEV_RETURN_V1` comments, `decision=accepted`, `candidate=<sha>` comment parsing, and `change_class=M0` body declarations are retired. Removing `pm-merge` disables GitHub auto-merge. Workflow-governance changes under `.github/workflows/` never auto-merge; Datas PM merges those via GitHub after CI.
8. Fork PRs and untrusted authors never auto-merge. A merge never deploys TD server/runtime. A `static/**` merge triggers only Cloudflare Pages, then performs a bounded readback of the published Pages route; GZ/immutable runtime is not auto-deployed.
9. Keep source/GitHub, release, effective runtime, provider receipt, API readback, and consumer evidence as separate states. Passing GitHub CI does not by itself prove production data health.
10. Do not put secrets, credentials, databases, runtime state, logs, provider receipts/evidence, or production artifacts in Git.

## Workflow-governance changes

Changes under `.github/workflows/` must not be self-authorizing. They require a separate trusted Datas PM merge via GitHub after CI; this does not create a routine human-review requirement. A normal application-code PR may not weaken, remove, or replace its own CI/automerge gate.

If GitHub Actions is temporarily unavailable, leave the affected PR unmerged rather than bypassing `main`. A future independent fallback runner may be added explicitly, but absence of the configured merge gate is not permission to direct-push routine code.

The nightly 02:17 Asia/Shanghai schedule (or `workflow_dispatch` with `suite=full`) runs all four shards including `slow` coverage, plus the local HTTP timing suite serially because it owns process-global server state. The CI job summaries record each shard's test duration; PR median duration is assessed from successful PR runs, not from a local estimate.

## Authority boundary

Autonomous code merge/deployment does not grant authority to change production credentials/accounts/permissions, perform destructive data/database operations, expose a public service, or bypass provider/runtime safety boundaries in `AGENTS.md`. Ordinary internal read-only collection and deployment still require their repository-defined runtime evidence.

## Public product and frontend changes

Public product, pricing, Cookbook, documentation, and customer-facing frontend changes must start from `docs/PRODUCT.md` and `docs/design/public-data-product-system-v1.md`.

1. Keep runtime facts separate from authored content. Catalog coverage, freshness, lineage, readiness, quotas, entitlement, expiry, and price must come from their authoritative backend or commerce contract; do not hard-code them as live claims.
2. Cookbook examples teach data preparation only. Every example names its dataset IDs, join/as-of rules, expected output schema, limitations, and synthetic/observed status. It must not contain strategy returns, alpha, win rate, recommendations, or a hidden provider call.
3. New public dataset families still use the provider registry and fixed `GET /v1/catalog` / `POST /v1/query` routes. A marketing page or add-on card cannot create activation or entitlement.
4. Customer-facing package names may map to backend tiers only through a reviewed server/commerce contract. Frontend labels do not grant categories, rate, concurrency, quota, trial, renewal, or payment state.
5. Public frontend work includes desktop, tablet, and mobile checks; keyboard focus; reduced motion; loading/empty/error/expired/trial-ended states; realistic synthetic fixtures; and visual comparison at a fixed viewport.
6. Changes that affect navigation, content semantics, commercial behavior, API examples, or customer-visible authorization update the relevant product/design/API documents in the same pull request. Pure visual polish may cite the existing contract when behavior is unchanged.
7. Agent connection variants compile from `docs/AGENT_INTEGRATIONS.md`. Do not maintain independent hand-written prompts in components. Every variant test proves that credentials are redacted, catalog is called before query, query limits are bounded, cursors are handled, and degraded/receipt metadata is checked before results are treated as usable.
