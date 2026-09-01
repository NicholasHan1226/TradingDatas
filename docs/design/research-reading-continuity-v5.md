# Research continuity and offline tutorials

Owner request: Nicholas, 2026-08-30; follow-up to PR #385 and
`research-reading-depth-v4.md`. Merged to `main` in PR #385. Scope is public
research/editorial/tutorial UI, tests, documentation and generated assets; no
data-plane or account change. Merge is not production publication.

## Acceptance contract

- Keep 200 unique external works and the two Featured/Topics views. Expand to
  24 four-section bilingual guides: every slot in the eight three-step subject
  journeys resolves to a guide. Cross-subject reading membership is not taxonomy
  reassignment or a second work. Original titles, DOI and bookmark IDs survive.
- Each new guide records primary-source URL, date and actual reading scope.
  Explain the question, evidence, interpretation and limitations without copying
  abstracts or claiming full-text review. Excerpt-only access remains excerpt-only.
- Article continuation shows its place in a topic journey, previous/next papers
  and authored connections between their questions and methods. Links remain
  language-neutral. Other records retain their related-reading fallback.
- Preserve each in-tab history entry's library filters and scroll position;
  an explicit article return restores the most recent library entry. This is
  browser-local navigation state, not synced reading history.
  Native tutorial section links and their back/forward traversal must retain
  section positioning instead of triggering the route-level scroll-to-top.
  Direct, refreshed and history-restored hash URLs must also wait for lazy
  tutorial content to mount before scrolling to the decoded target identity;
  leaving that hash must cancel its pending restoration before content mounts.
- Three tutorials offer same-origin downloads: synthetic input JSON, a readable
  JavaScript example and localized Python notebooks. Notebooks include setup,
  parameters, assumptions, input validation, expected-output assertions and next
  steps. Run offline, with no credentials, external queries or package install.
  Python results must match the existing JavaScript examples, including failure
  cases. Generate artifacts from maintained source, not hand-edited JSON copies.
- Verify desktop/tablet/mobile rendering, both locales/themes, keyboard/focus,
  copy outcomes, history and downloadable file content. A semantic inspection is
  not screen-reader speech, pointer emulation is not physical touch, and helper
  tests are not a real clipboard-permission denial. Report gaps separately.

## Verification / release

Use public-web `npm run test:sites`, `npm run build`, the notebook verification
script and the real preview. Evidence belongs in `public-web/design-qa.md` and
the PR, never in prominent reader panels. Exact-head CI and Datas PM approval
precede merge; exact-main deployment and live asset/deep-route/download readback
precede a publication claim. Preserve protected Sites/Worker files. Roll back
with a scoped revert and predecessor build, not data or credential changes.
