# Login refactor and session correctness review

Scope: public Login and its existing Account session bridge. This supplements
the earlier sign-out review in the same candidate; it does not deploy billing,
OTP identity, a second customer console or a new data API.

## Findings addressed

- Gateway 404/503 used to silently fall back to browser-stored bearer keys.
  Retired that path and removed legacy browser credentials without changing
  server keys. Existing direct users must sign in once again.
- HTTP 200 without a valid account projection could mint a session. Both
  gateway and client now require non-empty tenant/tier identity fields.
- Usage failure used to clear account identity. Identity and usage now load
  separately; usage errors retain sign-in and expose retry. Account validation
  failures hide sensitive projections with a retry notice, not a fake success.
- Late account/key responses could restore old UI state. Abort and session
  generation checks discard those results; key mutations and login are guarded.
- Upstream network exceptions, redirects and unbounded login bodies lacked
  explicit handling. Added timeout/error boundaries, streaming size checks and
  route-specific methods. Upstream 401 clears the scoped cookie.
- Sign-out no longer requires upstream configuration to clear the cookie, but
  still requires same origin. UI waits for explicit confirmation, retaining a
  visible retry state if it fails. Empty key lists no longer stay "Loading".

## Design direction and tokens

Quiet editorial entry: one panel, three method selectors, short brand statement
and existing data-material art. Existing floating header and Account preserved.
Mobile removes decoration, not the form or its visible level-one heading.
Reuse `surface-solid`, `surface`, `ink`, `muted`, `line`, `blue`, `aqua` and
existing radii. No new brand palette, art generation or animation. Main copy
13–16px, input height 48px, clear keyboard focus, error and disabled states.
Phone/Email explain their unavailable status; no contacts collected or fake OTP.

## Validation

- `npm run test:sites`: 53 tests passed, including login transport/errors,
  malformed account responses, eight-hour expiry, encrypted-cookie tamper,
  revoked key, CSRF origin, per-route methods, oversized/chunked request
  cancellation, sign-out outage/retry, and stale-state wiring.
- `npm run build`: passed; client and server/Sites packaging regenerated.
- `git diff --check`: passed.
- In-app browser against the loopback synthetic harness: successful login
  returns to the existing Account; invalid key remains on Login; malformed 200
  remains on Login; usage 503 retains signed-in Account with notice; failed
  logout retains Account and retry succeeds; late key result after logout does
  not restore Account. Phone/Email unavailable views and settings entry checked.
- Rendered 1280px desktop, 768px tablet, 390px mobile, English/Chinese and
  light/dark variants. At checked sizes document width equals viewport width.
  Keyboard focus reviewed. In-app automation's Enter action did not produce
  a request; the follow-up Chrome test below verifies native form submission.
  Reused static art introduces
  no motion. Theme/language remain in Account, including when signed out.

The harness is `public-web/scripts/login-qa-server.mjs`, loopback only, synthetic
data, no upstream or real customer credentials. Unit tests run in Node with Web
Crypto, not deployed workerd. No real OTP, merchant agreement, payment, credential
issuance or production successful-login test is claimed.

## Scoped design scorecard (manual, not user approval)

| Dimension | Score |
| --- | ---: |
| Visual hierarchy | 18/20 |
| Typography | 13/15 |
| Color semantics | 13/15 |
| Spacing rhythm | 13/15 |
| Interaction feedback | 9/10 |
| Accessibility baseline | 8/10 |
| Originality / brand fit | 9/10 |
| Responsive integrity | 5/5 |
| Total | 88/100 |

## Follow-up: identity checking and keyboard acceptance

The 2026-08-30 follow-up reproduced a brief signed-out prompt on Account reload,
before a valid identity read completed. A shared presentation state now separates
checking, authenticated, unavailable, and confirmed signed-out. Account entry
buttons wait during verification; private panels hide stale projections and do
not show a sign-in CTA during an outage. Public preferences and learning remain
accessible. Invalid login credentials still lead to sign-in, not outage retry.
This is a client presentation fix, not a new authorization mechanism.

- Added two state-transition tests and a private-panel wiring regression (53
  public-web tests total), plus slow-identity and identity-outage harness cases.
- Synthetic browser: initial check -> signed-out, successful login -> Account,
  refresh -> checking -> same Account; identity 503 -> retry with no private
  facts/sign-in prompt; API keys and preferences remain correctly separated.
- Chrome native Enter on the actual Login form reached `/account`; the harness
  recorded exactly one POST. No additional keydown handler was added. This is
  browser-level synthetic evidence, not a real-key or production login claim.
- Checked light Chinese at 390px and dark English at 768px, plus desktop state
  inspection; widths matched viewports. Existing typography, spacing, empty
  state and notice components are reused without new tokens or motion. Scoped
  design score remains 88/100; this pass fixes feedback, not the visual system.
- A brief theme transition can still show mixed contrast immediately after
  reload in the in-app browser; settled dark rendering is correct. First-paint
  theme initialization remains a separate visual follow-up, not a passed claim.
- Alipay onboarding still requires owner QR login in both available browsers;
  no account-specific eligibility, fee/limit, signing or payment was verified.

Files in this follow-up: App/accountSession presentation, state and workspace
tests, the synthetic QA harness, README, this report and the public design
contract, plus regenerated client build. No Worker, backend, keys or database
changed. Rollback is the previous candidate frontend; no migration is needed.

## Remaining boundaries and next three priorities

1. Connect owner-approved email/SMS delivery and a verified identity store with
   independently revocable sessions. The current eight-hour encrypted-key bridge
   cannot revoke a copied cookie individually; disabling its upstream key or
   expiry still prevents API use. Never claim account ownership from a typed
   email, phone or arbitrary tenant label.
2. Complete personal Alipay eligibility, fees, single/daily limits and signing;
   implement sandbox order/verification/provisioning only after merchant and
   commercial rules are known. See `../design/personal-alipay-checkout-v1.md`.
3. Obtain independent exact-head review, CI and PM release gate, then perform
   approved production readback. No live user keys/services changed in this task.

Integration: the pricing/dual-identity contract is separately in PR #387. Preserve
its same-scope, rate-only tiers and approved monthly/annual prices when merging;
regenerate App assets from the integrated source, never choose one dist bundle
over the other. The manual-renewal decision in this report's linked payment
contract supersedes the earlier undecided-renewal note.
