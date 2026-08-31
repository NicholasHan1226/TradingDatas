import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { identityDb } from './helpers/identity-db.mjs';
import { createEmailIdentityHandler } from '../worker/email-identity.js';
import { getSystemEmailLocale } from '../src/systemEmailLocale.js';

test('provisioned account binding does not enable email or use the data-plane store', async () => {
  const config = JSON.parse(await readFile(new URL('../wrangler.jsonc', import.meta.url), 'utf8'));
  assert.equal(config.name, 'tradingdatas');
  assert.equal(config.vars.EMAIL_LOGIN_ENABLED, 'false');
  assert.deepEqual(config.d1_databases, [{
    binding: 'IDENTITY_DB', database_name: 'tradingdatas-identity-v1',
    database_id: 'bb5e8d90-090f-40a5-9aa1-b91b33af7199',
  }]);
  assert.equal(config.vars.IDENTITY_PEPPER, undefined);
  assert.equal(config.vars.RESEND_API_KEY, undefined);
  const f = fixture();
  Object.assign(f.env, config.vars);
  const methods = await f.call('auth-methods');
  const readiness = await methods.json();
  assert.equal(readiness.email, false);
  assert.equal(readiness.phone, false);
  assert.equal((await f.challenge()).response.status, 503);
  assert.equal(f.sent.length, 0);
  assert.equal(f.env.IDENTITY_DB.sqlite.prepare('SELECT count(*) n FROM identity_users').get().n, 0);
});

function fixture(options = {}) {
  let now = 1_800_000_000;
  const sent = [];
  const env = { EMAIL_LOGIN_ENABLED: 'true', IDENTITY_DB: identityDb(), IDENTITY_PEPPER: 'test-only-identity-pepper-not-a-real-secret-0123456789', RESEND_API_KEY: 'test-only-not-a-real-key' };
  const handle = createEmailIdentityHandler({ now: () => now, fetchImpl: async (url, init) => {
    assert.equal(url, 'https://api.resend.com/emails');
    assert.equal(init.redirect, 'manual');
    sent.push(JSON.parse(init.body));
    return new Response(JSON.stringify({ id: 'test-message' }), {status: options.sendStatus || 200, headers: {'content-type':'application/json'}});
  }});
  const call = (path, body, cookie = '', extra = {}) => handle(new Request(`https://tradingdatas.test/api/account/${path}`, {
    method: body === undefined ? 'GET' : 'POST', headers: {origin:'https://tradingdatas.test', 'content-type':'application/json', 'cf-connecting-ip':'192.0.2.1', cookie, ...extra}, ...(body === undefined ? {} : {body: JSON.stringify(body)}),
  }), env);
  const challenge = async (email = 'reader@example.com') => {
    const response = await call('email/challenge', {email, locale:'en'});
    const payload = await response.json();
    return {response, payload, email, code: sent.at(-1)?.text.match(/\b\d{8}\b/)?.[0]};
  };
  const verify = (c, code = c.code) => call('email/verify', {email:c.email, challenge_id:c.payload.challenge_id, code});
  return {env, sent, call, challenge, verify, handle, advance: n => {now += n;}};
}

