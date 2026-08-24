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

## Checks and production build

```bash
npm run lint
npm run build
```

The build command refreshes `../static/app/`. Verify the committed output together with the React source before publishing.
