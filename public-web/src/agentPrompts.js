export const AGENTS = ['Claude', 'Codex', 'OpenClaw', 'Hermes', 'Other Agent'];
export const UNCONFIGURED_ORIGIN = '<TRADINGDATA_BASE_URL_FROM_ACCOUNT>';

function textBlock(markdown, heading) {
  const section = markdown.split(`${heading}\n`)[1];
  const match = section?.match(/```text\n([\s\S]*?)\n```/);
  if (!match) throw new Error('agent_contract_missing');
  return match[1];
}

export function apiOrigin(value = '') {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/') return null;
    return url.origin;
  } catch { return null; }
}

export function buildAgentPrompt(markdown, { agent = 'Codex', locale = 'en', baseUrl = '' } = {}) {
  if (!AGENTS.includes(agent)) throw new Error('unsupported_agent');
  const version = markdown.match(/Prompt version: `([^`]+)`/)?.[1];
  if (!version) throw new Error('agent_contract_missing');
  const endpoint = apiOrigin(baseUrl);
  const source = locale === 'zh'
    ? textBlock(markdown, '## Canonical setup prompt (Chinese)')
    : [textBlock(markdown, `### ${agent}`), textBlock(markdown, '## Canonical setup prompt'), textBlock(markdown, '### Shared first-query checklist')].join('\n\n');
  const text = source.replace(/\bTradingData\b/g, 'TradingDatas')
    .replaceAll('{{TRADINGDATA_BASE_URL}}', endpoint || UNCONFIGURED_ORIGIN)
    .replaceAll('{{AGENT_NAME}}', agent).replaceAll('{{PROMPT_VERSION}}', version);
  if (/\{\{/.test(text)) throw new Error('agent_contract_unresolved');
  return { text, version, endpoint, configured: Boolean(endpoint) };
}
