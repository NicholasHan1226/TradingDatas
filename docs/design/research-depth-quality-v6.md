# Research depth and maintenance v6

## Scope and ownership

Follow-up to `research-reading-continuity-v5.md`, 2026-08-30. Public website only;
no backend, provider activation, production data, account or hosting changes.
The candidate branches from PR #385 and will be reviewed as a dependent PR.
Merge and public release remain separately gated by Datas PM and exact-head CI.

## Content contract

- Keep 200 external works, stable IDs and the Featured / Topics reading views.
- Deepen eight existing guides, one per display subject, without increasing the
  24-guide count: Markowitz; Andersen et al.; Sloan; Carpenter/Whitelaw;
  Loughran/McDonald; Cong/Li/Wang; Brown/Warner; Diebold/Li.
- Explain question, original materials, method, findings, reading directions and
  limits in both languages. Link specific source sections; preserve the distinction
  between theory, historical evidence and our editorial interpretation. Record
  actual reading scope internally, not as user-facing development notes.
- Add three synthetic preparation tutorials: bar-grid gaps, document revisions,
  and spot/open-interest observation alignment. These teach input preparation,
  not trading, paper replication or dataset availability. Candidate dataset IDs
  must resolve to the repository registry; authenticated runtime coverage is not
  claimed by these examples.
- Generate JSON, standalone JavaScript and Chinese/English Python notebooks from
  maintained examples. No redistributed paper PDFs, vendor records or credentials.

## Maintenance contract

A read-only local check reports identity duplicates, missing bilingual text,
broken internal references, editorial version/scope gaps, repeated prose and
depth-review candidates. Optional bounded external-link checks distinguish hard
404/410 failures from access restrictions, throttling and transient failures.
Optional serial DOI checks compare registered bibliographic fields and reported
updates; they never replace an edition or advance a source date. Both use the
existing system-curl transport pattern with TLS verification enabled.
Neither HTTP success nor text-length heuristics certify research quality. Nothing
is automatically rewritten, removed, scheduled or published.

## Acceptance

Run the full public-web tests and build; execute both languages of all notebooks
in an actual Jupyter kernel if an isolated environment is available. Verify live
desktop/narrow layouts, language/theme changes, keyboard navigation, source links,
copy/run/download controls and accessibility semantics. Automated checks are not
equivalent to a human screen-reader or physical touch-device session. Document
unverified items explicitly before handing off the PR.

## Entry points

`docs/product/RESEARCH_LIBRARY.md`, `public-web/README.md`, source modules under
`public-web/src/`, generators/checks under `public-web/scripts/` and regression
tests under `public-web/tests/`. Re-run acceptance after content/schema changes;
rollback is a scoped feature-commit revert, never a production-data operation.
