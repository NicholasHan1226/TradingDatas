# TradingDatas public surface map

Status: product contract v2, 2026-08-26, with 2026-09-01 login and non-paying
preview routes. This document defines the public information architecture. It
does not claim that checkout, payment, or the public domain commerce plane are
live.

## 1. Navigation logic

The public website is a product library, not a collection of marketing pages.
Every primary section represents a durable object:

| Section | Object | Question answered | Primary next action |
| --- | --- | --- | --- |
| Data | dataset | What material exists, how is it structured, and can I trust it? | inspect a dataset |
| Features | transparent derived field | What repeatable transformation is available, exactly how was it produced, and which version is it? | inspect methodology |
| Recipes | executable preparation method | How do I combine datasets correctly for a research task? | open a recipe |
| Research | external paper, report, or case | What can I learn, and which data/methods does the work rely on? | read the TradingDatas record, then the source |
| Pricing | base plan; separate future add-on | Which request rate and billing period fit my needs? | review a non-paying purchase preview; no order or access grant |
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
Initial entries may include an adjusted price series, a point-in-time
fundamentals panel, a company-event timeline, and aligned daily/intraday
observations.

Recommended routes:

```text
/recipes
/recipes/:slug
```

Recipe detail shows the research task, inputs, time-alignment assumptions,
ordered steps, output schema, validation checks, limitations, related research,
and a reproducible request/notebook asset when available. It must not publish
backtest returns, alpha claims, or investment conclusions.

### Research `/research`

Research is an attributed learning database for externally authored papers,
industry reports, methodologies, and market cases. TradingDatas organizes and
explains relevance; it does not claim authorship or endorse conclusions.

Subcategories combine format and topic:

- formats: papers, industry research, cases, official methodologies;
- topics: A-share market, asset pricing, market microstructure, corporate
  fundamentals, alternative data, quantitative methods;
- reading paths: beginner, data preparation, method deep dive, market structure.

Recommended routes:

```text
/research
/research/:slug
```

Research detail shows citation, source link, research question, evidence and
data requirements, method summary, assumptions/limitations, related TradingDatas
datasets/features/recipes, and further reading. The internal record is the
first click; the external source remains authoritative.

### Pricing `/pricing`

Three base plans share the same base-data scope and differ only in request rate:

- Basic: 200/minute, 99/month;
- Professional: 600/minute, 299/month;
- Flagship: 1000/minute, 499/month.

No daily quota or commercial concurrency limit. Annual payment is twelve months
at 10% off: 1,069.20 / 3,229.20 / 5,389.20. CNY is the domestic-first display
assumption, pending settlement confirmation. Show one focused product, a rate-tier
selector and monthly/annual switch; make actual annual total distinct from its
monthly equivalent. Alternative data remains a separate trial/add-on area.
Prices are confirmed, but checkout/renewal/live grants require backend evidence.
The public action opens a non-paying purchase preview; the actual payment action
remains disabled. Existing key holders can sign in and return to their selection.
The preview has no order or entitlement writes. See
[product contract](../PRODUCT.md) and [identity/commerce plan](../design/customer-identity-commerce-v1.md).

Recommended routes:

```text
/pricing
/pricing/preview?plan=:plan&period=:period
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

### Login `/login`

Dedicated access-key entry to the existing Account workspace. Phone remains
unavailable. Email is a separately gated identity candidate and must not be
presented as live signup. `?next=` accepts only `/account` or a canonical
`/pricing/preview?plan=&period=` selection; every other value falls back to
`/account`. Successful sign-in does not create an order or change grants.

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
