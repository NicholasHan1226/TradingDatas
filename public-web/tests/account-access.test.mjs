import assert from 'node:assert/strict';
import test from 'node:test';
import {dataAccessMessage,keyManagementMessage} from '../src/accountAccess.js';
import {accountJson} from '../src/accountSession.js';

test('a failed access read is not an absent subscription or zero usage',()=>{
  const outage=dataAccessMessage({data_access_state:'unavailable'},'en');
  assert.match(outage.detail,/does not mean access was cancelled/);
  const revoked=dataAccessMessage({data_access_state:'invalid'},'zh');
  assert.match(revoked.detail,/网页登录仍有效/);
  assert.notEqual(outage.title,revoked.title);
  assert.equal(dataAccessMessage({data_access_state:'none'},'en'),null);
  assert.equal(dataAccessMessage({data_access_state:'connected'},'en'),null);
});
test('known key errors reach the UI without displaying arbitrary upstream text',async()=>{
  for(const code of ['invalid_key_label','key_limit_reached','current_key_protected','key_not_found','invalid_key_id','key_management_unavailable','key_scope_required']) {
    await assert.rejects(accountJson('keys',{},async()=>Response.json({error:code},{status:400})),{message:code});
    for(const locale of ['zh','en'])assert.ok(keyManagementMessage(code,locale));
  }
  await assert.rejects(accountJson('keys',{},async()=>Response.json({error:'private server text'},{status:400})),{message:'account_unavailable'});
  assert.doesNotMatch(keyManagementMessage('private server text','en'),/private server text/);
});
