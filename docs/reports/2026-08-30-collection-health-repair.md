# 2026-08-30 collection health repair

## Scope and evidence

Nicholas requested repair after the 10:45–10:47 CST production inspection. Work is
isolated from the dirty canonical checkout on `fix/collection-health-20260830`,
frozen base `97c814bef2014c6419a189de5faedfba12145a2c`. No account, credential,
provider activation, trading, database deletion, history rewrite, or notification
is authorized by this patch.

Fresh server observations at 11:02–11:11 CST:

- A-share effective release is `79c33f906cf3294ce4fa8a33bb54e4ce2417761c`;
  the trusted release verifier passed before the bounded news diagnosis.
  Crypto effective release is `15f463eee602e919244678985622adfedfea1189`.
- Funding-rate and Polymarket failures share the existing Singapore relay.
  `sg-relay-tunnel.service` repeatedly times out connecting to its configured
  host, despite systemd briefly reporting active while SSH is still connecting.
  The SOCKS listener is absent. A bounded connection attempt also timed out.
  The configured instance was not found in the accessible cloud account's
  checked regions; no key, host, firewall, or alternate route was changed.
- The most recent Polymarket successful capture was observed at
  `2026-08-28T15:38:44Z`. Six newer failed receipts must not refresh that success.
  Candidate read-only inspection of the live files returned ALERT with
  `last_success_age_h=35.5`, `failed_in_last_6=6`, and zero malformed files.
- The installed patrol exits 1 on an ALERT by design. Its separate TA rolling
  evaluation warning is outside this TD repair. Clearing failed unit state or
  fabricating evaluation output would not repair the data.
- A-share/news ingestion continues writing valid receipts. A lock-protected,
  three-call, no-database-write news diagnosis returned one empty outcome and
  two provider errors. These external errors are not fixed by the code below.
- Income/pledge-stat failed receipts remain from interrupted 2026-08-26 fanout.
  Main already includes #378's bounded resumable scheduling; the old effective
  release has not yet received it. New receipts and authenticated reads are
  required after an approved exact-main release before claiming recovery.

## Reproduced defects and changes

1. Valid event pages containing only pre-window rows pass completeness validation,
   but filtering leaves an empty array that the non-empty store rejects. For
   `empty_data_policy=allowed`, write a terminal empty receipt with null watermark
   and aggregate all-empty physical calls as empty. Mixed calls preserve current
   facts; future rows, duplicate keys, provider errors, and forbidden-empty
   contracts remain fail-closed. This repairs a reproduced failure path, not all
   possible Firecrawl errors; the exact payload of historical failed calls was
   not retained.
2. CN minute/postclose data covering Friday was marked stale on Sunday. Freeze
   only these two regular market cadences at the last Friday close over Saturday
   and Sunday; missing Friday data remains stale. No holiday calendar is invented,
   and events, reference datasets, Crypto, and Monday retain their existing rules.
3. A `YYYYMM` watermark used the first day of the month as its freshness reference.
   Use the last instant of the month, preserving the original data watermark.
4. Bring the existing patrol into version control and replace only its Polymarket
   section. Use successful capture timestamps and consistent nonempty row counts,
   deduplicate receipts, detect invalid records, and avoid simultaneous WARN/OK.
   The other installed checks are preserved. Installed baseline SHA-256:
   `b77c77ef760b38dbc6ab047411bc8e85e47a8198cdb99e6f0f8d0e2c670a773d`.

## Validation and release boundary

The initial regression run reproduced four failures: allowed old-only news pages,
Friday minute data on Sunday, Friday daily data on Sunday, and month watermarks.
The targeted regression set subsequently passed, including forbidden empty,
future data, missing Friday data, Crypto/Monday gaps, and patrol failure receipts.
A mixed fanout test also confirms one empty source cannot discard another source's
current facts. The adjacent ingestion/projection/provider suites are recorded in
the PR verification results; source syntax, shell syntax and diff checks passed.

M1 requires current-head Controller acceptance and exact-head CI before merge,
and exact-main CI plus release/rollback manifest checks before runtime cutover.
The production release and patrol installation are pending those gates at this
report's creation. No production recovery is claimed here.

Rollback restores the verified previous immutable pointer, with no deletion or
rewriting of facts/receipts. The patrol rollback restores a newly retained backup
of the exact installed script; it changes neither timer cadence nor log history.
The existing main scheduling/WAL/rt-min changes must be assessed as part of the
whole target release, not inferred safe solely from this small patch's tests.

## Next verification

- Restore the existing relay through its verified owner/control-plane access;
  then observe natural funding-rate/Polymarket receipts and authenticated API
  state separately. Do not replace the relay or relax host-key/TLS checks.
- After approved release, observe naturally scheduled news receipts and
  income/pledge-stat resumable progress; do not trigger an unbounded full fanout.
- Query CN minute/month datasets on the weekend and confirm old/missing data and
  external provider failures remain degraded.
- Read the updated patrol verdict; TD recovery does not clear unrelated TA alerts.
