# TradingDatas public surface map

Status: product contract v2, 2026-08-26. This document defines the public
information architecture. It does not claim that target product capabilities,
commerce, or the public domain are live.

## 1. Navigation logic

The public website is a product library, not a collection of marketing pages.
Every primary section represents a durable object:

| Section | Object | Question answered | Primary next action |
| --- | --- | --- | --- |
| Data | dataset | What material exists, how is it structured, and can I trust it? | inspect a dataset |
| Features | transparent derived field | What repeatable transformation is available, exactly how was it produced, and which version is it? | inspect methodology |
| Recipes | executable preparation method | How do I combine datasets correctly for a research task? | open a recipe |
| Research | external paper, report, or case | What can I learn, and which data/methods does the work rely on? | read the TradingDatas record, then the source |
| Pricing | package or add-on | Which complete data access package matches my work? | request private-beta access |
| Docs | product or technical guide | How does the platform, data contract, API, account, or policy work? | open a guide |
| Account | tenant-owned access state | What can I access and how do I connect it? | manage access or an integration |

Agent/MCP is a delivery route under Account and Docs. It is not the primary
reason to buy the product. The first promise is trustworthy, point-in-time-aware,
reproducible financial data.

## 2. Shared page grammar

All index pages follow:

```text
orientation -> taxonomy -> object list -> evidence -> usage -> access
```

All detail pages follow:

```text
identity -> maturity/availability -> trust/limitations -> schema/version
-> related objects -> sample -> next action
```

Status vocabulary is fixed:

- `observed`: current Evidence Plane has a real receipt and authenticated API
  readback for the stated observation; it is not a continuity claim;
- `stable`: the current dataset meets its applicable production cadence;
- `product definition`: a public-facing contract exists but the capability is
  not implemented;
- `private beta candidate`: the object may be offered only after its data,
  entitlement, support, and commercial contracts are verified;
- `planned`: direction only, with no availability promise.

## 3. Route and subcategory map

### Home `/`

One promise, one trust proof, two restrained actions. Lead with trustworthy,
traceable, reproducible A-share data. `Explore Data` is primary; Agent connection
is secondary. Show a synthetic example only when it is labelled as such.

### Data `/data`

Subcategories:

1. **A-share market and reference** — prices, adjustments, calendars,
   instruments, suspensions;
2. **Intraday and microstructure** — minutes, auctions, pre-market observations;
3. **Fundamentals and corporate actions** — statements, reports, dividends,
   capital and holders;
4. **Indices and funds** — constituents, weights, ETF and index observations;
5. **Alternative data** — company/regulatory information, news/policy, objective
   attention and interaction metadata;
6. **Receipts and coverage** — source, observation, quality, row coverage and
   limitations.

Recommended routes:

```text
/data
/datasets/:datasetId
/data/alternative
/data/receipts
```

Dataset detail must show stable identity, current capability level, provider
and license boundary, fields, primary key, cadence, coverage, freshness,
receipt/lineage evidence, known limitations, related features/recipes, a bounded
sample, and the access path. Availability comes from generated public artifacts,
never from page copy.

### Features `/features`

Features are transparent, versioned derived data—not alpha, rankings, strategy
signals, or recommendations. Initial A-share families may include adjusted
returns, liquidity measures, realized volatility, and fundamental-quality
measures.

Recommended routes:

```text
/features
/features/:featureId
/features/methodology
```

Feature detail must show exact formula, inputs, alignment rules, lookback,
missing-data policy, revision/PIT policy, version, test fixtures, limitations,
related datasets/recipes, and availability. Until a Feature Plane exists, every
feature page is `product definition` or `planned`.

### Recipes `/recipes`

Recipes replace the vague `Cookbook` label. A Recipe is a versioned preparation
contract that teaches use of the data without doing the customer's research.
The current `public-web` candidate exposes six synthetic teaching tutorials
as `/recipes/:id` pages: adjusted prices, point-in-time fundamentals, company
event timelines, minute-bar gaps, document-version ledgers, and
spot/open-interest observation alignment. Those pages are
`product_definition` teaching surfaces. Publishing them does not activate the
Recipe or Feature product plane, grant data, or imply observed coverage.

