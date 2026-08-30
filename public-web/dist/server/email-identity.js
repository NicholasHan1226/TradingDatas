// Isolated account control plane. This module cannot mint data/API entitlements.
const COOKIE = 'td_identity_session';
const TTL = 8 * 60 * 60;
const CHALLENGE_TTL = 10 * 60;
const encoder = new TextEncoder();
const EMAIL_FROM = 'TradingDatas <login@account.tradingdatas.com>';
const cookie = (value = '', age = TTL) => `${COOKIE}=${value}; Path=/api/account; Max-Age=${age}; HttpOnly; Secure; SameSite=Strict`;
const clearLegacy = 'td_account_session=; Path=/api/account; Max-Age=0; HttpOnly; Secure; SameSite=Strict';
function json(payload, status = 200, cookies = []) {
  const headers = new Headers({'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'});
  for (const value of cookies) headers.append('set-cookie', value);
  if (status === 429) headers.set('retry-after', '60');
  return new Response(JSON.stringify(payload), {status, headers});
}
function readCookie(request, name) {
  return (request.headers.get('cookie') || '').split(';').map(v=>v.trim()).find(v=>v.startsWith(`${name}=`))?.slice(name.length+1) || '';
}
export function emailConfigured(env) {
  return env.EMAIL_LOGIN_ENABLED === 'true' && Boolean(env.IDENTITY_DB && typeof env.IDENTITY_PEPPER === 'string' && env.IDENTITY_PEPPER.length >= 32 && env.RESEND_API_KEY);
}
function canonicalEmail(value) {
  if (typeof value !== 'string' || value.length > 254) return null;
  const email = value.trim().toLowerCase();
  // Deliberately conservative; do not collapse dots, aliases, or plus addresses.
  return /^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$/.test(email) && email.split('@')[0].length <= 64 ? email : null;
}
async function boundedJson(message) {
  if (!message.headers.get('content-type')?.toLowerCase().startsWith('application/json')) throw new Error('invalid_request');
  if (Number(message.headers.get('content-length') || 0) > 4096 || !message.body) throw new Error('invalid_request');
  const reader = message.body.getReader(); const chunks=[]; let size=0;
  try {
    while (true) {
      const {done,value}=await reader.read(); if(done) break;
      size+=value.byteLength; if(size>4096) {await reader.cancel(); throw new Error('invalid_request');} chunks.push(value);
    }
  } finally {reader.releaseLock();}
  const bytes=new Uint8Array(size); let offset=0; for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  return JSON.parse(new TextDecoder().decode(bytes));
}
const hex = bytes => Array.from(new Uint8Array(bytes), b=>b.toString(16).padStart(2,'0')).join('');
const randomToken = () => hex(crypto.getRandomValues(new Uint8Array(32)));
async function digest(value) {return hex(await crypto.subtle.digest('SHA-256',encoder.encode(value)));}
async function hmacKey(secret) {return crypto.subtle.importKey('raw',encoder.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign','verify']);}
async function mac(key, value) {return hex(await crypto.subtle.sign('HMAC',key,encoder.encode(value)));}
async function matches(key, value, signature) {
  const bytes=Uint8Array.from(signature.match(/../g) || [], pair=>parseInt(pair,16));
  return crypto.subtle.verify('HMAC',key,bytes,encoder.encode(value));
}
function randomCode() {
  let value; do {value=crypto.getRandomValues(new Uint32Array(1))[0];} while(value>=4_200_000_000);
  return String(value % 100_000_000).padStart(8,'0');
}
async function takeRate(db,key,now,limit,window=3600) {
  const start=Math.floor(now/window)*window;
  return Boolean(await db.prepare(`INSERT INTO identity_rate_buckets(bucket_key,hits,expires_at) VALUES (?,1,?)
    ON CONFLICT(bucket_key) DO UPDATE SET hits=hits+1 WHERE hits<? RETURNING hits`)
    .bind(`${key}:${start}`,start+window,limit).first());
}
async function pruneExpired(db, now) {
  // Bounded opportunistic cleanup; no timer or external production migration.
  await db.batch([
    db.prepare('DELETE FROM identity_challenges WHERE id IN (SELECT id FROM identity_challenges WHERE expires_at<=? LIMIT 100)').bind(now),
    db.prepare('DELETE FROM identity_sessions WHERE token_hash IN (SELECT token_hash FROM identity_sessions WHERE expires_at<=? LIMIT 100)').bind(now),
    db.prepare('DELETE FROM identity_rate_buckets WHERE bucket_key IN (SELECT bucket_key FROM identity_rate_buckets WHERE expires_at<=? LIMIT 100)').bind(now),
    db.prepare('DELETE FROM identity_send_cooldowns WHERE email_hash IN (SELECT email_hash FROM identity_send_cooldowns WHERE next_send_at<=? LIMIT 100)').bind(now-3600),
  ]);
}
function identityProjection(user, expiresAt) {
  return {identity:{kind:'email',user_id:user.id,email:user.email,email_verified:true,tenant_id:null,
    subscription_state:'not_subscribed',data_categories:[],session_expires_at:new Date(expiresAt*1000).toISOString()}};
}
async function readSession(db, token, now) {
  if(!/^[a-f0-9]{64}$/.test(token)) return null;
  return db.prepare(`SELECT u.id,u.email,s.expires_at FROM identity_sessions s JOIN identity_users u ON u.id=s.user_id
    WHERE s.token_hash=? AND s.expires_at>? AND s.revoked_at IS NULL AND u.disabled_at IS NULL`).bind(await digest(token),now).first();
}

// Dependency injection is for deterministic local tests. Production uses fetch
// and the real clock; no fixture key/code/provider switch is exposed over HTTP.
export function createEmailIdentityHandler({fetchImpl=(...args)=>fetch(...args), now=()=>Math.floor(Date.now()/1000)}={}) {
  return async function handleEmailIdentity(request, env) {
    const path=new URL(request.url).pathname;
    const token=readCookie(request,COOKIE);
    const emailRoute=path.startsWith('/api/account/email/');
    if(path==='/api/account/auth-methods') return request.method==='GET' ? json({email:emailConfigured(env),phone:false}) : json({error:'method_not_allowed'},405);
    if(!emailRoute && !token) {
      if(path==='/api/account/me' && emailConfigured(env) && !readCookie(request,'td_account_session')) return json({error:'unauthenticated'},401);
      return null; // Preserve the existing access-key bridge.
    }
    if(request.method!=='GET' && request.headers.get('origin')!==new URL(request.url).origin) return json({error:'origin_not_allowed'},403);
    try {
      const db=env.IDENTITY_DB;
      if(token && path==='/api/account/session' && request.method==='DELETE') {
        if(!db) return json({error:'identity_unavailable'},503);
        await db.prepare('UPDATE identity_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL').bind(now(),await digest(token)).run();
        return json({signed_out:true},200,[cookie('',0),clearLegacy]);
      }
      if(emailRoute) {
        if(!['/api/account/email/challenge','/api/account/email/verify'].includes(path)) return json({error:'not_found'},404);
        if(request.method!=='POST') return json({error:'method_not_allowed'},405);
        if(!emailConfigured(env)) return json({error:'email_login_unavailable'},503);
        let payload; try {payload=await boundedJson(request);} catch {return json({error:'invalid_request'},400);}
        const email=canonicalEmail(payload?.email);
        if(!email) return json({error:'invalid_request'},400);
        const time=now(); const key=await hmacKey(env.IDENTITY_PEPPER);
        const emailHash=await mac(key,`email:${email}`);
        // Cloudflare overwrites this header at the public Worker boundary. Missing
        // client evidence fails closed; never trust X-Forwarded-For as a fallback.
        const ip=request.headers.get('cf-connecting-ip');
        if(!ip) return json({error:'identity_unavailable'},503);
        const ipHash=await mac(key,`ip:${ip}`);
        // Bound attacker-controlled bucket cardinality before per-IP/email rows.
        if(!await takeRate(db,'identity-attempt-global',time,1000,600)) return json({error:'rate_limited'},429);
        if(path.endsWith('/challenge')) {
          if(!await takeRate(db,`send-ip:${ipHash}`,time,10) || !await takeRate(db,`send-email:${emailHash}`,time,5) || !await takeRate(db,'send-global',time,100)) return json({error:'rate_limited'},429);
          const cooldown=await db.prepare(`INSERT INTO identity_send_cooldowns(email_hash,next_send_at) VALUES (?,?)
            ON CONFLICT(email_hash) DO UPDATE SET next_send_at=excluded.next_send_at WHERE next_send_at<=? RETURNING email_hash`).bind(emailHash,time+60,time).first();
          if(!cooldown) return json({error:'rate_limited'},429);
          await pruneExpired(db,time);
          const id=crypto.randomUUID(); const code=randomCode(); const codeHash=await mac(key,`${id}:${email}:${code}`);
          await db.prepare(`INSERT INTO identity_challenges(email_hash,id,email,code_hash,expires_at,attempts,accepted,consumed_at) VALUES (?,?,?,?,?,0,0,NULL)
            ON CONFLICT(email_hash) DO UPDATE SET id=excluded.id,email=excluded.email,code_hash=excluded.code_hash,expires_at=excluded.expires_at,attempts=0,accepted=0,consumed_at=NULL`)
            .bind(emailHash,id,email,codeHash,time+CHALLENGE_TTL).run();
          const zh=payload.locale==='zh';
          let result;
          try {
            const response=await fetchImpl('https://api.resend.com/emails',{method:'POST',redirect:'manual',signal:AbortSignal.timeout(8000),
              headers:{authorization:`Bearer ${env.RESEND_API_KEY}`,'content-type':'application/json','idempotency-key':`td-login/${id}`},
              body:JSON.stringify({from:EMAIL_FROM,to:[email],subject:zh?'TradingDatas 登录验证码':'Your TradingDatas sign-in code',
                text:zh?`你的 TradingDatas 验证码是 ${code}，10 分钟内有效，仅可使用一次。请勿分享。若非本人操作，请忽略此邮件。`:`Your TradingDatas sign-in code is ${code}. It expires in 10 minutes and can be used once. Do not share it. If you did not request this, ignore this email.`})});
            if(!response.ok) {await response.body?.cancel(); throw new Error('delivery_unavailable');}
            result=await boundedJson(response);
            if(typeof result.id!=='string' || !result.id || result.id.length>200) throw new Error('delivery_unavailable');
          } catch {
            await db.prepare('DELETE FROM identity_challenges WHERE id=? AND accepted=0').bind(id).run();
            return json({error:'delivery_unavailable'},503);
          }
          await db.prepare('UPDATE identity_challenges SET accepted=1 WHERE id=?').bind(id).run();
          // Provider acceptance is not mailbox delivery; no known-user lookup here.
          return json({challenge_id:id,delivery:'accepted',expires_in:CHALLENGE_TTL,retry_after:60},202);
        }
        if(!await takeRate(db,`verify-ip:${ipHash}`,time,40,600)) return json({error:'rate_limited'},429);
        if(typeof payload.challenge_id!=='string' || !/^[a-f0-9-]{36}$/.test(payload.challenge_id) || typeof payload.code!=='string' || !/^\d{8}$/.test(payload.code)) return json({error:'invalid_code'},400);
        const row=await db.prepare(`UPDATE identity_challenges SET attempts=attempts+1 WHERE id=? AND email_hash=? AND expires_at>? AND accepted=1
          AND consumed_at IS NULL AND attempts<5 RETURNING email,code_hash`).bind(payload.challenge_id,emailHash,time).first();
        if(!row || !await matches(key,`${payload.challenge_id}:${email}:${payload.code}`,row.code_hash)) return json({error:'invalid_code'},400);
        const consumed=await db.prepare('UPDATE identity_challenges SET consumed_at=? WHERE id=? AND consumed_at IS NULL AND expires_at>? RETURNING email')
          .bind(time,payload.challenge_id,time).first();
        if(!consumed) return json({error:'invalid_code'},400);
        const sessionToken=randomToken(); const tokenHash=await digest(sessionToken); const expiresAt=time+TTL;
        const results=await db.batch([
          db.prepare('INSERT INTO identity_users(id,email,created_at) VALUES (?,?,?) ON CONFLICT(email) DO NOTHING').bind(crypto.randomUUID(),email,time),
          db.prepare('INSERT INTO identity_sessions(token_hash,user_id,created_at,expires_at) SELECT ?,id,?,? FROM identity_users WHERE email=? AND disabled_at IS NULL').bind(tokenHash,time,expiresAt,email),
          db.prepare('SELECT u.id,u.email FROM identity_users u JOIN identity_sessions s ON s.user_id=u.id WHERE s.token_hash=?').bind(tokenHash),
        ]);
        const user=results[2]?.results?.[0]; if(!user) return json({error:'invalid_code'},400);
        return json(identityProjection(user,expiresAt),200,[cookie(sessionToken),clearLegacy]);
      }
      // A present email cookie never silently falls back to an old API-key cookie.
      if(!db) return json({error:'identity_unavailable'},503);
      const session=await readSession(db,token,now());
      if(!session) return json({error:'unauthenticated'},401,[cookie('',0),clearLegacy]);
      if(path==='/api/account/me') return request.method==='GET' ? json(identityProjection(session,session.expires_at)) : json({error:'method_not_allowed'},405);
      if(path==='/api/account/session' && request.method==='POST') return json({error:'sign_out_first'},409);
      if(path==='/api/account/usage' || path==='/api/account/keys' || path.startsWith('/api/account/keys/')) return json({error:'subscription_required'},403);
      return json({error:'not_found'},404);
    } catch {return json({error:'identity_unavailable'},503);}
  };
}
export const handleEmailIdentity=createEmailIdentityHandler();
