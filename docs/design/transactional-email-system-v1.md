# TradingDatas transactional email templates v1

Owner: public-web account control plane. Scope: outbound email presentation, not authentication authority.

## Decision · 2026-08-30

Nicholas confirmed receiving the delivery-only test and required templates for future external mail. That plain-text test is not the production visual baseline. Inbox versus spam placement was not specified. No further email is authorized by this design change.

All TradingDatas external emails, including future delivery tests, must use a reviewed, versioned template with both HTML and authored plain text. New purposes require an explicit template; do not interpolate arbitrary subjects, HTML, or links into the sender. This project-specific requirement does not change global collaboration instructions.

## Visual contract

- Direction: quiet product correspondence, continuing the existing website. Original four-square mark, live TradingDatas wordmark, one message and one focal point. No market charts, hero artwork, marketing upsells or unnecessary login button.
- Light tokens: canvas `#f7f5f1`, surface `#fffdf9`, ink `#151917`, secondary `#616867`, action blue `#064bff`, aqua `#087f85`, divider `#e3e5e1`.
- Dark tokens: canvas `#08121e`, surface `#101e2d`, ink `#f1f5f7`, secondary `#b4c1cd`, blue `#91b5ff`, aqua `#74d8ce`, divider `#344555`.
- Typography: system sans-serif, 28px title, 16px body / 1.7 leading, 13px security/footer, 36px monospaced eight-digit code. At narrow widths, title 26px and code 30px. No downloaded font.
- Layout: max-width 560px, 32px desktop / 22px mobile content padding, 16–28px section rhythm, 16px card radius, subtle border, no shadow. Motion: none.
- Components: brand header, purpose label, title + short instruction, optional verification tile, safety note, restrained website footer. Forms, modals and loading/empty states are not applicable to static email.
- HTML uses presentation tables and critical inline styling. The optional logo has a fixed public URL without tracking parameters; essential text/code never lives inside images. Image blocking, stripped styles or unsupported dark mode must not remove instructions. Forced client color inversion remains a mailbox-client QA item.

## Content and sender boundary

`public-web/worker/email-templates.js` owns the shared frame and localized content. It returns only `subject`, `html`, and `text` for the existing Resend sender. No network access or recipient handling lives in the renderer.

Supported template IDs:

- `sign-in-code-v1`: zh / en; eight-digit code, caller-supplied expiry matching the challenge policy, one-use and non-sharing instructions, ignore-if-unrequested guidance. No code in subject/preheader.
- `delivery-test-v1`: zh / en; explicitly not a login and not a data/admin permission grant. No OTP. Rendering this template does not send it.

Future security, subscription and payment messages reuse the frame but need their own reviewed templates and real triggering events. No payment-success or administrator-grant message is introduced now. The existing approved sender remains `TradingDatas <login@account.tradingdatas.com>`; different email purposes do not automatically authorize a different sender or delivery.

## Integration and verification

Resend supports both [`html` and `text`](https://resend.com/docs/api-reference/emails/send-email); both are supplied explicitly. Reviewed against Cloudflare [Workers production guidance](https://developers.cloudflare.com/workers/best-practices/workers-best-practices/) and types `5.20260830.1`. No dependency, binding, database or provider change is required.

Verification (2026-08-30):

- `cd public-web && npm run test:sites`: 92/92 passed, including strict inputs, localized HTML/text equivalence, production send-path integration and build-module presence. New template tests first failed with the missing module before implementation.
- `npm run build`: passed; all three Worker source modules match generated copies, and client JS/CSS hashes are unchanged.
- `node scripts/check-email-runtime.mjs /absolute/path/to/miniflare/dist/src/index.js`: local workerd + isolated D1 passed templated challenge delivery through a mock, atomic one-use verification, revoked sessions, unsubscribed isolation and legacy-path regression. No real email or remote DB request.
- `npm run preview:email`: read-only loopback gallery, default port 5196. Browser interactions verified language/theme/width/display controls, Chinese light HTML, English dark HTML at 320px, Chinese image-blocked at 375px, delivery-test HTML and plain text. No clipped code or essential image-only content was observed. Preview theme forcing is explicitly a simulation.
- The existing public mark URL returned HTTP 200 with `image/png`. No unique image or click-tracking parameters were added.

Design self-assessment for the local template, not mailbox certification: **91/100** — hierarchy 19/20, typography 14/15, color 14/15, spacing 14/15, instruction clarity 9/10, accessibility 8/10, brand continuity 9/10, responsive 4/5. Dynamic interaction states are not applicable; instruction clarity replaces interaction feedback for email.

Three next checks: (1) separately authorize a branded test to QQ and inspect folder placement plus narrow-screen/dark rendering; (2) inspect Gmail/Outlook style stripping and forced inversion; (3) add event-specific templates only as corresponding real security/subscription services become available. Do not send just to raise a design score.

Email login stays disabled. No production deployment, credentials, identity roles, payments or SMS changed. Browser preview is not proof of rendering inside QQ, Gmail or Outlook, and template completion is not a production release. The candidate remains subject to exact-head CI and Datas PM review. Rollback is a normal revert of the template-only commit; no schema/data rollback is involved. The project rule file was checked in this session; discovery in a fresh session is not yet verified.
