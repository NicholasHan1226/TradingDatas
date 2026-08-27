# Data source landscape

Last reviewed: 2026-08-27 CST

This document defines how TradingDatas researches and presents connected and
candidate data sources. It is a product-research registry, not runtime
authority, a redistribution licence, a purchase record, or a claim that every
technically reachable source may be sold.

## Public Data-page model

The public Data page separates five questions:

1. **Connected contract index** — which provider-native interfaces are present
   in the immutable registry, grouped into user-facing material families.
2. **Collection-state history** — what was observed at a stated time, together
   with the limit of that evidence.
3. **Candidate source landscape** — what official or primary source has been
   reviewed, how it may be accessed, and what rights questions remain.
4. **Integration roadmap** — which evidence gate must be passed next.
5. **Receipts and access** — what makes a dataset eligible for authenticated
   use and, separately, for a sellable package.

The connected-interface snapshot is generated from
`config/provider_native_dataset_registry.yaml`. It includes contract/config
state only and deliberately excludes paths, tokens, payloads, tenant data and
current-health claims. `activation=active` means enabled registry
configuration; it does not replace same-day SQLite receipts, quality/freshness
projection or authenticated `catalog/query` readback.

## Current contract counts

| Surface | Contract coverage | Boundary |
|---|---:|---|
| Tushare through QuickSync | 190 interfaces; 133 configured active; 57 paused | Configuration, not a continuous-health claim |
| Firecrawl | 2 page-collection pipelines | Per-site rights remain source-specific |
| Binance public market data | 6 data families across a fixed 40-symbol universe, producing 240 dataset objects | 240 objects are not 240 upstream APIs |
| Tushare domestic discovery scope | 222 read-data capabilities | 32 discovery-only additions are not runtime contracts |

## Source record

Every candidate source must retain:

- stable source identity and official documentation URL;
- market/region and user-facing material family;
- technical access model: public REST/SDMX, bulk file, licensed feed, or
  commercial vendor API;
- rights state: public terms, source-specific terms, commercial licence, or
  unresolved review;
- research stage and roadmap phase;
- known data materials and expected cadence;
- later, an immutable provider contract, bounded canary, receipt and
  authenticated API readback.

The registry is intentionally open-ended. “All possible sources” means a
maintained intake system that can accept new evidence; it is not a one-time
claim to have enumerated every financial or alternative-data API in existence.

## First reviewed source universe

### China and Hong Kong markets

- [Shanghai Stock Exchange market-data products](https://english.sse.com.cn/markets/dataservice/products/) — L1/L2, historical, tick and order-book products; redistribution follows a licensed-vendor chain.
- [Shenzhen Stock Exchange data services](https://investor.szse.cn/English/services/dataServices/index.html) — real-time, delayed, end-of-day and L2 data; SSIC manages distribution.
- [HKEX data licensing](https://www.hkex.com.hk/Services/Market-Data-Services/Data-Licensing?sc_lang=en) — securities, derivatives and issuer-news licences.
- Beijing Stock Exchange, CFFEX, SHFE, DCE, CZCE and GFEX — official market,
  derivatives, warehouse, position and settlement materials; access and
  redistribution require product-level review.
- CNInfo and China Securities Index Company — announcements, methodologies,
  constituents and weights; document access and downstream redistribution are
  separate questions.

### China macro and policy

- [National Bureau of Statistics data portal](https://data.stats.gov.cn/)
- People's Bank of China, SAFE and China Customs statistical releases

These sources are high priority because they expand China research materials
without changing the A-share-first product position. A browser-visible table or
download is not assumed to be a stable API or to allow commercial
redistribution.

### Global fundamentals and macro

- [SEC developer resources and EDGAR Data APIs](https://www.sec.gov/about/developer-resources)
- [FRED/ALFRED API](https://fred.stlouisfed.org/docs/api/fred/overview.html)
- [World Bank developer information](https://datahelpdesk.worldbank.org/knowledgebase/topics/125589-developer-information)
- [ECB Data Portal API](https://data.ecb.europa.eu/help/api/overview)
- [UK Companies House Developer Hub](https://developer.company-information.service.gov.uk/)
- IMF and OECD SDMX data services

Open technical access still requires dataset/series-specific attribution,
licence, rate-limit and redistribution review. Revision and vintage semantics
are part of the data contract rather than optional metadata.

### Global markets and crypto

- [Nasdaq Data Link](https://docs.data.nasdaq.com/) — commercial and dataset-specific access.
- [Coinbase Exchange APIs](https://docs.cdp.coinbase.com/exchange/introduction/welcome)
- [Kraken API](https://docs.kraken.com/exchange/guides/rest/introduction)
- [OKX API](https://www.okx.com/docs-v5/en/)
- [Deribit API](https://docs.deribit.com/)
- [CoinGecko API](https://docs.coingecko.com/)
- [DefiLlama API](https://api-docs.defillama.com/)

Public market endpoints are technical candidates only. TradingDatas does not
create exchange accounts, request trading permission, or add write/account
operations to the data plane.

### News, web and physical-world alternatives

- [GDELT DOC API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
- [Common Crawl Index Server](https://index.commoncrawl.org/)
- licensed AIS, satellite, facility, mobility and supply-chain vendors

These sources remain separate add-ons. Page-level copyright, privacy,
geographic bias, historical stability and redistribution are mandatory gates.

## Roadmap gates

| Phase | Focus | Required exit evidence |
|---|---|---|
| P0 | Make current A-share, news and Crypto contracts legible | Registry identity, receipt-bound state, authenticated API readback, rights boundary |
| P1 | China exchanges, derivatives, disclosure and macro | Official source, redistribution permission, schema/cadence, bounded canary |
| P2 | Open global fundamentals and macro | Terms, revision/vintage model, entity mapping, receipt/API readback |
| P3 | Global market data and multi-venue Crypto | Vendor economics, market-data licence, historical depth, isolated runtime |
| P4 | News, web and physical-world alternative data | Source rights, privacy, coverage bias and separate add-on entitlement |

Only a completed phase gate may advance a source from discovery to a runtime
candidate. Only formal provider -> SQLite -> receipt -> authenticated API
evidence plus redistribution authority can make a dataset eligible for a
sellable package.
