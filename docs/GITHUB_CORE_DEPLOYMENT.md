# GitHub-driven core production deployment

## Scope and authority

This document binds GitHub Actions to the existing TradingDatas safe-release contract. `docs/OPERATIONS.md` remains the production runbook and `tools/release_manifest.py` remains the release-byte/current-pointer authority.

This lane covers only the primary TradingDatas runtime:

- `/opt/investment/releases/tradingdatas/current`;
- `tradingdatas-v1-internal.service`;
- `tradingdatas-provider-native-collect.service`;
- `tradingdatas-provider-native-collect.timer`;
- loopback API `127.0.0.1:18082`.

It does **not** deploy or control `tradingdatas-crypto-*`, `/opt/investment/releases/tradingdatas-crypto`, Crypto SQLite, Crypto credentials, or Crypto timers. Crypto keeps its independent runtime/release authority and requires a separate future deployment lane.

The workflow changes immutable Git release bytes and the core `current` pointer only. It does not modify SQLite facts or receipts, rotate provider credentials, change registry activation, expand provider entitlement, install systemd units, or change provider budgets.

## Tested release artifact

`TradingDatas CI` freezes the candidate from a clean checkout before dependency installation or tests can create caches:

1. `tools/release_manifest.py build` creates a deterministic manifest for exact `GITHUB_SHA`;
2. `git archive` creates the exact tracked Git tree for the same SHA;
3. SHA-256 checksum files are created for archive and manifest;
4. dependency install, compile and full pytest then run;
5. only a successful `push` run on `main` uploads the already-frozen artifact.

PR CI performs the same package construction so packaging itself is tested before bootstrap changes merge. PR artifacts are not production-published.

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

`Deploy TradingDatas Core Production` is a downstream `workflow_run`. It is eligible only when:

1. `TradingDatas CI` succeeded;
2. the upstream event was `push`;
3. the tested branch was `main`;
4. repository variable `TRADINGDATAS_CORE_DEPLOY_ENABLED` is exactly `true`;
5. GitHub Environment `production-core` supplies the required secrets;
6. the artifact is downloaded from the exact successful upstream run ID;
7. archive and manifest checksums verify;
8. manifest commit equals `github.event.workflow_run.head_sha`;
9. the tested SHA is still current GitHub `main` before upload and again before privileged cutover;
10. the installed wrapper, Python implementation and verifier hashes exactly match the tested commit;
11. the server `current` pointer still equals the `expected_current` identity bound into the signed request.

The two GitHub-main checks prevent a slower successful CI run from an older multi-agent merge from rolling production backward. The signed-current check independently prevents replay and concurrent server-pointer drift.

## Independent deployment-request authority

The SSH deployment account is transport identity, not release authority. Possession of its SSH key plus permission to invoke the fixed sudo wrapper must not be enough to manufacture an arbitrary release.

A separate 256-bit HMAC key is held only in:

- GitHub `production-core` Environment Secret `DEPLOY_REQUEST_KEY`;
- server root-only `/etc/tradingdatas-deploy/core-release.hmac`.

Both contain the same 64 lowercase hexadecimal characters. The server file must be a single-link `root:root` regular file, mode `0400`, inside a `root:root` mode `0700` directory. The deployment SSH user must not be able to read it.

For every release GitHub first reads the server's relative `current` commit as `expected_current`, then signs this canonical ASCII payload using HMAC-SHA256:

```text
v1\n
<target-sha>\n
<archive-sha256>\n
<manifest-sha256>\n
<expected_current>\n
```

The transported request is one line:

```text
v1 <target-sha> <archive-sha256> <manifest-sha256> <expected_current> <hmac-sha256>
```

The root implementation independently reconstructs the payload and verifies the HMAC with `hmac.compare_digest`. It also requires real `current == expected_current` before target installation/cutover.

Therefore:

- a compromised deployment SSH account cannot forge a different target/archive/manifest request without the independent key;
- editing a request invalidates its signature;
- replay after `current` changes fails closed;
- concurrent pointer drift after signing fails closed;
- the HMAC key is never uploaded to the spool or sent to the server through SSH during normal deployment.

HMAC authorization never bypasses manifest verification, current-main gating, privileged-code hash pinning, service quiescence, readback, or rollback.

## Privileged code boundary

Ordinary production runs never upload privileged executable code. One-time bootstrap installs three root-owned files:

```text
/usr/local/sbin/tradingdatas-core-release
/usr/local/lib/tradingdatas-release/production_core_release.py
/usr/local/lib/tradingdatas-release/release_manifest.py
```

