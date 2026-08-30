import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
const styleSource = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
const loginSource = await readFile(new URL("../src/LoginPage.jsx", import.meta.url), "utf8");
const sessionSource = await readFile(new URL("../src/accountSession.js", import.meta.url), "utf8");

test("registers a dedicated login route backed by the existing account session", () => {
  assert.match(appSource, /"login", "account"/);
  assert.match(appSource, /primaryRoute === "login"/);
  assert.match(appSource, /onSubmit=\{connectAccount\}/);
  assert.match(appSource, /window\.history\.replaceState\(\{\}, "", "\/account"\)/);
});

test("requires the same-site gateway and retires browser bearer storage", () => {
  assert.match(appSource, /await startAccountSession\(token\)/);
  assert.match(sessionSource, /credentials: "same-origin"/);
  assert.doesNotMatch(appSource, /sessionStorage\.setItem|Authorization: `Bearer/);
  assert.match(appSource, /localStorage\.removeItem\(LEGACY_ACCOUNT_TOKEN_KEY\)/);
  assert.doesNotMatch(appSource, /localStorage\.setItem\(LEGACY_ACCOUNT_TOKEN_KEY/);
});

test("keeps unavailable identity methods explicit and sends signed-out account actions to login", () => {
  assert.match(loginSource, /邮箱与短信登录尚未开放/);
  assert.match(loginSource, /aria-pressed/);
  assert.match(loginSource, /不会收集你的联系方式或发送验证码/);
  assert.match(appSource, /goTo\("\/login"\)/);
  assert.doesNotMatch(appSource, /忘记密码|Forgot password/);
});

test("provides responsive and dark-compatible login presentation", () => {
  assert.match(styleSource, /\.login-page \{/);
  assert.match(styleSource, /:root\[data-theme="dark"\] \.login-panel/);
  assert.match(styleSource, /@media \(max-width: 720px\)[\s\S]*\.login-page/);
});
