// Presentation only: no recipients, network, secrets, permissions or delivery.
export const EMAIL_LOGO_URL = 'https://tradingdatas.com/assets/tradingdata-mark.png';
const FONT = "Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif";
const escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
const copy = {
  zh: {
    lang: 'zh-CN', purpose: '账户安全', codeLabel: '一次性验证码',
    subject: 'TradingDatas 登录验证码', title: '继续登录。',
    intro: '在登录页面输入下方验证码，继续访问你的 TradingDatas 账户。',
    preview: '使用邮件中的一次性验证码完成登录。',
    expiry: minutes => `${minutes} 分钟内有效 · 仅可使用一次`,
    safety: '请勿分享此验证码。TradingDatas 不会通过邮件或聊天向你索取验证码。若非本人操作，请忽略此邮件。',
    footer: '高质量、可追溯的金融数据。',
    testSubject: 'TradingDatas 邮件投递测试', testTitle: '一封测试邮件。',
    testPurpose: '邮件通道测试', testPreview: '仅用于检查邮件投递与模板显示，无需操作。',
    testIntro: '这封邮件仅用于检查 TradingDatas 的邮件投递与品牌模板显示。你无需进行任何操作。',
    testSafety: '此邮件不会登录账户，不含有效验证码，也不授予数据或管理员权限。',
  },
  en: {
    lang: 'en', purpose: 'ACCOUNT ACCESS', codeLabel: 'ONE-TIME CODE',
    subject: 'Your TradingDatas sign-in code', title: 'Your sign-in code.',
    intro: 'Enter the code below on the sign-in page to continue to your TradingDatas account.',
    preview: 'Use the one-time code in this email to complete sign-in.',
    expiry: minutes => `Valid for ${minutes} minutes · Can be used once`,
    safety: 'Do not share this code. TradingDatas will never ask you to send it by email or chat. If you did not request this, ignore this email.',
    footer: 'High-quality financial data, with provenance.',
    testSubject: 'TradingDatas email delivery test', testTitle: 'A small delivery check.',
    testPurpose: 'EMAIL DELIVERY TEST', testPreview: 'A delivery and template check only. No action needed.',
    testIntro: 'This email checks TradingDatas mail delivery and the appearance of our branded template. No action is needed.',
    testSafety: 'This email does not sign you in, contains no valid verification code, and does not grant data or administrator access.',
  },
};

// Critical light styles are inline. Dark styling is progressive enhancement;
// the data attribute is only set by the loopback preview, never by the sender.
const DARK_RULES = [
  ['.canvas', 'background-color:#08121e!important;'],
  ['.surface', 'background-color:#101e2d!important;border-color:#344555!important;'],
  ['.ink', 'color:#f1f5f7!important;'],
  ['.muted', 'color:#b4c1cd!important;'],
  ['.accent', 'color:#74d8ce!important;'],
  ['.code-panel', 'background-color:#172c47!important;border-color:#36557c!important;'],
  ['.code', 'color:#91b5ff!important;'],
  ['.rule', 'border-color:#344555!important;'],
];
const darkCss = prefix => DARK_RULES.map(([selector, style]) => `${prefix}${selector}{${style}}`).join('\n');