test('profile deletion requires fresh verified session, exact confirmation and explicit maintenance enablement', async () => {
  const f=fixture(); const c=await f.challenge(); const verified=await f.verify(c);
  const cookie=verified.headers.getSetCookie().find(v=>v.startsWith('td_identity_session=')).split(';')[0];
  const expected={'x-td-identity':(await verified.json()).identity.user_id};
  assert.equal((await f.call('profile/deletion', {confirmation:'DELETE'},cookie)).status,503);
  f.env.IDENTITY_RETENTION_ENABLED='true';
  assert.equal(await f.call('profile/deletion',{confirmation:'DELETE'}),null);
  assert.equal((await f.call('profile/deletion',{confirmation:'DELETE'},cookie,{origin:'https://evil.example'})).status,403);
  assert.equal((await f.call('profile/deletion',{confirmation:'delete'},cookie,expected)).status,400);
  f.advance(601);
  assert.equal((await f.call('profile/deletion',{confirmation:'DELETE'},cookie,expected)).status,403);
  assert.equal(f.env.IDENTITY_DB.sqlite.prepare('SELECT count(*) n FROM identity_deletion_requests').get().n,0);
});
test('deletion queues only the session owner, disables sign-in and revokes every session without touching another user',async()=>{
  const f=fixture(); f.env.IDENTITY_RETENTION_ENABLED='true';
  const a=await f.verify(await f.challenge('delete@example.com'));
  const id=(await a.json()).identity.user_id;
  const cookie=a.headers.getSetCookie().find(v=>v.startsWith('td_identity_session=')).split(';')[0];
  const b=await f.verify(await f.challenge('keep@example.com'));
  const other=(await b.json()).identity.user_id;
  const otherCookie=b.headers.getSetCookie().find(v=>v.startsWith('td_identity_session=')).split(';')[0];
  const response=await f.call('profile/deletion',{confirmation:'DELETE',user_id:other},cookie,{'x-td-identity':id});
  assert.equal(response.status,202);
  assert.equal((await response.json()).deletion.state,'accepted');
  assert.ok(response.headers.getSetCookie().every(value=>value.includes('Max-Age=0')));
  assert.equal(f.env.IDENTITY_DB.sqlite.prepare('SELECT user_id FROM identity_deletion_requests').get().user_id,id);
  assert.equal((await f.call('me',undefined,cookie)).status,401);
  assert.equal((await f.call('me',undefined,otherCookie)).status,200);
  f.advance(61);
  assert.equal((await f.verify(await f.challenge('delete@example.com'))).status,400);
});
test('deletion batch failure does not disable the account or report success',async()=>{
  const f=fixture(); f.env.IDENTITY_RETENTION_ENABLED='true';
  const response=await f.verify(await f.challenge());
  const cookie=response.headers.getSetCookie().find(v=>v.startsWith('td_identity_session=')).split(';')[0];
  const expected={'x-td-identity':(await response.json()).identity.user_id};
  f.env.IDENTITY_DB.sqlite.exec("CREATE TRIGGER fail_delete BEFORE UPDATE ON identity_users BEGIN SELECT RAISE(ABORT,'fixture'); END;");
  assert.equal((await f.call('profile/deletion',{confirmation:'DELETE'},cookie,expected)).status,503);
  assert.equal((await f.call('me',undefined,cookie)).status,200);
  assert.equal(f.env.IDENTITY_DB.sqlite.prepare('SELECT count(*) n FROM identity_deletion_requests').get().n,0);
});

test('email remains disabled without complete configuration, with no outbound call', async () => {
  const f=fixture(); delete f.env.RESEND_API_KEY;
  assert.deepEqual(await (await f.call('auth-methods')).json(), {email:false, phone:false});
  assert.equal((await f.call('email/challenge',{email:'reader@example.com'})).status,503);
  assert.equal(f.sent.length,0);
});
test('the actual sender uses the shared localized HTML and text template with the challenge expiry', async () => {
  for (const locale of ['zh', 'en']) {
    const f = fixture();
    const response = await f.call('email/challenge', {email:'template@example.com', locale});
    assert.equal(response.status, 202);
    const policy = await response.json();
    const mail = f.sent[0];
    const code = mail.text.match(/\b\d{8}\b/)[0];
    assert.match(mail.html, /data-template="sign-in-code-v1"/);
    assert.ok(mail.html.includes(code));
    assert.match(mail.html, locale === 'zh' ? /lang="zh-CN"/ : /lang="en"/);
    assert.ok(mail.text.includes(String(policy.expires_in / 60)));
    assert.ok(!mail.subject.includes(code));
    assert.deepEqual(Object.keys(mail).sort(), ['from', 'html', 'subject', 'text', 'to']);
  }
});
test('device language reaches the branded sender on initial send and resend', async () => {
  const f = fixture();
  // Switching the website UI does not supply this field. A changed device
  // preference is resolved again on resend, never retained from the first send.
  for (const language of ['zh-Hant-TW', 'en-US', 'ja-JP']) {
    const response = await f.call('email/challenge', {
      email: 'language@example.com', locale: getSystemEmailLocale({language}),
    });
    assert.equal(response.status, 202);
    const mail = f.sent.at(-1);
    const chinese = language.startsWith('zh');
    assert.match(mail.html, chinese ? /lang="zh-CN"/ : /lang="en"/);
    assert.match(mail.subject, chinese ? /验证码/ : /sign-in code/i);
    assert.match(mail.text, chinese ? /请勿分享/ : /Do not share/);
    f.advance(61);
  }
  assert.equal(f.sent.length, 3);
});

