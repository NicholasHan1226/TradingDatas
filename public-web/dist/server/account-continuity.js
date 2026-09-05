import { portalKeyError, isPortalKeyPath } from './portal-errors.js';
// Account control plane only. All authority is re-read from the existing backend.
const enc = new TextEncoder();
const resourceKey = /^(dataset|research|method|doc):[a-z0-9][a-z0-9-]{0,159}$/;
const authorized = `SELECT u.id FROM identity_users u JOIN identity_sessions s ON s.user_id=u.id
  WHERE u.id=? AND s.token_hash=? AND s.expires_at>? AND s.revoked_at IS NULL AND u.disabled_at IS NULL`;

function json(payload, status=200) {
  return Response.json(payload,{status,headers:{'cache-control':'no-store','x-content-type-options':'nosniff',...(status===429?{'retry-after':'60'}:{})}});
}
async function readJson(message, limit=16384) {
  if(!message.headers.get('content-type')?.toLowerCase().startsWith('application/json') || !message.body) throw new Error('invalid_json');
  if(Number(message.headers.get('content-length')||0)>limit) throw new Error('too_large');
  const reader=message.body.getReader(); let size=0,text=''; const decoder=new TextDecoder();
  try {
    while(true) {
      const {done,value}=await reader.read(); if(done) return JSON.parse(text+decoder.decode());
      size+=value.byteLength; if(size>limit) {await reader.cancel(); throw new Error('too_large');}
      text+=decoder.decode(value,{stream:true});
    }
  } finally {reader.releaseLock();}
}
function exactObject(value, fields) {
  return value && !Array.isArray(value) && typeof value==='object' && Object.keys(value).length===fields.length && fields.every(field=>Object.hasOwn(value,field));
}
async function rate(db,id,time,kind,limit) {
  const window=Math.floor(time/60)*60;
  return Boolean(await db.prepare(`INSERT INTO identity_rate_buckets(bucket_key,hits,expires_at) VALUES (?,1,?)
    ON CONFLICT(bucket_key) DO UPDATE SET hits=hits+1 WHERE hits<? RETURNING hits`)
    .bind(`account-${kind}:${id}:${window}`,window+60,limit).first());
}
const authArgs=ctx=>[ctx.session.id,ctx.tokenHash,ctx.now()];
async function stillSignedIn(ctx) {return Boolean(await ctx.env.IDENTITY_DB.prepare(authorized).bind(...authArgs(ctx)).first());}
function identityMatches(ctx) {return ctx.request.headers.get('x-td-identity')===ctx.session.id;}

export function accountCapabilities(env) {
  const connection=env.ACCOUNT_CONNECTION_ENABLED==='true' && typeof env.SESSION_ENCRYPTION_KEY==='string' && env.SESSION_ENCRYPTION_KEY.length>=32 && Boolean(env.ACCOUNT_API_BASE);
  return {library:env.ACCOUNT_LIBRARY_ENABLED==='true',connection,admin_console:connection && env.ACCOUNT_ADMIN_ENABLED==='true'};
}

async function librarySnapshot(ctx) {
  const result=await ctx.env.IDENTITY_DB.prepare(`SELECT resource_key FROM account_bookmarks
    WHERE user_id IN (${authorized}) ORDER BY created_at DESC,resource_key LIMIT 500`).bind(...authArgs(ctx)).all();
  if(!await stillSignedIn(ctx)) return json({error:'unauthenticated'},401);
  return json({bookmarks:{user_id:ctx.session.id,keys:result.results.map(row=>row.resource_key)}});
}

