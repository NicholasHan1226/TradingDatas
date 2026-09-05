// Isolated sandbox commerce. Never issues credentials or modifies Portal grants.
import { BASE_PLANS, getPlanPrice } from '../src/pricing.js';
const TERMS = 'sandbox-fixed-days-v1';
const authenticated = `SELECT u.id FROM identity_users u JOIN identity_sessions s ON s.user_id=u.id
 WHERE u.id=? AND s.token_hash=? AND s.expires_at>? AND s.revoked_at IS NULL AND u.disabled_at IS NULL`;
const json = (value,status=200)=>Response.json(value,{status,headers:{'cache-control':'no-store','x-content-type-options':'nosniff'}});
const iso = time=>new Date(time*1000).toISOString();
const unavailable = ()=>({mode:'unavailable',checkout_available:false,subscription:null,orders:[],offers:[]});
function configured(env) {
 return env.COMMERCE_MODE==='sandbox' && env.COMMERCE_SANDBOX_DB && env.COMMERCE_SANDBOX_DB!==env.IDENTITY_DB;
}
// The offer version changes with every commercial field, including test terms.
// It is an opaque digest, never a price/authority supplied by the browser.
export async function buildSandboxOffer({id,tier,period,currency,amount_minor,requests_per_minute,terms_version=TERMS,term_days=period==='annual'?365:30}) {
 const commercial={id,tier,period,currency,amount_minor,requests_per_minute,environment:'sandbox',terms_version,term_days};
 const canonical=JSON.stringify([id,tier,period,currency,amount_minor,requests_per_minute,'sandbox',terms_version,term_days]);
 const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical));
 const version=`sandbox-${Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('')}`;
 return {...commercial,version};
}
async function offers() { return Promise.all(BASE_PLANS.flatMap(plan=>['monthly','annual'].map(period=>buildSandboxOffer({
 id:`${plan.id}-${period}`,tier:plan.id,period,currency:getPlanPrice(plan.id,period).currency,
 amount_minor:getPlanPrice(plan.id,period).totalMinor,requests_per_minute:plan.requestsPerMinute,
})))); }
function orderProjection(row) {
 const {id,offer_id,offer_version,tier,period,currency,amount_minor,term_days,terms_version,requests_per_minute,payment_state,provisioning_state}=row;
 return {id,offer_id,offer_version,tier,period,currency,amount_minor,term_days,terms_version,requests_per_minute,payment_state,provisioning_state,created_at:iso(row.created_at),environment:'sandbox'};
}
async function authorized(ctx) {
 return Boolean(await ctx.env.IDENTITY_DB.prepare(authenticated).bind(ctx.session.id,ctx.tokenHash,ctx.now()).first());
}
async function snapshot(ctx) {
 if(!configured(ctx.env)) return unavailable();
 const db=ctx.env.COMMERCE_SANDBOX_DB;
 const rows=await db.prepare('SELECT * FROM commerce_orders WHERE owner_id=? ORDER BY created_at DESC,id DESC LIMIT 20').bind(ctx.session.id).all();
 const sub=await db.prepare('SELECT * FROM commerce_subscriptions WHERE owner_id=?').bind(ctx.session.id).first();
 return {mode:'sandbox',checkout_available:true,offers:await offers(),orders:rows.results.map(orderProjection),subscription:sub?{
 id:sub.id,tier:sub.tier,period:sub.period,starts_at:iso(sub.starts_at),expires_at:iso(sub.expires_at),
 state:sub.expires_at>ctx.now()?'active':'expired',environment:'sandbox',terms_version:sub.terms_version,
 }:null};
}
async function boundedBody(request) {
 if(!request.headers.get('content-type')?.startsWith('application/json') || !request.body) throw Error('invalid_request');
 const reader=request.body.getReader(); let length=0,text=''; const decoder=new TextDecoder();
 try {while(true) {const {value,done}=await reader.read();if(done) return JSON.parse(text+decoder.decode());
 length+=value.byteLength;if(length>2048) {await reader.cancel();throw Error('invalid_request');}text+=decoder.decode(value,{stream:true});}}
 finally {reader.releaseLock();}
}
export async function handleCommerce(ctx) {
 const url=new URL(ctx.request.url),path=url.pathname;
 if(!['/api/account/commerce','/api/account/offers','/api/account/orders'].includes(path) && !path.startsWith('/api/account/orders/')) return null;
 try {
  if(ctx.request.headers.get('x-td-identity')!==ctx.session.id) return json({error:'identity_changed'},409);
  if(!await authorized(ctx)) return json({error:'unauthenticated'},401);
  if(url.search) return json({error:'invalid_request'},400);
  if(path==='/api/account/commerce' || path==='/api/account/offers') {
   if(ctx.request.method!=='GET') return json({error:'method_not_allowed'},405);
   const data=await snapshot(ctx);
   if(!await authorized(ctx)) return json({error:'unauthenticated'},401);
   return json(path.endsWith('/offers')?{mode:data.mode,checkout_available:data.checkout_available,offers:data.offers}:data);
  }
  if(!configured(ctx.env)) return json({error:'checkout_unavailable'},503);
  const db=ctx.env.COMMERCE_SANDBOX_DB;
  if(path==='/api/account/orders') {
   if(ctx.request.method!=='POST') return json({error:'method_not_allowed'},405);
   if(ctx.request.headers.get('origin')!==url.origin) return json({error:'origin_not_allowed'},403);
   const key=ctx.request.headers.get('idempotency-key');
   if(!key || !/^[A-Za-z0-9_-]{8,100}$/.test(key)) return json({error:'invalid_request'},400);
   let body;try {body=await boundedBody(ctx.request);}catch{return json({error:'invalid_request'},400);}
   if(!body || Array.isArray(body) || Object.keys(body).sort().join(',')!=='offer_id,offer_version') return json({error:'invalid_request'},400);
   const offer=(await offers()).find(item=>item.id===body.offer_id && item.version===body.offer_version);
   if(!offer) return json({error:'offer_changed'},409);
   if(!await authorized(ctx)) return json({error:'unauthenticated'},401);
   const id=`ord_${crypto.randomUUID()}`;
   await db.prepare(`INSERT INTO commerce_orders(id,owner_id,idempotency_key,offer_id,offer_version,tier,period,currency,amount_minor,term_days,terms_version,requests_per_minute,created_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(owner_id,idempotency_key) DO NOTHING`).bind(id,ctx.session.id,key,offer.id,offer.version,offer.tier,offer.period,offer.currency,offer.amount_minor,offer.term_days,offer.terms_version,offer.requests_per_minute,ctx.now()).run();
   const row=await db.prepare('SELECT * FROM commerce_orders WHERE owner_id=? AND idempotency_key=?').bind(ctx.session.id,key).first();
   if(row.offer_id!==offer.id || row.offer_version!==offer.version) return json({error:'idempotency_conflict'},409);
   if(!await authorized(ctx)) return json({error:'unauthenticated'},401);
   return json({mode:'sandbox',checkout_available:true,order:orderProjection(row)},row.id===id?201:200);
  }
  if(ctx.request.method!=='GET') return json({error:'method_not_allowed'},405);
  const id=path.slice('/api/account/orders/'.length);
  const row=await db.prepare('SELECT * FROM commerce_orders WHERE id=? AND owner_id=?').bind(id,ctx.session.id).first();
  if(!await authorized(ctx)) return json({error:'unauthenticated'},401);
  return row?json({mode:'sandbox',checkout_available:true,order:orderProjection(row)}):json({error:'not_found'},404);
 } catch {return json({error:'commerce_unavailable'},503);}
}

