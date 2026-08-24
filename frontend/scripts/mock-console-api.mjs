import http from 'node:http'

const port = Number(process.env.TD_CONSOLE_MOCK_PORT || 4174)
let tokens = [
  {
    token_hash_full: 'hash-admin-ui-test',
    token_hash_masked: 'sha256:8f2a…91cd',
    tenant_id: 'research-team',
    tier: 'research',
    scopes: ['read', 'admin'],
    data_categories: ['a_share', 'crypto', 'news'],
    data_category_mode: 'all',
    enabled: true,
    daily_limit: 12000,
    daily_usage: 1840,
    max_concurrent: 8,
    expires_at: null,
    expired: false,
  },
  {
    token_hash_full: 'hash-client-ui-test',
    token_hash_masked: 'sha256:2c90…7a13',
    tenant_id: 'quant-lab',
    tier: 'standard',
    scopes: ['read'],
    data_categories: ['a_share', 'news'],
    data_category_mode: 'restricted',
    enabled: true,
    daily_limit: 50000,
    daily_usage: 9230,
    max_concurrent: 8,
    expires_at: '2027-12-31T00:00:00Z',
    expired: false,
  },
]

const datasets = [
  { dataset_id: 'cn.dataset.daily', schema_major: 2, provider: 'tushare', market: 'CN', domain: 'market', cadence: 'postclose_daily', activation: 'active', entitlement: 'allowed', runtime_state: 'success', degraded: false, freshness_state: 'fresh', data_through: '2026-08-23', observed_at: '2026-08-24T08:00:00Z', reasons: [], coverage: { row_count: 481230 } },
  { dataset_id: 'cn.dataset.adj_factor', schema_major: 2, provider: 'tushare', market: 'CN', domain: 'reference', cadence: 'postclose_daily', activation: 'active', entitlement: 'allowed', runtime_state: 'stale', degraded: true, freshness_state: 'stale', data_through: '2026-08-20', observed_at: '2026-08-21T08:00:00Z', reasons: ['freshness_sla_exceeded'], coverage: { row_count: 38120 } },
  { dataset_id: 'crypto.spot.kline_5m', schema_major: 1, provider: 'binance', market: 'CRYPTO', domain: 'market', cadence: 'session_minute', activation: 'active', entitlement: 'public', runtime_state: 'empty', degraded: false, freshness_state: 'fresh', data_through: '2026-08-24T10:00:00Z', observed_at: '2026-08-24T10:05:00Z', reasons: [], coverage: { row_count: 99200 } },
  { dataset_id: 'cn.news.flash', schema_major: 1, provider: 'tushare', market: 'CN', domain: 'news', cadence: 'on_demand', activation: 'paused', entitlement: 'unknown', runtime_state: 'failed', degraded: true, freshness_state: 'unknown', data_through: null, observed_at: '2026-08-24T08:10:00Z', reasons: ['provider_unavailable'], coverage: { row_count: 0 } },
]

const requestedCollectionRows = Number(process.env.TD_CONSOLE_MOCK_COLLECTION_ROWS || datasets.length)
const collectionRowCount = Number.isFinite(requestedCollectionRows)
  ? Math.max(datasets.length, Math.min(5000, Math.floor(requestedCollectionRows)))
  : datasets.length
const markets = ['CN', 'CRYPTO', 'NEWS']
const providers = ['tushare', 'binance', 'firecrawl']
const cadences = ['postclose_daily', 'session_minute', 'on_demand', 'weekly']
const runtimeStates = ['success', 'success', 'success', 'stale', 'empty', 'failed']
const collectionDatasets = [
  ...datasets,
  ...Array.from({ length: collectionRowCount - datasets.length }, (_, offset) => {
    const index = offset + datasets.length + 1
    const runtimeState = runtimeStates[index % runtimeStates.length]
    const market = markets[index % markets.length]
    return {
      dataset_id: `${market.toLowerCase()}.stress.dataset_${String(index).padStart(4, '0')}`,
      schema_major: 1 + (index % 2),
      provider: providers[index % providers.length],
      market,
      domain: market === 'NEWS' ? 'news' : 'market',
      cadence: cadences[index % cadences.length],
      activation: index % 9 === 0 ? 'paused' : 'active',
      entitlement: 'allowed',
      runtime_state: runtimeState,
      degraded: runtimeState === 'stale' || runtimeState === 'failed',
      freshness_state: runtimeState === 'stale' ? 'stale' : 'fresh',
      data_through: runtimeState === 'empty' ? null : '2026-08-24',
      observed_at: '2026-08-24T10:05:00Z',
      reasons: runtimeState === 'failed' ? ['stress_fixture_failure'] : [],
      coverage: { row_count: index * 137 },
    }
  }),
]

const history = Array.from({ length: 30 }, (_, index) => ({
  date: `2026-08-${String(index + 1).padStart(2, '0')}`,
  total: 80 + ((index * 47) % 420),
}))

function json(response, status, body) {
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'access-control-allow-origin': '*',
    'access-control-allow-headers': 'authorization, content-type',
    'access-control-allow-methods': 'GET, POST, PATCH, DELETE, OPTIONS',
  })
  response.end(JSON.stringify(body))
}

