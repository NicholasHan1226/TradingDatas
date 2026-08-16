# Autonomous Development Workflow

This repository uses an agent-first workflow. Routine human code review is not a merge requirement, and GitHub Actions is not a mandatory gate.

## Normal workflow

1. Start from the latest `main` and check concurrent changes before integration.
2. Keep one task scoped to one branch or isolated candidate; do not overwrite unrelated work.
3. Run the smallest deterministic local/server validation that is relevant and available. For data/runtime changes, provider/receipt/SQLite/catalog/query/consumer readback is stronger production evidence than a hosted CI badge.
4. Push the candidate branch when useful for review, handoff, rollback, or parallel work. Pull requests are useful visibility but are not a required human approval mechanism.
5. Before merge, verify ancestry and diff scope; if `main` advanced, reapply/rebase onto the latest main rather than force-pushing.
6. The controller/trusted agent may merge validated normal work without waiting for a human approval or GitHub Actions run.
7. If GitHub Actions is available and runs, treat it as supplemental validation. Missing/skipped/billing-blocked Actions must not stop otherwise validated dataset onboarding, merge, immutable release, collection, internal API operation, or evidence-based dataset progression.
8. Do not put secrets, credentials, databases, runtime state, logs, provider receipts/evidence, or production artifacts in Git.
9. Keep source/GitHub, release, effective runtime, provider receipt, API readback, and consumer evidence as separate states.
10. Do not force-push or rewrite shared history.

## Workflow-governance changes

Changes under `.github/workflows/` require an explicit diff/policy check so a task cannot silently weaken safety boundaries. This check is machine-reviewable; it does not create a routine human approval requirement. Hosted CI must never be configured as the sole merge authority because Actions capacity may be unavailable.

## Authority boundary

Autonomous code merge/deployment does not grant authority to change production credentials/accounts/permissions, perform destructive data/database operations, expose a public service, or bypass the provider/runtime safety boundaries in `AGENTS.md`. Ordinary internal read-only collection and deployment still follow the deploy-first, evidence-based progression recorded in the repository ADRs.
