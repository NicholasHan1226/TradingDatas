# TradingDatas console frontend

React + TypeScript frontend for the TradingDatas login, administrator console, and customer data portal. Production assets are built into `../static/app/` and are committed with the source change.

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
