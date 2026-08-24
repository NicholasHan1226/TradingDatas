# TradingDatas console resilience v6

This iteration is a compatibility extension to the v4 visual language and v5
productivity model. It does not change authentication, API contracts, account
permissions, datasets, collectors, schedulers, databases, or production runtime.

## Narrow-screen navigation

- Workspace navigation remains a horizontal task rail below the shared shell.
  The active item is centered after route changes and each target keeps a minimum
  48 px height. A restrained edge fade indicates additional off-screen items.
- Admin customer-preview mode exposes one explicit return action in the preview
  banner. The duplicate header switch is hidden while previewing; logout remains
  available in the shell at every breakpoint.
- The preview banner reflows into a short vertical stack below 640 px instead of
  compressing the message and return action into one line.

## Dense table behavior

- The collection table keeps dataset identity sticky on the horizontal axis.
  A mobile-only instruction explains horizontal scrolling before the table.
- Filters use the available mobile row width; column and reset controls stay on a
  separate aligned action row. Table overflow stays inside the card rather than
  expanding the whole page.
- TanStack Virtual continues to own row-window rendering after filtering and
  sorting. Dataset truth, order, row identity, and server requests are unchanged.

## Empty-state system

The shared `EmptyState` component now has a semantic Lucide icon slot, stronger
title/hint hierarchy, an optional recovery action, and a stable minimum height.
Collection, credential, usage, health, data-browser, and customer-usage surfaces
select icons that match the missing object or healthy-zero state. The collection
zero-result state offers a direct filter reset.

## Isolated stress lane

`npm run mock-api:stress` sets `TD_CONSOLE_MOCK_COLLECTION_ROWS=1000` for the
bundled local mock API. The value is clamped from the four canonical fixtures to
5,000 and expands only `/admin/api/collection/status`; catalog and query fixtures
remain small. It must never be treated as production scale, freshness, coverage,
or data-pipeline evidence.

Acceptance at 1,000 rows:

- no page-level horizontal overflow at a 390 x 844 viewport;
- an overscanned DOM window rather than 1,000 rendered rows;
- table scrolling can reach virtual row index 999;
- all five admin pages and all three customer sections keep logout visible.

## Rollback

Reverting the v6 frontend commit restores the previous shared components and mock
fixture. No server rollback, credential change, migration, or service restart is
required.