async function readBody(request) {
  const chunks = []
  for await (const chunk of request) chunks.push(chunk)
  if (!chunks.length) return {}
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

const server = http.createServer(async (request, response) => {
  if (request.method === 'OPTIONS') return json(response, 204, {})
  const url = new URL(request.url, `http://${request.headers.host}`)
  const isCustomerSession = request.headers.authorization === 'Bearer ui-customer-token'

  if (request.method === 'GET' && url.pathname === '/portal/api/me') {
    const portal = isCustomerSession
      ? { tenant_id: 'quant-lab', tier: 'standard', scopes: ['read'], data_categories: ['a_share', 'news'], data_category_mode: 'restricted', enabled: true, max_concurrent: 8, minute_request_limit: 600, hourly_request_limit: null, daily_limit: 50000, expires_at: '2027-12-31T00:00:00Z', usage: { today_date: '2026-08-24', today_count: 9230, hourly_count: 482, hourly_window_seconds: 60 } }
      : { tenant_id: 'research-team', tier: 'internal', scopes: ['read', 'admin'], data_categories: ['a_share', 'crypto', 'news'], data_category_mode: 'all', enabled: true, max_concurrent: null, hourly_request_limit: null, daily_limit: null, expires_at: null, usage: { today_date: '2026-08-24', today_count: 1840, hourly_count: 121, hourly_window_seconds: 3600 } }
    return json(response, 200, { api_version: 'v1', request_id: 'mock-me', portal })
  }
  if (request.method === 'GET' && url.pathname === '/portal/api/me/usage') {
    return json(response, 200, { api_version: 'v1', request_id: 'mock-portal-usage', portal_usage: { tenant_id: isCustomerSession ? 'quant-lab' : 'research-team', daily_limit: isCustomerSession ? 50000 : null, today_count: isCustomerSession ? 9230 : 1840, history } })
  }
  if (request.method === 'GET' && url.pathname === '/admin/api/tokens') return json(response, 200, { tokens, count: tokens.length })
  if (request.method === 'POST' && url.pathname === '/admin/api/tokens') {
    const body = await readBody(request)
    const item = { token_hash_full: `hash-${body.tenant_id}`, token_hash_masked: 'sha256:new…mock', tenant_id: body.tenant_id, tier: body.tier, scopes: body.scopes, data_categories: body.data_categories, data_category_mode: 'restricted', enabled: true, daily_limit: body.daily_limit ?? null, daily_usage: 0, max_concurrent: body.max_concurrent ?? null, expires_at: body.expires_at ?? null, expired: false }
    tokens = [...tokens, item]
    return json(response, 201, { token: 'td_mock_created_token' })
  }
  if (url.pathname.startsWith('/admin/api/tokens/')) {
    const hash = decodeURIComponent(url.pathname.split('/').pop())
    if (request.method === 'PATCH') {
      const body = await readBody(request)
      tokens = tokens.map((item) => item.token_hash_full === hash ? { ...item, ...body } : item)
      return json(response, 200, { ok: true })
    }
    if (request.method === 'DELETE') {
      tokens = tokens.filter((item) => item.token_hash_full !== hash)
      return json(response, 200, { ok: true })
    }
  }
  if (request.method === 'GET' && url.pathname === '/admin/api/usage') {
    return json(response, 200, { daily: { 'research-team': { date: '2026-08-24', count: 1840, daily_limit: null }, 'quant-lab': { date: '2026-08-24', count: 9230, daily_limit: 50000 } }, hourly: { 'research-team': { count_in_window: 121, tier_limit: null, window_seconds: 3600 }, 'quant-lab': { count_in_window: 482, tier_limit: 600, window_seconds: 60 } }, cache: { dedup_entries: 214, dedup_bytes: 45870, active_requests: 2 } })
  }
  if (request.method === 'GET' && url.pathname === '/admin/api/usage/history') return json(response, 200, { history })
  if (request.method === 'GET' && url.pathname === '/admin/api/collection/status') {
    const active = collectionDatasets.filter((item) => item.activation === 'active').length
    return json(response, 200, { datasets: collectionDatasets, total: collectionDatasets.length, active, paused: collectionDatasets.length - active })
  }
  if (request.method === 'GET' && url.pathname === '/admin/api/health/alerts') return json(response, 200, { alerts: [{ severity: 'critical', title: '新闻数据源连接失败', detail: 'cn.news.flash 最近一次采集返回 provider_unavailable。' }, { severity: 'warning', title: '复权因子数据已过新鲜度窗口', detail: 'cn.dataset.adj_factor 需要检查下一次 post-close 采集。' }, { severity: 'info', title: 'Crypto 数据集本窗口为空', detail: '当前窗口未产生新增行，历史覆盖仍保留。' }] })
  if (request.method === 'GET' && url.pathname === '/v1/catalog') return json(response, 200, { api_version: 'v1', data: datasets })
  if (request.method === 'POST' && url.pathname === '/v1/query') {
    const body = await readBody(request)
    const rows = body.dataset_id === 'crypto.spot.kline_5m' ? [] : [
      { ts_code: '000001.SZ', trade_date: '20260823', close: 12.84, volume: 829300 },
      { ts_code: '600519.SH', trade_date: '20260823', close: 1584.2, volume: 102300 },
    ]
    return json(response, 200, { data: rows, next_cursor: body.cursor ? null : rows.length ? 'mock-page-2' : null, metadata: { runtime_state: rows.length ? 'success' : 'empty', data_through: '2026-08-23', reasons: [] } })
  }

  return json(response, 404, { error: { code: 'not_found', message: `${request.method} ${url.pathname} is not mocked` } })
})

server.listen(port, '127.0.0.1', () => {
  process.stdout.write(`TradingDatas mock console API listening on http://127.0.0.1:${port}\n`)
})
