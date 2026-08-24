# TradingDatas console product system v3

## Direction

The console follows a **modern data infrastructure** direction: crisp,
technical, static, and data-first. The login page combines the task focus of
Mem0's split layout with the strong colour field and stable form hierarchy of
Stripe's sign-in surface. The authenticated workspace uses a deep control
rail, a narrow context header, and bright dense content surfaces. It does not
reuse either company's brand assets or product copy.

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

- Login: static 48/52 split on desktop; a single credential task on the left
  and a compact product/data-plane explanation on the right. Mobile collapses
  to the form without hiding security guidance.
- Admin: access and data-plane navigation groups, global context header, one
  page intro, one action/filter row, then task-specific content.
- Customer: Overview, API Guide, and Agent Setup are separate tabs so the
  first screen is concise and each copy task has a stable home.

## Runtime and rollback boundary

This remains a static frontend refactor. Authentication, token values, API
routes, registry, collectors, schedulers, receipts, databases, and provider
runtime are unchanged. Reverting the single frontend merge commit restores the
previous bundle without changing the data pipeline.
