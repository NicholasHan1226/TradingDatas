import test from 'node:test';
import assert from 'node:assert/strict';
import {handleDataApi} from '../worker/data-api.js';
import worker from '../worker/index.js';
const env={ACCOUNT_API_BASE:'https://backend.example',SESSION_ENCRYPTION_KEY:'never-use-this'};
const req=(path='/v1/catalog',init={})=>new Request(`https://site.example${path}`,{...init,headers:{authorization:'Bearer caller-key',...init.headers}});
const error=async(response,status,code)=>{
  assert.equal(response.status,status);
  const payload=await response.json();
  assert.equal(payload.api_version,'v1');assert.equal(payload.error.code,code);
  assert.equal(typeof payload.error.message,'string');assert.equal(typeof payload.error.retryable,'boolean');
  assert.ok(payload.request_id);assert.equal(payload.receipt,undefined);
  assert.equal(response.headers.get('cache-control'),'no-store');
};
test('only exact data methods route, unknown v1 paths never become the site shell',async()=>{
  const noFetch=()=>{throw new Error('must not fetch');};
  for(const path of ['/v1','/v1/other','/v1/catalog/']) await error(await handleDataApi(req(path),env,noFetch),404,'not_found');
  await error(await handleDataApi(req('/v1/catalog',{method:'POST'}),env,noFetch),405,'method_not_allowed');
  await error(await handleDataApi(req('/v1/query?x=1',{method:'POST'}),env,noFetch),400,'invalid_request');
  const options=await handleDataApi(req('/v1/query',{method:'OPTIONS'}),env,noFetch);
  assert.equal(options.status,204);assert.equal(options.headers.get('allow'),'POST, OPTIONS');
  await error(await worker.fetch(req('/v1/unknown'),{ASSETS:{fetch:noFetch}}),404,'not_found');
});
test('caller Authorization is required; cookie and access-key headers cannot supply data credentials',async()=>{
  for(const authorization of ['', 'Basic abc','Bearer a, Bearer b','Bearer a b']) {
    await error(await handleDataApi(req('/v1/catalog',{headers:{authorization,cookie:'td_account_session=secret','x-api-key':'other'}}),env,()=>assert.fail('called')),401,'unauthenticated');
  }
});
test('catalog preserves authenticated JSON bytes and query params while filtering headers',async()=>{
  const payload=' {"api_version":"v1","datasets":[],"metadata":{"receipt":"source-only"}} ';
  const response=await handleDataApi(req('/v1/catalog?cursor=abc%2Bdef',{headers:{cookie:'private','x-forwarded-for':'spoof','cf-connecting-ip':'spoof'}}),env,async(url,init)=>{
    assert.equal(String(url),'https://backend.example/v1/catalog?cursor=abc%2Bdef');
    assert.deepEqual([...init.headers.keys()].sort(),['accept','authorization']);
    assert.equal(init.headers.get('authorization'),'Bearer caller-key');assert.equal(init.redirect,'manual');assert.ok(init.signal);
    return new Response(payload,{headers:{'content-type':'application/json','set-cookie':'private','location':'private','content-length':'999','retry-after':'60'}});
  });
  assert.equal(await response.text(),payload);assert.equal(response.headers.get('set-cookie'),null);assert.equal(response.headers.get('location'),null);
  assert.equal(response.headers.get('content-length'),null);assert.equal(response.headers.get('retry-after'),'60');
});
test('query forwards original bytes with fixed length and delegates schema validation',async()=>{
  const bytes=new TextEncoder().encode('{ "dataset_id": "中文", "unknown": true }');
  const response=await handleDataApi(req('/v1/query',{method:'POST',headers:{'content-type':'application/json; charset=utf-8'},body:bytes}),env,async(url,init)=>{
    assert.equal(String(url),'https://backend.example/v1/query');assert.equal(init.headers.get('content-length'),String(bytes.length));
    assert.deepEqual(init.body,bytes);assert.equal(init.headers.has('transfer-encoding'),false);
    return Response.json({api_version:'v1',request_id:'backend',error:{code:'invalid_request',message:'request is invalid',retryable:false}},{status:400});
  });
  assert.equal(response.status,400);assert.equal((await response.json()).request_id,'backend');
});
test('query bounds declared and streamed bodies, rejects mismatches and content encoding',async()=>{
  const noFetch=()=>assert.fail('must not call upstream');
  await error(await handleDataApi(req('/v1/query',{method:'POST',headers:{'content-type':'application/json','content-length':'65537'},body:'x'}),env,noFetch),413,'budget_exceeded');
  let cancelled=false;
  const body=new ReadableStream({pull(controller){controller.enqueue(new Uint8Array(40_000));},cancel(){cancelled=true;}});
  await error(await handleDataApi(req('/v1/query',{method:'POST',duplex:'half',headers:{'content-type':'application/json'},body}),env,noFetch),413,'budget_exceeded');
  assert.equal(cancelled,true);
  await error(await handleDataApi(req('/v1/query',{method:'POST',headers:{'content-type':'application/json','content-length':'3'},body:'{}'}),env,noFetch),400,'invalid_request');
  await error(await handleDataApi(req('/v1/query',{method:'POST',headers:{'content-type':'application/json','content-encoding':'gzip'},body:'{}'}),env,noFetch),415,'unsupported_media_type');
  const max=new Uint8Array(65_536);
  assert.equal((await handleDataApi(req('/v1/query',{method:'POST',headers:{'content-type':'application/json'},body:max}),env,async(_url,init)=>{assert.equal(init.body.length,65_536);return Response.json({});})).status,200);
});
test('redirects, edge HTML and transport exceptions never expose secrets or become data',async()=>{
  for(const upstream of [
    ()=>new Response('secret',{status:302,headers:{location:'https://evil.example','content-type':'application/json'}}),
    ()=>new Response('private edge HTML',{status:403,headers:{'content-type':'text/html'}}),
    ()=>{throw new Error('private details');},
  ]) await error(await handleDataApi(req(),env,upstream),502,'service_unavailable');
  for(const status of [401,403,429,503]) {
    const result=await handleDataApi(req(),env,async()=>Response.json({error:{code:'backend_error'}},{status}));
    assert.equal(result.status,status);assert.deepEqual(await result.json(),{error:{code:'backend_error'}});
  }
});
test('response remains streamed and cancellation reaches upstream',async()=>{
  let cancelled=false;
  const body=new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('{'));},cancel(){cancelled=true;}});
  const response=await handleDataApi(req(),env,async()=>new Response(body,{headers:{'content-type':'application/json'}}));
  const reader=response.body.getReader();assert.equal(new TextDecoder().decode((await reader.read()).value),'{');
  await reader.cancel();assert.equal(cancelled,true);
});
test('uses a separate thirty-second deadline and rejects unsafe configuration',async(t)=>{
  const real=AbortSignal.timeout;t.mock.method(AbortSignal,'timeout',ms=>{assert.equal(ms,30_000);return real(30_000);});
  for(const base of ['http://backend.example','https://user:secret@backend.example','https://site.example']) await error(await handleDataApi(req(),{ACCOUNT_API_BASE:base},()=>assert.fail('called')),503,'service_unavailable');
  const controller=new AbortController();controller.abort();
  await error(await handleDataApi(req('/v1/query',{method:'POST',headers:{'content-type':'application/json'},body:'{}',signal:controller.signal}),env,()=>assert.fail('called')),504,'service_unavailable');
});
