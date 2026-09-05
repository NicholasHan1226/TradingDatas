# TradingDatas public surface map

Status: product contract updated 2026-09-05 for public help/setup and private
Account routing; non-paying preview routes remain available. This document defines the public information architecture. It
does not claim that checkout, payment, or the public domain commerce plane are
live.

## 1. Navigation logic

The public website is a product library, not a collection of marketing pages.
Top-level navigation is Data / Research / Pricing. Features and
Recipes remain addressable content, not additional top-level items. The
upper-right Account menu provides Docs and language/theme without login. The
Account workspace also links to Docs; neither desktop nor mobile primary
navigation includes it. Docs opens the public `/docs` hub. Object map:

| Section | Object | Question answered | Primary next action |
| --- | --- | --- | --- |
| Data | dataset | What material exists, how is it structured, and can I trust it? | inspect a dataset |
| Features | transparent derived field | What repeatable transformation is available, exactly how was it produced, and which version is it? | inspect methodology |
| Recipes | executable preparation method | How do I combine datasets correctly for a research task? | open a recipe |
| Research | external paper, report, or case | What can I learn, and which data/methods does the work rely on? | read the TradingDatas record, then the source |
| Pricing | base plan; separate future add-on | Which request rate and billing period fit my needs? | review a non-paying purchase preview; no order or access grant |
| Docs | product or technical guide | How does the platform, data contract, API, account, or policy work? | open a guide |
| Account | tenant-owned access state | What can I access and how do I connect it? | manage access or an integration |

Agent/MCP is a public delivery tutorial/template at `/connect`, linked from
Docs in Account and Docs. Reading or copying it needs no website session; data API
requests still require the caller's Bearer credential. It is not the primary
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
sample, and the access path. Static product definitions do not establish runtime
availability. Data and product pages remain publicly readable; authenticated
collection evidence uses `GET /api/account/catalog`, the same-site Account
session bridge to the existing `GET /v1/catalog`. It uses only the current user's
connected data key, with no service token and no anonymous data grant. This is
an Account bridge, not another provider data endpoint.

Guests see a login prompt; accounts without a connected key see the connection
path. Authorized users can inspect every non-Crypto dataset returned for their
key, including stored coverage, runtime state and receipt evidence. Errors and
expired authorization remain visible and retryable; static definitions never
masquerade as a successful runtime response. `queryable` means the query contract
is available, not that a specific query returns rows. One snapshot is not a
trend, continuity statistic or stable-service promise.

Product-to-dataset mappings use actual registered identifiers. Copyable query
examples must satisfy the current query schema; planned or unmatched products
must not invent a dataset ID or claim coverage. Crypto is internal-only and is
excluded from public Data products, catalog projections, packages and service
counts. Crypto-related external Research records remain educational content.

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

Docs is reached from Account, never a desktop/mobile primary navigation item.
The public `/docs` hub presents first connection, Agent setup and account help
first, then a grouped directory spanning getting started, data, APIs, methods
and account guidance. Desktop uses a persistent directory beside the reading
column; mobile uses a native collapsible directory. Detail pages have specific
authored steps, on-page links, relevant next actions and adjacent guides. Keep
existing `/docs/:slug` URLs. Avoid oversized marketing headings, equal-height
card grids, internal authority panels and generic placeholder articles.

`public-web/src/documentation.js` is the single authored bilingual content source
for the directory, article body and global search metadata; platform and API
contracts remain authoritative for factual statements. Examples are copy-only.
Email identity is distinct from existing API access, and purchase/renewal stays
paused until the commerce service is available.

Current `/v1/catalog` and `/v1/query` remain the only public data API contract.
Future canonical/PIT/feature endpoints must not be described as live.

### Login `/login`

Dedicated identity entry to the existing private Account workspace. Available
methods come from the identity service; phone remains unavailable. `?next=`
accepts `/account`, its known overview/subscription/usage/keys/billing/security
sections, or a canonical `/pricing/preview?plan=&period=` selection. Reject
external URLs, API routes, unknown sections, duplicate parameters and fragments;
invalid returns fall back to `/account`. Login restores the requested section
without creating an order or changing grants.

### Public setup and saved material

`/docs` and `/docs/:slug` are public help; `/connect` presents Agent/MCP
tutorials/templates without login. `/bookmarks` contains only browser-local
saved references; opening it does not read a private account library.

### Account `/account` and `/account/:section`

Only overview, subscription, usage, keys, billing and security are private
sections. Account may link out to public help without duplicating those pages.
Unknown sessions show checking first. Confirmed guests redirect to login with
their safe section preserved; unavailable identity shows retry, not a redirect.
Account facts come from authenticated tenant-scoped APIs. Billing/payment remain
unavailable while commerce is paused; website login never grants API access.

### Utilities

`/status`, `/changelog`, `/corrections`, and license/support material belong in
the footer and Docs utility navigation. They should not compete with the three
primary destinations in the global header.

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
