import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { AGENTS, apiOrigin, buildAgentPrompt, UNCONFIGURED_ORIGIN } from '../src/agentPrompts.js';
const contract = await readFile(new URL('../../docs/AGENT_INTEGRATIONS.md', import.meta.url), 'utf8');

for (const agent of AGENTS) for (const locale of ['en', 'zh']) {
  test(`${agent}/${locale} derives safe bounded instructions from the canonical source`, () => {
    const prompt = buildAgentPrompt(contract, { agent, locale, baseUrl: 'https://data.example.test' });
    assert.equal(prompt.configured, true);
    assert.ok(prompt.text.indexOf('GET /v1/catalog') < prompt.text.indexOf('POST /v1/query'));
    for (const term of ['dataset_id', 'schema_major', 'selectable', 'limit=1', 'next_cursor', 'receipt_id', 'lineage', 'freshness', 'quality', 'degraded', 'Retry-After', 'TRADINGDATA_API_KEY']) assert.ok(prompt.text.includes(term), term);
    assert.ok(prompt.text.includes('https://data.example.test'));
    assert.match(prompt.text, /queryability\.queryable === true/);
    assert.match(prompt.text, /queryability\.reasons/);
    assert.doesNotMatch(prompt.text, /queryability=(true|false)/);
    assert.doesNotMatch(prompt.text, /\{\{|cn-equity-daily|schema_major": 1/);
  });
}
test('missing or unsafe configuration stays a draft and is never copied as a URL', () => {
  for (const value of ['', 'http://data.example.test', 'https://user:password@example.test', 'https://example.test/?key=secret', 'https://example.test/#secret', 'https://example.test/key/secret', 'not-a-url']) {
    assert.equal(apiOrigin(value), null);
    const prompt = buildAgentPrompt(contract, { baseUrl: value });
    assert.equal(prompt.configured, false);
    assert.ok(prompt.text.includes(UNCONFIGURED_ORIGIN));
    assert.ok(!prompt.text.includes('password@'));
  }
});
test('unknown agent or incomplete source fails rather than producing partial instructions', () => {
  assert.throws(() => buildAgentPrompt(contract, { agent: 'unknown' }));
  assert.throws(() => buildAgentPrompt('missing'));
});
