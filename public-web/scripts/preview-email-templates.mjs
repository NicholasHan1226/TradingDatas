// Loopback-only visual fixture. No provider, credentials, users or send route.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { renderEmail, EMAIL_LOGO_URL } from '../worker/email-templates.js';

const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const choices = {
  kind: [['sign-in-code', '登录验证码'], ['delivery-test', '投递测试']],
  locale: [['zh', '中文'], ['en', 'English']],
  theme: [['light', '浅色'], ['dark', '深色'], ['system', '跟随系统']],
  width: [['560', '桌面 · 560'], ['375', '手机 · 375'], ['320', '窄屏 · 320']],
  view: [['html', 'HTML 邮件'], ['no-images', '不加载图片'], ['text', '纯文本']],
};
const server = createServer(async (request, response) => {
  const reply = (status, body, type = 'text/html; charset=utf-8') => {
    response.writeHead(status, {'content-type':type, 'cache-control':'no-store', 'x-content-type-options':'nosniff'});
    response.end(body);
  };
  if (request.method !== 'GET') return reply(405, 'Preview is read-only.');
  try {
    const url = new URL(request.url, 'http://127.0.0.1');
    if (url.pathname === '/assets/tradingdata-mark.png') return reply(200, await readFile(new URL('../public/assets/tradingdata-mark.png', import.meta.url)), 'image/png');
    if (!['/', '/email'].includes(url.pathname)) return reply(404, 'Not found');
    const params = Object.fromEntries(Object.entries(choices).map(([key, values]) => [key, values.some(([v]) => v === url.searchParams.get(key)) ? url.searchParams.get(key) : values[0][0]]));
    const mail = renderEmail({kind:params.kind, locale:params.locale, ...(params.kind === 'sign-in-code' ? {code:'00000000', expiresInMinutes:10} : {})});
    if (url.pathname === '/email') {
      if (params.view === 'text') return reply(200, `<!doctype html><html lang="${params.locale === 'zh' ? 'zh-CN' : 'en'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Plain-text email preview</title></head><body style="margin:0;padding:24px;background:${params.theme === 'dark' ? '#08121e' : '#fffdf9'};color:${params.theme === 'dark' ? '#f1f5f7' : '#151917'}"><pre style="white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.8 monospace;">${escape(mail.text)}</pre></body></html>`);
      let html = mail.html.replace(EMAIL_LOGO_URL, '/assets/tradingdata-mark.png');
      // Force stylesheet states for design QA; this is not mailbox dark-mode proof.
      if (params.theme !== 'system') html = html.replace('<html lang=', `<html data-preview-theme="${params.theme}" lang=`).replace('@media (prefers-color-scheme: dark)', '@media (prefers-color-scheme: no-preference)');
      if (params.view === 'no-images') html = html.replace(/<img [^>]+>/g, '');
      return reply(200, html);
    }
    const controls = Object.entries(choices).map(([key, values]) => `<label>${{kind:'用途',locale:'语言',theme:'配色',width:'内容宽度',view:'显示方式'}[key]}<select name="${key}">${values.map(([value,label]) => `<option value="${value}"${params[key] === value ? ' selected' : ''}>${label}</option>`).join('')}</select></label>`).join('');
    const src = '/email?' + new URLSearchParams(params).toString();
    reply(200, `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TradingDatas · 邮件模板预览</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f7f5f1;color:#151917;font:14px/1.6 Arial,'PingFang SC',sans-serif}header{padding:24px 28px;background:#fffdf9;border-bottom:1px solid #e3e5e1}h1{margin:0 0 6px;font-size:20px}p{margin:0;color:#616867}form{display:flex;align-items:end;gap:14px;flex-wrap:wrap;margin-top:20px}label{display:grid;gap:5px;font-size:12px;color:#616867}select,button{font:inherit;background:#fffdf9;border:1px solid #ccd1cc;border-radius:8px;padding:8px 12px;color:#151917}button{background:#064bff;color:white;border-color:#064bff;cursor:pointer}button:focus-visible,select:focus-visible{outline:3px solid #74d8ce;outline-offset:3px}main{padding:20px 0}main p{padding:0 20px;text-align:center;font-size:12px}iframe{display:block;width:min(100%,${params.width}px);height:850px;margin:12px auto;border:0}
    </style></head><body><header><h1>TradingDatas · 邮件模板</h1><p>本地预览 · 验证码为无效示例 · 不发送邮件 · 配色为设计模拟，并非邮箱客户端验收</p><form method="get">${controls}<button type="submit">更新预览</button></form></header><main><p>主题：${escape(mail.subject)}</p><iframe title="邮件内容预览" src="${escape(src)}" sandbox="allow-same-origin"></iframe></main></body></html>`);
  } catch { reply(500, 'Preview unavailable'); }
});
server.listen(Number(process.env.TD_EMAIL_PREVIEW_PORT || 5196), '127.0.0.1', () => {
  console.log(`Email template preview: http://127.0.0.1:${server.address().port}/ (fixtures only; no mail sent)`);
});
