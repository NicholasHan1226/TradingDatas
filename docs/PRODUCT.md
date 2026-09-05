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

TradingDatas sells **trustworthy, point-in-time-aware, reproducible financial
data material**, not research conclusions. Its current Evidence Plane acquires
licensed financial data, preserves the provider-native payload, applies only
mechanically verifiable normalization, retains lineage and receipt evidence,
and delivers the result through one stable API. The target Product Plane may
add versioned canonical identity, point-in-time history, and transparent
derived Features while preserving links to provider-native facts and receipts.
It does not author opaque factors, forecasts, sentiment, alpha, portfolio
advice, orders, or trading decisions.

The public website may teach customers how to query, align, join, and validate
datasets. That educational layer is a usage manual for the data product. It may
show synthetic or explicitly bounded sample output, but it must not become a
second data authority, a research publication, or a strategy-performance
service.

The public Data page may project a non-sensitive contract/config snapshot and a
reviewed candidate-source landscape. It must keep five states distinct:
discovered source, technically reachable source, registry contract,
receipt/API-observed dataset, and redistribution-authorized sellable data. The
landscape method and first reviewed source universe are defined in
[`docs/product/DATA_SOURCE_LANDSCAPE.md`](product/DATA_SOURCE_LANDSCAPE.md).

Unbound public product pages must label collection evidence as unverified on
that page, without inferring that collection has not started. Synthetic sample
rows and receipt illustrations are labelled beside the object; no authored
percentage, time window or receipt is a health claim. Product slugs do not become
API dataset IDs. Agent setup remains a draft until the public API origin and
authorized catalog/query behavior are verified; see
[public evidence readiness](design/public-evidence-readiness-v1.md).

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

## Public product experience

The public experience has seven durable information areas:

- **Data**: the discoverable core/alternative-data catalog, shared dataset
  template, receipt explanation, and explicit alternative-data ordering path;
- **Features**: transparent, versioned derived data with public formula, inputs,
  alignment, missingness, revision rules, tests, and limitations; this is a
  target plane and is not live until separately implemented and read back;
- **Recipes**: versioned preparation contracts that connect a customer task to
  datasets, optional transparent Features, time alignment, output schema,
  validation and limitations;
- **Research**: externally authored financial papers and research, reorganized
  through TradingDatas' own learning taxonomy while preserving source,
  authorship, year, venue, and outbound attribution;
- **Pricing**: a small number of complete A-share workflow packages plus
  separately selected alternative-data access;
- **Docs**: the task-oriented public help hub with a grouped directory and
  authored step-by-step guides, retaining existing `/docs/:slug` addresses.
  It is the platform-wide help hub for product areas, data guidance,
  API/Agents, learning methods, packages, account, schema, pagination, quota,
  and errors;
- **Account**: private overview, subscription, expiry, usage, API keys, billing
  and security, with shortcuts to public help. Public `/docs`, `/connect` and
  browser-local `/bookmarks` do not require login. The top navigation is
  Data / Research / Pricing; language and appearance live in
  the upper-right menu and work before login.

`Recipes` replaces the vague `Cookbook` label. A Recipe answers both questions
in order: **what can I prepare?** and **how do I prepare it correctly?** Short
overview entries may stop after required datasets and limitations; executable
entries continue into the full Recipe contract below.

`Research` is a primary learning area, but not a TradingDatas research desk. It
indexes external papers, industry research, and market-structure cases under a consistent platform
taxonomy such as asset pricing, market microstructure, corporate fundamentals,
alternative data, quantitative methods, and A-share markets. Each record keeps
external authorship and source attribution. TradingDatas may map a paper to the
raw data materials needed to reproduce or extend it, but does not adopt the
paper's conclusions. The reading path is question -> evidence/data -> method
and limits -> related Data/Feature/Recipe material. `Benchmark` is not a primary product area. Research and
Recipe content must not present PnL, win rate, alpha, security recommendations,
provider rankings, or a platform-authored market conclusion.

Dataset-detail pages are the closest product analogue to an OpenRouter model
page. They combine objective product facts in one place: purpose, schema,
coverage, cadence, current metadata projection, lineage, sample response,
integration examples, package requirement, known limitations, and compatible
Recipes. Runtime values still come from catalog/query; marketing copy
must never invent availability or history.

