# Research reading depth and preparation tutorials

Owner request: Nicholas, 2026-08-30. Scope: PR #385, `public-web` only.
Source of truth: the accepted Featured/Topics model in `research-dual-view-v3.md`,
the source policy in `../product/RESEARCH_LIBRARY.md`, and current source records.

## Reader experience

- Keep two views. Featured adds twelve attributed, expanded guides; Topics adds
  three-step reading sequences for each of the eight subjects, before the first
  unfiltered page. Publication filtering still filters only the bibliography.
- Never count a guide, translation, tutorial or route membership as another paper.
  The library remains 200 external works, of which twelve have expanded notes.
- Three existing preparation routes become bilingual teaching articles with inputs,
  four steps, local synthetic demonstrations, expected outputs, limitations,
  source references and related research. Existing method bookmark IDs survive.
- Example code and runtime demonstrations use the same pure functions. No provider
  call, token access, strategy calculation, external write or product activation.
  Copy failure provides a selectable fallback; success appears only after a
  fulfilled clipboard write. Real API examples are copy-only, bounded to three
  rows and require authenticated catalog values, grants and appropriate filters.
- As-of examples use max(publication, first observation), retain amendments and
  reject ambiguous versions. Calendar examples choose the first opening strictly
  after availability and retain unresolved timestamps or insufficient coverage.
  These are conservative teaching conventions, not historical PIT guarantees.

## Build and delivery

`scripts/research-public-projection.mjs` projects the source catalogue to only
reader-consumed fields during Vite production builds; it does not rewrite source
metadata. React has a separately cacheable chunk and tutorial code is lazy-loaded.
`scripts/build-research-pages.mjs` runs after the existing Sites preparation step,
generating 208 static HTML entries with escaped bilingual sharing metadata and
canonical URLs. The existing Worker and Sites handoff contracts remain unchanged.
Client route/language changes refresh title, description, canonical and OG fields.
Static share metadata is not full article SSR and does not certify crawler uptake.

## Validation and rollback

Run `npm run build` and `npm run test:sites` in `public-web`, then inspect the actual
production build in desktop and narrow viewports. Verify twelve guide links, eight
sequences, all three example runs, both locales, dark/light, keyboard controls,
bookmarks, back navigation, copy outcomes and absence of horizontal overflow.
Test denial/unavailable clipboard through the shared helper's deterministic tests;
report separately whether a real browser denial and physical screen reader were
tested. Read generated HTML without JavaScript to confirm share metadata.

All content/build changes travel in the feature PR. Exact-head CI and the current
PM merge gate precede main integration; exact-main CI/deploy and route/asset readback
are distinct release evidence. No ECS/collector/API contract change is in scope.
Rollback is a scoped revert of the release commit plus regeneration/redeployment
of its predecessor's public build, not a reset of data or credentials.

Last local verification and remaining release work belong in `public-web/design-qa.md`
and the PR, not in public article bodies.
