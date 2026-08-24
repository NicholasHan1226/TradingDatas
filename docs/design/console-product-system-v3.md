# TradingDatas console product system v3

## Direction

The console follows a **calm-fintech / neo-industrial data infrastructure**
direction: crisp, technical, static, and data-first. The login page now uses
the same graphite data plane, cobalt action colour, neutral work surface, and
typographic wordmark as the authenticated workspace. It presents TradingDatas
as a public financial-data platform rather than a security-system surface.
The authenticated workspace uses a deep control rail, a narrow
context header, and bright dense content surfaces.

Abstract decoration is static and structural only: fixed grids, crisp data
lines, and restrained cobalt/cyan colour fields. Motion is reserved for
functional feedback such as a spinner; page entrances, animated ornaments,
floating glows, and decorative transitions are excluded.

## Design tokens

### Typography

- Chinese and Latin UI: system sans stack with PingFang SC and Noto Sans SC
  fallbacks.
- Data identifiers: system monospace stack.
- Scale: 11 / 12 / 14 / 16 / 20 / 24 / 32px.
- Headings use 600 weight and tight tracking; body copy uses 400--500 weight;
  labels use 500 weight without excessive all-caps letter spacing.

### Color

- `--td-canvas`: neutral product canvas.
- `--td-surface` and `--td-surface-raised`: primary and raised work surfaces.
- `--td-ink`, `--td-ink-soft`, `--td-muted`, `--td-faint`: four text levels.
- `--td-accent`, `--td-accent-strong`, `--td-accent-quiet`: selection and
  primary actions only.
- `--td-success`, `--td-warning`, `--td-danger`, `--td-info`: runtime states;
  they never substitute for navigation color.
- Cyan, violet, and orange are sparse market-signal accents for A-share,
  crypto, and news context. They never imply runtime health or become link
  colours.

### Spacing, radius, and shadow

- 4px base rhythm: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40.
- Radius: 6px controls, 10px panels, 14px dialogs.
- Shadow 1 separates floating controls; shadow 2 is reserved for dialogs and
  the login card. Tables and ordinary cards use borders instead of elevation.

### Motion

- Enter: none for pages and cards.
- Feedback: 120ms color/border response; loading uses a small spinner.
- Exit: dialogs disappear immediately after the close action.
- `prefers-reduced-motion` remains enforced globally.

## Component contract

- Button: 32px or 40px height, visible focus ring, explicit disabled/loading
  state, and semantic danger styling.
- Input/select: 40px height, persistent label, 1px neutral border, blue focus
  ring, and no decorative inner glow.
- Card: 10px radius, 1px border, optional compact header; cards group tasks,
  not every metric.
- Table: sticky quiet header, 44px minimum row, tabular numbers, horizontal
  overflow, hover and focus-within feedback.
- Modal: labelled dialog, Escape/backdrop close, 14px radius, no ornamental
  animation, destructive copy separated from the action.
- Navigation: desktop resource rail plus mobile select; user preview and logout
  remain reachable on every section.

## Page model

- Login: static 44/56 split on desktop; a single credential task on the left
  and an integrated graphite product/data-plane narrative on the right. The
  right side uses an abstract market signal and product capabilities rather
  than fabricated live metrics. Mobile collapses to the form while retaining
  public-platform context, market coverage, and credential guidance.
- Admin: access and data-plane navigation groups, global context header, one
  page intro, one action/filter row, then task-specific content.
- Customer: Overview and Documentation are the primary sections. Documentation
  groups Platform, API Quickstart, and Agent Setup as secondary categories so
  product background and integration material have one stable home without
  crowding the product navigation.
- Tier presentation: display one localized name per tier. New credentials use
  the canonical Basic, Standard, and Flagship tier keys; legacy tier keys remain
  visible only while editing an existing credential.

## Runtime and rollback boundary

This remains a static frontend refactor. Authentication, token values, API
routes, registry, collectors, schedulers, receipts, databases, and provider
runtime are unchanged. Reverting the single frontend merge commit restores the
previous bundle without changing the data pipeline.