test('one verified email creates one identity, no tenant or data grant; opaque cookie only', async () => {
  const f=fixture(); const c=await f.challenge(); assert.equal(c.response.status,202);
  assert.equal(c.payload.delivery,'accepted'); assert.equal(JSON.stringify(c.payload).includes(c.code),false);
  assert.match(c.code,/^\d{8}$/); assert.equal(f.sent[0].from,'TradingDatas <login@account.tradingdatas.com>');
  const response=await f.verify(c); assert.equal(response.status,200);
  const data=await response.json(); assert.equal(data.identity.email,'reader@example.com');
  assert.equal(data.identity.subscription_state,'not_subscribed'); assert.equal(data.identity.tenant_id,null);
  assert.deepEqual(data.identity.data_categories,[]);
  const cookie=response.headers.getSetCookie().find(v=>v.startsWith('td_identity_session='));
  assert.match(cookie,/HttpOnly; Secure; SameSite=Strict/); assert.ok(!cookie.includes('reader'));
  const me=await f.call('me',undefined,cookie.split(';')[0]); assert.equal(me.status,200);
  for(const path of ['keys','usage','keys/key_aaaaaaaaaaaaaaaa']) {
    assert.equal((await f.call(path,undefined,cookie.split(';')[0])).status,403);
  }
  assert.equal(f.env.IDENTITY_DB.sqlite.prepare('SELECT count(*) n FROM identity_users').get().n,1);
});
test('parallel verification consumes a challenge exactly once',async()=>{
  const f=fixture(); const c=await f.challenge();
  const results=await Promise.all([f.verify(c),f.verify(c),f.verify(c)]);
  assert.equal(results.filter(r=>r.status===200).length,1);
  assert.equal(f.env.IDENTITY_DB.sqlite.prepare('SELECT count(*) n FROM identity_sessions').get().n,1);
});
test('wrong, expired, exhausted and mismatched-email codes fail closed',async()=>{
  const f=fixture(); const c=await f.challenge();
  assert.equal((await f.verify({...c,email:'other@example.com'})).status,400);
  for(let i=0;i<5;i++) assert.equal((await f.verify(c,'notacode')).status,400);
  for(let i=0;i<5;i++) assert.equal((await f.verify(c,c.code==='00000000'?'11111111':'00000000')).status,400);
  assert.equal((await f.verify(c)).status,400);
  f.advance(61); const next=await f.challenge(); f.advance(601);
  assert.equal((await f.verify(next)).status,400);
});
test('resend has atomic cooldown; new challenge invalidates old code',async()=>{
  const f=fixture(); const c=await f.challenge();
  const results=await Promise.all([f.challenge(),f.challenge()]);
  assert.ok(results.every(r=>r.response.status===429)); assert.equal(f.sent.length,1);
  f.advance(61); const next=await f.challenge();
  assert.equal((await f.verify(c)).status,400); assert.equal((await f.verify(next)).status,200);
});
test('provider errors never claim delivery or create a usable challenge',async()=>{
  const f=fixture({sendStatus:500}); const c=await f.challenge(); assert.equal(c.response.status,503);
  assert.equal(c.payload.delivery,undefined); assert.equal((await f.verify(c)).status,400);
  assert.equal(f.env.IDENTITY_DB.sqlite.prepare('SELECT count(*) n FROM identity_users').get().n,0);
});
test('provider redirects are not followed and never issue an accepted challenge',async()=>{
  const f=fixture({sendStatus:302});const c=await f.challenge();
  assert.equal(c.response.status,503);assert.equal(f.sent.length,1);
  assert.equal(f.env.IDENTITY_DB.sqlite.prepare('SELECT count(*) n FROM identity_challenges').get().n,0);
});
test('same-site origin, content type and payload size are enforced before sending',async()=>{
  const f=fixture();
  assert.equal((await f.call('email/challenge',{email:'x@example.com'},'',{origin:'https://evil.test'})).status,403);
  assert.equal((await f.call('email/challenge',{email:'x@example.com'},'',{'content-type':'text/plain'})).status,400);
  assert.equal((await f.call('email/challenge',{email:'x'.repeat(5000)})).status,400);
  assert.equal(f.sent.length,0);
});
test('logout revokes stored session, replay and expiry do not fall back to legacy keys',async()=>{
  const f=fixture(); const response=await f.verify(await f.challenge());
  const cookie=response.headers.getSetCookie().find(v=>v.startsWith('td_identity_session=')).split(';')[0];
  const logout=await f.handle(new Request('https://tradingdatas.test/api/account/session',{method:'DELETE',headers:{origin:'https://tradingdatas.test',cookie}}),f.env);
  assert.equal(logout.status,200); assert.equal((await f.call('me',undefined,cookie)).status,401);
  f.advance(61); const next=await f.verify(await f.challenge());
  const nextCookie=next.headers.getSetCookie().find(v=>v.startsWith('td_identity_session=')).split(';')[0];
  f.advance(8*3600+1); assert.equal((await f.call('me',undefined,nextCookie)).status,401);
});
test('database outage cannot be reported as signed out, and error details stay private',async()=>{
  const f=fixture(); const response=await f.verify(await f.challenge());
  const cookie=response.headers.getSetCookie().find(v=>v.startsWith('td_identity_session=')).split(';')[0];
  f.env.IDENTITY_DB={prepare(){throw new Error('private database details');}};
  const me=await f.call('me',undefined,cookie); assert.equal(me.status,503); assert.ok(!(await me.text()).includes('private'));
  const logout=await f.handle(new Request('https://tradingdatas.test/api/account/session',{method:'DELETE',headers:{origin:'https://tradingdatas.test',cookie}}),f.env);
  assert.equal(logout.status,503); assert.equal((await logout.json()).signed_out,undefined);
});

