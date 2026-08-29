import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
const styleSource = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");

test("registers a dedicated login route backed by the existing account session", () => {
  assert.match(appSource, /"login", "account"/);
  assert.match(appSource, /primaryRoute === "login"/);
  assert.match(appSource, /onSubmit=\{connectAccount\}/);
  assert.match(appSource, /window\.history\.replaceState\(\{\}, "", "\/account"\)/);
});

test("keeps unavailable identity methods explicit and sends signed-out account actions to login", () => {
  assert.match(appSource, /邮箱与短信登录尚未开放/);
  assert.match(appSource, /goTo\("\/login"\)/);
  assert.doesNotMatch(appSource, /忘记密码|Forgot password/);
});

test("provides responsive and dark-compatible login presentation", () => {
  assert.match(styleSource, /\.login-page \{/);
  assert.match(styleSource, /:root\[data-theme="dark"\] \.login-panel/);
  assert.match(styleSource, /@media \(max-width: 720px\)[\s\S]*\.login-page/);
});
