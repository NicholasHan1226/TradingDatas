// Optional local workerd/D1 acceptance. Supply an installed Miniflare module
// path; no dependency, credentials, database or deployment is provisioned here.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';

if (!process.argv[2]) throw new Error('Usage: node scripts/check-email-runtime.mjs /absolute/path/to/miniflare/dist/src/index.js');
const { Miniflare, convertV4MiniflareOptions } = await import(pathToFileURL(process.argv[2]).href);
const mail = [];
const outbound = [];
let upstreamRedirect = false;
const moduleFiles = ['index.js', 'email-identity.js', 'email-templates.js'].map(name => ({
  type: 'ESModule', path: fileURLToPath(new URL(`../worker/${name}`, import.meta.url)),
}));
const options = {
  modules: moduleFiles,
  compatibilityDate: '2026-08-29',
  bindings: { EMAIL_LOGIN_ENABLED: 'true', IDENTITY_PEPPER: 'local-runtime-only-pepper-never-a-real-secret', RESEND_API_KEY: 'local-runtime-fixture', ACCOUNT_API_BASE: 'https://account.example.test', SESSION_ENCRYPTION_KEY: 'local-only-legacy-session-fixture' },
  d1Databases: { IDENTITY_DB: 'isolated-local-identity-test' },
  outboundService: async request => {
    outbound.push(request.url);
    if (request.url === 'https://account.example.test/portal/api/me') {
      assert.equal(request.headers.get('authorization'), 'Bearer legacy-fixture');
      return upstreamRedirect ? new Response(null,{status:302,headers:{location:'https://never-follow.example.test/'}}) : Response.json({portal:{tenant_id:'legacy-fixture-tenant',tier:'basic'}});
    }
    assert.equal(request.url, 'https://api.resend.com/emails');
    assert.equal(request.headers.get('authorization'), 'Bearer local-runtime-fixture');
    mail.push(await request.json());
    return Response.json({ id: 'local-workerd-acceptance' });
  },
};
const runtime = new Miniflare(convertV4MiniflareOptions ? convertV4MiniflareOptions(options) : options);
try {
  const db = await runtime.getD1Database('IDENTITY_DB');
  const schema = await readFile(new URL('../worker/identity-schema.sql', import.meta.url), 'utf8');
  for (const statement of schema.split(';').filter(value => value.trim())) await db.prepare(statement).run();
  const call = (route, body, cookie = '', method = body === undefined ? 'GET' : 'POST') => runtime.dispatchFetch(`https://tradingdatas.test/api/account/${route}`, {
    method, headers: { origin: 'https://tradingdatas.test', 'content-type': 'application/json', 'cf-connecting-ip': '192.0.2.1', cookie },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  assert.deepEqual(await (await call('auth-methods')).json(), { email: true, phone: false });
  assert.equal((await call('me')).status, 401);
  const legacy = await call('session',{access_key:'legacy-fixture'});
  assert.equal(legacy.status,200);
  assert.equal((await legacy.json()).portal.tenant_id,'legacy-fixture-tenant');
  upstreamRedirect = true;
  assert.equal((await call('session',{access_key:'legacy-fixture'})).status,502);
  assert.ok(!outbound.some(url=>url.includes('never-follow')));
  const challengeResponse = await call('email/challenge', { email: 'workerd@example.com' });
  assert.equal(challengeResponse.status, 202, `Challenge failed: ${await challengeResponse.clone().text()}; intercepted requests: ${JSON.stringify(outbound)}`);
  const challenge = await challengeResponse.json();
  const body = { email: 'workerd@example.com', challenge_id: challenge.challenge_id, code: mail[0].text.match(/\b\d{8}\b/)[0] };
  assert.match(mail[0].html, /data-template="sign-in-code-v1"/);
  assert.ok(mail[0].html.includes(body.code));
  const verified = await Promise.all([call('email/verify', body), call('email/verify', body)]);
  assert.deepEqual(verified.map(r => r.status).sort(), [200, 400]);
  const success = verified.find(r => r.status === 200);
  assert.equal((await success.json()).identity.subscription_state, 'not_subscribed');
  const cookie = success.headers.getSetCookie().find(v => v.startsWith('td_identity_session=')).split(';')[0];
  assert.equal((await call('me', undefined, cookie)).status, 200);
  assert.equal((await call('keys', undefined, cookie)).status, 403);
  assert.equal((await call('usage', undefined, cookie)).status, 403);
  assert.equal((await call('session', undefined, cookie, 'DELETE')).status, 200);
  assert.equal((await call('me', undefined, cookie)).status, 401);
  assert.equal(mail.length, 1);
  console.log('PASS: local workerd + D1 challenge, atomic one-use verification, account isolation, session revocation and legacy login/redirect rejection. No email sent.');
} finally { await runtime.dispose(); }
