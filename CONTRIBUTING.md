# Autonomous Development Workflow

This repository uses an agent-first, machine-gated workflow. Routine human code review or approval is not a merge requirement.

## Normal workflow

1. Start from the latest `main` and check concurrent changes before integration.
2. Keep one task scoped to one branch and one pull request; do not overwrite unrelated work.
3. Do not push routine code directly to `main`. Do not force-push or rewrite shared history.
4. Run relevant deterministic local validation before opening or updating the pull request. Data/runtime work must still obtain its provider/receipt/SQLite/catalog/query/consumer evidence where applicable.
5. Open a pull request to `main`. Human review is not required.
6. The pull-request CI is the routine Git merge gate. It runs four `pytest-shard` slices in parallel, each with `pytest-xdist -n auto`, and excludes only `slow` canary, local-HTTP, and timing suites. A failing, missing, cancelled, or stale CI result must not auto-merge.
7. A successful CI run may be squash-merged automatically only when the tested SHA is still the current PR head and the PR comes from a trusted same-repository branch.
8. Fork PRs and untrusted authors never auto-merge.
9. Keep source/GitHub, release, effective runtime, provider receipt, API readback, and consumer evidence as separate states. Passing GitHub CI does not by itself prove production data health.
10. Do not put secrets, credentials, databases, runtime state, logs, provider receipts/evidence, or production artifacts in Git.

## Workflow-governance changes

Changes under `.github/workflows/` must not be self-authorizing. They require a separate trusted controller/machine-governance check before merge; this does not create a routine human-review requirement. A normal application-code PR may not weaken, remove, or replace its own CI/automerge gate.

If GitHub Actions is temporarily unavailable, leave the affected PR unmerged rather than bypassing `main`. A future independent fallback runner may be added explicitly, but absence of the configured merge gate is not permission to direct-push routine code.

The nightly 02:17 Asia/Shanghai schedule (or `workflow_dispatch` with `suite=full`) runs all four shards including `slow` coverage, plus the local HTTP timing suite serially because it owns process-global server state. The CI job summaries record each shard's test duration; PR median duration is assessed from successful PR runs, not from a local estimate.

## Authority boundary

Autonomous code merge/deployment does not grant authority to change production credentials/accounts/permissions, perform destructive data/database operations, expose a public service, or bypass provider/runtime safety boundaries in `AGENTS.md`. Ordinary internal read-only collection and deployment still require their repository-defined runtime evidence.