## Data products, packages, and add-ons

The owner resumed account/subscription integration and payment testing on
2026-09-05. Develop the durable, isolated test flow alongside existing customer
access; production collection of payment still needs an identified merchant,
settlement terms and actual provider verification. Manual renewal/no automatic
debit remains confirmed. Production preview creates no order or data grant.
Implementation, state distinctions and resumption gates are recorded in
[Payment flow preparation](design/payment-flow-preparation-v1.md).

The commercial presentation may group datasets into a small number of complete
packages organized by customer workload, instead of exposing upstream
permissions or per-interface checkboxes. Package names, prices, dataset grants,
trial duration, renewal behavior, and invoice terms become real only when the
commerce contract and server-side entitlements implement them.

The current backend tier identifiers remain `basic`, `standard`, and
`flagship`. The target customer-facing mapping is **Basic / 基础版** to `basic`,
**Professional / 专业版** to `standard`, and **Flagship / 旗舰版** to `flagship`.
The commercial contract differentiates the three tiers only by a rolling
per-minute request limit: 200, 600, and 1000. It has no daily quota or
commercial concurrency limit. The frontend may not grant those limits by
itself: authenticated Account readback remains the authority for the effective
tier, request frequency, expiry, and category access.

Owner-confirmed commercial choices (2026-08-30): support both mobile-phone
and email sign-in/registration, independently of API keys. Email identity, revocable sessions and explicit existing-key connection are
implemented; current activation evidence belongs in STATUS. SMS and account
recovery remain separate follow-up work. Both credentials must be verified before they can be linked to
the same account; never merge accounts from matching unverified input.

