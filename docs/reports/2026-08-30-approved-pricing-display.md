# Confirmed pricing display and identity-method decisions

Date: 2026-08-30 CST. Merged as GitHub PR #387 (`489f5be6` on main, 2026-09-01).
This report is the candidate-branch verification record for the approved price
display and dual-identity requirement. It is not a release, live identity
implementation, payment event, or account grant. Later main work added the
non-paying `/pricing/preview` path and a gated email-identity candidate;
those do not turn this display contract into checkout.

## Owner decisions and scope

- Both mobile-phone and email sign-in/registration are required, independent of
  Agent/API keys, within the existing Account experience.
- Monthly prices: 99 / 299 / 499. Annual payment: monthly × 12 × 90%.
- CNY is the domestic-first display assumption and remains a settlement-currency
  confirmation gate. Merchant, sending services, renewal/refund and tax policies
  are not selected by this change.
- Corrected contradictory progressive-scope copy: all tiers share base-data
  scope/history policy and differ only in 200/600/1000 requests/minute.
- Added actual annual totals, equivalent monthly prices and annual savings.
  Disabled checkout remains explicit; existing key holders retain a login link.
- No new login delivery endpoint, user database, payment processor, real order,
  permission change, migration, provider call or production operation.

## Verification

- `cd public-web && npm ci`: completed using the existing lockfile.
- `npm run test:sites`: 32 passed (including five pricing tests).
- `npm run build`: passed, regenerating the committed public distribution.
- `git diff --check`: passed.
- Browser exercised actual React UI at local port 5192:
  - All three monthly and annual totals matched 99/299/499 and
    1,069.20/3,229.20/5,389.20.
  - Annual equivalents and savings were checked in tests and rendered cards.
  - Next-plan wraps Flagship to Basic without changing the period; direct tier
    controls and monthly/annual buttons expose pressed state.
  - Visiting Account preferences, changing Chinese to English and light to dark,
    then returning through navigation retained selected Flagship + annual.
  - Desktop 1280px dark English, tablet 768px light Chinese, mobile 390px light
    Chinese were inspected. Document widths matched viewport widths in all three.
  - Native buttons retained visible focus outlines. Disabled purchase controls
    remained disabled; the access-key login page remained reachable and honestly
    stated email/SMS were not yet available. No authentication secrets were used.
- This branch does not include the separate unmerged sign-out PR #386. If #386
  merges first, integrate main and regenerate dist before releasing this branch.

## Design decisions and scoped review

Direction: preserve the warm editorial single-product showcase, floating header
and quiet surfaces; improve price clarity without redesigning Account or home.
Reuse existing `--ink`, `--muted`, `--blue`, surface/line tokens and 8/16/24px
spacing. No new palette, font family or artwork. Price is 32–44px (40px mobile),
period and equivalent are secondary, and annual total is never disguised as a
monthly charge. Small labels now use muted text instead of low-contrast yellow.
Billing buttons have 44px targets, pressed/focus states and restrained 140ms
feedback; mobile displays the price before detailed coverage.

Manual, scoped score (not a benchmark or full-site accessibility audit):

| Dimension | Score |
| --- | ---: |
| Visual hierarchy | 18/20 |
| Typography | 13/15 |
| Color semantics | 14/15 |
| Spacing rhythm | 13/15 |
| Interaction feedback | 9/10 |
| Accessibility baseline | 8/10 |
| Brand fit | 9/10 |
| Responsive integrity | 5/5 |
| Total | 89/100 |

Remaining work: (1) integrate verified phone/email delivery and account binding,
(2) implement merchant sandbox and idempotent paid-to-access provisioning after
business decisions, (3) perform exact-merged-build, real account and production
readback. Public-web instruction changes were file-checked; loading in a fresh
session was not independently tested.

## Release and rollback

Feature branch + PR, exact-head CI and Datas PM approval remain required.
Revert the scoped source/docs change and rebuild for a UI rollback; no database
rollback or credential rotation is needed. Current production is unchanged by
this candidate until an approved merge, exact-SHA deployment and readback occur.
