# Research reader refinement

Scope: PR #385 public-web candidate. User feedback, 2026-08-30: internal
development/verification notes do not belong in a public article body.

## Design and content boundary

Retain the existing warm editorial canvas, artwork, navigation and bilingual
identity. A paper is a reading destination, not a six-card QA dashboard.
Use title/author/source, primary reading actions, a short orientation and
content-sized reading sections. Show source-specific limitations where useful;
never inflate short entries with category-level process boilerplate.
Keep verification evidence, readiness and generic checklists in content records
and maintenance docs. Missing deep reading notes stay absent, not fabricated.

Reuse Inter/system/PingFang typography; title 32–52px, body 16px/1.8, supporting
text 12–14px. Reuse --bg, --ink, --muted, --line, --blue tokens; no new palette.
Use 8px spacing increments (16/24/32/48), existing 6–12px control radii and
existing floating-header shadow only. No new decorative cards or motion.
Reading actions use 44px minimum targets, visible focus and pressed/disabled
states. Existing search input, cards, list and account menu retain their contracts.
Responsive content becomes one column below 760px; wrapping source titles and
actions must not overflow. Respect reduced-motion preferences for navigation.

## Behavior and verification

Opening the complete library or a question resets format and page. Direct filter
changes reset page; returning from a paper restores the in-tab library view and
scroll position. No new tracking or account storage. Bookmarks remain browser-local.
Citation copying has explicit success/failure feedback and a selectable fallback.

Run public-web tests/build and inspect the actual candidate in both languages
and themes. Record fresh screenshots, tested viewport coverage and residual
limitations in the delivery report. No merge or production release is implied.