Owner-confirmed account role (2026-08-30): the owner's designated email identity
is intended to access both the existing private Account and the administrator
console. Keep one identity with separately authorized workspaces, not two user
accounts or another customer dashboard. Verification and an explicit server-owned
administrator role are required; an email string or UI switch cannot grant it.
Shared administrator sign-in is separately gated and is not granted by email login.
See [owner access contract](design/account-admin-convergence-v1.md#owner-identity-and-two-workspaces).

The approved numeric prices are 99 / 299 / 499 per month. The domestic-first
display uses CNY (currency assumption to confirm before merchant activation).
Annual payment is twelve monthly prices at 10% off, billed as one annual total:

| Plan | Per month | Annual total | Monthly equivalent on annual plan |
| --- | ---: | ---: | ---: |
| Basic (`basic`) | ¥99 | ¥1,069.20 | ¥89.10 |
| Professional (`standard`) | ¥299 | ¥3,229.20 | ¥269.10 |
| Flagship (`flagship`) | ¥499 | ¥5,389.20 | ¥449.10 |

Prices may be displayed with an explicit checkout-unavailable state; they do
not establish a live offer, payment, automatic renewal, tax/invoice treatment,
or data entitlement. Merchant configuration, renewal/refund policy and the
approved sellable dataset scope remain activation gates. Implementation plan:
[Customer identity and commerce](design/customer-identity-commerce-v1.md).

The backend contract in this code tree enforces those three rolling minute
limits, rejects commercial `daily_limit` and `max_concurrent` writes, and retains
request counts as usage history without a daily quota. Production behavior remains unverified
until the exact main release and authenticated Account readback confirm it.

Alternative data is a separate product area and may be offered as an add-on.
Any free trial must state the included datasets, start/end timestamps, post-trial
behavior, and whether payment will occur. The intended product rule is that an
educational trial ends without automatic charging unless the customer
explicitly purchases the add-on; implementation and payment-provider evidence
are required before the UI may claim that behavior is live.

Public discovery uses a dedicated `Data > Alternative Data` collection. Each
alternative dataset detail page shows its source/licence boundary, coverage,
receipt evidence, sample schema, compatible Recipes, current trial/add-on state,
and an `Add alternative data` action. Purchase starts from that page or the
separate alternative-data section in Pricing, passes through an explicit
add-on checkout summary, and only becomes access after server-side entitlement
readback. It is never hidden inside a base-package comparison table.

## Agent connection contract

The public product is Agent-first. Agent/MCP tutorials and templates live at public `/connect`, reached through
Docs in Account alongside `/docs`. Reading and copying setup material do not require
website login; actual data requests always require an independent API Bearer key. The connection surface provides tailored copy-ready
setup prompts for Claude, Codex, OpenClaw, Hermes, and a generic HTTP-capable
agent. Each prompt references a secret credential slot instead of embedding an
API key and requires the same catalog -> query -> metadata validation sequence.

Agent-specific prompts may adapt setup wording, but must not fork the API,
dataset semantics, trust rules, or authorization model. Their canonical
contract and frontend behavior are defined in `docs/AGENT_INTEGRATIONS.md`.

## Language contract

The public site and signed-in account support Simplified Chinese (`zh-CN`) and
English (`en`). On first visit, the site follows the browser/system language:
Chinese locales select `zh-CN`; all other locales fall back to English. A user
can switch language and appearance in the upper-right menu without signing in. An explicit choice is remembered
locally and, when signed in, may also be saved as an account preference.

Language choice changes authored copy, labels, dates, number formatting, and
accessible names. It never translates dataset IDs, field names, schema values,
API routes, receipt IDs, reason codes, or provider-native payloads. Missing
translations fall back to English at the message/key level without rendering a
mixed or blank navigation state.

## Feature contract

A Feature is a transparent, versioned derived data object. Every published
Feature must state exact formula, input object versions, lookback, time/as-of
alignment, missing-data policy, revision policy, fixtures/tests, limitations,
and lineage. A Feature cannot represent a ranking, signal, strategy,
recommendation, or performance promise. The current runtime does not implement
a Feature Plane; public entries remain `product definition` or `planned` until
materialization, entitlement, lineage, API contract, and production readback
exist.

## Recipe contract

A Recipe teaches data preparation and stops before research judgment.
Every published recipe must contain:

1. a narrowly stated preparation goal;
2. required dataset IDs and package/add-on requirements;
3. joins, keys, time-zone and as-of alignment rules;
4. bounded catalog/query examples without a real credential;
5. the expected output schema or a clearly labelled sample output;
6. missing-data, revision, point-in-time and licensing caveats;
7. next analysis steps that belong to the customer, not conclusions produced by
   TradingDatas.

Allowed effect language describes data preparation: coverage gained, records
matched, time alignment, duplicates removed, output shape, latency, or query
cost. Disallowed effect language claims investment or predictive performance:
alpha, expected return, win rate, signal quality, recommendation, or strategy
ranking.

Recipe content is versioned documentation. It never writes to the facts
database, changes a receipt, activates a dataset, grants an entitlement, or
creates another public API route.

## Third-party and alternative data

Third-party sources enter through the same reviewed provider contract,
provider-native validation, facts/receipt storage, and fixed catalog/query API.
TradingDatas may clean mechanically verifiable syntax, identifiers, time zones,
and field types while retaining the original payload and source lineage. It may
not erase source differences or describe unlicensed data as resellable.

Before public sale or trial, each data family needs explicit redistribution or
customer-use rights, observed transport entitlement, an activated dataset
contract, real receipt/API readback, and an account entitlement mapping. A
provider listing, a successful call, or a Recipe page cannot substitute for
those gates.

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

The target commercial account decision is the intersection of three independent
gates:

```text
endpoint scope (catalog/read/query)
AND allowed data categories (market/domain allowlist)
AND per-minute request limit
```

- Endpoint scope decides whether the key may discover or query data.
- Category entitlement decides which A-share, Crypto, News, or future datasets
  appear in catalog and may be queried.
- The commercial tier supplies only a rolling per-minute request ceiling: 200
  for Basic, 600 for Professional, and 1000 for Flagship. There is no daily
  quota or commercial concurrency limit in the target contract.

Target customer-facing tiers are Basic, Professional, and Flagship. Existing
backend and legacy tier identifiers remain readable for compatibility. The code
tree now enforces the target commercial limit model; production remains
unverified until the exact main release and authenticated Account readback
confirm it.

An authenticated customer may create additional same-tenant API keys for a
device or Agent. These keys inherit the current tier, non-administrator scopes,
category allowlist, expiry, and applicable limits; self-service cannot elevate
access. Raw key material is returned once. Customers may disable another key,
but the key currently authenticating Account is protected from self-lockout.

## Account and administrator surfaces

There are two deliberately separate surfaces, not two competing customer
workspaces:

- the private **Account** at `tradingdatas.com/account` is the only
  customer account UI. It reads only that token's plan, enabled data categories,
  request-frequency limit, expiry, request history and same-tenant API keys
  through the customer Portal API. Its sections are overview, subscription,
  usage, keys, billing and security; help links open the public documentation
  and setup pages;
- the React application under `static/app/` is administrator-only. It manages
  customer access, runtime exceptions, platform usage, and authenticated
  catalog/query verification;
- a customer token is rejected by `static/app/` and directed to the public
  Account instead of entering a second customer workspace;
- only a token with `admin` scope or `internal` tier enters the administrator
  application, and it does not impersonate or switch into a customer UI.

Private `/account` and `/account/:section` check unknown sessions before showing
content. Only a confirmed guest redirects to `/login?next=` with an allowlisted
private section; successful login restores that section. Identity outages show
retry instead of redirecting. Payment remains paused; website authentication
never supplies credentials to the public data API.

Administrator sections keep durable hash routes so reload, copied links, and
browser history preserve the current task without requiring a Pages SPA
fallback. Table preferences and console-experience counters are browser-local
only. The counters are aggregate product-QA signals and never contain or transmit
tokens, tenant IDs, dataset IDs, request bodies, API responses, or device identity.

## Implementation truth and stop line

Bearer authentication, endpoint scopes, rolling commercial per-minute request
limits, legacy-tier hourly/daily/concurrency limits, and per-account
data-category allowlists are implemented in this code tree. Commercial tiers
have no daily quota or concurrency ceiling; they are still bounded by their
200/600/1000 request-per-minute contracts. The allowlist is enforced server-side
for both catalog visibility and query authorization, projected through the
customer portal, and editable through the admin token API.
Customer-scoped key listing, creation, and non-current-key disable are also
implemented. Passwordless email identity and explicit existing-key connection
are also implemented. Commerce is currently an isolated simulator plus a
production-unavailable read surface; account-synced bookmarks remain separately
gated. Production claims require the current STATUS readback.

The confirmed customer identity target supports phone and email within the same
Account. The current access-key login is an explicitly temporary same-site cookie
bridge, not proof of personal identity or a verified email/phone. Login methods
must disclose unavailable delivery rather than collecting contacts or simulating
codes. Legacy browser-stored credentials are retired; existing API keys remain
unchanged. The initial payment direction is active monthly/yearly payment and
manual renewal, not automatic debit; personal-Alipay eligibility and signing
remain unverified. See `design/personal-alipay-checkout-v1.md` for the launch gates.

The stable category keys are `a_share`, `crypto`, and `news`. Existing token
records that omit `data_categories` retain their previous all-current-category
access for compatibility; an explicit empty list grants no dataset access.
Unknown category values fail closed during token configuration load or admin
mutation. Production availability remains a separate release/readback fact in
`STATUS.md`.

## Core documentation map

- `docs/PRODUCT.md`: product identity, customers, categories, access model;
- `docs/ARCHITECTURE.md`: authority chain and technical boundaries;
- `docs/API.md`: current implemented HTTP and token contract;
- `docs/OPERATIONS.md`: deployment, runtime, verification, rollback;
- `docs/design/console-product-system-v4.md`: shared console information
  architecture, design language, role-switching and visual QA contract;
- `docs/design/console-productivity-v5.md`: hash navigation, persisted operator
  table behavior, local anonymous console analytics and rollback boundary;
- `docs/design/console-resilience-v6.md`: narrow-screen navigation, semantic
  empty states, dense-table containment and the isolated stress-test lane;
- `docs/product/PUBLIC_SURFACE_MAP.md`: public object, navigation, index/detail
  page, and maturity-language contract;
- `docs/product/PRODUCT_PLANES.md`: current Evidence Plane and target
  canonical/PIT, Feature, Recipe, delivery, and commerce boundaries;
- `docs/design/public-data-product-system-v1.md`: public visual system,
  commerce surfaces, component contract, and frontend acceptance rules;
- `STATUS.md`: time-sensitive production evidence and known gaps;
- `AGENTS.md`: development and release rules.

When product categories, account policy, public behavior, or Agent integration
changes, update this file together with the API/architecture documents and the
code that enforces the change.
