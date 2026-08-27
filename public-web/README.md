# TradingDatas public web candidate

Independent React/Vite candidate for the public `tradingdatas.com` product
experience. It does not replace the authenticated console under `frontend/`
or prove that the public domain, Pages route, DNS, HTTPS, commerce, account, or
API subdomain is live.

## Local development

```bash
npm install
npm run dev
```

The prototype includes the confirmed public-home visual direction, responsive
Data/Features/Recipes/Research/Pricing/Docs navigation, a task-oriented Data catalog with
the connected-interface index, collection-history ledger, reviewed candidate-source landscape and phased integration roadmap, and
alternative-data ordering proposal, an external-paper/industry-research/case
library with internal detail records, transparent Feature definitions, versioned
Recipe examples, three proposed A-share workflow packages, a platform-wide
searchable Docs hub with article routes, independent history-aware product pages, a grouped Account workspace
containing `zh-CN`/`en` and system/light/dark settings, and a client-only Agent
setup prompt flow. `src/productManifest.js` is explicitly a design contract;
Feature/PIT/commerce states are not runtime claims. Example receipt values and the
`api.tradingdatas.com` address are explicitly proposal/synthetic UI content,
not runtime evidence.

The candidate landscape is maintained research, not an exhaustive list of every
global API. Technical reachability, redistribution rights, runtime activation,
receipt-backed availability and sellable package eligibility remain separate
states. See [`docs/product/DATA_SOURCE_LANDSCAPE.md`](../docs/product/DATA_SOURCE_LANDSCAPE.md).

Regenerate and verify the public contract/config snapshot after the provider
registry changes:

```bash
python scripts/build-connected-interface-snapshot.py
python scripts/build-connected-interface-snapshot.py --check
```

## Checks

```bash
npm run build
npm run test:sites
```

Keep the generated raster assets in `public/assets/`. Do not rebuild the brand
mark or data-material artwork with CSS, inline SVG, or placeholder elements.
