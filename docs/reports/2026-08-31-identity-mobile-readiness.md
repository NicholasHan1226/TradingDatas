# Identity mobile and refresh readiness — 2026-08-31

Scope: continuation of PR #397 in the existing Login/Account, with no redesign,
production writes, real outgoing mail, payment/SMS activation or role grants.

## Changes and source

- Integrated main `0f5f0daf01ebde3d978e302d4f605b940779beb3` through merge
  `6a18dbe`; only the STATUS heading conflicted. Both account candidate and
  data-runtime records are preserved. This does not revalidate production data.
- Cancelling the inline deletion form clears its fields/errors and restores
  focus to Request account deletion, including Chinese and English labels.
- Every identity readback clears the previous identity, usage, keys and raw
  one-time key before adopting its result, advances the request epoch and aborts
  the old read. This addresses stale sensitive projections across a changed
  shared session without adding an account surface or changing authorization.
- Two narrow regression assertions cover focus wiring and refresh ordering.
  These are source-structure tests, not a claim of full browser race coverage.

## Fresh evidence

- Build passed; `npm run test:sites`: **111/111 passed**. The generated client
  and Worker artifacts accompany their sources. No dependency/lockfile changes.
- Actual local workerd/D1 harness passed challenge/atomic verification,
  unsubscribed isolation, deletion/revocation, scheduled purge and legacy
  redirect rejection. Only disposable local fixtures; no external mail sent.
- Independent limited-diff review: no new P0/P1; no effect self-loop, epoch order
  preserves stale-result rejection, same-tab login/readback remains supported,
  and the focus callback is safe after unmount. It did not independently run
  browser/StrictMode/multi-tab concurrency or grant production clearance.
- Browser used a real 390×844 viewport override, not the earlier iframe fallback.
  Email sign-in, sign-out, fresh email verification, incorrect confirmation
  disabled, ten-minute freshness error, cancellation and focus restoration were
  observed. English/light and Chinese/dark views retained readable content and
  disabled/focus states; document and scroll widths were both 390px.
- Final mobile deletion submission was blocked by the browser action guard.
  No bypass or alternate submission was attempted. That final UI transition
  remains unverified this turn; local backend tests are not a replacement for it.
  The synthetic account remains active. Real-user deletion was never attempted.

## Release state and remaining work

At 00:22 CST, the previous candidate `d45f896` had green PR checks but no reviews
or `pm-merge`, and main advancement made the PR conflict. This follow-up resolves
the source conflict; it requires new exact-head CI and Datas PM approval.
`https://tradingdatas.com/api/account/auth-methods` returned 404 `not_found`, not
an enabled email-login service. Historical green checks are not this head's CI.

Both login and retention enable flags remain false. No remote additive schema,
Worker deployment, secret provisioning or scheduler activation occurred. Before
launch: exact-head CI/PM approval, private delivery/pepper configuration, reviewed
identity-only migration, live OTP verification, active scheduling/alert evidence
and backup/mail-log retention checks. Payment/SMS and admin/tenant linking remain
separate, unavailable capabilities. No full security-scan clearance is claimed.

Rollback is the previous candidate for these UI changes. For any future runtime
release, preserve session revocation and pending deletion requests; do not remove
the account store or alter financial data. See
[retention](../design/identity-retention-v1.md),
[email identity](../design/email-identity-v1.md) and the
[earlier readiness record](2026-08-30-identity-retention-readiness.md).
