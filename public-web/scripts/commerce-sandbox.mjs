// Local-only durable simulator; not a payment-provider sandbox integration.
// Never imported by the deployed Worker. No network, keys or Portal writes.
import { DatabaseSync } from 'node:sqlite';
import { readFileSync, existsSync, realpathSync, statSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { settleSandboxPayment } from '../worker/commerce.js';
// Resolve aliases before opening either store. Existing hard links are also
// rejected; the two schemas must never share a physical database file.
export function assertSeparateSandboxFiles(identityFile, commerceFile) {
 if(!identityFile || !commerceFile || identityFile===':memory:' || commerceFile===':memory:') return;
 const canonical = file => existsSync(file) ? realpathSync(file) : path.join(realpathSync(path.dirname(path.resolve(file))),path.basename(file));
 if(canonical(identityFile)===canonical(commerceFile)) throw Error('Identity and commerce sandbox databases must be separate files');
 if(existsSync(identityFile) && existsSync(commerceFile)) {
  const left=statSync(identityFile),right=statSync(commerceFile);
  if(left.dev===right.dev && left.ino===right.ino) throw Error('Identity and commerce sandbox databases must be separate files');
 }
}
export function openCommerceSandbox(filename=':memory:') {
 const sqlite=new DatabaseSync(filename);
 sqlite.exec(readFileSync(new URL('../worker/commerce-schema.sql',import.meta.url),'utf8'));
 return {sqlite,prepare(sql) {let args=[];return {
  bind(...values){args=values;return this;},async first(){return sqlite.prepare(sql).get(...args)||null;},
  async run(){return {meta:sqlite.prepare(sql).run(...args)};},async all(){return {results:sqlite.prepare(sql).all(...args)};},
  execute(){return {results:sqlite.prepare(sql).all(...args)};},
 };},async batch(statements){sqlite.exec('BEGIN');try{const result=statements.map(s=>s.execute());sqlite.exec('COMMIT');return result;}catch(error){sqlite.exec('ROLLBACK');throw error;}}};
}
if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) {
 const [filename,orderId]=process.argv.slice(2);
 if(!filename || !orderId) throw Error('Usage: node scripts/commerce-sandbox.mjs <isolated sandbox.sqlite> <order id>');
 const db=openCommerceSandbox(filename);
 try {
  const order=db.sqlite.prepare('SELECT * FROM commerce_orders WHERE id=?').get(orderId);
  if(!order) throw Error('Sandbox order not found');
  const notification={environment:'sandbox',event_id:`local-${order.id}`,order_id:order.id,status:'paid',currency:order.currency,amount_minor:order.amount_minor};
  const result=await settleSandboxPayment({COMMERCE_MODE:'sandbox',COMMERCE_SANDBOX_DB:db},notification,{
   verify:async event=>event, // Local fixture only; no real signature/provider claim.
   provision:async ({idempotency_key})=>({environment:'sandbox',idempotency_key,state:'active'}),
  });
  console.log(JSON.stringify({simulation:true,actual_data_grants:false,...result}));
 }finally {db.sqlite.close();}
}