They correspond to tested repository files:

```text
tools/production_core_release_wrapper.sh
tools/production_core_release.py
tools/release_manifest.py
```

`production_core_release_wrapper.sh` is the **only** command permitted by the scoped sudo rule. The installed wrapper is root-owned mode `0755`; Python implementation and verifier are root-owned mode `0444`.

Before every ordinary deployment GitHub calculates all three SHA-256 values from the exact tested commit and requires the installed server copies to match. A PR that changes any of these files therefore cannot automatically deploy with stale privileged code: an approved server bootstrap from that commit must update/read back the trust boundary first.

### Isolated Python startup

The sudo wrapper does not rely on the implementation's shebang and does not execute ordinary venv startup behavior. It launches the fixed runtime as:

```text
python -I -S
```

using `/opt/tradingdatas/venv/bin/python3`.

`-I` isolates Python from user environment/current-directory import injection; `-S` prevents `site` startup and therefore prevents site-packages and `.pth` processing before privileged code runs. The wrapper then reads the root-only Python implementation and executes it with `sys.argv[0]` bound to the fixed installed wrapper identity.

Bootstrap also verifies the `/opt`/TradingDatas/venv interpreter directory chain is root-controlled, the resolved interpreter is root-owned and not group/world writable, and the fixed wrapper is `/bin/bash` based. The Python implementation and verifier use only the standard library.

This keeps the scoped sudo capability independent of application `site-packages` contents.

## Provision the HMAC authority

Generate the key on an authorized administrator terminal, never in chat or the repository. A server-side setup shape is:

```bash
sudo install -d -o root -g root -m 0700 /etc/tradingdatas-deploy
sudo sh -c 'umask 077; openssl rand -hex 32 > /etc/tradingdatas-deploy/core-release.hmac'
sudo chown root:root /etc/tradingdatas-deploy/core-release.hmac
sudo chmod 0400 /etc/tradingdatas-deploy/core-release.hmac
```

Verify locally that it is one 64-character lowercase-hex line. Add the exact same 64 characters directly to GitHub Environment Secret `DEPLOY_REQUEST_KEY`.

`tools/bootstrap_production_core_server.sh` validates but does not generate, rotate, display, or copy the key. Rotation is a separate authorized change performed while automatic deployment remains disabled.

## One-time server bootstrap

A dedicated non-root SSH deployment account must already exist and have an SSH-capable shell. From a trusted checkout of the approved commit, run as root:

```bash
sudo ./tools/bootstrap_production_core_server.sh <deploy-user>
```

Bootstrap is fail-closed. Before adding the sudo boundary it requires:

- trusted Python interpreter directories and resolved runtime are root-controlled;
- `/etc/tradingdatas-deploy` is `root:root` mode `0700`;
- `core-release.hmac` is a one-hardlink `root:root` mode `0400` file containing one valid 256-bit lower-hex key;
- `/opt/investment/releases/tradingdatas` already exists, is root-owned and not group/world writable;
- `current` is already normalized to a relative 40-character commit symlink;
- that immutable release exists;
- external manifest directory already exists and is root-controlled;
- `manifests/<current>.json` exists;
- the existing current release verifies successfully using the approved checkout's verifier **before** privileged files/sudoers are installed;
- deployment spool is empty.

If production still uses a legacy absolute `current`, do not normalize it implicitly here. Use the reviewed `normalize-current` procedure in `docs/OPERATIONS.md` while API/collector are inactive and timer disabled, verify current, then run bootstrap.

Bootstrap then:

1. installs root-only verifier and Python release implementation;
2. installs the isolated root wrapper;
3. re-verifies current using the installed verifier under isolated Python startup;
4. creates `/var/tmp/tradingdatas-core-deploy` as `0700` owned by the deployment user;
5. writes a sudoers entry allowing only `/usr/local/sbin/tradingdatas-core-release` as root;
6. validates sudoers with `visudo`;
7. prints only runtime paths and the three installed code hashes for readback.

It does not print/generate the HMAC key, create GitHub secrets, enable the deployment variable, modify provider credentials, touch SQLite, or enable/disable production units.

## GitHub configuration

Create Environment:

```text
production-core
```

Add Environment Secrets:

- `DEPLOY_HOST`;
- `DEPLOY_USER`;
- `DEPLOY_SSH_KEY`;
- `DEPLOY_KNOWN_HOSTS`;
- `DEPLOY_REQUEST_KEY` — the exact 64 lower-hex characters matching the root-only server key.

Do not disable SSH host-key checking and do not commit or send either private key through chat.

Create repository Actions variables:

