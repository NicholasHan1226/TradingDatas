import test from 'node:test';
import assert from 'node:assert/strict';
import { catalogOwner, catalogQuery, catalogView, domesticRows, retryCatalog, selectCatalogRows } from '../src/catalogEvidence.js';
const rows=[{dataset_id:'cn.equity.daily',schema_major:2,runtime:{state:'success'}},{dataset_id:'cn.dataset.income',schema_major:1,runtime:{state:'empty'}},{dataset_id:'global.news.flash',schema_major:1,runtime:{state:'failed'}},{dataset_id:'cn.dataset.adj_factor',schema_major:2,runtime:{state:'stale'}}];
test('all domestic rows remain discoverable independently of product mappings and status',()=>{
  assert.deepEqual(selectCatalogRows(rows),rows);
  assert.equal(selectCatalogRows(rows,{state:'empty'})[0].dataset_id,'cn.dataset.income');
  assert.equal(selectCatalogRows(rows,{query:'global.news'})[0].runtime.state,'failed');
  assert.deepEqual(selectCatalogRows(rows,{productId:'cn-equity-daily'}).map(row=>row.dataset_id),['cn.equity.daily','cn.dataset.adj_factor']);
  assert.deepEqual(selectCatalogRows(rows,{productId:'unmapped-product'}),[]);
});
test('unavailable access hides old evidence and retries identity before a fresh catalog',()=>{
  const connected={identity_kind:'email',user_id:'alice',data_access_state:'connected'};
  const snapshot={account:connected,status:'ready',rows};
  const unavailable={...connected,data_access_state:'unavailable'};
  const base={active:true,checking:false,account:unavailable,snapshot};
  assert.equal(catalogView(base),'error');
  const calls=[];
  const callbacks={onRetryAccount:()=>calls.push('identity'),onRetryCatalog:()=>calls.push('catalog')};
  retryCatalog({...base,...callbacks});
  assert.deepEqual(calls,['identity']);
  assert.equal(catalogView({...base,checking:true}),'loading');
  const recovered={...connected};
  assert.equal(catalogView({...base,account:recovered}),'loading');
  const fresh={account:recovered,status:'ready',rows:[]};
  assert.equal(catalogView({...base,account:recovered,snapshot:fresh}),'ready');
  retryCatalog({account:recovered,snapshot:fresh,...callbacks});
  assert.deepEqual(calls,['identity','catalog']);
  retryCatalog({account:recovered,snapshot:{account:recovered,status:'error',recheck:true},...callbacks});
  assert.deepEqual(calls,['identity','catalog','identity']);
  for(const data_access_state of ['none','invalid']) assert.equal(catalogView({...base,account:{...connected,data_access_state}}),'unconnected');
});
test('defensive projection excludes Crypto and rejects partial catalogs',()=>{
  assert.deepEqual(domesticRows({data:[...rows,{dataset_id:'crypto.spot.example'},{dataset_id:'cn.fake',market:'CRYPTO_PERP'}],next_cursor:null}),rows);
  assert.throws(()=>domesticRows({data:[],next_cursor:'later'}));
});
test('copy-only query uses exact authoritative schema and no credentials',()=>{
  const query=catalogQuery(rows[0]);assert.equal(query.schema_major,2);assert.equal(query.dataset_id,'cn.equity.daily');assert.equal(query.limit,1);
  assert.deepEqual(Object.keys(query),['dataset_id','schema_major','fields','filters','as_of','cursor','limit','include_receipt_proofs']);
  for(const schema_major of [undefined,'2',0,1.5]) assert.equal(catalogQuery({...rows[0],schema_major}),null);
});
test('identity check, logout and same-tenant session replacement immediately hide old data',()=>{
  const account={tenant_id:'tenant-a'};const snapshot={account,status:'ready',rows};
  assert.equal(catalogOwner(account),'tenant-a');
  assert.equal(catalogOwner({user_id:'alice',tenant_id:'tenant-a'}),'alice');
  const base={active:true,account,snapshot};
  assert.equal(catalogView(base),'ready');
  assert.equal(catalogView({...base,checking:true}),'loading');
  assert.equal(catalogView({...base,account:null}),'guest');
  assert.equal(catalogView({...base,account:{tenant_id:'tenant-a'}}),'loading');
  assert.equal(catalogView({...base,account:{tenant_id:'tenant-b'}}),'loading');
  assert.equal(catalogView({...base,account:null,error:'account_unavailable'}),'error');
  assert.equal(catalogView({...base,account:{identity_kind:'email',user_id:'alice',data_access_state:'none'}}),'unconnected');
  assert.equal(catalogView({...base,active:false}),'inactive');
});
