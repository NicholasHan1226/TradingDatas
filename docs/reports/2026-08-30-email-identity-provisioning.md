# Account-store preparation — 2026-08-30

Scope: owner-approved continuation of the existing Login/Account email identity.
This is isolated infrastructure preparation, not account activation or a public
website deployment. Source: live Wrangler/D1 readback and Resend domain readback.

## Exact target and preflight

- Cloudflare account: `1f049ae7407c623d20349e5a916b85d5`.
- Worker intended for a later reviewed release: `tradingdatas`.
- New database: `tradingdatas-identity-v1`.
- Database ID: `bb5e8d90-090f-40a5-9aa1-b91b33af7199`.
- Created: `2026-08-30T12:24:03.753Z` (20:24 CST).
- Requested location hint / observed region: APAC; observed serving colo HKG.
  This is not a legal data-residency guarantee. Read replication is disabled.
- Before creation, D1 listing had no TradingDatas DB. The unrelated `hovvi`
  resource was not modified. Before schema initialization, the new DB contained
  only Cloudflare's internal `_cf_KV` table and zero application tables.

The previously stopped authorization attempt was not bypassed. After the renewed
go-ahead, OAuth granted account/user read, Worker-script/D1 write and refresh access,
stored encrypted with its key in macOS Keychain. No global trust setting changed.
Wrangler 4.127.1 required command-scoped `NODE_EXTRA_CA_CERTS=/etc/ssl/cert.pem`
on this host; default/system-CA Node fetch failed issuer validation, whereas the
existing system PEM succeeded. Never use an insecure TLS override.

## Initialization and readback

Applied `public-web/worker/identity-schema.sql` only to the new exact database ID.
SHA-256: `7ad50489e30678931af094cb24a9c0c5d9624eb43daad8bc06d0912e6e14a4a7`.

Ten schema statements completed. Five application tables and four named expiry
indexes were read back; users, challenges, sessions, rate buckets and send cooldowns
all contained **zero rows**. `PRAGMA foreign_key_check` returned no violations.
No credentials, PII or synthetic accounts were written to this remote DB.

This was a one-time schema-file initialization, not a migration-ledger run.
Future schema changes require a reviewed migration and rollback plan; do not
blindly rerun the initializer against a populated database.

Read-only verification (run from `public-web/`, with the authorized account):

```bash
npx --yes wrangler@4.127.1 d1 info tradingdatas-identity-v1 --json
npx --yes wrangler@4.127.1 d1 execute bb5e8d90-090f-40a5-9aa1-b91b33af7199 --remote --command "SELECT name, type FROM sqlite_master WHERE name LIKE 'identity_%' ORDER BY type, name; PRAGMA foreign_key_check;" --json
```

## Candidate configuration and remaining gates

`public-web/wrangler.jsonc` declares this DB as `IDENTITY_DB` and pins
`EMAIL_LOGIN_ENABLED="false"`. The candidate contains no sender or pepper secret.
The new regression test verifies that even a complete secret set cannot override
the false flag: no send, user creation or reported email availability occurs.
Build output is unchanged; no visual redesign was made in this checkpoint.

Resend domain `account.tradingdatas.com`, DKIM, MX and SPF were verified again at
20:21 CST. Receiving/open/click tracking remain disabled. No Resend key was created,
no Worker secret was changed and no real mail was sent. Creating a sender key is
deferred until the reviewed release has a secure provisioning destination and an
explicit test recipient. Do not modify the unrelated existing Resend key.

Required before public activation:

1. Exact-head CI and Datas PM merge/release gate; the author must not self-approve.
2. Check deployment credential access to the new binding without replacing keys.
3. Approve identity retention/deletion/support ownership and abuse budgets.
4. Securely provision new domain-restricted sending secret and random pepper.
5. Deliver to an explicitly approved test inbox, then verify expiry/replay,
   session isolation/revocation and both existing-key/email paths in staging.
6. Authorize the exact-source public release and read back actual runtime behavior.

Payment, SMS, subscription grants, key linking and all financial-data collectors
remain outside this preparation. Resource creation does not satisfy these gates.

## Rollback and verification

Keep the account DB unbound and email disabled if the release does not proceed;
no existing service depends on this new resource. Do not delete the DB as automatic
cleanup. Once sessions exist, retain read/revoke support until expiry or explicit
revocation. No rollback may rotate existing customer keys or touch financial data.

Local checks: 85/85 public-web tests, production asset build, and local workerd/D1
atomic-code/isolation/revocation/legacy-redirect checks passed. All local outbound
email was intercepted. Remote checks cover schema only, not real sign-in or delivery.
Wrangler deployment dry-run passed with the exact D1 binding and false flag; it
did not upload or deploy code and does not prove deployment-token permissions.
The PR integration preserves both email work and main's unrelated collection records.
