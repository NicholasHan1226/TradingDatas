import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { requestProfileDeletion } from '../src/accountSession.js';

const receipt = { state: 'accepted', requested_at: '2026-08-30T12:00:00Z', delete_by: '2026-09-29T12:00:00Z' };
test('account deletion sends only explicit confirmation to the same-site route', async () => {
  let calls = 0;
  const result = await requestProfileDeletion(async (url, init) => {
    calls++;
    assert.equal(url, '/api/account/profile/deletion');
    assert.equal(init.method, 'POST');
    assert.equal(init.credentials, 'same-origin');
    assert.deepEqual(JSON.parse(init.body), { confirmation: 'DELETE' });
    assert.ok(init.signal instanceof AbortSignal);
    return Response.json({ deletion: receipt }, { status: 202 });
  });
  assert.deepEqual(result, receipt); assert.equal(calls, 1);
});
test('missing or malformed acceptance is not presented as deletion success', async () => {
  for (const body of [{}, { deletion: { state: 'complete' } }, { deletion: { ...receipt, delete_by: 'invalid' } }]) {
    await assert.rejects(requestProfileDeletion(async () => Response.json(body)), /deletion_unconfirmed/);
  }
  await assert.rejects(requestProfileDeletion(async () => new Response('<html>offline</html>')), /account_unavailable/);
  await assert.rejects(requestProfileDeletion(async () => { throw new TypeError('offline'); }), /account_unavailable/);
});
test('fresh verification, authorization and store errors remain distinct', async () => {
  for (const [status, error, expected] of [[403, 'recent_sign_in_required', 'recent_sign_in_required'], [403, 'forbidden', 'access_denied'], [401, 'unauthenticated', 'signed_out'], [503, 'identity_unavailable', 'account_unavailable']]) {
    await assert.rejects(requestProfileDeletion(async () => Response.json({ error }, { status })), new RegExp(expected));
  }
});
test('deletion controls keep visible disabled treatment and pending action guards', () => {
  const styles = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
  const panel = readFileSync(new URL('../src/EmailAccountPanel.jsx', import.meta.url), 'utf8');
  assert.match(styles, /\.email-deletion-actions \.primary-button:disabled \{[^}]*box-shadow: none/);
  assert.match(panel, /onClick=\{onSignOut\} disabled=\{signingOut \|\| deleting\}/);
  assert.match(panel, /disabled=\{confirmation !== "DELETE" \|\| deleting \|\| signingOut\}/);
});
