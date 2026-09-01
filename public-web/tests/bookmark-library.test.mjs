import test from 'node:test';
import assert from 'node:assert/strict';
import { createBookmarkLibrary } from '../src/bookmarkLibrary.js';
const user=id=>({identity_kind:'email',user_id:id,capabilities:{library:true}});
function setup(request) {
  const writes=[]; let local='["doc:start-1"]';
  const storage={getItem:()=>local,setItem:(_key,value)=>{writes.push(value);local=value;}};
  return {library:createBookmarkLibrary({request,storage}),writes};
}
test('sign-in never uploads local bookmarks; explicit import preserves local and cloud sources',async()=>{
  const calls=[];
  const f=setup(async(endpoint,init)=>{calls.push({endpoint,init});return {bookmarks:{user_id:'alice',keys:endpoint.endsWith('/import')?['doc:start-1','research:paper']:['research:paper']}};});
  await f.library.setContext(user('alice'),'authenticated');
  assert.equal(calls.length,1); assert.equal(calls[0].endpoint,'bookmarks'); assert.equal(calls[0].init.expectedIdentity,'alice');
  assert.deepEqual(f.library.snapshot().keys,['research:paper']); assert.deepEqual(f.writes,[]);
  await f.library.importLocal();
  assert.deepEqual(JSON.parse(calls[1].init.body).keys,['doc:start-1']); assert.deepEqual(f.writes,[]);
  f.library.setContext(null,'signed_out');
  assert.deepEqual(f.library.snapshot().keys,['doc:start-1']);
});
test('late reads and mutations cannot restore another identity after switching or logout',async()=>{
  const pending=[]; const f=setup((endpoint,init)=>new Promise(resolve=>pending.push({endpoint,init,resolve})));
  const first=f.library.setContext(user('alice'),'authenticated');
  f.library.setContext(null,'checking'); assert.deepEqual(f.library.snapshot().keys,[]);
  const second=f.library.setContext(user('bob'),'authenticated');
  pending[1].resolve({bookmarks:{user_id:'bob',keys:['doc:bob']}});await second;
  pending[0].resolve({bookmarks:{user_id:'alice',keys:['doc:alice']}});await first;
  assert.deepEqual(f.library.snapshot().keys,['doc:bob']);
  const mutate=f.library.toggle('doc:new');
  f.library.setContext(null,'signed_out');
  pending[2].resolve({bookmarks:{user_id:'bob',keys:['doc:new']}});await mutate;
  assert.equal(f.library.snapshot().mode,'local');assert.deepEqual(f.library.snapshot().keys,['doc:start-1']);
});
test('failed writes and mismatched response identities are never shown as saved',async()=>{
  let fail=false; const f=setup(async()=>{if(fail) throw new Error('identity_changed');return {bookmarks:{user_id:'alice',keys:[]}};});
  await f.library.setContext(user('alice'),'authenticated'); fail=true;
  await f.library.toggle('doc:unconfirmed');
  assert.equal(f.library.snapshot().status,'error'); assert.deepEqual(f.library.snapshot().keys,[]);assert.deepEqual(f.writes,[]);
  const mismatch=setup(async()=>({bookmarks:{user_id:'bob',keys:['doc:private']}}));
  await mismatch.library.setContext(user('alice'),'authenticated');
  assert.equal(mismatch.library.snapshot().status,'error');assert.deepEqual(mismatch.library.snapshot().keys,[]);
});
test('unavailable identity does not fall back to a local write and malformed local state is safe',async()=>{
  const f=setup(async()=>{throw new Error('unexpected');});
  f.library.setContext(null,'unavailable');f.library.toggle('doc:new');assert.deepEqual(f.writes,[]);
  const library=createBookmarkLibrary({storage:{getItem:()=>'{"unexpected":true}'},request:async()=>{}});
  library.setContext(null,'signed_out');assert.deepEqual(library.snapshot().keys,[]);
});