async function handleLibrary(ctx,path) {
  const {env,request,session}=ctx;
  if(!accountCapabilities(env).library) return json({error:'library_unavailable'},503);
  if(!identityMatches(ctx)) return json({error:'identity_changed'},409);
  const method=request.method;
  if(path==='/api/account/bookmarks') return method==='GET'?librarySnapshot(ctx):json({error:'method_not_allowed'},405);
  if(!['/api/account/bookmarks/item','/api/account/bookmarks/import'].includes(path)) return json({error:'not_found'},404);
  if(path.endsWith('/item')?!['PUT','DELETE'].includes(method):method!=='POST') return json({error:'method_not_allowed'},405);
  if(!await rate(env.IDENTITY_DB,session.id,ctx.now(),'library',60)) return json({error:'rate_limited'},429);
  let body; try {body=await readJson(request);} catch {return json({error:'invalid_request'},400);}
  let keys;
  if(path.endsWith('/import')) {
    if(!exactObject(body,['keys']) || !Array.isArray(body.keys) || body.keys.length<1 || body.keys.length>100) return json({error:'invalid_request'},400);
    keys=[...new Set(body.keys)];
  } else {
    if(!exactObject(body,['key'])) return json({error:'invalid_request'},400);
    keys=[body.key];
  }
  if(keys.some(key=>typeof key!=='string' || !resourceKey.test(key))) return json({error:'invalid_request'},400);
  const db=env.IDENTITY_DB;
  try {
    // D1 batch is transactional. Auth is part of every mutation, not just an
    // earlier read; the SQL trigger makes imports all-or-nothing at 500 items.
    await db.batch(keys.map(key=>method==='DELETE'
      ?db.prepare(`DELETE FROM account_bookmarks WHERE resource_key=? AND user_id IN (${authorized})`).bind(key,...authArgs(ctx))
      :db.prepare(`INSERT OR IGNORE INTO account_bookmarks(user_id,resource_key,created_at)
         SELECT id,?,? FROM (${authorized})`).bind(key,ctx.now(),...authArgs(ctx))));
  } catch(error) {
    if(String(error.message).includes('library_full')) return json({error:'library_full'},409);
    throw error;
  }
  return librarySnapshot(ctx);
}

function encode(bytes) {return btoa(String.fromCharCode(...bytes)).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');}
function decode(value) {return Uint8Array.from(atob(value.replaceAll('-','+').replaceAll('_','/')),char=>char.charCodeAt(0));}
async function encryptionKey(secret) {
  const raw=await crypto.subtle.digest('SHA-256',enc.encode(secret));
  return crypto.subtle.importKey('raw',raw,{name:'AES-GCM'},false,['encrypt','decrypt']);
}
async function sealCredential(key,ctx) {
  const iv=crypto.getRandomValues(new Uint8Array(12));
  const data=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:enc.encode(`td-connection-v1:${ctx.session.id}`)},await encryptionKey(ctx.env.SESSION_ENCRYPTION_KEY),enc.encode(key));
  return `v1.${encode(iv)}.${encode(new Uint8Array(data))}`;
}
async function openCredential(box,ctx) {
  const [version,iv,data,...rest]=box.split('.');
  if(version!=='v1' || rest.length || box.length>4096) throw new Error('invalid_connection');
  const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:decode(iv),additionalData:enc.encode(`td-connection-v1:${ctx.session.id}`)},await encryptionKey(ctx.env.SESSION_ENCRYPTION_KEY),decode(data));
  const key=new TextDecoder().decode(plain);
  if(!key || key.length>1024) throw new Error('invalid_connection');
  return key;
}
export const ACCOUNT_CATALOG_MAX_BYTES = 2 * 1024 * 1024;

// A projection of the caller-authorized catalog, never a grant or health rewrite.
export function domesticCatalogProjection(payload) {
  if (!payload || !Array.isArray(payload.data) || payload.next_cursor != null) throw new Error('invalid_catalog_projection');
  return {api_version:payload.api_version, catalog_version:payload.catalog_version, request_id:payload.request_id,
    data:payload.data.filter(row => typeof row?.dataset_id==='string'
      && (row.dataset_id.startsWith('cn.') || row.dataset_id.startsWith('global.news.'))
      && !String(row.market || '').toUpperCase().startsWith('CRYPTO')), next_cursor:null};
}

