import test from "node:test";
import assert from "node:assert/strict";
import {accountPath, accountSectionForRoute, isAccountRoute, privateAccountSections} from "../src/accountNavigation.js";
import {safeLoginDestination} from "../src/purchasePreview.js";
test("private deep links survive safe login return while public materials stay public", () => {
 for(const section of privateAccountSections) {
  const path=accountPath(section); assert.equal(isAccountRoute(path.slice(1)),true);
  assert.equal(accountSectionForRoute(path.slice(1)),section);
  assert.equal(safeLoginDestination(`?next=${encodeURIComponent(path)}`),path);
 }
 for(const [section,path] of [["bookmarks","/bookmarks"],["docs","/docs"],["agents","/connect"]]) {
  assert.equal(accountPath(section),path); assert.equal(isAccountRoute(path.slice(1)),false);
 }
});
test("login targets cannot carry credentials, another tenant, or an external redirect", () => {
 for(const target of ["/account/keys?token=secret","/account/keys#token","/account/../login","/account//keys","//evil.test/account","https://evil.test/account/keys","/account/keys/extra","/account/unknown"]) assert.equal(safeLoginDestination(`?next=${encodeURIComponent(target)}`),"/account");
});
