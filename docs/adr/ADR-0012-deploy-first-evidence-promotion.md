# ADR-0012: Deploy-first and evidence-driven promotion

- Status: accepted
- Date: 2026-08-16

## Context

TradingDatas exists to keep internal financial data continuously available to TradingAgent and other internal consumers. GitHub Actions may be unavailable because hosted runner spending is not enabled. The system also cannot depend on recurring human confirmation for ordinary internal dataset onboarding, recovery, or maturity changes.

Excessive global gates and large engineering refactors would delay the more valuable objective: collecting real data, preserving receipts/lineage, serving the fixed API, and learning from actual runtime behavior.

## Decision

1. Production/data availability takes precedence over non-essential refactoring and tooling work.
2. GitHub Actions is optional and is not a production release gate.
3. Every dataset advances independently through `contract_ready -> observed -> stable` from deterministic machine-verifiable evidence.
4. Once frozen eligibility rules are satisfied, internal read-only capability promotion does not require human confirmation.
5. A failed or incomplete dataset degrades itself; it does not block unrelated datasets or consumers.
6. Runtime safety remains fail-closed for provider authorization, secrets, request/resource budgets, integrity, completeness and lineage.
7. Current runtime facts come from receipts and fresh readback, not from Markdown status statements.
8. Large package/layout refactors are deferred unless they directly resolve a demonstrated reliability, correctness, security or operating-cost problem.

## Release evidence without GitHub Actions

A release can be accepted using the repository's existing deterministic validation and production readback chain:

```text
source candidate
-> deterministic local/server checks
-> immutable release
-> systemd/service/timer readback
-> SQLite receipts
-> authenticated catalog/query readback
-> applicable consumer readback
```

A GitHub commit or pull request is source history, not production proof.

## Consequences

- Real data begins accumulating sooner.
- The system can repair and promote ordinary internal capabilities without waiting for a person.
- Documentation must remain concise so it does not become a second runtime authority.
- Engineering improvements continue incrementally behind running capabilities rather than becoming a platform-wide prerequisite.