- `TRADINGDATAS_CORE_DEPLOY_ENABLED=false` during bootstrap;
- optional `DEPLOY_PORT`, default `22`.

The enable variable is repository-level because the job-level `if:` gate is evaluated before Environment variables are available to a runner.

## Fixed spool and immutable target staging

The root implementation accepts no command-line arguments. After `.incoming` promotion, the spool must contain exactly:

```text
request
tradingdatas-core-<target-sha>.tar.gz
<target-sha>.release.json
```

The request/archive/manifest must be single-link regular files owned by the non-root sudo caller and not group/world writable. Archive/manifest are copied into root-owned temporary files before verification.

A new target archive may populate only a previously nonexistent SHA release. Archive paths/types must match the manifest exactly; unsafe/duplicate paths, links, devices/special members and extra files are rejected. The staged release is normalized to the existing TradingDatas contract:

- release directories `0555`;
- ordinary files `0444`;
- Git-executable files `0555`;
- `root:root` ownership;
- no extra cache, `.git`, or embedded release manifest.

The trusted verifier performs final exact content/Git-blob/mode verification. An existing SHA release is reused only when it independently passes the same verifier.

The target manifest remains outside the immutable release at:

```text
/opt/investment/releases/tradingdatas/manifests/<commit>.json
```

The previous current manifest/release is independently loaded and verified before production unit state changes.

## Safe-release order

For a real version change the root implementation preserves pre-deploy API/timer state and follows this order:

1. verify signed request and `current == expected_current`;
2. verify rollback and target manifests/releases;
3. disable/stop `tradingdatas-provider-native-collect.timer` so no new collector starts;
4. wait a bounded period for any already-running collector oneshot to finish naturally;
5. never force-stop an active collector during normal cutover;
6. if API was active, require loopback `GET /v1/catalog` to return expected unauthenticated `401`, then stop API;
7. require API inactive and `127.0.0.1:18082` closed;
8. use trusted controller `switch-current` from verified rollback manifest to verified target;
9. `verify-current` target;
10. if API was previously active, start it and bounded-wait `/v1/catalog` for `401`;
11. verify API `MainPID` cwd resolves to target immutable release;
12. restore timer to exactly its previous enabled/active state.

If API/timer were intentionally inactive/disabled, deployment does not enable them. This lane never starts/stops Crypto services or timers.

## Rollback

If failure occurs after pointer switch, rollback uses the same trusted controller:

1. disable/stop core collector timer;
2. wait collector inactive;
3. stop core API and require port 18082 closed;
4. switch back from target manifest to independently verified previous manifest;
5. verify previous current;
6. restore previous API state and bounded `/v1/catalog` readback;
7. restore previous timer state;
8. return non-zero so GitHub records deployment failure.

SQLite facts, receipts and provider data are never rolled back or deleted. A pre-switch failure restores observed runtime state without changing `current`.

## Failure evidence

Success removes the fixed request/archive/manifest from `/var/tmp/tradingdatas-core-deploy`.

A failed privileged request intentionally leaves those fixed files as incident evidence. The next automatic deployment requires an empty spool and therefore stops instead of overwriting evidence. An authorized operator must inspect/preserve required evidence and clear only those exact fixed files after the incident is resolved. Do not add generic recursive cleanup.

Files still named `.incoming` have not entered privileged authority. If GitHub `main` advances during upload, or server `current` changes after request signing but before cutover, the workflow removes only those exact `.incoming` files and performs no privileged release action.

## Verification after success

After root helper success GitHub independently reads:

```text
/opt/investment/releases/tradingdatas/current
```

and requires the relative target to equal the tested commit SHA.

Before returning success, the helper has already completed HMAC verification, signed-current verification, manifest `verify-current`, runtime-state restoration, API readback and process-cwd verification.

## Change control

Deployment trust-boundary files are:

```text
.github/workflows/ci.yml
.github/workflows/deploy-core-production.yml
tools/production_core_release_wrapper.sh
tools/production_core_release.py
tools/bootstrap_production_core_server.sh
tools/release_manifest.py
```

The HMAC key is runtime secret material and must never be committed. Changes to wrapper/implementation/verifier require approved server bootstrap/readback before automatic deployment resumes because installed hashes are pinned to the exact tested commit.

The existing automerge guard excludes `.github/workflows/` changes, so this bootstrap cannot self-merge through normal trusted-agent automerge. Ordinary application PRs may continue through existing CI/automerge; production remains separately gated by successful current-main CI, exact artifact identity, independent HMAC authorization, pinned privileged-code hashes and explicit deployment enable variable.
