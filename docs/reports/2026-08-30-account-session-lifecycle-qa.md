# Account session lifecycle verification — 2026-08-30

## Scope and authority

Source baseline: `97c814bef2014c6419a189de5faedfba12145a2c`.
This pass first added local lifecycle tests, then implemented the user-approved
sign-out failure fix in the public client. It also corrects the design document's
stale claim that the upstream binding is absent. No Worker/backend runtime,
production secret, customer credential, tenant permission or database was changed.

## Verified

- Six synthetic Worker lifecycle tests: eight-hour expiry boundary; ciphertext
  tampering and different encryption keys; upstream 401/403/429/503 propagation
  without issuing cookies; authenticated account/usage/key read routing and
  upstream revocation; same-origin key-write enforcement; scoped logout clearing.
- The follow-up adds five sign-out helper tests plus a UI wiring regression:
  explicit success, network/HTTP/payload failures, retry, timeout, direct-mode
  compatibility and shared guarded entry points. All 39 public-web tests pass
  with `cd public-web && npm run test:sites` after `npm run build`.
- Production browser `/login/` displays the existing access-key entry. One
  deliberately invalid synthetic string is rejected with the invalid/disabled/
  expired-key message, without entering Account.
- Login page document width equals viewport width at 1280px and 390px; mobile
  rendering retains the form and primary action. This is not authenticated
  Account or dark-theme acceptance evidence.

All automated success cases mock the upstream with a synthetic tenant and key.
They prove the Worker contract, not production authentication or tenant isolation.

## Sign-out UI acceptance (local, synthetic only)

A loopback-only HTTP fixture served the actual built React app and synthetic
Account responses, with no real credentials or upstream calls. The first DELETE
returned 503 and the second returned `{signed_out:true}`.

- Overview: pending status and disabled button; failure retains account facts and
  shows an alert with a keyboard-accessible retry action.
- The same alert persists when switching to Preferences or Security; English and
  Chinese content both render correctly.
- Security: retry shows the pending state, then removes the connected identity,
  account facts and error. Reload remains signed out in the fixture.
- Checked dark desktop (1280px), light tablet (768px) and light mobile (390px).
  Mobile/tablet document widths match their viewports. The mobile retry button
  retains a visible focus ring and a 44px minimum target height.

Design direction: preserve the quiet editorial Account layout. Inter/PingFang,
existing ink/surface/yellow/blue tokens, 8px radius, and 16/24px spacing are reused;
no new color token or motion is introduced. A single shared feedback component
adds pending, alert, disabled and retry states without a new dashboard.

Scoped manual design score: hierarchy 18/20, typography 13/15, color semantics
14/15, spacing 14/15, feedback 10/10, accessibility 8/10, brand fit 9/10,
responsive integrity 5/5 = 91/100. This is a local visual assessment, not a full
accessibility audit. Remaining verification: real-account logout, screen-reader
announcement checks, and broader authenticated Account responsive coverage.

## Remaining acceptance and limitations

- Nicholas must sign in at `https://tradingdatas.com/login/` with an intended
  customer key, without posting it in chat. Then verify Account overview,
  subscription/expiry, usage, reload persistence and explicit logout. Do not
  inspect browser cookies or storage to obtain the key.
- Key creation/disabling needs a separately bounded mutation test and approval;
  proxy tests do not establish live backend authorization.
- Logout clears the current cookie; the documented stateless bridge cannot
  individually revoke a copied cookie. The regression deliberately records this
  boundary instead of claiming server-side session revocation.
- `disconnectAccount()` now clears local UI state only after explicit confirmed
  success; unconfirmed responses retain state with retry. A ten-second abort
  prevents indefinite pending, duplicate submissions are guarded, and older
  account reads are invalidated after success. This is locally verified, not
  evidence of successful production logout.

The client fix needs the normal reviewed PR and public Worker asset release.
Local candidate changes are not a merged or published release. Rollback is the
previous public release; there is no migration or secret rotation.
