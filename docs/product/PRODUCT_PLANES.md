# TradingDatas product planes

Status: target product architecture. Current runtime authority and proposed
product capabilities are intentionally separated.

## Current plane: provider-native Evidence Plane

The current public contract is the immutable registry, provider-native
validation, SQLite facts plus transaction-scoped receipt, metadata projection,
and authenticated `GET /v1/catalog` / `POST /v1/query` chain.

It is responsible for faithful raw material, fail-closed reads, coverage,
lineage, receipts, and provider-neutral delivery. This plane remains the
authority for all statements about current data availability.

## Target plane: canonical and point-in-time Product Plane

The product should add a separately versioned layer for canonical security and
entity identity, as-of availability, revisions, restatements, delistings, and
corporate-action history. It must preserve links back to provider-native facts
and receipts. It must not overwrite or reinterpret the Evidence Plane in place.

No canonical/PIT public endpoint is implemented by this document. Any future
API needs a new reviewed contract, migration, tests, and production readback.

## Target plane: transparent Feature Plane

Features are versioned transformations whose formula, inputs, time alignment,
missing-data policy, revision policy, tests, and limitations are public. They
are data products, not signals or advice. A feature is unavailable until its
own materialization, lineage, receipt/version, entitlement, and readback exist.

## Target plane: Recipe Plane

A Recipe is an executable and versioned method for preparing or combining data.
It references datasets and optional transparent features, declares assumptions,
produces a known output schema, and contains validation checks. It teaches use
without performing research or promising trading performance.

## Content plane: Research and Docs

Research records curate externally authored work with citation, source,
question, evidence, method, limitations, and links to relevant TradingDatas
objects. Docs explains the platform and its contracts. Neither plane can grant
data access or invent runtime availability.

Public `/recipes/:id` tutorials that ship with the research library are
content-plane teaching articles. They reuse existing Recipe bookmark IDs and
may generate same-origin synthetic notebooks, but they do not implement,
version, entitle or activate the Recipe Plane. See
[`RESEARCH_LIBRARY.md`](RESEARCH_LIBRARY.md).

## Delivery plane

HTTP API, MCP/Agent connection, notebooks, and exports are delivery mechanisms.
They consume the same authorized product objects. Agent-first delivery remains
important, but it is subordinate to data trust, reproducibility, and product
fit.

## Commerce and account plane

Packages and add-ons map tenant entitlement to versioned product objects and
runtime limits. Only authenticated backend state may represent subscription,
trial, expiry, renewal, payment, invoice, or access.

## Public artifact boundary

The public website must eventually consume a generated, non-secret public
manifest produced from reviewed product metadata and runtime projections. It
must never read production SQLite directly or maintain a second hand-written
availability registry.

Until generation exists, repository content manifests are design-contract data
and must label every object `product_definition`, `planned`, or `synthetic`.