async function upstream(ctx,path,key,init={},bodyLimit=512*1024) {
  const base=new URL(ctx.env.ACCOUNT_API_BASE);
  if(base.protocol!=='https:' || base.username || base.password || base.search || base.hash) throw new Error('invalid_backend');
  const headers=new Headers({'authorization':`Bearer ${key}`,'accept':'application/json'});
  if(init.body!==undefined) headers.set('content-type','application/json');
  const response=await ctx.fetchImpl(new URL(path,base).toString(),{...init,headers,redirect:'manual',signal:AbortSignal.timeout(path==='/v1/catalog' && bodyLimit===ACCOUNT_CATALOG_MAX_BYTES?20000:8000)});
  if(response.status>=300 && response.status<400) {await response.body?.cancel(); throw new Error('redirect_rejected');}
  if(!response.ok) {
    if(response.status===400 && isPortalKeyPath(path)) {
      let error=null;
      try {error=portalKeyError(await readJson(response,4096));} catch {await response.body?.cancel().catch(()=>{});}
      return {status:400,error};
    }
    await response.body?.cancel(); return {status:response.status};
  }
  return {status:response.status,payload:await readJson(response,bodyLimit)};
}
function validPortal(portal) {
  return portal && typeof portal.tenant_id==='string' && portal.tenant_id.length>0 && portal.tenant_id.length<=200 && typeof portal.tier==='string'
    && portal.enabled===true && Array.isArray(portal.scopes) && portal.scopes.every(scope=>typeof scope==='string')
    && Array.isArray(portal.data_categories) && portal.data_categories.every(category=>['a_share','crypto','news'].includes(category));
}
async function readConnection(ctx) {
  if(!accountCapabilities(ctx.env).connection) return {state:'unavailable'};
  const row=await ctx.env.IDENTITY_DB.prepare(`SELECT c.* FROM account_connections c WHERE c.user_id IN (${authorized})`).bind(...authArgs(ctx)).first();
  if(!row) return {state:'none'};
  try {
    const key=await openCredential(row.credential_box,ctx);
    const result=await upstream(ctx,'/portal/api/me',key);
    if([401,403].includes(result.status)) return {state:'invalid',present:true};
    if(result.status!==200 || !validPortal(result.payload?.portal)) return {state:'unavailable',present:true};
    if(result.payload.portal.tenant_id!==row.tenant_id) return {state:'invalid',present:true};
    // Do not finish a delayed read using a connection deleted/replaced meanwhile.
    const current=await ctx.env.IDENTITY_DB.prepare(`SELECT 1 FROM account_connections WHERE user_id IN (${authorized}) AND credential_box=?`).bind(...authArgs(ctx),row.credential_box).first();
    if(!current) return {state:'invalid'};
    return {state:'connected',present:true,portal:result.payload.portal,admin:result.payload.portal.scopes.includes('admin') || result.payload.portal.tier==='internal',key,box:row.credential_box};
  } catch {return {state:'unavailable',present:true};}
}
export async function accountContinuityProjection(ctx) {
  const capabilities=accountCapabilities(ctx.env);
  const result=capabilities.connection?await readConnection(ctx):{state:'unavailable'};
  // Never serialize the internal credential or encrypted envelope.
  return {capabilities,data_access:result.state==='connected'?{state:'connected',present:true,portal:result.portal,admin:result.admin}:{state:result.state,present:result.present===true}};
}

