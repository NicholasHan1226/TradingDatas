# TradingDatas deep-surface design QA

## Evidence

- Before captures: `.artifacts/audit-v11/before/` (production release `6d0cec0`).
- After captures: `.artifacts/audit-v11/after/` (local release candidate).
- Source visual truth: `.artifacts/audit-v11/before/customer-access.png`.
- Browser-rendered implementation: `.artifacts/audit-v11/after/customer-access.png`.
- Normalized side-by-side input: `.artifacts/audit-v11/permission-before-after.png`.
- Desktop viewport: 1440 x 1024 CSS px at density 1.
- Mobile viewport: 390 x 844 CSS px at density 1.
- Surfaces: all five admin sections, customer overview, permissions, quickstart,
  Agent documentation and usage conventions.
- Source and implementation captures are both 1440 x 1024 pixels at the same
  1440 x 1024 CSS viewport and device density 1; the combined comparison scales
  each proportionally into a 720 x 512 cell.

## Full-view comparison

The iteration extends the existing precision-infrastructure direction into the
deep pages. It keeps the typography-only wordmark, warm porcelain canvas and
horizontal navigation, then replaces English system eyebrows, repeated rounded
cards and raw status values with editorial headers, divided ledgers and visible
Chinese task language.

The normalized side-by-side permission comparison was the full-view fidelity
input. A separate focused crop was not required because the 1440 x 1024 source
and implementation were also opened independently at full resolution for table
labels, icon alignment, dividers, code text and small-state badges.

## Focused comparison

- Hierarchy: customer permissions now starts with one account contract and one
  capability ledger; markets and endpoints are subordinate lists rather than
  equal-weight cards.
- Documentation: directory and article share one frame; quickstart, Agent
  prompt, function definition and reference pages use the same editorial and
  code-panel grammar.
- Admin density: page headers, toolbar surfaces, metrics, tables and status
  badges share the same radius, hairline and typography rules. Mobile customer
  management changes from a compressed nine-column table into per-customer
  task cards.
- Language: deep-page context and runtime states are visible in Chinese. API
  paths, dataset IDs and schema values remain technical identifiers.
- Responsive: desktop and 390px captures have no document-level horizontal
  overflow; data tables retain contained horizontal scrolling where needed.
- Interactions: all eight workspace routes loaded; documentation navigation and
  copy, data sample query, customer edit/create dialogs, table column dialog,
  usage reset confirmation and admin/customer switching were exercised.

## Comparison history

1. P2 customer permissions used four same-weight cards and decorative icon
   tiles. Fixed with an account contract, a three-column limit ledger and
   ordered market/endpoint rows.
2. P2 mobile customer management squeezed nine columns into a narrow scroll
   surface. Fixed with a dedicated card representation below 640px.
3. P2 deep pages used English uppercase system eyebrows and raw runtime values.
   Fixed with Chinese task labels and central activation/runtime translations.

## Findings

- No actionable P0/P1/P2 visual or interaction differences remain.
- Accepted constraint: technical provider, cadence and dataset identifiers stay
  untranslated because they are operating contracts, not interface prose.
- P3 follow-up: migrate the remaining secondary admin feature icons to Phosphor
  when those feature files next receive functional changes.

## Open questions

- None blocking. Production data density may expose longer provider reasons or
  tenant names than the mock; both remain constrained or locally scrollable.

## Implementation checklist

- [x] Production before-state captured and compared.
- [x] Desktop and mobile browser captures reviewed.
- [x] Primary controls and workspace routes exercised.
- [x] Console error-level output checked.
- [x] Build, lint and focused API/console tests passed.

final result: passed