// No HTTP route invokes this function. A trusted test harness injects a verifier
// and an idempotent sandbox provisioner. verify must reject invalid signatures,
// unexpected merchant/app identities and unverified trade states before returning
// a normalized event. Provider sandbox credentials are absent.
export async function settleSandboxPayment(env,notification,{verify,provision,now=()=>Math.floor(Date.now()/1000)}={}) {
 if(!configured(env) || typeof verify!=='function' || typeof provision!=='function') throw Error('sandbox_unavailable');
 const event=await verify(notification);
 if(!event || event.environment!=='sandbox' || event.status!=='paid' || typeof event.event_id!=='string' || !event.event_id || event.event_id.length>200) throw Error('payment_unverified');
 const db=env.COMMERCE_SANDBOX_DB;
 const order=await db.prepare('SELECT * FROM commerce_orders WHERE id=?').bind(event.order_id).first();
 if(!order || event.currency!==order.currency || event.amount_minor!==order.amount_minor) throw Error('payment_mismatch');
 const previous=await db.prepare('SELECT * FROM commerce_events WHERE event_id=?').bind(event.event_id).first();
 if(previous && (previous.order_id!==order.id || previous.currency!==event.currency || previous.amount_minor!==event.amount_minor)) throw Error('event_conflict');
 await db.batch([
  db.prepare('INSERT INTO commerce_events(event_id,order_id,currency,amount_minor,verified_at) VALUES (?,?,?,?,?) ON CONFLICT(event_id) DO NOTHING').bind(event.event_id,order.id,event.currency,event.amount_minor,now()),
  db.prepare(`UPDATE commerce_orders SET payment_state='verified_paid',provisioning_state=CASE WHEN provisioning_state='active' THEN 'active' ELSE 'pending' END WHERE id=? AND EXISTS(SELECT 1 FROM commerce_events WHERE event_id=? AND order_id=?)`).bind(order.id,event.event_id,order.id),
  db.prepare(`INSERT INTO commerce_provisions(order_id,state) SELECT id,'pending' FROM commerce_orders WHERE id=? AND payment_state='verified_paid' ON CONFLICT(order_id) DO NOTHING`).bind(order.id),
 ]);
 const saved=await db.prepare('SELECT * FROM commerce_events WHERE event_id=?').bind(event.event_id).first();
 if(saved.order_id!==order.id) throw Error('event_conflict');
 const state=await db.prepare('SELECT * FROM commerce_provisions WHERE order_id=?').bind(order.id).first();
 if(state.state==='active') return {state:'active',order_id:order.id};
 await db.prepare('UPDATE commerce_provisions SET attempts=attempts+1 WHERE order_id=?').bind(order.id).run();
 try {
  // Replays/concurrent delivery may invoke the adapter more than once. Adapter
  // MUST honor this stable key; never issue production keys from this callback.
  const receipt=await provision({idempotency_key:order.id,owner_id:order.owner_id,tier:order.tier,requests_per_minute:order.requests_per_minute,term_days:order.term_days,terms_version:order.terms_version,environment:'sandbox'});
  if(receipt?.environment!=='sandbox' || receipt?.idempotency_key!==order.id || receipt?.state!=='active') throw Error('provision_unconfirmed');
  const time=now(),seconds=order.term_days*86400;
  await db.batch([
   db.prepare(`INSERT INTO commerce_subscriptions(id,owner_id,tier,period,starts_at,expires_at,terms_version)
    SELECT ?,?,?,?,?,?,? FROM commerce_provisions WHERE order_id=? AND state!='active'
    ON CONFLICT(owner_id) DO UPDATE SET tier=excluded.tier,period=excluded.period,terms_version=excluded.terms_version,expires_at=MAX(commerce_subscriptions.expires_at,excluded.starts_at)+?`).bind(`sub_${order.owner_id}`,order.owner_id,order.tier,order.period,time,time+seconds,order.terms_version,order.id,seconds),
   db.prepare(`UPDATE commerce_provisions SET state='active',last_error=NULL,completed_at=? WHERE order_id=?`).bind(time,order.id),
   db.prepare(`UPDATE commerce_orders SET provisioning_state='active' WHERE id=?`).bind(order.id),
  ]);
  return {state:'active',order_id:order.id};
 } catch {
  await db.batch([
   db.prepare(`UPDATE commerce_provisions SET state='failed',last_error='provision_unconfirmed' WHERE order_id=? AND state!='active'`).bind(order.id),
   db.prepare(`UPDATE commerce_orders SET provisioning_state='failed' WHERE id=? AND provisioning_state!='active'`).bind(order.id),
  ]);
  const current=await db.prepare('SELECT state FROM commerce_provisions WHERE order_id=?').bind(order.id).first();
  return {state:current.state,order_id:order.id};
 }
}
