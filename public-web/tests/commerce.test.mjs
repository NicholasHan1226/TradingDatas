import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync,mkdtempSync,rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { identityDb } from './helpers/identity-db.mjs';
import { handleCommerce,settleSandboxPayment,buildSandboxOffer } from '../worker/commerce.js';
function store(path=':memory:') {
 const sqlite=new DatabaseSync(path);sqlite.exec(readFileSync(new URL('../worker/commerce-schema.sql',import.meta.url),'utf8'));
 return {sqlite,prepare(sql){let args=[];return {bind(...values){args=values;return this;},async first(){return sqlite.prepare(sql).get(...args)||null;},async run(){return {meta:sqlite.prepare(sql).run(...args)};},async all(){return {results:sqlite.prepare(sql).all(...args)};},execute(){return {results:sqlite.prepare(sql).all(...args)};}};},async batch(statements){sqlite.exec('BEGIN');try{const result=statements.map(s=>s.execute());sqlite.exec('COMMIT');return result;}catch(e){sqlite.exec('ROLLBACK');throw e;}}};
}
function fixture(commerce=store()) {
 const identity=identityDb();for(const id of ['alice','bob']) {identity.sqlite.prepare('INSERT INTO identity_users VALUES (?,?,?,NULL)').run(id,`${id}@example.com`,100);identity.sqlite.prepare('INSERT INTO identity_sessions VALUES (?,?,?,?,NULL)').run(id,id,100,99999999);}
 const env={IDENTITY_DB:identity,COMMERCE_MODE:'sandbox',COMMERCE_SANDBOX_DB:commerce};
 async function request(path='commerce',method='GET',body,owner='alice',key='test-key-123') {
 return handleCommerce({env,session:{id:owner},tokenHash:owner,now:()=>1000,request:new Request(`https://example.com/api/account/${path}`,{method,headers:{origin:'https://example.com','content-type':'application/json','x-td-identity':owner,'idempotency-key':key},...(body?{body:JSON.stringify(body)}:{})})});}
 return {env,request};
}
async function selection(f,id='basic-monthly') {const offers=(await (await f.request('offers')).json()).offers;const offer=offers.find(item=>item.id===id);return {offer_id:offer.id,offer_version:offer.version};}
async function order(f,key='test-key-123') {return (await (await f.request('orders','POST',await selection(f),'alice',key)).json()).order;}
function callbacks(overrides={}) {return {verify:async value=>value,provision:async({idempotency_key})=>({environment:'sandbox',idempotency_key,state:'active'}),now:()=>1000,...overrides};}
function paid(order,id='evt1'){return {event_id:id,environment:'sandbox',status:'paid',order_id:order.id,amount_minor:order.amount_minor,currency:order.currency};}
test('production missing bindings exposes unavailable and forbids order writes',async()=>{
 const f=fixture();delete f.env.COMMERCE_MODE;
 assert.deepEqual(await (await f.request()).json(),{mode:'unavailable',checkout_available:false,subscription:null,orders:[],offers:[]});
 assert.equal((await f.request('orders','POST',{offer_id:'basic-monthly',offer_version:'unavailable'})).status,503);
 assert.equal(f.env.COMMERCE_SANDBOX_DB.sqlite.prepare('SELECT COUNT(*) n FROM commerce_orders').get().n,0);
 f.env.COMMERCE_MODE='live';assert.equal((await (await f.request()).json()).mode,'unavailable');
 f.env.COMMERCE_MODE='sandbox';f.env.COMMERCE_SANDBOX_DB=f.env.IDENTITY_DB;assert.equal((await (await f.request()).json()).mode,'unavailable');
});
test('immutable offers, idempotency and ownership survive concurrent create',async()=>{
 const f=fixture();const offers=(await (await f.request('offers')).json()).offers;assert.equal(offers.length,6);assert.equal(offers.find(x=>x.id==='flagship-annual').amount_minor,538920);
 const choice=await selection(f);const responses=await Promise.all(Array.from({length:6},()=>f.request('orders','POST',choice)));const ids=await Promise.all(responses.map(async r=>(await r.json()).order.id));assert.equal(new Set(ids).size,1);
 assert.equal((await f.request('orders','POST',await selection(f,'standard-monthly'))).status,409);
 assert.equal((await f.request('orders','POST',{...choice,amount_minor:1})).status,400);
 assert.equal((await f.request(`orders/${ids[0]}`,'GET',null,'bob')).status,404);
 assert.equal((await f.request(`orders/${ids[0]}`)).status,200);
 assert.equal((await (await f.request('commerce','GET',null,'bob')).json()).orders.length,0);
 f.env.IDENTITY_DB.sqlite.prepare("UPDATE identity_sessions SET revoked_at=1 WHERE user_id='alice'").run();assert.equal((await f.request()).status,401);
});
test('bad verification, amount, currency, status cannot confirm payment',async()=>{
 const f=fixture(),o=await order(f);const valid=paid(o);
 for(const event of [{...valid,amount_minor:1},{...valid,currency:'USD'},{...valid,environment:'live'},{...valid,status:'failed'}]) await assert.rejects(settleSandboxPayment(f.env,event,callbacks()));
 await assert.rejects(settleSandboxPayment(f.env,valid,callbacks({verify:async()=>{throw Error('bad_signature');}})));
 await assert.rejects(settleSandboxPayment(f.env,{...valid,merchant:'unexpected'},callbacks({verify:async value=>{if(value.merchant!=='test-merchant') throw Error('wrong_merchant');return value;}})),/wrong_merchant/);
 assert.equal((await (await f.request()).json()).orders[0].payment_state,'pending');
});
test('paid provision failure retries without re-payment; duplicate concurrent delivery adds one term',async()=>{
 const f=fixture(),o=await order(f),event=paid(o);
 assert.equal((await settleSandboxPayment(f.env,event,callbacks({provision:async()=>{throw Error('offline');}}))).state,'failed');
 let state=await (await f.request()).json();assert.equal(state.orders[0].payment_state,'verified_paid');assert.equal(state.orders[0].provisioning_state,'failed');assert.equal(state.subscription,null);
 await Promise.all(Array.from({length:5},()=>settleSandboxPayment(f.env,event,callbacks())));
 state=await (await f.request()).json();assert.equal(state.subscription.expires_at,new Date((1000+30*86400)*1000).toISOString());assert.equal(state.orders[0].provisioning_state,'active');
 const second=await order(f,'renewal-key-2');await settleSandboxPayment(f.env,paid(second,'evt2'),callbacks());
 state=await (await f.request()).json();assert.equal(state.subscription.expires_at,new Date((1000+60*86400)*1000).toISOString());
 await assert.rejects(settleSandboxPayment(f.env,paid(second,'evt1'),callbacks()),/event_conflict/);
});
test('file-backed ledger survives process-equivalent reopen independently of identity retention',async()=>{
 const directory=mkdtempSync(join(tmpdir(),'td-commerce-'));try{
 const path=join(directory,'sandbox.sqlite');let db=store(path),f=fixture(db);const o=await order(f);await settleSandboxPayment(f.env,paid(o),callbacks());db.sqlite.close();
 db=store(path);f=fixture(db);assert.equal((await (await f.request()).json()).orders[0].id,o.id);assert.equal((await (await f.request()).json()).subscription.state,'active');
 assert.equal((await (await f.request('orders','POST',await selection(f))).json()).order.id,o.id);
 assert.equal(f.env.IDENTITY_DB.sqlite.prepare("SELECT COUNT(*) n FROM sqlite_master WHERE name LIKE 'commerce_%'").get().n,0);db.sqlite.close();
 }finally{rmSync(directory,{recursive:true,force:true});}
});
test('missing or mismatched identity rejected, injected settlement cannot use production',async()=>{
 const f=fixture();const response=await handleCommerce({env:f.env,session:{id:'alice'},tokenHash:'alice',now:()=>1000,request:new Request('https://example.com/api/account/commerce')});assert.equal(response.status,409);
 f.env.COMMERCE_MODE='live';await assert.rejects(settleSandboxPayment(f.env,{},callbacks()),/sandbox_unavailable/);
});
test('verified email route integrates without changing identity or Portal grants',async()=>{
 const { createEmailIdentityHandler }=await import('../worker/email-identity.js');
 const f=fixture(),token='a'.repeat(64);
 const hash=Buffer.from(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(token))).toString('hex');
 f.env.IDENTITY_DB.sqlite.prepare('INSERT INTO identity_sessions VALUES (?,?,?,?,NULL)').run(hash,'alice',100,99999999);
 const handler=createEmailIdentityHandler({now:()=>1000,fetchImpl:async()=>{throw Error('must not call upstream');}});
 const response=await handler(new Request('https://example.com/api/account/commerce',{headers:{cookie:`td_identity_session=${token}`,'x-td-identity':'alice'}}),f.env);
 assert.equal(response.status,200);assert.equal((await response.json()).mode,'sandbox');
 const me=await handler(new Request('https://example.com/api/account/me',{headers:{cookie:`td_identity_session=${token}`}}),f.env);
 const identity=(await me.json()).identity;assert.equal(identity.subscription_state,'not_subscribed');assert.deepEqual(identity.data_categories,[]);
 const forged=await handler(new Request('https://example.com/api/account/orders',{method:'POST',headers:{cookie:`td_identity_session=${token}`,origin:'https://evil.example','x-td-identity':'alice','content-type':'application/json','idempotency-key':'forged-key'},body:JSON.stringify(await selection(f))}),f.env);
 assert.equal(forged.status,403);
});
test('unconfirmed provision never grants, late failure never rolls back active, storage failure stays unavailable',async()=>{
 const f=fixture(),o=await order(f),event=paid(o);
 assert.equal((await settleSandboxPayment(f.env,event,callbacks({provision:async()=>({state:'active',environment:'live'})}))).state,'failed');
 await settleSandboxPayment(f.env,event,callbacks());
 await assert.rejects(settleSandboxPayment(f.env,{...event,status:'failed'},callbacks()));
 assert.equal((await (await f.request()).json()).subscription.state,'active');
 f.env.COMMERCE_SANDBOX_DB={prepare(){throw Error('secret database path');}};
 const response=await f.request();assert.equal(response.status,503);assert.deepEqual(await response.json(),{error:'commerce_unavailable'});
});
test('optional durable preview identity reopens with same owner and rejects aliased database paths',async()=>{
 const { assertSeparateSandboxFiles }=await import('../scripts/commerce-sandbox.mjs');
 const { symlinkSync,linkSync }=await import('node:fs');
 const directory=mkdtempSync(join(tmpdir(),'td-preview-db-'));
 try {
  const identityFile=join(directory,'identity.sqlite'),commerceFile=join(directory,'commerce.sqlite');
  assertSeparateSandboxFiles(identityFile,commerceFile);
  assert.throws(()=>assertSeparateSandboxFiles(identityFile,join(directory,'.','identity.sqlite')),/separate files/);
  let identity=identityDb(identityFile);identity.sqlite.prepare('INSERT INTO identity_users VALUES (?,?,?,NULL)').run('durable-owner','reader@example.com',100);identity.sqlite.close();
  identity=identityDb(identityFile);assert.equal(identity.sqlite.prepare('SELECT id FROM identity_users WHERE email=?').get('reader@example.com').id,'durable-owner');identity.sqlite.close();
  symlinkSync(identityFile,join(directory,'alias.sqlite'));assert.throws(()=>assertSeparateSandboxFiles(identityFile,join(directory,'alias.sqlite')),/separate files/);
  linkSync(identityFile,join(directory,'hardlink.sqlite'));assert.throws(()=>assertSeparateSandboxFiles(identityFile,join(directory,'hardlink.sqlite')),/separate files/);
 }finally{rmSync(directory,{recursive:true,force:true});}
});
test('offer version binds all commercial fields and stale version cannot reuse an order key',async()=>{
 const fields={id:'basic-monthly',tier:'basic',period:'monthly',currency:'CNY',amount_minor:9900,requests_per_minute:200,terms_version:'sandbox-fixed-days-v1',term_days:30};
 const original=await buildSandboxOffer(fields);assert.equal((await buildSandboxOffer({...fields})).version,original.version);
 for(const change of [{amount_minor:10000},{currency:'USD'},{requests_per_minute:201},{terms_version:'sandbox-fixed-days-v2'},{term_days:31},{tier:'standard'},{period:'annual'}]) assert.notEqual((await buildSandboxOffer({...fields,...change})).version,original.version);
 const f=fixture();const o=await order(f);
 const stale=await f.request('orders','POST',{offer_id:o.offer_id,offer_version:'sandbox-stale-version'});
 assert.equal(stale.status,409);assert.equal((await stale.json()).error,'offer_changed');
 assert.equal((await (await f.request()).json()).orders.length,1);
});
test('settlement and subscription use immutable purchased term snapshot, not current offer defaults',async()=>{
 const f=fixture(),o=await order(f);
 // Model a persisted order written by an older release whose test term differed.
 const prior={id:o.offer_id,tier:o.tier,period:o.period,currency:o.currency,amount_minor:o.amount_minor,requests_per_minute:150,term_days:17,terms_version:'sandbox-older-test-terms'};
 const priorOffer=await buildSandboxOffer(prior);
 f.env.COMMERCE_SANDBOX_DB.sqlite.prepare('UPDATE commerce_orders SET term_days=?,terms_version=?,requests_per_minute=?,offer_version=? WHERE id=?').run(prior.term_days,prior.terms_version,prior.requests_per_minute,priorOffer.version,o.id);
 const current=(await (await f.request('offers')).json()).offers.find(item=>item.id===o.offer_id);
 assert.notEqual(current.version,priorOffer.version);assert.equal(current.term_days,30);
 await settleSandboxPayment(f.env,paid(o),callbacks());
 const snapshot=await (await f.request()).json();
 assert.equal(snapshot.subscription.expires_at,new Date((1000+17*86400)*1000).toISOString());
 assert.equal(snapshot.subscription.terms_version,prior.terms_version);
 assert.equal(snapshot.orders[0].requests_per_minute,150);assert.equal(snapshot.orders[0].term_days,17);
});
