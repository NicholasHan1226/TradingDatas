# TradingDatas navigation-depth audit

## Evidence

- Product: local public-site candidate at `http://127.0.0.1:4173/`
- Flow: primary navigation landing pages at 1440 x 1024, Chinese, light theme
- Screens: `data.jpg`, `research.jpg`, `cookbook.jpg`, `pricing.jpg`, `docs.jpg`
- Contact sheet: `contact-sheet.jpg`

## Steps and health

1. Data landing — visually healthy, product depth incomplete.
2. Research library — searchable and attributable, detail flow incomplete.
3. Cookbook landing — visually coherent, but only a hero/list teaser.
4. Pricing landing — packages are readable, comparison and beta/access flow incomplete.
5. Docs hub — category/search structure exists, article actions do not yet open authoritative pages.

## Findings

- **P1 — Navigation stops at marketing landings.** Data, Cookbook, Pricing, and
  Docs have no durable subcategory/detail object routes. Users cannot move from
  orientation to a Dataset, Recipe, Package, or Docs article with version,
  limitations, authority, and a next action.
- **P1 — The product object model is invisible.** The current IA does not expose
  the distinction between provider-native evidence, future Canonical/PIT
  datasets, transparent Features, Recipes, external Research, and delivery
  methods. This makes the website look more complete than the backend product
  plane actually is.
- **P1 — Agent delivery is over-weighted in the content contract.** The shared
  product review correctly reframes Agent/MCP as one delivery method. The first
  buying reason should be trustworthy, point-in-time, reproducible data.
- **P2 — Research is the closest complete index but still leaves the product.**
  External-source actions go directly to Scholar. A TradingDatas Research detail
  page should first preserve citation/summary, map required data materials, link
  related Recipes, and then offer the external source.
- **P2 — Pricing lacks an honest current-stage conversion.** Packages are marked
  pending, but there is no explicit private-beta/request-access path or
  explanation of what can be purchased now versus what is still proposed.
- **P2 — Missing public trust utilities.** Status, changelog/schema changes,
  corrections, and license/redistribution boundaries are not discoverable from
  the product pages.

## Accessibility limits

The screenshots show readable hierarchy and contrast, but they do not prove
keyboard order, screen-reader labels, zoom resilience, or full focus-state
coverage. Those require browser interaction checks after implementation.

## Recommended logic

Every index should follow `orientation -> taxonomy -> object list -> evidence ->
usage -> access`. Every detail should follow `identity -> maturity/availability
-> trust and limitations -> schema/version -> related objects -> sample -> next
action`. The public website must display generated product facts and must not
become a second data authority.
