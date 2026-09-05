// Translate only known customer-key business refusals; never expose backend text.
const errors = new Map([
  ['key label must be a string', 'invalid_key_label'],
  ['key label must contain 1 to 64 characters', 'invalid_key_label'],
  ['customer API key limit reached', 'key_limit_reached'],
  ['current credential cannot be disabled', 'current_key_protected'],
  ['API key not found', 'key_not_found'],
  ['invalid key id', 'invalid_key_id'],
  ['API key management requires a token-hash credential', 'key_management_unavailable'],
  ['current credential has no delegable data scope', 'key_scope_required'],
]);
export function portalKeyError(payload) {
  if(!payload || Array.isArray(payload) || typeof payload !== 'object' || typeof payload.error !== 'string') return null;
  return errors.get(payload.error) || null;
}
export function isPortalKeyPath(path) {
  return path === '/portal/api/me/keys' || /^\/portal\/api\/me\/keys\/key_[a-f0-9]{16}$/.test(path);
}
