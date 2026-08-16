# Overseas news / sentiment source design (v1, draft)

> Status: design draft (unfrozen). Date: 2026-08-16.

## Objective

Extend the news/sentiment pipeline beyond mainland-China sources so that
overseas market-moving information (Fed, US equities, global macro, and
cross-market spillover into A-share/HK/US names) becomes available through
the same `cn.*`-style provider-neutral dataset + `/v1/query` contract.

## Ordering

- Phase A (this design): source list, cadence, routing, provider split.
- Phase B (implementation): freeze one English flash source, one regulator
  source, one sentiment source; registry-only onboarding where the transport
  is already generic (Firecrawl); no new collector unless a protocol gap is
  proven.

## Source list (candidate, to be frozen by fresh evidence)

English flash / wire:

- Reuters (headlines) — blocked by hard paywall/anti-bot; use Firecrawl
  search/scrape only if a stable public page is found; otherwise mark excluded.
- Bloomberg — hard paywall; excluded unless a licensed feed exists.
- CNBC markets live — public list, candidate.
- MarketWatch latest news — public list, candidate.
- Financial Times markets — paywall; candidate for headline-only pages.
- WSJ — paywall; excluded by default.

Regulator / official:

- Federal Reserve press releases — public, high value.
- SEC press releases — public.
- US Treasury / EIA releases — public, medium value.

Sentiment (objective counts only):

- Stocktwits trending / Reddit r/wallstreetbets top — objective counts only
  (no opinion text), same `objective_factual` constraint as 雪球.

Hong Kong (cross-market):

- HKEX news, 信报/经济日报 public lists — candidate, high cross-market value
  for A/H dual-listed names.

## Provider split

- Firecrawl remains the default for scrape/search of public list pages. Its
  cloud proxy already handles most anti-bot; no new collector is required for
  these sources — they onboard as more `literal_values` fanout entries under
  the existing `cn.news.flash` / a future `global.news.flash` dataset.
- A dedicated overseas dataset id (e.g. `global.news.flash`) is preferable to
  mixing timezones and markets inside `cn.news.flash`; the provider-neutral
  registry supports this without code changes.
- Only if a source needs a non-HTTP transport (websocket ticker, licensed
  feed) would a new adapter be justified, and only after recording the
  config-expression gap per the complexity-stop rule.

## Singapore relay (optional, do not build until needed)

The user has a Singapore server available as an egress relay if mainland
egress to a specific host is blocked or a stable non-residential IP is
needed. When required:

- Run a plain HTTPS CONNECT proxy (or SSH -D) on the SG host, NOT a second
  Firecrawl instance.
- Firecrawl's own cloud proxy already crosses the firewall; the relay is only
  for direct-http fallbacks or host-level allow-listing.
- Keep the relay outside the repository credential surface: proxy address and
  credentials live in the same kind of root-owned, 0600, O_NOFOLLOW leaf file
  as the Firecrawl/QuickSync tokens. Never commit them.
- Adapter change if any: add an optional proxy env to the transport layer
  only when a concrete host is proven unreachable without it.

## Cadence

- English flash: event cadence 15-30 min during US session (09:30-16:00 ET),
  hourly otherwise. Same calendar-window mechanism already used by
  `cn.dataset.news`; no new cadence class.
- Regulator releases: event cadence, hourly, bounded lookback 1 day.
- Sentiment counts: event cadence, 2-4/day.

## Acceptance

- One frozen English flash source + one regulator source first; fresh HTTPS
  evidence, dry-run non-zero plan, bounded execute, receipt, `/v1/query`
  readback — same gate as the mainland Firecrawl canary.
- No production timer until the acceptance evidence is reviewed.
