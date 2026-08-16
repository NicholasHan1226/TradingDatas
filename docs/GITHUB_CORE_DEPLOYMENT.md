# GitHub-driven core production deployment

## Scope and authority

This document binds GitHub Actions to the existing TradingDatas safe-release contract. `docs/OPERATIONS.md` remains the production runbook and `tools/release_manifest.py` remains the release-byte/current-pointer authority.

This lane covers only the primary TradingDatas runtime:

- `/opt/investment/releases/tradingdatas/current`;
- `tradingdatas-v1-internal.service`;
- `tradingdatas-provider-native-collect.service`;
- `tradingdatas-provider-native-collect.timer`;
- the loopback API on `127.0.0.1:18082`.

It does **not** deploy or control `tradingdatas-crypto-*`, `/opt/investment/releases/tradingdatas-crypto`, Crypto SQLite, Crypto credentials, or Crypto timers. Crypto keeps its separate release/runtime authority and requires its own future deployment lane.

The workflow changes Git release bytes and the core `current` pointer only. It does not modify SQLite facts or receipts, rotate credentials, change registry activation, expand provider entitlement, install systemd units, or change provider budgets.

## CI release candidate

`TradingDatas CI` freezes the deployable candidate from the clean checkout before tests can create local caches or other untracked files:

1. `tools/release_manifest.py build` creates a deterministic manifest for the exact `GITHUB_SHA`;
2. `git archive` creates the exact tracked Git tree for the same SHA;
3. SHA-256 checksum files are created for both archive and manifest;
4. the normal dependency installation, compile step and full test suite run;
5. only a successful `push` run on `main` uploads the previously frozen artifact.

PR CI performs the same manifest/archive construction so release packaging is tested before bootstrap changes can merge. PR artifacts are not production-published.

The uploaded artifact is named:

```text
tradingdatas-core-release-<40-char-git-sha>
```

and contains:

```text
tradingdatas-core-<sha>.tar.gz
tradingdatas-core-<sha>.tar.gz.sha256
<sha>.release.json
<sha>.release.json.sha256
```

## Production workflow gate

`Deploy TradingDatas Core Production` runs from `workflow_run` only when:

1. `TradingDatas CI` concluded successfully;
2. the upstream event was `push`;
3. the tested branch was `main`;
4. repository variable `TRADINGDATAS_CORE_DEPLOY_ENABLED` is exactly `true`;
5. the `production-core` Environment supplies the SSH secrets;
6. the exact artifact from the successful upstream workflow-run ID exists and its checksums are valid;
7. the manifest commit equals `github.event.workflow_run.head_sha`;
8. that tested SHA is still current GitHub `main` immediately before upload and again immediately before privileged cutover;
9. the installed production helper and trusted release verifier hashes equal the versions in the tested commit.

The two `main` checks prevent a slower successful CI run from an older multi-agent merge from rolling production backward after a newer commit reaches `main`.

## Trusted helper and verifier

Ordinary deployment runs never upload a new privileged helper or execute release verification code from the unverified target release.

One-time server bootstrap installs:

```text
/usr/local/sbin/tradingdatas-core-release
/usr/local/lib/tradingdatas-release/release_manifest.py
```

Both are root-owned. The release helper receives a scoped passwordless sudo rule; the verifier remains read-only trusted code outside all target releases.

Before every ordinary deployment, GitHub calculates the SHA-256 of:

```text
tools/production_core_release.py
tools/release_manifest.py
```

from the exact tested commit and requires the installed server copies to have the same hashes. Therefore a PR that changes either trust-boundary file cannot silently deploy with stale or unreviewed privileged code. Such a change requires a new trusted server bootstrap from the approved commit before automatic deployment can resume.

The deployment SSH account does not receive a general root shell or wildcard `systemctl` sudo rule.

## One-time server bootstrap

A dedicated non-root SSH deployment account must already exist and have an SSH-capable shell. From a trusted checkout of the approved commit, run as root:

```bash
sudo ./tools/bootstrap_production_core_server.sh <deploy-user>
```

Bootstrap is fail-closed. Before installing the automation trust boundary it requires:

- `/opt/investment/releases/tradingdatas` already exists, is root-owned and not group/world writable;
- `current` is already normalized to a relative 40-character commit symlink;
- that immutable release exists;
- the external rollback manifest already exists at `manifests/<current>.json`;
- the existing `current` release verifies successfully with UID/GID `0` using the trusted verifier;
- the deployment spool is empty.

If production still has the documented legacy absolute `current` pointer, do **not** make this bootstrap normalize it implicitly. Perform the existing reviewed `normalize-current` procedure from `docs/OPERATIONS.md` while API/collector are inactive and the timer is disabled, verify the normalized current release, then run this bootstrap.

Bootstrap then:

1. installs the trusted verifier outside the release tree;
2. installs the fixed root helper;
3. creates `/var/tmp/tradingdatas-core-deploy` as `0700` owned by the deployment SSH account;
4. writes a sudoers entry allowing only `/usr/local/sbin/tradingdatas-core-release` as root;
5. validates the sudoers entry with `visudo`;
6. prints the installed helper/verifier SHA-256 values for readback.

