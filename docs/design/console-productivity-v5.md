# TradingDatas console productivity v5

This iteration extends, rather than replaces, the visual and role contract in
`console-product-system-v4.md`. It adds durable navigation, operator-scale data
tables, and privacy-preserving local product feedback without changing any API,
token, entitlement, collector, scheduler, database, or data-plane behavior.

## Durable workspace navigation

- Canonical client routes use hashes so a Pages reload never depends on an SPA
  fallback: `#/admin/<section>` and `#/portal/<section>/<document>`.
- Admin credentials still open the admin workspace when no explicit route is
  present. Customer credentials cannot resolve an admin route.
- Browser forward/back, copied links, reload, admin preview, and return all use
  one route model. The latest valid admin and customer locations are stored
  locally; logout removes the current URL route but does not rotate or mutate
  the bearer token.
- Search, filters, sorting, and visible columns persist only in the current
  browser. No persisted UI state contains a bearer token or API payload.

## Operator data table

The data-runtime table uses TanStack Table v9 for deterministic sorting and
column visibility, and TanStack Virtual for final-row virtualization after
filtering and sorting. The renderer remains owned by TradingDatas so the v4
typography, tags, density, sticky header, focus style, and responsive container
stay consistent.

- Dataset identity is the non-hideable anchor column.
- Every visible header is keyboard-focusable and exposes its sorting action.
- Column visibility, filters, and sorting can be reset as one local view.
- Virtualization renders an overscanned window from the final sorted row model;
  it never changes API data, filtering truth, or row identity.

## Local console analytics

The usage workspace contains a clearly separated `控制台体验` panel. It is a
browser-local aggregate for product QA, not service usage or customer analytics.

- Stored values are counters by workspace and event type only.
- It does not store or transmit token values, tenant IDs, dataset IDs, query
  bodies, API responses, device identifiers, IP addresses, or raw event logs.
- Events cover workspace views, workspace switching, successful copy/query/key
  tasks, and visible request failures.
- The operator can reset the aggregate without affecting server usage, accounts,
  credentials, datasets, or runtime services.

## Performance and rollback

Admin and customer workspaces are lazy-loaded behind the shared login shell.
Chart, table, and virtual-list code is split into independent production chunks,
keeping the unauthenticated login path small. Reverting the v5 frontend commit
restores v4 behavior; local route/table/analytics keys become inert and no
server rollback or data migration is required.

`VITE_API_BASE` is an isolated local-QA override only. Cloudflare Pages builds
must leave it unset so the browser uses the fixed production API endpoint. The
console must not expose the service address as an editable login field.

The narrow-screen navigation, action-state, empty-state, and stress-fixture rules
that extend this system are documented in `console-resilience-v6.md`.
