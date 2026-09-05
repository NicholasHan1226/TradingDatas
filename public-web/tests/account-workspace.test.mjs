import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
const styleSource = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");

test("renders authenticated plan, usage, and security sections from portal data", () => {
  assert.match(appSource, /accountSection === "subscription"/);
  assert.match(appSource, /accountSection === "usage"/);
  assert.match(appSource, /accountSection === "security"/);
  assert.match(appSource, /accountUsage\?\.history/);
  assert.match(appSource, /accountData\.minute_request_limit/);
  assert.match(appSource, /HttpOnly same-site session/);
});

test("keeps unimplemented identity and commerce capabilities explicit", () => {
  assert.match(appSource, /另类数据加购尚未单独投影/);
  assert.match(appSource, /<AccountCommerce[\s\S]*section="billing"/);
  assert.match(appSource, /凭证绑定与跨设备会话列表尚未开放/);
  assert.match(appSource, /短信服务暂未接入/);
  assert.doesNotMatch(appSource, /模拟订单号|mock invoice|verification code sent/i);
});

test("defers anonymous session resolution until an Account intent", () => {
  assert.match(appSource, /const \[accountSessionRequested, setAccountSessionRequested\] = useState\(\(\) => \(isAccountRoute\(route\) \|\| route === "login"\)\)/);
  assert.match(appSource, /if \(!accountSessionRequested\) \{[\s\S]*clearAccountView\(\)[\s\S]*return undefined/);
  assert.match(appSource, /if \(\(isAccountRoute\(route\) \|\| route === "login"\)\) setAccountSessionRequested\(true\)/);
  assert.match(appSource, /\}, \[accountConnectionRevision, accountSessionRequested\]\);/);
});

test("uses a lightweight responsive account presentation", () => {
  assert.match(styleSource, /\.account-plan-hero \{/);
  assert.match(styleSource, /\.account-usage-chart \{/);
  assert.match(styleSource, /\.account-security-panel/);
  assert.match(styleSource, /@media \(max-width: 720px\)[\s\S]*\.account-plan-hero/);
});

test("all logout entry points share a guarded confirmation and visible retry state", () => {
  const handler = appSource.slice(appSource.indexOf("async function disconnectAccount()"), appSource.indexOf("async function createAccountKey("));
  assert.match(handler, /if \(accountSignOutInFlight\.current\) return/);
  assert.ok(handler.indexOf("await confirmAccountSignOut(fetch, 10_000, accountData?.user_id || \"\")") < handler.indexOf("clearAccountView()"));
  assert.match(handler, /error\.message === "identity_changed"/);
  assert.match(handler, /requestAccountProjectionRefresh/);
  assert.equal((appSource.match(/onClick=\{disconnectAccount\} disabled=\{accountSignOutPending\}/g) || []).length, 3);
  assert.match(appSource, /role=\{accountSignOutError \? "alert" : "status"\}/);
  assert.match(appSource, /未能确认退出，会话可能仍然有效/);
  assert.match(appSource, /Sign-out could not be confirmed/);
});

test("a visibility refresh deferred by account work is drained after the last operation", () => {
  assert.match(appSource, /const accountVisibilityRefreshPending = useRef\(false\)/);
  const settle = appSource.slice(appSource.indexOf("function settleAccountOperation("), appSource.indexOf("function clearAccountView()"));
  assert.match(settle, /operation\.current = false/);
  assert.match(settle, /accountLoginInFlight\.current \|\| accountSignOutInFlight\.current \|\| accountKeyInFlight\.current/);
  assert.match(settle, /requestAccountProjectionRefresh\(\)/);
  const visibility = appSource.slice(appSource.indexOf("// Recheck after returning to the page"), appSource.indexOf("  }, []);", appSource.indexOf("// Recheck after returning to the page")));
  assert.match(visibility, /accountVisibilityRefreshPending\.current = true/);
  assert.match(visibility, /requestAccountProjectionRefresh\(\)/);
  assert.equal((appSource.match(/settleAccountOperation\(accountLoginInFlight\)/g) || []).length, 3);
  assert.equal((appSource.match(/settleAccountOperation\(accountSignOutInFlight\)/g) || []).length, 2);
  assert.equal((appSource.match(/settleAccountOperation\(accountKeyInFlight\)/g) || []).length, 2);
  assert.match(appSource, /function handleAccountIdentityChanged\(\)[\s\S]*clearAccountView\(\)[\s\S]*requestAccountProjectionRefresh\(\)/);
});

test("late reads and key mutations cannot restore a previous account", () => {
  assert.match(appSource, /accountEpoch\.current \+= 1/);
  assert.match(appSource, /accountReadAbort\.current\?\.abort\(\)/);
  // Includes the independent email login path in addition to the five legacy guards.
  assert.equal((appSource.match(/if \(accountEpoch\.current !== epoch\) return/g) || []).length, 6);
  assert.match(appSource, /if \(!current\(\)\) return/);
  assert.match(appSource, /用量暂时无法加载，你仍然处于登录状态/);
});

test("identity refresh clears sensitive projections before adopting a shared session", () => {
  const refresh = appSource.slice(appSource.indexOf("    clearLegacyAccountToken();\n"), appSource.indexOf("  }, [accountConnectionRevision, accountSessionRequested]);"));
  const clear = appSource.slice(appSource.indexOf("  function clearAccountView()"), appSource.indexOf("  async function deleteEmailProfile()"));
  assert.ok(refresh.indexOf("clearAccountView()") < refresh.indexOf("const epoch = accountEpoch.current"));
  assert.ok(refresh.indexOf("clearAccountView()") < refresh.indexOf("readAccountIdentity("));
  assert.match(clear, /accountEpoch\.current \+= 1/);
  for (const setter of ["setAccountData(null)", "setAccountUsage(null)", "setAccountKeys([])", 'setAccountNewKey("")', 'setAccountKeyLabel("")']) assert.ok(clear.includes(setter), setter);
});

test("private panels wait for identity instead of flashing a sign-in prompt", () => {
  assert.match(appSource, /getAccountViewState\(\{ loading: accountLoading, account: accountData, error: accountError \}\)/);
  assert.match(appSource, /accountPrivateSection && accountChecking/);
  assert.match(appSource, /accountPrivateSection && accountViewState === "unavailable" \? null/);
  assert.match(appSource, /disabled=\{accountChecking\} aria-busy=\{accountChecking\}/);
  assert.match(appSource, /No need to sign in again/);
  assert.match(appSource, /accountViewState === "unavailable" && <div className="account-signout-feedback" role="alert"/);
});

test("account design does not reintroduce the retired browser credential fallback", async () => {
  const contract = await readFile(new URL("../../docs/design/account-admin-convergence-v1.md", import.meta.url), "utf8");
  assert.match(contract, /There is no direct-bearer or browser-storage fallback/);
  assert.doesNotMatch(contract, /compatibility path (keeps|is|remains|still clears)|falls back only to the current tab/);
});
