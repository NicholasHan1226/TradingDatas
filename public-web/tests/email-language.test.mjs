import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { getSystemEmailLocale } from '../src/systemEmailLocale.js';

test('Chinese system locales select Chinese, other primary languages select English', () => {
  for (const language of ['zh', 'zh-CN', 'zh-Hans-CN', 'zh-Hant-TW', 'zh-HK', 'ZH-cn']) assert.equal(getSystemEmailLocale({language}), 'zh');
  for (const language of ['en', 'en-GB', 'fr-FR', 'ja-JP', '', undefined, 'not-zh']) assert.equal(getSystemEmailLocale({language}), 'en');
  assert.equal(getSystemEmailLocale({language:'en-US',languages:['en-US','zh-CN']}), 'en');
  assert.equal(getSystemEmailLocale({languages:['zh-TW','en']}), 'zh');
  assert.equal(getSystemEmailLocale(null), 'en');
});
test('initial send and resend resolve system language, not the selected website UI language', () => {
  const source = readFileSync(new URL('../src/EmailSignIn.jsx', import.meta.url),'utf8');
  assert.match(source, /locale: getSystemEmailLocale\(\)/);
  assert.match(source, /onClick=\{send\}/);
});