async function handleConnection(ctx) {
  const {env,session,request}=ctx; const db=env.IDENTITY_DB;
  if(!accountCapabilities(env).connection) return json({error:'connection_unavailable'},503);
  if(!identityMatches(ctx)) return json({error:'identity_changed'},409);
  if(!['POST','DELETE'].includes(request.method)) return json({error:'method_not_allowed'},405);
  if(session.created_at<ctx.now()-600) return json({error:'recent_sign_in_required'},403);
  if(!await rate(db,session.id,ctx.now(),'connection',6)) return json({error:'rate_limited'},429);
  if(request.method==='DELETE') {
    await db.prepare(`DELETE FROM account_connections WHERE user_id IN (${authorized} AND s.created_at>=?)`).bind(...authArgs(ctx),ctx.now()-600).run();
    return await stillSignedIn(ctx)?json({disconnected:true,user_id:session.id}):json({error:'unauthenticated'},401);
  }
  let body; try {body=await readJson(request,4096);} catch {return json({error:'invalid_request'},400);}
  if(!exactObject(body,['access_key']) || typeof body.access_key!=='string' || !body.access_key.trim() || body.access_key.trim().length>1024 || /[\r\n]/.test(body.access_key)) return json({error:'invalid_request'},400);
  if(await db.prepare('SELECT 1 FROM account_connections WHERE user_id=?').bind(session.id).first()) return json({error:'connection_exists'},409);
  const key=body.access_key.trim();
  const result=await upstream(ctx,'/portal/api/me',key);
  if([401,403].includes(result.status)) return json({error:'invalid_access_key'},403);
  if(result.status!==200 || !validPortal(result.payload?.portal)) return json({error:'connection_unavailable'},503);
  const box=await sealCredential(key,ctx);
  const inserted=await db.prepare(`INSERT INTO account_connections(user_id,credential_box,tenant_id,created_at)
    SELECT id,?,?,? FROM (${authorized} AND s.created_at>=?)
    WHERE true ON CONFLICT(user_id) DO NOTHING RETURNING user_id`)
    .bind(box,result.payload.portal.tenant_id,ctx.now(),...authArgs(ctx),ctx.now()-600).first();
  if(!inserted) return json({error:'connection_unconfirmed'},409);
  return json({connected:true,user_id:session.id});
}

