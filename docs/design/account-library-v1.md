# Account continuity and personal library v1

Status: implementation merged; 2026-09-05 integration release in preparation.
Current activation/readback lives in `STATUS.md`; the earlier candidate report is
historical. This release enables only existing-key account connection. Personal
library and administrator bridging stay disabled; payment remains paused.

## Frozen boundary

An email session establishes identity, never a tenant, plan or administrator role.
The existing Account may explicitly connect one already-issued data access key after
a sign-in within ten minutes. A successful authenticated `/portal/api/me` supplies
all data rights; the connection is possession-based delegated access, not ownership
transfer, email matching, a purchase, or a new entitlement. No client-supplied tenant,
scope or tier is accepted. Existing financial facts and issued API keys are untouched.

The account store holds a user-bound AES-GCM encrypted credential. It never returns
that credential, saves it in browser storage, or places it in a URL. Every data or
administrative request revalidates the backend authority; revocation/expiry blocks
data access while email sign-in and the personal library remain independent. A
connection cannot be silently replaced; disconnect first. Disconnect requires fresh
identity, removes the stored connection, and does not revoke upstream API keys.

Admin access is not inferred from the owner email. Only the existing backend's
`admin` scope / `internal` tier can authorize a restricted console. `/admin/` reuses
the built `frontend` AdminApp and calls the same-origin bridge under
`/api/account/admin/`. The bridge allowlists existing admin token, usage, health,
collection and data overview routes, plus existing catalog/query for the restricted
data browser; it is not a general-purpose proxy or new public data API. Every call
requires expected identity and current backend admin authority. Administrative writes
additionally require email verification within ten minutes. No credential is sent to
the admin frontend. Standalone `/app/` remains the legacy bearer-only admin fallback;
its CORS backend never receives identity cookies. Shared sign-in is a candidate until
the deployed flow is verified, not a claim based on an Admin link alone.

## Library

Verified identities may store at most 500 stable resource references, of kinds
`dataset`, `research`, `method`, `doc`. References contain no URL, email, title, notes
or data payload. The existing public index resolves display content; unknown or
retired references grant no access. GET returns only the current user's references.
PUT/DELETE are per-reference and idempotent; import is an explicit, bounded, atomic
union, never a replacement of another device's library. Mutation rate is bounded.

Guest bookmarks stay in `td-bookmarks` in this browser. Sign-in never automatically
uploads them. Account → Bookmarks names the verified identity and offers an explicit
import; the local copy remains after import. Cloud references never enter browser
storage. Logout/account refresh hides cloud state immediately; requests and responses
carry the expected identity so another tab's session switch cannot write to the
wrong library. Errors show an unconfirmed state, never a false saved success.

## Routes and controls

These are account control-plane routes, not additional public data endpoints:

- `/api/account/connection`: POST connect, DELETE disconnect; recent sign-in,
  same-origin, expected identity, request-size and rate checks.
- `/api/account/bookmarks`: GET current library.
- `/api/account/bookmarks/item`: PUT/DELETE one `{ key }`.
- `/api/account/bookmarks/import`: POST `{ keys }`, at most 100 per explicit import.
- Existing `me`, `usage`, `keys` remain the only customer projections of the backend.

The committed integration configuration enables `ACCOUNT_CONNECTION_ENABLED`;
`ACCOUNT_LIBRARY_ENABLED` and `ACCOUNT_ADMIN_ENABLED` remain false. Apply the
reviewed account-only schema before this configuration reaches production.
Additive schema is `public-web/worker/account-library-schema.sql`; applying it is a
separate reviewed D1 operation. Migration includes dependent-authority revocation on
profile disable and cascaded personal-library cleanup on explicit profile purge.
That revocation remains effective even after flags are disabled or code rolled back.
Deletion requires `X-TD-Identity` matching the authenticated session, including when
connection/library flags are off; missing or different identity returns 409. Its
receipt includes `user_id`, which the frontend verifies before clearing state.
Do not roll back to an old deletion endpoint lacking this stale-tab check.
SESSION_ENCRYPTION_KEY rotation invalidates stored connections; reconnect explicitly.

## Acceptance and release

Test two users/two sessions, cross-tab identity mismatch, stale responses, invalid
credentials, provider redirects/failure/revocation, no account provisioning from a
key, idempotency/import limits, CSRF, oversized bodies, delete/link races and cascade
cleanup. Run Node SQLite tests, actual local workerd/D1 tests, build and browser
checks on existing Account in both languages and themes. Synthetic fixtures are not
production evidence. Freeze candidate for independent review and exact-head CI.

Production requires PM review, exact-source upload preserving staged encrypted
secrets, separately approved schema/flag changes, real recipient-approved email
acceptance, runtime/D1/session/backend readback and a rollback verification. Keep
email, connection, library and admin acceptance as separate conclusions. Payment and
SMS remain unavailable throughout this slice.
