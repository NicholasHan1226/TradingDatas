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

## Production release

The public website is deployed to the existing Cloudflare static-assets Worker
named `tradingdatas`. `public-web/wrangler.jsonc` binds the committed
`dist/client` build to the small SPA fallback Worker in `dist/server/index.js`.
For direct navigation, that Worker serves the app shell for extensionless
`GET`/`HEAD` routes outside `/api/` and `/assets/`, even when a generic client
does not send `Accept: text/html`. Missing API routes, assets, extensionful
files, and non-navigation methods remain ordinary fail-closed `404`s.

Pushes to `main` that change `public-web/**` run the repository Cloudflare
workflow. The workflow checks out the immutable source SHA, deploys the Worker,
then requires `/`, `/account/`, `/data/`, `/research/`, and `/pricing/` to return
the exact JavaScript asset referenced by that checkout. A local build or a
successful upload alone is not production evidence.