Recommended routes:

```text
/recipes
/recipes/:slug
```

Recipe detail shows the research task, inputs, time-alignment assumptions,
ordered steps, output schema, validation checks, limitations, related research,
and a reproducible request/notebook asset when available. Current downloads are
generated synthetic fixtures, not provider data. It must not publish
backtest returns, alpha claims, or investment conclusions.

### Research `/research`

Research is an attributed learning database for externally authored papers,
industry reports, methodologies, and market cases. TradingDatas organizes and
explains relevance; it does not claim authorship or endorse conclusions.

Confirmed reading views are Featured and Topics. They share one 200-work
catalog. Topics uses eight display subjects plus an all-literature index, in
pages of 12: asset pricing, market microstructure, company & financials,
China & comparative markets, alternative data, crypto markets, research
methods, and macro & fixed income. Stored `quant-methods` records display
under research methods without changing identity. Topics also filters by
publication type, full guides (`depth=guide`), related data-preparation
materials (`materials=prepared`), and recently guided sort (`sort=recent`).

Additional navigation, not extra works:

- eight three-stage subject journeys (24 core guides);
- three curated path pages;
- three company-topic question routes;
- authored comparison pairs on article pages (at most three, excluding
  previous/next sequence neighbors), with a same-topic summary-only fallback
  when no pair exists;
- an eight-item recently guided shelf on Featured.

Recommended routes:

```text
/research
/research?view=topics
/research/:slug
/research/paths/:pathId
```

Research detail is a reader article: original authorship, source access,
bookmark, citation, optional BibTeX/RIS download, editorial orientation,
source-specific limits, and optional related Data/Feature/Recipe links.
Guide bodies load on demand in production builds. Preparation state,
source-check timestamps, and generic checklists stay internal. The external
source remains authoritative. Inclusion is not endorsement, replication, or a
live-data claim. See `docs/product/RESEARCH_LIBRARY.md`.

### Pricing `/pricing`

Packages are organized by A-share work scenario, not upstream API names:

- A-share Research;
- Systematic Research;
- Trading Data.

Alternative data remains a separate trial/add-on area. Package comparison must
show included data families, historical/intraday scope, runtime limits,
alternative-data trial state, support, and entitlement term. Price, checkout,
renewal, and live access remain unavailable until the commerce contract is
implemented. The honest current conversion is `Request private beta`.

Recommended routes:

```text
/pricing
/pricing/alternative
/pricing/beta
```

### Docs `/docs`

Docs is the explanation layer for the entire website, not an API hero page.
Categories:

- platform and product model;
- data model, IDs, schema, coverage, receipts, PIT and revisions;
- API and Agents/MCP;
- Features and Recipes;
- packages, account, billing and security;
- policy: license, corrections, deprecation, status and changelog.

Every card opens a real article route and names its authority source. Current
`/v1/catalog` and `/v1/query` remain the only public API contract. Future
canonical/PIT/feature endpoints must not be documented as live.

### Account `/account`

Groups:

- Overview;
- Data access: subscription/add-ons, usage/limits, API keys;
- Integrations: Agent/MCP and other clients;
- Billing: orders, payment records and invoices;
- Settings: language/appearance, security and sessions.

Language and appearance controls stay here. All account facts must come from
authenticated tenant-scoped APIs; prototype state is not entitlement evidence.

### Utilities

`/status`, `/changelog`, `/corrections`, and license/support material belong in
the footer and Docs utility navigation. They should not compete with the six
primary product objects in the global header.

## 4. Product-object relations

```text
external Research record
  -> requires Dataset(s)
  -> may use transparent Feature(s)
  -> links to executable Recipe(s)
  -> delivered through API / Agent / notebook / export
  -> governed by Package + entitlement
```

This relation is navigational, not a research claim. Results and investment
decisions remain the user's responsibility.