/** Render a named, authored template; do not accept arbitrary copy or links. */
export function renderEmail(options) {
  const {kind, locale = 'en', code, expiresInMinutes} = options;
  if (!['sign-in-code', 'delivery-test'].includes(kind)) throw new Error('unsupported_email_template');
  const signIn = kind === 'sign-in-code';
  const allowed = signIn ? ['kind', 'locale', 'code', 'expiresInMinutes'] : ['kind', 'locale'];
  if (Object.keys(options).some(key => !allowed.includes(key))) throw new Error('unsupported_template_parameter');
  if (signIn && (typeof code !== 'string' || code.length !== 8 || !/^[0-9]{8}$/.test(code) || !Number.isInteger(expiresInMinutes) || expiresInMinutes < 1 || expiresInMinutes > 60)) throw new Error('invalid_verification_content');
  const c = copy[locale === 'zh' || locale === 'zh-CN' ? 'zh' : 'en'];
  const subject = signIn ? c.subject : c.testSubject;
  const title = signIn ? c.title : c.testTitle;
  const purpose = signIn ? c.purpose : c.testPurpose;
  const intro = signIn ? c.intro : c.testIntro;
  const preview = signIn ? c.preview : c.testPreview;
  const safety = signIn ? c.safety : c.testSafety;
  const expiry = signIn ? c.expiry(expiresInMinutes) : '';
  const text = ['TradingDatas', title, intro, ...(signIn ? [c.codeLabel, code, expiry] : []), safety, c.footer, 'https://tradingdatas.com'].join('\n\n');
  const html = `<!doctype html>
<html lang="${c.lang}">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<title>${escapeHtml(subject)}</title>
<style>
  :root { color-scheme: light dark; supported-color-schemes: light dark; }
  @media (prefers-color-scheme: dark) { ${darkCss('')} }
  ${darkCss('html[data-preview-theme="dark"] ')}
  @media only screen and (max-width:480px) {
    .outer { padding:24px 12px!important; }
    .content { padding:28px 22px!important; }
    .title { font-size:26px!important; }
    .code { font-size:30px!important;letter-spacing:3px!important; }
  }
</style>
</head>
<body class="canvas" style="margin:0;padding:0;background-color:#f7f5f1;font-family:${FONT};color:#151917;-webkit-text-size-adjust:100%;">
<div class="preheader" style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">${escapeHtml(preview)}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" class="canvas" style="width:100%;background-color:#f7f5f1;">
<tr><td align="center" class="outer" style="padding:48px 20px;">
<!--[if mso]><table role="presentation" width="560" align="center"><tr><td><![endif]-->
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" class="surface" data-template="${kind}-v1" style="width:100%;max-width:560px;background-color:#fffdf9;border:1px solid #e3e5e1;border-radius:16px;">
<tr><td class="content" style="padding:36px 36px 32px;">
  <table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr>
    <td width="44" style="width:44px;vertical-align:middle;"><img src="${EMAIL_LOGO_URL}" alt="" width="32" height="32" style="display:block;border:0;width:32px;height:32px;"></td>
    <td class="ink" style="font-family:${FONT};font-size:23px;font-weight:600;letter-spacing:-0.8px;color:#151917;">TradingDatas</td>
  </tr></table>
  <p class="accent" style="margin:40px 0 12px;font-size:11px;font-weight:600;letter-spacing:1.4px;line-height:1.5;color:#087f85;">${escapeHtml(purpose)}</p>
  <h1 class="title ink" style="margin:0 0 16px;font-size:28px;line-height:1.25;letter-spacing:-0.7px;font-weight:600;color:#151917;">${escapeHtml(title)}</h1>
  <p class="muted" style="margin:0;font-size:16px;line-height:1.7;color:#616867;">${escapeHtml(intro)}</p>
  ${signIn ? `<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;margin-top:28px;"><tr><td class="code-panel" align="center" style="padding:22px 12px;background-color:#f0f4ff;border:1px solid #dce5ff;border-radius:10px;">
    <p class="muted" style="margin:0 0 10px;font-size:11px;line-height:1.5;letter-spacing:1px;color:#616867;">${escapeHtml(c.codeLabel)}</p>
    <p class="code" dir="ltr" style="margin:0;font-family:'Courier New',monospace;font-size:36px;font-weight:700;line-height:1.25;letter-spacing:4px;color:#064bff;white-space:nowrap;">${code}</p>
    <p class="muted" style="margin:12px 0 0;font-size:12px;line-height:1.7;color:#616867;">${escapeHtml(expiry)}</p>
  </td></tr></table>` : ''}
  <p class="muted" style="margin:24px 0 0;font-size:13px;line-height:1.8;color:#616867;">${escapeHtml(safety)}</p>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;margin-top:28px;"><tr><td class="rule" style="border-top:1px solid #e3e5e1;padding-top:22px;">
    <p class="muted" style="margin:0 0 6px;font-size:12px;line-height:1.7;color:#616867;">${escapeHtml(c.footer)}</p>
    <a class="muted" href="https://tradingdatas.com" style="color:#616867;font-size:12px;line-height:1.7;text-decoration:underline;text-underline-offset:3px;">tradingdatas.com</a>
  </td></tr></table>
</td></tr></table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table>
</body></html>`;
  return {subject, html, text};
}