test('normalized email reuses one identity; another verified email stays isolated',async()=>{
  const f=fixture(); const first=await (await f.verify(await f.challenge('Reader@Example.com'))).json();
  f.advance(61); const again=await (await f.verify(await f.challenge('reader@example.com'))).json();
  const other=await (await f.verify(await f.challenge('another@example.com'))).json();
  assert.equal(first.identity.user_id,again.identity.user_id);
  assert.notEqual(first.identity.user_id,other.identity.user_id);
  assert.equal(f.env.IDENTITY_DB.sqlite.prepare('SELECT count(*) n FROM identity_users').get().n,2);
});
test('stored challenges and sessions contain hashes, not usable codes or cookies',async()=>{
  const f=fixture();const c=await f.challenge();const response=await f.verify(c);
  const raw=response.headers.getSetCookie().find(v=>v.startsWith('td_identity_session=')).split(';')[0].split('=')[1];
  const row=f.env.IDENTITY_DB.sqlite.prepare('SELECT * FROM identity_challenges').get();
  assert.match(row.code_hash,/^[a-f0-9]{64}$/); assert.notEqual(row.code_hash,c.code);
  const session=f.env.IDENTITY_DB.sqlite.prepare('SELECT * FROM identity_sessions').get();
  assert.match(session.token_hash,/^[a-f0-9]{64}$/);assert.notEqual(session.token_hash,raw);
});
test('disabled users cannot sign in or retain a session',async()=>{
  const f=fixture();const response=await f.verify(await f.challenge());
  const cookie=response.headers.getSetCookie().find(v=>v.startsWith('td_identity_session=')).split(';')[0];
  f.env.IDENTITY_DB.sqlite.prepare('UPDATE identity_users SET disabled_at=1').run();
  assert.equal((await f.call('me',undefined,cookie)).status,401);
  f.advance(61); assert.equal((await f.verify(await f.challenge())).status,400);
});
test('disabling new email login retains revocation; email sessions never inherit a key session',async()=>{
  const f=fixture();const response=await f.verify(await f.challenge());
  const cookie=response.headers.getSetCookie().find(v=>v.startsWith('td_identity_session=')).split(';')[0]+'; td_account_session=old-key-session';
  assert.equal((await f.call('session',{access_key:'unrelated'},cookie)).status,409);
  f.env.EMAIL_LOGIN_ENABLED='false';
  assert.equal((await f.call('email/challenge',{email:'reader@example.com'})).status,503);
  assert.equal((await f.call('me',undefined,cookie)).status,200);
  const logout=await f.handle(new Request('https://tradingdatas.test/api/account/session',{method:'DELETE',headers:{origin:'https://tradingdatas.test',cookie}}),f.env);
  assert.equal(logout.status,200);assert.equal(logout.headers.getSetCookie().length,2);
  assert.equal((await f.call('me',undefined,cookie)).status,401);
});
test('email/IP/global send caps are enforced across challenges and restart-safe storage',async()=>{
  const f=fixture();
  for(let i=0;i<5;i++){assert.equal((await f.challenge()).response.status,202);f.advance(61);}
  assert.equal((await f.challenge()).response.status,429);assert.equal(f.sent.length,5);
  const bucket=f.env.IDENTITY_DB.sqlite.prepare("SELECT bucket_key FROM identity_rate_buckets WHERE bucket_key LIKE 'send-global:%'").get();
  f.env.IDENTITY_DB.sqlite.prepare('UPDATE identity_rate_buckets SET hits=100 WHERE bucket_key=?').run(bucket.bucket_key);
  assert.equal((await f.challenge('other@example.com')).response.status,429);
  assert.equal(f.sent.length,5);
  assert.equal((await f.call('email/challenge',{email:'x@example.com'},'',{'cf-connecting-ip':''})).status,503);
});
