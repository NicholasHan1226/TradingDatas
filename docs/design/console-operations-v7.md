# TradingDatas console operations v7

This iteration extends the calm-fintech system in
`console-product-system-v4.md` with an operator-first incident surface. It does
not change customer permissions, rotate credentials, add public API routes, or
turn valid empty/on-demand datasets into incidents.

## Direction

The health workspace is a **quiet operations desk**: light porcelain surfaces,
compact typography, cobalt action cues, and semantic rose/amber/blue accents.
It replaces the long stream of generic system cards with a two-column incident
queue that answers five questions in one scan: what failed, where, when, why,
and what the operator should do next.

## Alert contract

- Only active failed, stale/degraded, or unobserved datasets become runtime
  alerts. Paused datasets and valid empty results remain available in the data
  runtime table but do not create health noise.
- Every dataset alert carries stable identity, runtime state, provider,
  cadence, data waterline, observation time, reason codes, and a bounded
  suggested action. Receipt-integrity alerts use a separate kind.
- The API keeps raw reason codes for diagnosis; the interface uses concise
  Chinese task language for titles and actions.
- Severity filters, empty states, keyboard focus, and desktop/mobile wrapping
  use the shared v4-v6 component contract.

## Performance contract

Admin catalog-derived endpoints may reuse one five-second in-process projection
only when the authenticated grant set and SQLite file modification identity are
unchanged. The cache is a short request accelerator, never a replacement for
SQLite receipt authority. A changed database file invalidates it immediately.

## Component changes

- Health alerts become structured incident cards with a dedicated icon,
  severity tag, four-field evidence ledger, reason-code tags, and a suggested
  action surface.
- The summary strip and severity control stay above the queue so the first
  screen communicates impact before detail.
- Cards use the existing small-radius, hairline, low-shadow geometry; no dark
  hero, glass layer, oversized gradient, or green link treatment is introduced.

## Responsive acceptance

- Desktop: two-column incident queue; mobile and tablet: one column with the
  evidence ledger reflowing from four to two fields.
- No page-level horizontal overflow at 390 px; identifiers may wrap without
  hiding severity or action guidance.
- Logout, customer preview, severity filters, loading, empty, error, and mixed
  alert states remain reachable with keyboard and touch.

## Rollback

Reverting this frontend/API change restores the previous health presentation
and removes the short projection cache. No token, receipt, data row, timer, or
customer permission requires migration or rollback.
