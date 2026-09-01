# Consumer compatibility and collection release preflight

Observed at 2026-08-30 14:54–15:00 CST. This is a source/release task record,
not a declaration of complete history or stable production.

## Authorization and frozen starting points

Nicholas explicitly selected the Datas PM flow without Controller acceptance,
then authorized all four follow-ups: three read-only consumer adaptations,
controlled release/recollection, minute provider-time/progress correction, and
financial partition continuation. This does not activate CNFutures, trading,
new services, new providers, higher transport budgets, or destructive data work.
The superseded Controller hold in the earlier dated recovery report is closed
by this decision and PR #393 comments.

- TD main: `4ef956544fc9eb50584b0bfa00fcf83e5e12711c`, PR #393;
  exact-main CI `33297146774` passed all four fast shards (2,108 passed,
  1 skipped). The withdrawn daily-cursor proposal is absent.
- Initial TA main: `474700918ef6096320ef62857aab58242bbeb650`.
  Changes remain separate from TD integration.
- A-share installed release: `385a4fa4fb461fd1e276e5cfd6577dbcb0758b3d`;
  trusted verifier confirmed all 392 files and tree
  `e39fb8d3e89832857a8fa2c6cb44510174e6da45`.
- Crypto installed release: `15f463eee602e919244678985622adfedfea1189`;
  no Crypto release switch is part of the three schema fixes.

The active SSH alias is `marketgraph-main`, root at the Guangzhou host documented
in `Finance/PRODUCTION_ACCESS.md`. The older `marketgraph-root` alias in
OPERATIONS is not configured on this client; no SSH identity or credentials
were changed. Use the documented existing identity with strict host-key checking.

## Fresh baseline and observed compatibility gaps

Authenticated catalog at 14:54: A-share 192 datasets: 87 success, 43 empty,
57 paused, 4 unobserved, and 1 stale (`rt_min_daily`). Crypto had 240 success.
The two internal API services and A-share collector timer were active. The
collector was allowed to finish naturally; no process was killed.

The `fut_basic` major-1 `fut_code=M` query, bounded to five 100-row pages, returned
415 persisted rows and 208 distinct `ts_code` values, all DCE. Quality remained
degraded for missing `trade_time_desc`; receipt lineage was complete. This is
not compatible with the old TA reader's frozen 207-row partial cohort. Preserve
old facts; do not deduplicate the response silently or loosen the old contract.
The major-2 consumer requires an explicit, separately tested bounded contract,
actual counts, unique identity, valid quality, replay and receipt lineage, while
keeping PIT/runtime/trading authority false. Its exact real count remains to be
verified after recollection.

Broker's catalog identity is `[month, broker, ts_code, name]`; native YYYYMM
must remain month precision, not a fabricated daily publication timestamp.
The wire catalog does not publish an `as_of_field` attribute. Consumer as-of
behavior must follow the frozen registry/query contract and existing source
proof, not a missing top-level JSON key. Minute major-2 compatibility must bind
the actual query identity and must not synthesize a response `freq` field.

## Release procedure and stop conditions

1. Freeze reviewed TD/TA candidates, run meaningful negative regressions and
   independent review, integrate through PRs, and validate actual merged SHAs.
2. Build archive and manifest from a clean exact-main checkout. Stage only into
   new immutable directories; verify target and rollback with the installed
   trusted verifier. A local package alone is not a deployment.
3. Validate nonzero bounded plans with the target registry. Keep broker July and
   August in separate manifests because each manifest requires unique dataset
   IDs. Preserve all six `fut_basic` exchange variants.
4. Pause the original timer and drain its service; do not kill the collector.
   Stop the affected API, atomically switch verified `current`, restore API and
   wait for bounded authentication/listener readiness. Use the same installed
   service, lock and private one-shot selector for authorized recollection.
5. Read back real facts/receipts, authenticated catalog/query and relevant
   read-only consumers. Unsupported old major requests must fail closed;
   unaffected datasets must retain their matching active-config receipts.
6. Restore the original timer and verify selector cleanup, release integrity,
   service state and natural rounds. On a release-induced integrity, service or
   data failure, switch to the verified previous immutable release; keep all
   new facts/receipts and do not change credentials or database history.

Sunday cannot prove a fresh Monday minute response or closing coverage. Source
tests and controlled readbacks must retain that gap. Financial continuation must
preserve the actual requested partition and explicit coverage debt; constant
daily capacity below incoming work cannot support an eventual-full promise.

## Current delivery state

At 15:19 CST, TA PR #609 merged as
`eb4699164b84e622d05c70be0e5535f18a934862`, tree-identical to reviewed candidate
`e883f6f353ccd3284c0ee1559f6e28a19b6da2fa`. Candidate CI `33298567303` passed
6,036 Python tests plus 266 subtests (one skipped), and 361 frontend tests.
Parent independent targeted verification passed 169 tests. Exact-main CI
`33298942543` also passed. No TA trading runtime was switched.

The major-2 maintenance script is outside the repository at
`work/collection-progress-20260830/release_major2.py`, SHA256
`92b769901d7cf7e9da17456f092952e7cb0fe59a0a867aa1b6b7c5f83c92ba2e`.
Independent review closed the maintenance/recovery defects and verified the
July historical-partition check: if stale, reasons and quality evidence must
be exactly `freshness_sla_exceeded`; stale July is not a schema defect and does
not justify an automatic rollback. August and futures still require non-stale,
valid quality. The script alone provides sample readback, not full acceptance.

At 15:27 CST the verified TD `4ef9565` release was switched and the original
timer restored active. The API remained active after the maintenance window;
selector cleanup and trusted manifest verification passed. No provider process
was killed. Eight new successful receipts, independently validated from SQLite
under the existing service owner, recorded 11,740 inserted rows and no rejects:
308 July broker rows, 236 August broker rows, and 11,196 futures rows across
all six exchange variants. Authenticated complete pagination at 15:28 returned
these same counts with unique identities; August/futures were valid, fresh and
lineage-complete, while July had only the expected historical freshness debt.
Five unaffected datasets still returned valid complete samples. Old broker and
futures major-1 requests returned HTTP 400 `invalid_request`, each with a
successful current-major control request.

Real TA consumer acceptance remains pending at this checkpoint. The first
helper attempt used the diagnostic token path and was correctly rejected by
the TA service-secret-root policy before network access. The existing
`/run/secrets/tradingagent/` token and its existing service owner were then used
without copying, changing permissions or modifying credentials. The readers
still rejected the real response contract and are being diagnosed; generic
API success must not be called consumer success.
