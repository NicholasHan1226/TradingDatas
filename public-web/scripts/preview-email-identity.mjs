// Local-only acceptance harness: memory-only identity DB and synthetic mail.
// Never imported by the build or Worker. No real network delivery or API keys.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import worker from '../worker/index.js';
import { createEmailIdentityHandler } from '../worker/email-identity.js';
import { identityDb } from '../tests/helpers/identity-db.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../dist/client');
const port=Number(process.env.TD_IDENTITY_PREVIEW_PORT || 5195);
const origin=`http://127.0.0.1:${port}`;
const outbox=[];
const env={EMAIL_LOGIN_ENABLED:'true',IDENTITY_DB:identityDb(),IDENTITY_PEPPER:'local-preview-only-not-a-real-secret-0123456789012345',RESEND_API_KEY:'local-synthetic-only',
  ASSETS:{async fetch(request){
    const requested=decodeURIComponent(new URL(request.url).pathname);
    const file=path.resolve(root,`.${requested==='/'?'/index.html':requested}`);
    if(!file.startsWith(`${root}/`)) return new Response('Not found',{status:404});
    try {const body=await readFile(file); const type={'.html':'text/html','.js':'application/javascript','.css':'text/css','.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp','.svg':'image/svg+xml','.woff2':'font/woff2'}[path.extname(file)] || 'application/octet-stream';
      return new Response(body,{headers:{'content-type':type}});
    } catch{return new Response('Not found',{status:404});}
  }}};
const handler=createEmailIdentityHandler({fetchImpl:async (_url,init)=>{
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
    else response=await handler(request,env) || await worker.fetch(request,env);
    res.writeHead(response.status,{...Object.fromEntries(response.headers),'set-cookie':response.headers.getSetCookie()});
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch {res.writeHead(500);res.end('Local preview error');}
});
server.listen(port,'127.0.0.1',()=>console.log(`Synthetic email identity preview: ${origin}/login ; test-only mailbox: ${origin}/__test__/mail`));