Bootstrap does not create GitHub secrets, enable the GitHub deployment variable, modify credentials, touch SQLite, or enable/disable production units.

## GitHub configuration

Create a GitHub Environment named:

```text
production-core
```

Add Environment Secrets:

- `DEPLOY_HOST` — production server hostname or IP;
- `DEPLOY_USER` — the same dedicated deployment account used during bootstrap;
- `DEPLOY_SSH_KEY` — private key for only that deployment account;
- `DEPLOY_KNOWN_HOSTS` — pinned SSH host-key entry for the production server.

Do not disable SSH host-key checking and do not commit the private key or host secrets.

Create repository Actions variables:

- `TRADINGDATAS_CORE_DEPLOY_ENABLED=false` during bootstrap;
- optional `DEPLOY_PORT`, default `22`.

The enable variable is repository-level because the job-level `if:` gate is evaluated before Environment variables are available to a runner.

## Immutable target staging

The root helper reads one fixed spool request:

```text
<commit> <archive-sha256> <manifest-sha256>
```

It accepts no command-line arguments. Uploaded files must be single-link regular files owned by the non-root sudo caller and not group/world writable. The helper copies them into root-owned temporary files before using them as release authority inputs.

The trusted verifier validates the target manifest. A new target archive is then staged only into a previously nonexistent SHA-named directory. Archive paths/types must match the manifest exactly; links and special members are rejected. The staged release is normalized to the existing TradingDatas contract:

- release root/directories `0555`;
- ordinary files `0444`;
- Git-executable files `0555`;
- owner/group `root:root`;
- no extra file, `.git`, cache or manifest embedded inside the release.

The trusted verifier performs the final exact content/Git-blob/mode verification. An existing SHA release is reused only if it independently passes the same verifier.

The target manifest is stored outside the release at:

```text
/opt/investment/releases/tradingdatas/manifests/<commit>.json
```

The previous `current` manifest is loaded and the previous release is verified before any production unit state changes.

## Safe-release order

For a real version change, the root helper preserves the pre-deploy API/timer state and follows this order:

1. disable and stop `tradingdatas-provider-native-collect.timer` so no new collection run can start;
2. wait a bounded time for any already-running `tradingdatas-provider-native-collect.service` oneshot to finish naturally;
3. never force-stop an active collector during normal cutover;
4. if the API was active, first prove loopback `GET /v1/catalog` returns the expected unauthenticated `401`, then stop the API;
5. require the API inactive and port `127.0.0.1:18082` closed;
6. use the trusted verifier/controller to atomically `switch-current` from the independently verified rollback manifest to the verified target manifest;
7. run `verify-current` for the target;
8. if the API was active before release, start it and bounded-wait `/v1/catalog` until it returns `401`;
9. verify the API `MainPID` working directory resolves to the target immutable release;
10. restore the timer to exactly its previous enabled/active state.

If the API was intentionally inactive before release, deployment does not start it. If the timer was intentionally disabled/inactive, deployment does not enable it.

This lane never starts or stops Crypto services/timers.

## Rollback

The previous release and external manifest are frozen and independently verified before cutover.

If failure occurs after `current` has switched, rollback uses the same trusted controller:

1. disable/stop the core collector timer;
2. wait for any collector run to become inactive;
3. stop the core API and require port 18082 closed;
4. `switch-current` back from the target manifest to the previous manifest;
5. `verify-current` on the previous release;
6. restore the previous API state and bounded `/v1/catalog` readback;
7. restore the previous timer enabled/active state;
8. return non-zero so GitHub records the deployment failure.

SQLite facts, receipts and provider data are not rolled back or deleted.

A failure before pointer cutover restores the previously observed API/timer state without changing `current`.

## Failure evidence and spool policy

Successful deployment removes the fixed request/archive/manifest from `/var/tmp/tradingdatas-core-deploy`.

A failed privileged deployment intentionally leaves the uploaded fixed request/archive/manifest in the spool as incident evidence. The next automatic deployment requires an empty spool and therefore stops rather than overwriting that evidence. An authorized operator must inspect the failed deployment, preserve any required evidence, and clear only those exact fixed files after the incident is resolved. Do not add generic recursive cleanup to the workflow or root helper.

Files that are still only `.incoming` have not entered the privileged request. If GitHub `main` advances during upload, the workflow removes only those exact `.incoming` files and skips cutover.

## Verification after success

After the root helper returns success, GitHub independently reads:

```text
/opt/investment/releases/tradingdatas/current
```

and requires the relative symlink target to equal the tested commit SHA.

The helper itself has already performed manifest `verify-current`, service state restoration, loopback API readback and process working-directory verification before returning success.

## Change control

Changes to any of these are deployment trust-boundary changes:

```text
.github/workflows/ci.yml
.github/workflows/deploy-core-production.yml
tools/production_core_release.py
tools/bootstrap_production_core_server.sh
tools/release_manifest.py
```

The existing automerge guard excludes `.github/workflows/` changes, so this initial workflow bootstrap cannot self-merge through the normal trusted-agent automerge route.

Ordinary application PRs may continue through the existing CI/automerge path. Production remains separately gated by successful current-`main` CI, exact release artifact identity, pinned server trust-boundary hashes and the explicit repository deployment enable variable.
