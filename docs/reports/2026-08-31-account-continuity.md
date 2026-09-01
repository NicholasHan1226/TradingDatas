# Account continuity candidate — 2026-08-31

## Scope and state

Branch: `codex/account-library-v1`, following email candidate `ea1c536` / PR #397.
This is a local implementation and release candidate, not production activation.
The existing public Account design is retained. The existing administrator React
application is reused at same-origin `/admin/`; no second customer dashboard is added.

- A recently verified email identity can explicitly connect an already-issued
  data access key. The server encrypts the credential with user-bound associated
  data and rechecks the upstream tenant and authorization on every bridged call.
- Plan, expiry, usage and key management project the existing backend authority.
  An email address, first registration or client-supplied role grants nothing.
- Server-confirmed administrators can enter the existing Admin app through a
  fixed-route same-origin bridge. Ordinary customers cannot use that bridge.
- Bookmarks are identity-scoped references, capped at 500. Guest/local bookmarks
  remain separate; import is explicit, additive, and bounded to 100 per action.
  Logout, identity changes and late responses clear or invalidate private state.
- Payments and SMS remain deferred. No order, subscription or new data grant is
  created by this work.

Contract: [Account continuity v1](../design/account-library-v1.md).

## Verification performed before submission

- Public-site deterministic suite: **127/127 passing**.
- Public build and administrator TypeScript/build: passing; generated artifacts
  are included with their source. Worker source/generated copies are checked.
- Administrator lint: zero errors, 16 warnings. Existing React-hook warnings
  remain; the new wrapper also reports effect/ref warnings around deliberate
  identity invalidation. These are not reported as a warning-free lint pass.
- Public bundle emits Vite's 500 kB chunk advisory (about 501.45 kB raw / 145 kB
  gzip). No new dependency or lockfile change; further code splitting is deferred.
- Actual local workerd/D1 checks passed email verification, explicit bookmark
  import, encrypted connection, customer rejection at the admin bridge, disable
  trigger revocation, profile purge cascades, and legacy redirect rejection.
- Browser checks on loopback used synthetic `example.com` identities and fake
  upstream keys only: email verification, explicit connection, projected plan /
  expiry / usage, bookmark save, Chinese/English and light/dark appearance,
  narrow responsive Account, and the reused administrator app's actual render.
  The latest handler was tested on port 5202. No actual administrator mutation
  or real customer email was sent from the browser.
- Source/documentation whitespace checks passed. The full generated-artifact
  diff reports ten whitespace-only lines inside the unchanged third-party
  scroll-lock CSS template in the two built Admin bundles. Generated/vendor
  bytes were not hand-edited to suppress that warning.
- Latest main `ddccda1` was integrated without conflicts, preserving its catalog
  process isolation and prewindow clock repairs. Public source was unchanged
  by that integration. GitHub CI and production acceptance remain separate gates.

## Independent review and fixed finding

A bounded independent read-only review found a P1 cross-tab deletion flaw: an
old identity's UI could otherwise submit a deletion under a newer cookie identity.
The handler now requires a matching `X-TD-Identity`; absent or mismatched values
return 409 before any write. The acceptance receipt contains `user_id`, and the
client rejects mismatched receipts.

The reviewer replayed the two-identity case and matching-identity deletion,
verified 38 focused tests, and exercised delayed connection, delayed admin
response and simultaneous-connection races in disposable stores. No remaining
confirmed P0/P1 was found within that review. This is not a production security
certification or a substitute for staged end-to-end acceptance.

**Do not release the older PR #397 implementation alone without retaining this
deletion safeguard.** Preserve the database disable trigger on rollback, too.

## Release boundary / remaining work

- `EMAIL_LOGIN_ENABLED`, `IDENTITY_RETENTION_ENABLED`,
  `ACCOUNT_CONNECTION_ENABLED`, `ACCOUNT_LIBRARY_ENABLED` and
  `ACCOUNT_ADMIN_ENABLED` remain false in the committed configuration.
- `account-library-schema.sql` is additive and tested only in disposable local
  stores. It has **not** been applied to the remote identity D1 database.
- This turn did not alter production credentials, users, roles, traffic or
  feature flags, and did not send a real email. Previously staged private
  provisioning is documented separately and is not a deployment.
- Submit the exact candidate, pass CI, and obtain the repository's Datas PM
  approval before integration/release. The PM task/approval is still unresolved.
- Before activation, verify the dedicated store/binding, preserve the staged
  secrets explicitly, apply the reviewed additive schema to the confirmed
  target, and run authorized real email and upstream account/admin acceptance.
- Verify collection runtime and commercial entitlements independently. Synthetic
  Basic plan / usage / admin fixtures prove UI and authorization handling only.
- Backup retention, real email-client rendering, physical-device assistive
  technology and production scheduled cleanup remain separate acceptance items.

Rollback: turn off the new entry flags, retain the additive schema and disable
trigger, preserve revocation/deletion safety and honor queued deletion deadlines.
Do not restore deleted identities, delete legacy keys or touch financial facts.
See [operations](../OPERATIONS.md) for the candidate release sequence.
