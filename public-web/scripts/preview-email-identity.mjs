// Local-only acceptance harness: synthetic mail, optional isolated identity persistence.
// Never imported by the build or Worker. No real network delivery or API keys.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import worker from '../worker/index.js';
import { createEmailIdentityHandler } from '../worker/email-identity.js';
import { identityDb } from '../tests/helpers/identity-db.mjs';
import { openCommerceSandbox, assertSeparateSandboxFiles } from './commerce-sandbox.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../dist/client');
const port=Number(process.env.TD_IDENTITY_PREVIEW_PORT || 5195);
const origin=`http://127.0.0.1:${port}`;
const outbox=[];
assertSeparateSandboxFiles(process.env.TD_IDENTITY_PREVIEW_DB,process.env.TD_COMMERCE_SANDBOX_DB);
const env={EMAIL_LOGIN_ENABLED:'true',IDENTITY_RETENTION_ENABLED:'true',ACCOUNT_CONNECTION_ENABLED:'true',ACCOUNT_LIBRARY_ENABLED:'true',ACCOUNT_ADMIN_ENABLED:'true',SESSION_ENCRYPTION_KEY:'local-preview-only-encryption-material',ACCOUNT_API_BASE:'https://account.example.test',IDENTITY_DB:identityDb(process.env.TD_IDENTITY_PREVIEW_DB || ':memory:'),IDENTITY_PEPPER:'local-preview-only-not-a-real-secret-0123456789012345',RESEND_API_KEY:'local-synthetic-only',
  ASSETS:{async fetch(request){
    const requested=decodeURIComponent(new URL(request.url).pathname);
    const file=path.resolve(root,`.${requested==='/'?'/index.html':requested}`);
    if(!file.startsWith(`${root}/`)) return new Response('Not found',{status:404});
    try {const body=await readFile(file); const type={'.html':'text/html','.js':'application/javascript','.css':'text/css','.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp','.svg':'image/svg+xml','.woff2':'font/woff2'}[path.extname(file)] || 'application/octet-stream';
      return new Response(body,{headers:{'content-type':type}});
    } catch{return new Response('Not found',{status:404});}
  }}};
// Opt-in isolated local ledger. Default preview/production has no commerce.
if(process.env.TD_COMMERCE_SANDBOX_DB) Object.assign(env,{COMMERCE_MODE:'sandbox',COMMERCE_SANDBOX_DB:openCommerceSandbox(process.env.TD_COMMERCE_SANDBOX_DB)});
const handler=createEmailIdentityHandler({fetchImpl:async (_url,init)=>{
  if(_url.startsWith('https://account.example.test/')) {
    const key=init.headers.get('authorization');
    if(!['Bearer preview-reader-key','Bearer preview-admin-key'].includes(key)) return Response.json({error:'invalid_token'},{status:401});
    if(_url.endsWith('/portal/api/me')) return Response.json({portal:{tenant_id:'synthetic-preview',tier:'basic',scopes:key==='Bearer preview-admin-key'?['read','admin']:['read'],data_categories:['a_share'],enabled:true,minute_request_limit:200,daily_limit:null,expires_at:'2027-01-01T00:00:00Z',usage:{today_count:7}}});
    if(_url.includes('/portal/api/me/usage')) return Response.json({portal_usage:{today_count:7,history:[]}});
    if(_url.endsWith('/portal/api/me/keys')) return Response.json({api_keys:[]});
    if(_url.endsWith('/admin/api/tokens')) return Response.json({tokens:[],count:0});
    return Response.json({error:'synthetic_route_unavailable'},{status:404});
  }
  if(_url!=='https://api.resend.com/emails') throw new Error('Synthetic harness blocks unknown outbound');
  const email=JSON.parse(init.body);
  if(!email.to.every(address=>address.endsWith('@example.com'))) return Response.json({error:'use-example-com-only'},{status:400});
  outbox.push(email); return Response.json({id:`synthetic-${outbox.length}`});
}});
const server=http.createServer(async (req,res)=>{
  try {
    if(req.headers.host!==`127.0.0.1:${port}`) {res.writeHead(403);res.end();return;}
    const chunks=[];let size=0;
    for await(const chunk of req){size+=chunk.length;if(size>16384){res.writeHead(413);res.end();return;}chunks.push(chunk);}
    const headers=new Headers();for(const [key,value] of Object.entries(req.headers)){if(value) headers.set(key,String(value));}
    headers.set('cf-connecting-ip','127.0.0.1');
    const request=new Request(new URL(req.url,origin),{method:req.method,headers,...(['GET','HEAD'].includes(req.method)?{}:{body:Buffer.concat(chunks)})});
    let response;
    if(req.url==='/__test__/mail' && req.method==='GET') response=new Response(`<!doctype html><html><meta charset="utf-8"><body><h1>LOCAL SYNTHETIC MAIL — NOT SENT</h1><p>Only example.com fixtures. Memory-only; never deployed.</p><pre>${JSON.stringify(outbox,null,2).replaceAll('&','&amp;').replaceAll('<','&lt;')}</pre></body></html>`,{headers:{'content-type':'text/html; charset=utf-8','cache-control':'no-store'}});
    else if(new URL(request.url).pathname==='/__test__/viewport' && req.method==='GET') {
      const params=new URL(request.url).searchParams;
      const width=['390','768','1024'].includes(params.get('width'))?Number(params.get('width')):390;
      const page=['/docs','/connect','/bookmarks','/account/keys','/account/billing','/account/subscription'].includes(params.get('page'))?params.get('page'):'/account';
      // A real nested layout viewport for responsive review; no app-state injection.
      response=new Response(`<!doctype html><html><meta charset="utf-8"><title>Local account viewport</title><body style="margin:0;background:#d7d9dc"><nav style="padding:12px;font:14px sans-serif">LOCAL SYNTHETIC REVIEW · <a href="?width=390">390px</a> · <a href="?width=768">768px</a></nav><iframe title="Account responsive preview" src="${page}" style="display:block;width:${width}px;height:850px;max-width:100%;border:0;margin:auto"></iframe></body></html>`,{headers:{'content-type':'text/html; charset=utf-8','cache-control':'no-store'}});
    }
    else if(process.env.TD_IDENTITY_PREVIEW_ACCOUNT_UNAVAILABLE==='true' && new URL(request.url).pathname==='/api/account/me') response=new Response(JSON.stringify({error:'account_upstream_unavailable'}),{status:503,headers:{'content-type':'application/json'}});
    else response=await handler(request,env) || await worker.fetch(request,env);
    res.writeHead(response.status,{...Object.fromEntries(response.headers),'set-cookie':response.headers.getSetCookie()});
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch {res.writeHead(500);res.end('Local preview error');}
});
server.listen(port,'127.0.0.1',()=>console.log(`Synthetic email identity preview: ${origin}/login ; test-only mailbox: ${origin}/__test__/mail`));
