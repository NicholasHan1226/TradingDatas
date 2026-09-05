// Exact public data routes. Browser identity and stored account keys are never used.
const MAX_BODY = 65_536;
const details = {
  invalid_request: ['request is invalid', false],
  unauthenticated: ['authentication required', false],
  not_found: ['resource not found', false],
  method_not_allowed: ['method is not allowed', false],
  budget_exceeded: ['request exceeds allowed budget', false],
  unsupported_media_type: ['unsupported media type', false],
  service_unavailable: ['service temporarily unavailable', true],
};
function headers(allow) {
  return new Headers({'content-type':'application/json; charset=utf-8','cache-control':'no-store',
    'access-control-allow-origin':'*','access-control-allow-methods':allow,
    'access-control-allow-headers':'Content-Type, Authorization','allow':allow,
    'x-content-type-options':'nosniff'});
}
function failure(status,code,allow,head=false) {
  const [message,retryable]=details[code];
  return new Response(head?null:JSON.stringify({api_version:'v1',request_id:crypto.randomUUID(),error:{code,message,retryable}}),{status,headers:headers(allow)});
}
async function readBody(request,signal) {
  if(!request.body) return new Uint8Array();
  const reader=request.body.getReader(); const chunks=[]; let size=0;
  const abort=()=>{void reader.cancel().catch(()=>{});};
  signal.addEventListener('abort',abort,{once:true});
  try {
    signal.throwIfAborted();
    while(true) {
      const {done,value}=await reader.read(); signal.throwIfAborted();
      if(done) break;
      size+=value.byteLength;
      if(size>MAX_BODY) {await reader.cancel(); return null;}
      chunks.push(value);
    }
    const result=new Uint8Array(size); let offset=0;
    for(const chunk of chunks) {result.set(chunk,offset);offset+=chunk.byteLength;}
    return result;
  } finally {signal.removeEventListener('abort',abort);reader.releaseLock();}
}
export async function handleDataApi(request,env,fetchImpl=fetch) {
  const url=new URL(request.url), catalog=url.pathname==='/v1/catalog',query=url.pathname==='/v1/query';
  const allow=catalog?'GET, OPTIONS':query?'POST, OPTIONS':'OPTIONS';
  const fail=(status,code)=>failure(status,code,allow,request.method==='HEAD');
  if(!catalog && !query) return fail(404,'not_found');
  if(request.method==='OPTIONS') return new Response(null,{status:204,headers:headers(allow)});
  if(request.method!==(catalog?'GET':'POST')) return fail(405,'method_not_allowed');
  if(query && url.search) return fail(400,'invalid_request');
  const auth=request.headers.get('authorization');
  // No cookie exchange or server credential fallback on the data plane.
  if(!auth || !/^Bearer [^\s,]+$/.test(auth)) return fail(401,'unauthenticated');
  const length=request.headers.get('content-length');
  if(length!==null && !/^(0|[1-9][0-9]*)$/.test(length)) return fail(400,'invalid_request');
  if(catalog && ((length!==null && length!=='0') || request.headers.has('transfer-encoding'))) return fail(400,'invalid_request');
  if(query && request.headers.has('content-encoding')) return fail(415,'unsupported_media_type');
  if(query && !/^application\/json(?:\s*;|\s*$)/i.test(request.headers.get('content-type')||'')) return fail(415,'unsupported_media_type');
  if(query && length!==null && Number(length)>MAX_BODY) {await request.body?.cancel();return fail(413,'budget_exceeded');}
  const signal=AbortSignal.any([request.signal,AbortSignal.timeout(30_000)]);
  try {
    const base=new URL(env.ACCOUNT_API_BASE);
    if(base.protocol!=='https:' || base.username || base.password || base.search || base.hash || base.origin===url.origin) return fail(503,'service_unavailable');
    const outgoing=new Headers({'authorization':auth,'accept':'application/json'});
    let body;
    if(query) {
      body=await readBody(request,signal);
      if(body===null) return fail(413,'budget_exceeded');
      if(length!==null && Number(length)!==body.byteLength) return fail(400,'invalid_request');
      outgoing.set('content-type',request.headers.get('content-type'));
      // Fixed bytes let Workers emit a real Content-Length, never chunked framing.
      outgoing.set('content-length',String(body.byteLength));
    }
    const response=await fetchImpl(new URL(url.pathname+url.search,base),{method:request.method,headers:outgoing,body,redirect:'manual',signal});
    if(response.status>=300 && response.status<400) {await response.body?.cancel();return fail(502,'service_unavailable');}
    if(!/^application\/json(?:\s*;|\s*$)/i.test(response.headers.get('content-type')||'')) {await response.body?.cancel();return fail(502,'service_unavailable');}
    const publicHeaders=headers(allow);
    publicHeaders.set('content-type',response.headers.get('content-type'));
    for(const name of ['retry-after']) if(response.headers.has(name)) publicHeaders.set(name,response.headers.get(name));
    // Preserve JSON bytes, status and receipt semantics; do not buffer/cache results.
    return new Response(response.body,{status:response.status,headers:publicHeaders});
  } catch {return fail(signal.aborted?504:502,'service_unavailable');}
}
