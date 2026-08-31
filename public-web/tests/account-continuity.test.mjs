import test from 'node:test';
import assert from 'node:assert/strict';
import { identityDb } from './helpers/identity-db.mjs';
import { createEmailIdentityHandler } from '../worker/email-identity.js';
import { runIdentityMaintenance } from '../worker/identity-retention.js';

async function fixture() {
  const db=identityDb(); let clock=1_800_000_000; let upstreamState='active'; const calls=[];
  const env={IDENTITY_DB:db, IDENTITY_PEPPER:'local-test-only-identity-pepper-value', RESEND_API_KEY:'fixture-only',
    EMAIL_LOGIN_ENABLED:'true', IDENTITY_RETENTION_ENABLED:'true', ACCOUNT_LIBRARY_ENABLED:'true', ACCOUNT_CONNECTION_ENABLED:'true', ACCOUNT_ADMIN_ENABLED:'true',
    SESSION_ENCRYPTION_KEY:'local-only-encryption-material-not-a-real-secret', ACCOUNT_API_BASE:'https://backend.example'};
  const handler=createEmailIdentityHandler({now:()=>clock, fetchImpl:async (url,init)=>{
    calls.push({url:String(url),init});
    if(upstreamState==='redirect') return new Response(null,{status:302,headers:{location:'https://untrusted.example'}});
    if(upstreamState==='offline') throw new Error('offline');
    if(upstreamState==='revoked' || !['Bearer fixture-key-a','Bearer fixture-admin-key'].includes(init.headers.get('authorization'))) return Response.json({error:'invalid_token'},{status:401});
    const portal={tenant_id:'tenant-a',tier:'basic',scopes:['read'],data_categories:['a_share'],enabled:true,minute_request_limit:200,daily_limit:null,expires_at:null};
    if(init.headers.get('authorization')==='Bearer fixture-admin-key') portal.scopes.push('admin');
    if(upstreamState==='tenant_changed') portal.tenant_id='tenant-other';
    if(String(url).endsWith('/portal/api/me')) return Response.json({portal});
    if(String(url).includes('/usage')) return Response.json({portal_usage:{history:[],today_count:7}});
    return Response.json({api_keys:[]});
  }});
  async function user(id) {
    const token=(id==='alice'?'a':'b').repeat(64);
    const hash=Buffer.from(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(token))).toString('hex');
    db.sqlite.prepare('INSERT INTO identity_users(id,email,created_at) VALUES(?,?,?)').run(id,`${id}@example.com`,clock);
    db.sqlite.prepare('INSERT INTO identity_sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)').run(hash,id,clock,clock+28800);
    return {id,token,hash};
  }
  const alice=await user('alice'),bob=await user('bob');
  const request=(actor,path,method='GET',body,extra={})=>handler(new Request(`https://site.example/api/account/${path}`,{
    method,headers:{origin:'https://site.example',cookie:`td_identity_session=${actor.token}`,'x-td-identity':actor.id,'content-type':'application/json',...extra},
    body:body===undefined?undefined:JSON.stringify(body),
  }),env);
  return {db,env,alice,bob,request,calls,setState:v=>upstreamState=v,advance:n=>clock+=n,now:()=>clock};
}
test('cloud library is isolated, idempotent and bound to the expected identity',async()=>{
  const f=await fixture(); const key='dataset:cn-equity-daily';
  assert.equal((await f.request(f.alice,'bookmarks/item','PUT',{key})).status,200);
  assert.equal((await f.request(f.alice,'bookmarks/item','PUT',{key})).status,200);
  assert.deepEqual((await (await f.request(f.alice,'bookmarks')).json()).bookmarks.keys,[key]);
  assert.deepEqual((await (await f.request(f.bob,'bookmarks')).json()).bookmarks.keys,[]);
  assert.equal((await f.request(f.bob,'bookmarks/item','PUT',{key},{'x-td-identity':'alice'})).status,409);
  assert.equal((await f.request(f.alice,'bookmarks/item','DELETE',{key})).status,200);
  assert.equal((await f.request(f.alice,'bookmarks/item','DELETE',{key})).status,200);
});
test('same-identity administrator bridge denies ordinary users, URL forwarding and cross-account writes',async()=>{
  const f=await fixture();
  await f.request(f.alice,'connection','POST',{access_key:'fixture-key-a'});
  assert.equal((await f.request(f.alice,'admin/admin/api/tokens')).status,403);
  await f.request(f.bob,'connection','POST',{access_key:'fixture-admin-key'});
  assert.equal((await (await f.request(f.bob,'me')).json()).data_access.admin,true);
  assert.equal((await f.request(f.bob,'admin/admin/api/tokens')).status,200);
  assert.equal((await f.request(f.bob,'admin/https://evil.example')).status,404);
  assert.equal((await f.request(f.bob,'admin/admin/api/tokens','POST',{}, {'x-td-identity':'alice'})).status,409);
  f.advance(601);
  assert.equal((await f.request(f.bob,'admin/admin/api/tokens','POST',{})).status,403);
  assert.equal((await f.request(f.bob,'admin/admin/api/tokens')).status,200);
  f.setState('revoked');
  assert.equal((await f.request(f.bob,'admin/admin/api/tokens')).status,403);
});
test('encrypted credentials are bound to identity, not transferable D1 rows',async()=>{
  const f=await fixture();await f.request(f.alice,'connection','POST',{access_key:'fixture-key-a'});
  f.db.sqlite.prepare('INSERT INTO account_connections SELECT ?,credential_box,tenant_id,created_at FROM account_connections WHERE user_id=?').run('bob','alice');
  const result=await (await f.request(f.bob,'me')).json();
  assert.equal(result.data_access.state,'unavailable');assert.equal(result.data_access.portal,undefined);
});
test('library import is explicit, validated, additive and atomic at its cap',async()=>{
  const f=await fixture();
  assert.equal((await f.request(f.alice,'bookmarks/import','POST',{keys:['doc:start-1','method:pit-panel']})).status,200);
  assert.equal((await f.request(f.alice,'bookmarks/import','POST',{keys:['research:paper-one','doc:start-1']})).status,200);
  assert.equal((await f.request(f.alice,'bookmarks/import','POST',{keys:['https://evil.example']})).status,400);
  assert.equal((await f.request(f.alice,'bookmarks/import','POST',{keys:Array.from({length:101},(_,i)=>`doc:d-${i}`)})).status,400);
  for(let i=3;i<499;i++) f.db.sqlite.prepare('INSERT INTO account_bookmarks VALUES(?,?,?)').run('alice',`doc:d-${i}`,f.now());
  assert.equal((await f.request(f.alice,'bookmarks/import','POST',{keys:['doc:new-a','doc:new-b']})).status,409);
  assert.equal(f.db.sqlite.prepare('SELECT COUNT(*) n FROM account_bookmarks').get().n,499);
  assert.equal((await f.request(f.alice,'bookmarks/item','PUT',{key:'doc:last'})).status,200);
  assert.equal((await f.request(f.alice,'bookmarks/item','PUT',{key:'doc:last'})).status,200);
  assert.equal((await f.request(f.alice,'bookmarks/item','PUT',{key:'doc:overflow'})).status,409);
});
test('library rejects CSRF, unbound requests, unsupported methods and disabled flags',async()=>{
  const f=await fixture();
  assert.equal((await f.request(f.alice,'bookmarks/item','PUT',{key:'doc:start-1'},{origin:'https://other.example'})).status,403);
  assert.equal((await f.request(f.alice,'bookmarks', 'GET',undefined,{'x-td-identity':''})).status,409);
  assert.equal((await f.request(f.alice,'bookmarks','POST',{})).status,405);
  f.env.ACCOUNT_LIBRARY_ENABLED='false';
  assert.equal((await f.request(f.alice,'bookmarks')).status,503);
});
test('email alone grants no access; explicit connection projects only backend rights',async()=>{
  const f=await fixture();
  assert.equal((await f.request(f.alice,'usage')).status,403);
  assert.equal((await f.request(f.alice,'connection','POST',{access_key:'wrong'})).status,403);
  const linked=await f.request(f.alice,'connection','POST',{access_key:'fixture-key-a'});
  assert.equal(linked.status,200);
  const row=f.db.sqlite.prepare('SELECT * FROM account_connections').get();
  assert.equal(row.tenant_id,'tenant-a'); assert.ok(!row.credential_box.includes('fixture-key-a'));
  const me=await (await f.request(f.alice,'me')).json();
  assert.equal(me.identity.tenant_id,null); assert.equal(me.data_access.portal.minute_request_limit,200);
  assert.equal(me.data_access.admin,false);
  assert.ok(!JSON.stringify(me).includes('fixture-key-a'));
  assert.equal((await f.request(f.alice,'usage?days=30')).status,200);
  assert.equal((await f.request(f.bob,'usage')).status,403);
  assert.equal((await f.request(f.alice,'connection','POST',{access_key:'fixture-admin-key'})).status,409);
  assert.equal((await f.request(f.alice,'keys','GET',undefined,{'x-td-identity':'bob'})).status,409);
  assert.equal((await f.request(f.alice,'keys','POST',{label:'test'},{'x-td-identity':'bob'})).status,409);
});
test('connection never accepts client authority and rejects stale identity',async()=>{
  const f=await fixture();
  assert.equal((await f.request(f.alice,'connection','POST',{access_key:'fixture-key-a',tenant_id:'other',role:'admin'})).status,400);
  f.advance(601);
  assert.equal((await f.request(f.alice,'connection','POST',{access_key:'fixture-key-a'})).status,403);
  assert.equal(f.db.sqlite.prepare('SELECT COUNT(*) n FROM account_connections').get().n,0);
});
test('backend revocation, mismatch, failure and redirects do not become rights or logout',async()=>{
  const f=await fixture();
  await f.request(f.alice,'connection','POST',{access_key:'fixture-key-a'});
  for(const state of ['revoked','tenant_changed','redirect','offline']) {
    f.setState(state);
    const me=await (await f.request(f.alice,'me')).json();
    assert.equal(me.identity.email_verified,true); assert.equal(me.data_access.portal,undefined);
    assert.notEqual((await f.request(f.alice,'usage')).status,200);
  }
  assert.ok(f.calls.every(call=>call.init.redirect==='manual'));
  assert.ok(f.calls.every(call=>call.url.startsWith('https://backend.example/portal/api/')));
});
test('disconnection leaves identity, bookmarks, upstream keys and another user untouched',async()=>{
  const f=await fixture(); await f.request(f.alice,'connection','POST',{access_key:'fixture-key-a'});
  await f.request(f.alice,'bookmarks/item','PUT',{key:'doc:start-1'});
  assert.equal((await f.request(f.alice,'connection','DELETE',{})).status,200);
  assert.equal((await (await f.request(f.alice,'me')).json()).data_access.state,'none');
  assert.equal((await (await f.request(f.alice,'bookmarks')).json()).bookmarks.keys.length,1);
  assert.ok(f.calls.every(call=>!['DELETE','PATCH'].includes(call.init.method)));
});
test('profile disable revokes connections despite flags, and purge cascades own library only',async()=>{
  const f=await fixture(); await f.request(f.alice,'connection','POST',{access_key:'fixture-key-a'});
  await f.request(f.alice,'bookmarks/item','PUT',{key:'doc:start-1'});
  await f.request(f.bob,'bookmarks/item','PUT',{key:'doc:start-2'});
  f.env.ACCOUNT_CONNECTION_ENABLED='false'; f.env.ACCOUNT_LIBRARY_ENABLED='false';
  assert.equal((await f.request(f.alice,'profile/deletion','POST',{confirmation:'DELETE'})).status,202);
  assert.equal(f.db.sqlite.prepare('SELECT COUNT(*) n FROM account_connections').get().n,0);
  f.env.ACCOUNT_LIBRARY_ENABLED='true';
  assert.equal((await f.request(f.alice,'bookmarks')).status,401);
  await runIdentityMaintenance(f.env,f.now());
  assert.deepEqual(f.db.sqlite.prepare('SELECT user_id FROM account_bookmarks').all().map(row=>row.user_id),['bob']);
});
test('stale-tab or missing identity cannot delete the newly signed-in account',async()=>{
  const f=await fixture();
  for(const identity of ['alice','']) {
    assert.equal((await f.request(f.bob,'profile/deletion','POST',{confirmation:'DELETE'},{'x-td-identity':identity})).status,409);
  }
  assert.equal(f.db.sqlite.prepare('SELECT COUNT(*) n FROM identity_users WHERE disabled_at IS NOT NULL').get().n,0);
  const result=await (await f.request(f.bob,'profile/deletion','POST',{confirmation:'DELETE'})).json();
  assert.equal(result.deletion.user_id,'bob');
});
