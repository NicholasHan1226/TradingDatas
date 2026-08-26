# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

## TradingDatas public visual contract

- The confirmed home direction is a warm editorial canvas with an abstract generative data-material field: dispersed blue/aqua particles become ordered traces, with one restrained receipt-yellow verification accent.
- Keep `TradingDatas` as one word and retain the supplied four-square mark. Do not recreate it with CSS or inline SVG.
- The registered public domain is `tradingdatas.com`. Registration alone does not prove DNS, HTTPS, deployment, or `api.tradingdatas.com` runtime availability; verify those separately before release claims.
- Use the art system at three densities: quiet dispersal for hero/transition space, directed weave for catalog organization, and ordered lattice for receipt/provenance surfaces.
- The artwork supports product content; it must not become a chart, flowchart, trading terminal, particle globe, purple gradient, neon crypto treatment, or perpetual motion effect.
- Public pages support `zh-CN` and `en`, default from system language, plus light/dark/system appearance. Agent/MCP setup belongs under the Account experience.
- Research is a curated external-literature library organized with TradingDatas' own taxonomy. Preserve authorship and source attribution; do not present external conclusions as TradingDatas research. Language and appearance controls live inside Account, not as a separate header control.
- Data, Features, Recipes, Research, Pricing, Docs, and Account are independent browser-history pages with directly addressable detail objects. Keep the homepage focused; do not regress them to same-page anchors or large header dropdowns. Account groups are Overview, Data access, Integrations, Billing, and Settings.
- Data explains the user-facing A-share taxonomy, shared dataset template, receipt evidence, alternative-data families, and the proposed trial/add-on order path. Features are transparent/versioned target objects and remain labelled product-definition/planned until a real runtime plane exists. Recipes teach reproducible preparation and combination without research conclusions. Research separates paper, industry-research, and case formats from topic taxonomy and teaches a question -> evidence -> limits -> Data/Feature/Recipe reading path.
- Pricing presents the proposed A-share Research, Systematic Research, and Trading Data workload packages, with alternative data kept as optional add-ons. Docs is the searchable platform-wide help hub; do not collapse it back into an API-only landing page.
- Package names, prices, trial periods, real-time grants, payment, and entitlement are proposal-only until the commerce backend confirms them. The public frontend must never turn client state into access authority.

The object grammar is fixed: index pages use `orientation -> taxonomy -> object list -> evidence -> usage -> access`; detail pages use `identity -> maturity/availability -> trust/limitations -> schema/version -> related objects -> sample -> next action`. The local `productManifest.js` is design-contract content, never runtime authority.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.
