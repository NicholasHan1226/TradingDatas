# Research library 200: candidate verification

Scope: `codex/research-source-atlas-v1`, PR #385. Verified 2026-08-30.
This report describes the local candidate, not a production deployment.

## Content checks

- 200 unique records and stable routes; normalized source titles and DOI identities
  have no duplicates. Translations and reading-path membership do not add records.
- 184 papers/proceedings articles, 6 working papers, 2 books/chapters,
  4 institutional/industry references, 2 cases, 2 live primary-source guides.
- 186 publisher-registered metadata records and 14 primary/official-source records.
  Final verifier: `requested=186, verified=186, unresolved=0` (checked metadata
  is cached; official-source exceptions are reviewed separately).
- All records contain Chinese/English editorial titles/orientations, data inputs,
  limitations and preparation checks; all related object IDs resolve.
- Corrected mismatched China-market citation, intraday authors, same-title digest
  substitutions, book-review substitution, incomplete authors and source editions.
  Crossref identity hashes are not full-paper hashes. Full-text peer review,
  replication, comprehensive retraction screening and redistribution rights are
  not claimed.

## Local checks

- `node scripts/verify-research-sources.mjs`: passed, no unresolved records.
- `node --test tests/research-catalog.test.mjs`: 7 passed.
- `npm run test:sites`: 34 passed, including search, account, login and Worker tests.
- `npm run build`: passed; required Sites/Worker outputs generated.
- `git diff --check`: passed.

## Actual browser observations

Local preview: `http://localhost:5176/research`, 1280×720.

- English and Chinese research landing/detail pages rendered; original source
  titles and DOI links retained in Chinese mode.
- All ten full-library pages were clicked: 200 rendered links, 200 distinct links;
  final page ends with *Tokenomics: Dynamic Adoption and Valuation*.
- Books/chapters filter displays two records and removes unneeded pagination.
- Chinese global search `代币经济` finds the final record and opens its detail page.
- A point-in-time reading path opens four actual linked records.
- A signed-out visitor can enter Account preferences, choose Chinese, and restore
  System mode (English in the test browser). No credential was entered.
- Dark landing and light detail rendering were visually inspected. No horizontal
  overflow was observed in the inspected desktop states.

## Remaining boundaries

- Tablet/mobile viewport and reduced-motion browser regression remain unverified
  in this run. Existing responsive styles remain; desktop evidence does not prove
  narrow-screen behavior.
- Production domain/Worker, merge, provider/SQLite/runtime, paid grants and real
  authenticated account behavior were not exercised or changed.
- Vite reports a 657 kB minified main chunk (about 193 kB gzip); build passes, but
  broader payload splitting/performance work is not included in this content PR.
- Public-web rule documentation was updated and checked as a file; fresh-session
  rule-discovery smoke was not run.
- No recurring ingestion/publication automation was created. Future content
  updates use the documented editorial and source-verification workflow.

Next: inspect the exact PR-head CI results and finish narrow-screen/reduced-motion
review before any publication decision. Removing/reverting this candidate commit
restores the preceding research content; there is no data-plane migration.
