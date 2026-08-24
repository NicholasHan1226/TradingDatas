# Admin console workspace v2

## Direction

The console uses a calm-fintech research-workstation direction: a dark control
plane frames a quiet neutral data canvas. Blue denotes navigation and selected
context only; health, availability, and degraded states keep their semantic
colors. This keeps dense operational facts legible without turning every
surface into a competing dashboard card.

## System decisions

- Typography: system sans for Chinese and UI copy; monospace is reserved for
  dataset IDs, hashes, dates, and quantitative values. Page titles use 22px;
  section labels use 10px tracked uppercase; supporting UI uses 11--14px.
- Tokens: `--td-canvas`, `--td-surface-raised`, `--td-ink-soft`,
  `--td-accent-quiet`, semantic state tokens, a 4px spacing rhythm, 8/12/18px
  radius steps, and two shadow levels are the shared visual contract.
- Interaction: 120ms control feedback, 180ms state transitions, visible focus
  rings, `aria-pressed` selection in the data browser, and non-blocking status
  text throughout.
- Responsive behaviour: desktop keeps the control-plane rail; compact layouts
  keep the section selector, user-preview action, and logout action in the
  header so no critical navigation disappears.

## Scope and rollback

This is a presentation-only refactor. API contracts, authentication, tokens,
collectors, schedules, receipts, and query semantics are unchanged. Revert the
single merge commit to return to the former static bundle and shared styles.
