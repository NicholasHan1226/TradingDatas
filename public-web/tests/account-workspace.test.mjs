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
  assert.match(appSource, /accountCurrentKey\?\.fingerprint/);
});

test("keeps unimplemented identity and commerce capabilities explicit", () => {
  assert.match(appSource, /另类数据加购尚未单独投影/);
  assert.match(appSource, /账单记录尚未接入/);
  assert.match(appSource, /邮箱、短信和跨设备会话尚未开放/);
  assert.doesNotMatch(appSource, /模拟订单号|mock invoice|verification code sent/i);
});

test("does not probe an account session from an anonymous public page", () => {
  assert.match(appSource, /TAB_ACCOUNT_TOKEN_KEY\) \? "direct" : "anonymous"/);
  assert.match(appSource, /accountAuthMode === "anonymous" \|\| \(accountAuthMode === "direct" && !accountToken\)/);
  assert.match(appSource, /if \(accountAuthMode === "anonymous"\) setAccountAuthMode\("session"\);/);
  assert.match(appSource, /setAccountAuthMode\("anonymous"\);/);
});

test("uses a lightweight responsive account presentation", () => {
  assert.match(styleSource, /\.account-plan-hero \{/);
  assert.match(styleSource, /\.account-usage-chart \{/);
  assert.match(styleSource, /\.account-security-panel/);
  assert.match(styleSource, /@media \(max-width: 720px\)[\s\S]*\.account-plan-hero/);
});
