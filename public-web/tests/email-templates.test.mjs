import test from 'node:test';
import assert from 'node:assert/strict';
import { renderEmail } from '../worker/email-templates.js';

for (const locale of ['zh', 'en']) {
  test(`sign-in template includes equivalent HTML and text in ${locale}`, () => {
    const mail = renderEmail({kind: 'sign-in-code', locale, code: '01234567', expiresInMinutes: 10});
    assert.deepEqual(Object.keys(mail).sort(), ['html', 'subject', 'text']);
    assert.match(mail.html, /data-template="sign-in-code-v1"/);
    assert.match(mail.html, /01234567/);
    assert.match(mail.text, /01234567/);
    assert.ok(!mail.subject.includes('01234567'));
    assert.ok(!mail.html.match(/<div class="preheader"[^>]*>(.*?)<\/div>/s)[1].includes('01234567'));
    for (const body of [mail.html, mail.text]) {
      assert.match(body, locale === 'zh' ? /10 分钟/ : /10 minutes/);
      assert.match(body, locale === 'zh' ? /仅可使用一次/ : /used once/);
      assert.match(body, locale === 'zh' ? /请勿分享/ : /Do not share/);
      assert.match(body, locale === 'zh' ? /忽略此邮件/ : /ignore this email/);
    }
    assert.match(mail.html, /lang="(?:zh-CN|en)"/);
    assert.match(mail.html, /prefers-color-scheme: dark/);
    assert.match(mail.html, /role="presentation"/);
    assert.match(mail.html, /TradingDatas/);
    assert.match(mail.html, /tradingdata-mark\.png/);
    assert.ok(Buffer.byteLength(mail.html) < 25000);
    assert.doesNotMatch(mail.html, /<script|<form|<iframe|@import|javascript:|tracking|<svg/i);
    assert.equal((mail.html.match(/<img /g) || []).length, 1);
    assert.equal((mail.html.match(/<h1[ >]/g) || []).length, 1);
  });
  test(`delivery-test template cannot be confused with login in ${locale}`, () => {
    const mail = renderEmail({kind: 'delivery-test', locale});
    assert.match(mail.html, /data-template="delivery-test-v1"/);
    for (const body of [mail.html, mail.text]) {
      assert.match(body, locale === 'zh' ? /不会登录账户/ : /does not sign you in/);
      assert.match(body, locale === 'zh' ? /不授予数据或管理员权限/ : /does not grant data or administrator access/);
      assert.doesNotMatch(body, /\b\d{8}\b/);
    }
  });
}

test('strict parameters reject arbitrary content, malformed codes and unsupported templates', () => {
  for (const code of ['<script>', '1234567', '123456789', 12345678, '1234567\n', '12345678\n']) {
    assert.throws(() => renderEmail({kind: 'sign-in-code', code, expiresInMinutes: 10}));
  }
  for (const expiresInMinutes of [undefined, 0, -1, 1.5, 61, '<img>']) {
    assert.throws(() => renderEmail({kind: 'sign-in-code', code: '01234567', expiresInMinutes}));
  }
  assert.throws(() => renderEmail({kind: 'arbitrary-message', html: '<script>'}));
  assert.throws(() => renderEmail({kind: 'delivery-test', code: '01234567'}));
  assert.throws(() => renderEmail({kind: 'delivery-test', subject: 'Injected subject'}));
});

test('language defaults safely and expiry copy is supplied by the challenge policy', () => {
  const mail = renderEmail({kind: 'sign-in-code', locale: '<img>', code: '98765432', expiresInMinutes: 5});
  assert.match(mail.html, /lang="en"/);
  assert.doesNotMatch(mail.html, /<img>/);
  assert.match(mail.text, /5 minutes/);
  assert.match(renderEmail({kind: 'delivery-test', locale: 'zh-CN'}).html, /lang="zh-CN"/);
});
