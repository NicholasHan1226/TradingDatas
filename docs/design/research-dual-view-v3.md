# Research: Featured and Topics

Confirmed by Nicholas on 2026-08-30. Scope: PR #385 public-web candidate only.

## Source and reading model

Implement the selected combined mock (`exec-2aec2b00-09b7-4fc7-a312-9735bb302624.png`):
one research section with exactly two quiet local navigation links, Featured and
Topics. Featured uses the editorial China-market paper spread and two reading-path
entrances. Topics uses an unboxed subject index and bibliographic rows. All
literature is a subject-index entry, not a third navigation destination. A small
disclosure keeps the third existing path and all preparation methods reachable.

Reuse the existing global header, supplied brand, Phosphor icons, Inter/system
body text and warm/dark tokens. Editorial display type uses local Songti/Georgia
fallbacks; no added font download or package dependency. The generated architectural
hero is decorative, not a real exchange photograph or research evidence. No
tickers, market statistics, publisher logos or fabricated report covers.

## Content and state contract

- The same 200 records, IDs, original authors, source links and bookmarks serve
  both views. No new paper, translation, conclusion or provider grant is added.
- Eight display subjects group the existing taxonomy. `quant-methods` joins
  `research-methods` only in discovery; original records and search aliases remain.
- Topic counts derive from all records, independent of the selected format.
  Result count reflects the selected subject and format. Lists contain 12 items
  per page; the whole collection remains searchable through the one global search.
- `/research` opens Featured for a fresh visit. `?view=topics` opens Topics;
  optional `topic`, `format` and one-based `page` parameters reproduce discovery.
  Unknown values fall back safely; out-of-range pages clamp to the final page.
- Switching views preserves filters/page; choosing a subject or all literature
  resets format and page to avoid stale combinations. Format changes reset page.
- Filter/view edits replace the current discovery history entry. Article
  navigation creates a normal history entry; native back and the reader's return
  link restore discovery. Refresh preserves URL filters/page, not scroll position.
  In-tab return restores the latest discovery scroll. This is not reading history
  synchronization or per-entry cross-device storage.
- The Topics index becomes a horizontally scrollable text index on small screens;
  semantic links remain keyboard reachable. Empty combinations offer a type reset.
- Language and appearance keep the existing Account controls and system defaults.
  Chinese guides keep original-language paper titles visible; neither language
  changes DOI/source/bookmark identity. Internal review records stay internal.

## Verification and rollback

Run `npm run test:sites` and `npm run build` in public-web. The discovery tests
cover taxonomy conservation, URL normalization, view/filter transitions, bilingual
rendering and every topic/type empty state. Browser verification covers both views,
reader return/native history, bookmarks, language/theme, desktop/tablet/mobile,
keyboard focus and long titles. `public-web/design-qa.md` records the selected
visual comparison and residual gaps. Retain the current preview and existing PR;
no merge/deployment authority is inferred. Revert this scoped commit through a PR
to restore the reader-v2 presentation; no data migration is involved.
