# TradingDatas console frontend

React + TypeScript frontend for the TradingDatas login, administrator console, and customer data portal. Production assets are built into `../static/app/` and are committed with the source change.

The current source tree is the authenticated console. The public Data / Cookbook / Pricing / Docs / Account candidate now lives independently in `../public-web/` and is governed by `../docs/design/public-data-product-system-v1.md`; it must not be improvised inside the operator console or presented as deployed. Public content may reuse tokens and primitives, but customer acquisition, dataset discovery, educational Cookbook entries, Agent/MCP connection, checkout, and authenticated operations remain distinct task surfaces.

Frontend code must preserve three authorities:

- runtime dataset state comes from catalog/query and receipt-backed metadata;
- account access, quotas, expiry, trials, and payments come from authenticated server/commerce projections;
- Cookbook prose and synthetic examples are versioned content and never override either authority.

Do not put real tokens, customer responses, provider payloads, production status, or unverified prices into fixtures, screenshots, analytics, local storage, or committed bundles.

## Local development

```bash
npm install
npm run dev
```

The application defaults to the official API endpoint. For local UI verification, start the bundled mock API in a second terminal:

```bash
npm run mock-api
```

The mock listens on `127.0.0.1:4174` and contains only synthetic records. Use `ui-test-token` for the administrator flow or `ui-customer-token` for the customer-only flow. It exists for browser interaction tests and must not be used as production data evidence.

For the collection-table stress lane, start 1,000 synthetic collection rows:

```bash
npm run mock-api:stress
```

`TD_CONSOLE_MOCK_COLLECTION_ROWS` affects only the mock collection-status response,
is capped at 5,000 rows, and leaves the mock catalog/query fixtures small. At 1,000
rows, verify that the table keeps only an overscanned window in the DOM, reaches row
index 999, and does not create page-level horizontal overflow at 390px.

## Checks and production build

```bash
npm run lint
npm run build
```

The build command refreshes `../static/app/`. Verify the committed output together with the React source before publishing.

For any future public experience, also verify the route/content matrix, dataset-detail responsive layout, Cookbook code-copy behavior, Agent prompt redaction/copy/test states, `zh-CN`/`en` detection and switching, package/add-on states, keyboard navigation, reduced motion, and truthful synthetic/observed labels before considering the frontend a release candidate.
