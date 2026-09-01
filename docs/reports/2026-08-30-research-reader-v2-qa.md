# Research reader v2 — candidate verification

Scope: `codex/research-source-atlas-v1`, PR #385. This report records local
candidate checks, not merge, publication or production availability.

## Change and scope

- Removed the public preparation-state/source-check panels, generic three-step
  checklists and oversized equal-height detail cards. Evidence remains in the
  maintained records; individual check dates no longer inherit the library date.
- Added first-screen original-source, local bookmark and citation-copy actions;
  failed clipboard access offers a selectable citation, never false success.
- Kept article-specific limitations and original authorship. Generic topic
  profiles are not presented as individual-paper analysis. Related data/methods
  are collapsed and clearly distinguished from the original sample.
- Added two bilingual Tokenomics reading sections, based on the author copy's
  abstract/introduction. Source: https://nengwang-economics.com/publications/papers/Cong_Li_Wang_RFS_2020_authorcopy.pdf
  This is not a full-paper review; the other 199 records are not newly deep-reviewed.
- Reset incompatible filters on full-library/question entries; keep in-tab
  library page/filters and clicked reading position on return from details.
  No reload/cross-device reading-history claim.

## Fresh checks

- `node --test tests/*.test.mjs`: 41 passed, including server-rendering all 200
  records in both languages and checking that internal QA labels are absent.
- `npm run build`: passed; JS 661.38kB / 194.67kB gzip. The existing >500kB
  chunk warning remains; this change is not a performance-optimization claim.
- `git diff --check`: passed. Updated public-web rules were read and checked in
  this session; automatic instruction discovery in a fresh session is unverified.
- Browser: book filter -> financial question now returns 28 records, not zero;
  Clear filters returns all 200. Page 2 -> Portfolio Selection -> Back to
  Research retains Page 2 and the clicked row position.
- Browser: Tokenomics bookmark updates to Saved; Copy citation reports success.
  Original DOI is exposed near the title; links and citation keep original identity.
- Actual 1280x720 desktop rendering: Chinese/light and English/dark reviewed.
  Actual embedded 390px and 768px content viewports: Chinese/light reviewed;
  390px English/dark long-title wrapping reviewed. No visible horizontal clipping.
  These are responsive browser layouts, not physical-device touch tests.
- The temporary responsive test page was removed before the final build and
  is not a deliverable or public route.
- Source files, authored docs and generated build are the only changed scopes.
  No backend, workflow, credentials, registry, provider or production edits.

## Design assessment

Direction: existing warm editorial reader. Existing typography/colors/radii and
header shadow reused; no new token family or artwork. Content determines height,
with 16–48px spacing, 44px action targets, visible focus and saved/copy feedback.

| Dimension | Score |
| --- | ---: |
| Hierarchy | 18/20 |
| Typography | 14/15 |
| Color semantics | 14/15 |
| Spacing | 14/15 |
| Interaction feedback | 9/10 |
| Accessibility baseline | 8/10 |
| Brand fit | 9/10 |
| Responsive integrity | 4/5 |
| Total | 90/100 |

This is an editorial self-assessment, not independent review or WCAG certification.
Score does not establish production readiness. Remaining checks: physical-device
touch, native browser Back/Forward across multiple divergent library visits,
clipboard-denied runtime, full accessibility audit and all external-link access.

Next three priorities: deepen core paper-specific orientations; expand curated
reading paths; complete physical-device and keyboard/assistive-technology QA.