async function handleDataAccess(ctx,path) {
  if(!accountCapabilities(ctx.env).connection) return json({error:'subscription_required'},403);
  if(!identityMatches(ctx)) return json({error:'identity_changed'},409);
  const url=new URL(ctx.request.url); let target;
  if(path==='/api/account/catalog') {
    if(url.search) return json({error:'invalid_request'},400);
    target='/v1/catalog';
  } else if(path==='/api/account/usage') {
    const days=url.searchParams.get('days')||'30';
    if(!/^\d{1,2}$/.test(days) || Number(days)<1 || Number(days)>90 || [...url.searchParams.keys()].some(key=>key!=='days')) return json({error:'invalid_request'},400);
    target=`/portal/api/me/usage?days=${days}`;
  } else if(path==='/api/account/keys') target='/portal/api/me/keys';
  else {
    const id=path.match(/^\/api\/account\/keys\/(key_[a-f0-9]{16})$/)?.[1];
    if(!id) return json({error:'not_found'},404);
    target=`/portal/api/me/keys/${id}`;
  }
  const methods=path==='/api/account/keys'?['GET','POST']:path.startsWith('/api/account/keys/')?['PATCH']:['GET'];
  if(!methods.includes(ctx.request.method)) return json({error:'method_not_allowed'},405);
  if(!await rate(ctx.env.IDENTITY_DB,ctx.session.id,ctx.now(),'portal',120)) return json({error:'rate_limited'},429);
  const connection=await readConnection(ctx);
  if(connection.state!=='connected') return json({error:connection.state==='unavailable'?'connection_unavailable':'subscription_required'},connection.state==='unavailable'?503:403);
  let body;
  if(ctx.request.method!=='GET') {
    try {body=JSON.stringify(await readJson(ctx.request));} catch {return json({error:'invalid_request'},400);}
  }
  if(!await currentConnection(ctx,connection.box)) return json({error:'identity_changed'},409);
  const result=await upstream(ctx,target,connection.key,{method:ctx.request.method,body},path==='/api/account/catalog'?ACCOUNT_CATALOG_MAX_BYTES:512*1024);
  if(!await currentConnection(ctx,connection.box)) return json({error:'identity_changed'},409);
  // A revoked data credential is not an invalid email session.
  if([401,403].includes(result.status)) return json({error:'subscription_required'},403);
  if(result.status===429) return json({error:'rate_limited'},429);
  if(result.status===400 && result.error) return json({error:result.error},400);
  if(!result.payload) return json({error:'connection_unavailable'},503);
  return json(path==='/api/account/catalog'?domesticCatalogProjection(result.payload):result.payload,result.status);
}
async function currentConnection(ctx,box) {
  return Boolean(await ctx.env.IDENTITY_DB.prepare(`SELECT 1 FROM account_connections WHERE user_id IN (${authorized}) AND credential_box=?`).bind(...authArgs(ctx),box).first());
}
async function handleAdmin(ctx,path) {
  if(!accountCapabilities(ctx.env).admin_console) return json({error:'admin_unavailable'},503);
  if(!identityMatches(ctx)) return json({error:'identity_changed'},409);
  // Explicit allowlist, never an arbitrary forwarding URL. The upstream still
  // authorizes every operation using exactly the already-linked credential.
  const target=path.slice('/api/account/admin'.length);
  const routes={
    '/admin/api/tokens':['GET','POST'], '/admin/api/usage':['GET'],
    '/admin/api/usage/history':['GET'], '/admin/api/collection/status':['GET'],
    '/admin/api/data/overview':['GET'], '/admin/api/health/alerts':['GET'],
    '/v1/catalog':['GET'], '/v1/query':['POST'],
  };
  const methods=routes[target] || (/^\/admin\/api\/tokens\/[a-f0-9]{64}$/.test(target)?['PATCH','DELETE']:null);
  if(!methods) return json({error:'not_found'},404);
  if(!methods.includes(ctx.request.method)) return json({error:'method_not_allowed'},405);
  if(!await rate(ctx.env.IDENTITY_DB,ctx.session.id,ctx.now(),'admin',120)) return json({error:'rate_limited'},429);
  const connection=await readConnection(ctx);
  if(connection.state!=='connected') return json({error:'admin_access_required'},403);
  if(!connection.admin) return json({error:'admin_access_required'},403);
  const mutation=ctx.request.method!=='GET' && target!=='/v1/query';
  if(mutation && ctx.session.created_at<ctx.now()-600) return json({error:'recent_sign_in_required'},403);
  let body;
  if(!['GET','DELETE'].includes(ctx.request.method)) {
    try {body=JSON.stringify(await readJson(ctx.request));} catch {return json({error:'invalid_request'},400);}
  }
  const search=new URL(ctx.request.url).search;
  if(search.length>2048) return json({error:'invalid_request'},400);
  if(!await currentConnection(ctx,connection.box)) return json({error:'identity_changed'},409);
  const result=await upstream(ctx,`${target}${search}`,connection.key,{method:ctx.request.method,body});
  if(!await currentConnection(ctx,connection.box)) return json({error:'identity_changed'},409);
  if([401,403].includes(result.status)) return json({error:'admin_access_required'},403);
  if(result.status===429) return json({error:'rate_limited'},429);
  if(!result.payload) return json({error:'admin_request_unavailable'},503);
  return json(result.payload,result.status);
}
export async function handleAccountContinuity(ctx) {
  const path=new URL(ctx.request.url).pathname;
  if(path==='/api/account/bookmarks' || path.startsWith('/api/account/bookmarks/')) return handleLibrary(ctx,path);
  if(path==='/api/account/connection') return handleConnection(ctx);
  if(path.startsWith('/api/account/admin/')) return handleAdmin(ctx,path);
  if(path==='/api/account/catalog' || path==='/api/account/usage' || path==='/api/account/keys' || path.startsWith('/api/account/keys/')) return handleDataAccess(ctx,path);
  return null;
}
