# Autonomous Development Workflow

This repository uses an agent-first, machine-gated workflow. Routine human code review or approval is not a merge requirement.

## Normal workflow

1. Start from the latest `main` and record the exact base SHA used for the task.
2. Keep one task scoped to one branch and one pull request; do not overwrite unrelated work.
3. Do not push routine code directly to `main`. Do not force-push or rewrite shared history.
4. Run relevant deterministic local validation before opening or updating the pull request. Data/runtime work must still obtain its provider/receipt/SQLite/catalog/query/consumer evidence where applicable.
5. Open a pull request to `main`. Human review is not required.
6. Pull-request CI is the routine Git merge gate. A failing, missing, cancelled, or stale CI result must not auto-merge.
7. A successful CI run may be squash-merged automatically only when the tested SHA is still the current PR head and the PR comes from a trusted same-repository branch.
8. Main advancing after CI does **not** automatically serialize every agent. If the PR touches only disjoint dataset/provider/local files and none of its files were changed on `main` since the recorded base, it may merge against current `main` without a forced branch update. If files overlap, or the PR touches shared core/governance/deployment authority, the branch must be refreshed and CI rerun.
9. Fork PRs and untrusted authors never auto-merge.
10. Keep source/GitHub, release, effective runtime, provider receipt, API readback, and consumer evidence as separate states. Passing GitHub CI does not by itself prove production data health.
11. Do not put secrets, credentials, databases, runtime state, logs, provider receipts/evidence, or production artifacts in Git.

## Fresh-base authority paths

These paths require a current-`main` integration check whenever `main` advanced after the PR base:

- `.github/**`
- root `AGENTS.md` and `CONTRIBUTING.md`
- `deploy/**` and `docs/OPERATIONS.md`
- dependency roots such as `requirements*` and `pyproject.toml`
- shared core entry points such as `api_server.py`, `auth.py`, `catalog_service.py`, `query_service.py`, `dataset_registry.py`, `runtime_paths.py`, and `storage/**`

Dataset/provider/config work outside these paths may proceed in parallel when its exact changed files do not overlap changes merged to `main` after the PR base. File overlap always requires refresh and rerun.

## Workflow-governance changes

Changes under `.github/workflows/` must not be self-authorizing. They require a separate trusted controller/machine-governance check before merge; this does not create a routine human-review requirement. A normal application-code PR may not weaken, remove, or replace its own CI/automerge gate.

Repository-side branch/ruleset protection is defense in depth, not something workflow files can prove by themselves. Do not claim `main` is protected unless a fresh GitHub settings/API readback confirms it. If protection is absent, report that as governance debt; do not silently reinterpret workflow convention as branch protection.

If GitHub Actions is temporarily unavailable, leave the affected PR unmerged rather than bypassing `main`. A future independent fallback runner may be added explicitly, but absence of the configured merge gate is not permission to direct-push routine code.

## Post-merge and deployment

Every merge creates a new `main` SHA. Production deployment must depend on validation of that exact current `main` SHA and must re-check that it is still current before cutover. Provider/data evidence remains separate and must be read back after deployment where applicable.

## Authority boundary

Autonomous code merge/deployment does not grant authority to change production credentials/accounts/permissions, perform destructive data/database operations, expose a public service, or bypass provider/runtime safety boundaries in `AGENTS.md`. Ordinary internal read-only collection and deployment still require their repository-defined runtime evidence.
