# Research 140-guide editorial boundary

Date: 2026-09-01. Scope: public-web candidate content and static build only.
This is not production publication, a full-text review claim, or evidence of
data availability.

## Current projection

- 200 distinct external source identities.
- 140 bilingual reader guides: 139 with six source-located sections and one
  four-section Dechow/Dichev abstract-based orientation.
- 60 summary-only records, intentionally retained as attributed discovery
  records rather than inflated into guides.
- Six synthetic preparation tutorials. They do not call a provider or reproduce
  a paper's original dataset.

`researchBatchOne140.js` is the final twenty-guide cumulative increment after
the historical 120-guide modules. Earlier `research-*-guides` records preserve
the count and review boundary of their own batch; they must not be read as the
current cumulative total.

## Reader and maintenance boundary

The public library keeps original authorship, direct source links, local-only
bookmarks, an unofficial Chinese editorial title, authored orientation, and
source-specific limitations. It does not expose internal verification notes,
claim that every source is accessible, or imply that linked TradingDatas products
reproduce a paper's original sample.

Use `npm run audit:research` before content changes. It separates structural
errors from editorial review cues. Optional link and metadata checks are bounded,
read-only, and never auto-rewrite identities or advance a source-review date.

## Verification recorded for this candidate

- `npm run audit:research`: 200 records, 140 guides, six tutorials, zero
  structural errors; 60 summary-only entries remain editorial candidates, not
  defects.
- Baseline `npm run test:sites` passed locally on Node 26.0.0 before this
  documentation clarification; the focused research, public-evidence and
  account-workspace tests plus `npm run build` passed afterwards.
- Local browser inspection at a 390 px viewport: Research rendered without page
  horizontal overflow or console errors. This is local visual evidence only.

Before a public-content release, rerun source checks for the chosen batch,
inspect both themes/languages and keyboard navigation, obtain the required review,
then separately verify the exact deployed routes and assets.
