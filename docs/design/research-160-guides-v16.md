# Research guide continuation: 160

Date: 2026-09-01. Scope: public-web editorial candidate only; no provider,
registry, collection, entitlement or runtime change.

## Selection and evidence

This batch converts twenty existing, publisher-verified catalogue identities from
summary-only orientations into six-section bilingual reader guides. It keeps the
library at 200 source identities and raises the number of guides from 140 to 160.
The sources were checked through their DOI landing records or the original JSTOR
archive page; the selection favours foundational primary journal articles and a
recent peer-reviewed crypto-market paper. Exa was used to read the public source
descriptions and confirm the guide's scope. The direct primary source pages are
the evidence URLs embedded in the reader.

The batch covers six market-microstructure, six corporate-fundamentals, three
methods, one text/alternative-data, one asset-pricing, one macro-finance and two
crypto-market records. Each guide explicitly separates question, design,
data/timing, interpretation, replication checks and scope boundary. It avoids
table-level numbers, causal claims beyond the source description, investment
advice, and claims that TradingDatas carries the original source sample.

## Acceptance

- 200 unique source identities remain unchanged.
- 160 reader guides, each with six bilingual source-linked sections.
- 40 records remain clearly summary-only; this is not presented as 200 full-text
  reviews.
- `npm run audit:research`, relevant Node tests, `npm run build`, `npm run
  test:sites`, responsive browser checks and CI remain separate release gates.
