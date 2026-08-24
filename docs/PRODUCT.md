# TradingDatas Product Contract

## Product identity

TradingDatas is an independent, provider-neutral financial-data platform under
the `Finance/TradingDatas` repository. It is not a TradingAgent module and does
not make trading decisions. Its product role is comparable to Tushare: organize
market data into a discoverable catalog and expose one stable read/query API.

The platform is public-facing, while every data request remains authenticated.
Public-facing does not mean every dataset is anonymously readable or licensed
for unrestricted redistribution. Each dataset and customer account must still
respect upstream terms, observed provider entitlement, activation state, and the
account access contract.

## Primary consumers

TradingDatas is Agent-first infrastructure. The main consumption path is an AI
agent or agent runtime such as Claude, Codex, OpenClaw, Hermes, or another tool
that can issue authenticated HTTP requests. Human-facing consoles exist to
manage access, inspect usage and runtime health, and copy reliable integration
instructions; they are not a separate data authority.

An agent follows the same fixed sequence:

1. call `GET /v1/catalog` to discover allowed datasets and their schema;
2. select a `dataset_id` and `schema_major` from that response;
3. call `POST /v1/query` with bounded filters, ordering, fields, and pagination;
4. inspect freshness, receipt, lineage, degraded state, and `next_cursor` before
   treating the result as usable.

## Product-facing data categories

Customer access is organized by data category, not by upstream vendor route.
The initial product navigation is:

- **A-share**: mainland China equities and related reference/fundamental data;
- **Crypto**: approved public cryptocurrency market datasets running in their
  isolated provider data plane;
- **News**: objective news/announcement/event datasets, independent of whether
  the upstream transport is Tushare, Firecrawl, or a future provider.

The registry remains the technical authority. Product categories map to its
`market` and `domain` metadata; adding a provider never adds a provider-specific
public endpoint. News is a content domain rather than a market, so future UI and
access policy must not overload one ambiguous field to represent both concepts.

## Account access and limits

The intended account decision is the intersection of three independent gates:

```text
endpoint scope (catalog/read/query)
AND allowed data categories (market/domain allowlist)
AND runtime limits (rate, concurrency, daily quota)
```

- Endpoint scope decides whether the key may discover or query data.
- Category entitlement decides which A-share, Crypto, News, or future datasets
  appear in catalog and may be queried.
- The commercial tier supplies a requests-per-minute ceiling and a default
  simultaneous-request ceiling; a per-key daily query ceiling applies in
  parallel. Passing one ceiling never bypasses another.

Current canonical commercial tiers are Basic, Standard, and Flagship. Existing
legacy tiers remain readable and editable for compatibility but are not offered
for new credentials. Exact numeric defaults remain authoritative in `auth.py`
and the API contract, not in marketing copy.

## Implementation truth and stop line

As of 2026-08-24, bearer authentication, endpoint scopes, per-minute commercial
rate limits, simultaneous-request limits, and per-key daily limits are
implemented. Catalog rows already carry market/domain metadata.

Per-account category allowlists and catalog/query enforcement are an approved
product requirement but are **not yet implemented**. Today, a valid `read`
scope can access every dataset visible through the fixed API. The console must
not present category controls as effective, and general public onboarding must
not rely on category isolation, until the backend contract, fail-closed tests,
admin mutation API, portal projection, and production readback are delivered in
a separate security-sensitive change.

## Core documentation map

- `docs/PRODUCT.md`: product identity, customers, categories, access model;
- `docs/ARCHITECTURE.md`: authority chain and technical boundaries;
- `docs/API.md`: current implemented HTTP and token contract;
- `docs/OPERATIONS.md`: deployment, runtime, verification, rollback;
- `STATUS.md`: time-sensitive production evidence and known gaps;
- `AGENTS.md`: development and release rules.

When product categories, account policy, public behavior, or Agent integration
changes, update this file together with the API/architecture documents and the
code that enforces the change.
