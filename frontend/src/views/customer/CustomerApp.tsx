import { useEffect, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ApiClient } from '../../lib/api'
import type { DataCategory, PortalInfo, PortalMeResponse, PortalUsageResponse } from '../../lib/types'
import {
  Badge,
  Button,
  Card,
  CopyButton,
  ErrorBanner,
  LoadingPanel,
  PageIntro,
  ProgressBar,
  TABLE_ROW_CLASS,
  TIER_LABELS,
} from '../../components/ui'

function daysUntil(iso: string | null): number | null {
  if (!iso) return null
  const ms = Date.parse(iso.endsWith('Z') ? iso : iso + 'Z') - Date.now()
  return Math.ceil(ms / 86_400_000)
}

const DATA_CATEGORY_DETAILS: Record<DataCategory, { label: string; detail: string }> = {
  a_share: { label: 'A 股', detail: '境内市场行情、基础资料与基本面等数据' },
  crypto: { label: '加密资产', detail: '隔离运行面提供的公共行情与衍生数据' },
  news: { label: '新闻', detail: '新闻、公告与事件类客观数据' },
}

export default function CustomerApp({
  client,
  tenantId,
  onLogout,
  onViewAdmin,
}: {
  client: ApiClient
  tenantId: string
  onLogout: () => void
  onViewAdmin?: () => void
}) {
  const [section, setSection] = useState<'overview' | 'docs'>('overview')
  const [docSection, setDocSection] = useState<'platform' | 'api' | 'agent'>('platform')
  const [me, setMe] = useState<PortalInfo | null>(null)
  const [history, setHistory] = useState<{ date: string; total: number }[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const [meResp, usage] = await Promise.all([
          client.get<PortalMeResponse>('/portal/api/me'),
          client.get<PortalUsageResponse>('/portal/api/me/usage', { days: '30' }),
        ])
        if (!alive) return
        setMe(meResp.portal)
        setHistory(usage.portal_usage.history ?? [])
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : '加载失败')
      }
    })()
    return () => {
      alive = false
    }
  }, [client])

  const curlExample = `# 1) 浏览可用的数据集目录（取 dataset_id 与 schema_major）
curl ${client.baseUrl}/v1/catalog \\
  -H "Authorization: Bearer <你的API密钥>"

# 2) 查询某个数据集的数据行（dataset_id 与 schema_major 来自目录）
curl -X POST ${client.baseUrl}/v1/query \\
  -H "Authorization: Bearer <你的API密钥>" \\
  -H "Content-Type: application/json" \\
  -d '{"dataset_id": "cn.dataset.adj_factor", "schema_major": 2,
       "filters": {"ts_code": {"eq": "000001.SZ"}}, "limit": 100}'`

  const agentPrompt = `你是交易数据分析助手，通过 TradingDatas HTTP API 获取真实行情与基本面数据。

## 连接信息
- Base URL：${client.baseUrl}
- 认证：所有请求携带 Header「Authorization: Bearer <你的API密钥>」。
- 密钥由用户提供，不要把它写进代码仓库或日志。

## 工作流程
1) 找数据集：GET ${client.baseUrl}/v1/catalog
   返回数据集列表，每个条目包含：
   - dataset_id 与 schema_major（查询时两者都必须提供）
   - default_fields / fields（可用字段）
   - filter_operators（各字段支持的过滤操作符）
   - limits.max_page_size（单页行数上限）
2) 取数据：POST ${client.baseUrl}/v1/query，JSON 请求体：
   必填：dataset_id（字符串）、schema_major（整数）
   常用可选：
   - filters：按字段过滤，操作符支持 eq / in / gte / lte / between
     例："filters": {"ts_code": {"eq": "000001.SZ"}}
     例："filters": {"trade_date": {"gte": "2026-08-01"}}
   - order：排序数组，元素形如 "字段名:asc" 或 "字段名:desc"
   - limit：单页行数，不超过该数据集 limits.max_page_size
   - cursor：翻页时传上一页响应中的 next_cursor
3) 读响应：
   - data：数据行对象数组（每行是 字段名->值）
   - next_cursor：非 null 表示还有下一页，用它继续翻页
   - metadata.data_through：当前数据截至时间

## 规则
- 先查 catalog 确认 dataset_id、schema_major 和字段名后再 query，不要凭记忆猜。
- 收到 429 表示超出套餐的频率或限额：停止请求并等待后重试（指数退避）。
- 收到 401 表示密钥无效、已暂停或已过期：提示用户检查账号。
- 这些是只读接口；响应里的 request_id 可用于向管理员反馈问题。`

  const toolDefsJson = JSON.stringify(
    [
      {
        type: 'function',
        function: {
          name: 'tradingdatas_catalog',
          description:
            '浏览 TradingDatas 数据集目录，返回每个数据集的 dataset_id、schema_major、可用字段、过滤操作符与单页上限。查询前必须先在这里获取参数。',
          parameters: { type: 'object', properties: {}, required: [] },
        },
      },
      {
        type: 'function',
        function: {
          name: 'tradingdatas_query',
          description:
            '查询 TradingDatas 指定数据集的数据行。dataset_id 与 schema_major 必须来自 tradingdatas_catalog 的结果。',
          parameters: {
            type: 'object',
            properties: {
              dataset_id: { type: 'string', description: '数据集 ID，来自目录' },
              schema_major: { type: 'integer', description: '数据集主版本号，来自目录' },
              filters: {
                type: 'object',
                description:
                  '按字段过滤，值为单操作符对象；操作符：eq/in/gte/lte/between。例：{"ts_code":{"eq":"000001.SZ"}}',
              },
              order: {
                type: 'array',
                items: { type: 'string' },
                description: '排序，元素形如 "trade_date:desc"',
              },
              limit: { type: 'integer', description: '单页行数，不超过目录中该数据集的上限' },
              cursor: { type: 'string', description: '上一页响应中的 next_cursor，用于翻页' },
            },
            required: ['dataset_id', 'schema_major'],
          },
        },
      },
    ],
    null,
    2,
  )

  const pythonExample = `import json
import os
import urllib.request

BASE = "${client.baseUrl}"
KEY = os.environ["TRADINGDATAS_API_KEY"]  # 不要硬编码密钥

def get_catalog():
    req = urllib.request.Request(
        BASE + "/v1/catalog",
        headers={"Authorization": "Bearer " + KEY},
    )
    return json.load(urllib.request.urlopen(req, timeout=30))

def query(dataset_id, schema_major, **extra):
    body = dict(dataset_id=dataset_id, schema_major=schema_major, **extra)
    req = urllib.request.Request(
        BASE + "/v1/query",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + KEY,
                 "Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req, timeout=30))

# 目录 -> 选数据集 -> 翻页取数
catalog = get_catalog()
resp = query("cn.dataset.adj_factor", 2,
             filters={"ts_code": {"eq": "000001.SZ"}},
             order=["trade_date:desc"], limit=100)
rows, next_cursor = resp["data"], resp["next_cursor"]
while next_cursor:
    resp = query("cn.dataset.adj_factor", 2, cursor=next_cursor)
    rows.extend(resp["data"])
    next_cursor = resp["next_cursor"]`

  if (!me && !error) return <LoadingPanel label="加载你的套餐信息…" />

  return (
    <div className="min-h-full bg-[var(--td-canvas)]">
      {/* Top bar */}
      <header className="sticky top-0 z-10 border-b border-slate-200/80 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div>
              <div className="text-[18px] font-bold tracking-[-0.055em] text-slate-950">TradingDatas</div>
              <div className="mt-0.5 text-[10px] font-medium tracking-[0.1em] text-[var(--td-faint)]">DATA ACCESS</div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden rounded-md bg-slate-100 px-2 py-1 font-mono text-[11px] text-slate-500 sm:inline">{tenantId}</span>
            {onViewAdmin && (
              <Button variant="secondary" size="sm" onClick={onViewAdmin}>
                返回管理端
              </Button>
            )}
            <Button variant="secondary" size="sm" onClick={onLogout}>退出</Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-7 px-5 py-7 pb-16 sm:px-6 sm:py-8">
        {error && <ErrorBanner message={error} />}

        {me && (
          <>
            <PageIntro
              eyebrow="DATA ACCESS"
              title={section === 'overview' ? '你的数据访问概览' : '文档中心'}
              description={section === 'overview' ? '查看套餐状态、请求额度和近 30 天调用趋势。' : '集中查看平台分类、API 快速开始、认证说明与 Agent 接入资源。'}
              action={
                <nav aria-label="用户前台页面" className="flex rounded-[var(--td-radius-sm)] border border-[var(--td-line)] bg-white p-1">
                  {([['overview', '概览'], ['docs', '文档']] as const).map(([value, label]) => (
                    <button key={value} type="button" aria-pressed={section === value} onClick={() => setSection(value)} className={`min-h-8 rounded px-3 text-xs font-medium focus-visible:outline-2 focus-visible:outline-[var(--td-accent)] ${section === value ? 'bg-[var(--td-accent-quiet)] text-[var(--td-accent-strong)]' : 'text-[var(--td-muted)] hover:bg-slate-50 hover:text-[var(--td-ink)]'}`}>
                      {label}
                    </button>
                  ))}
                </nav>
              }
            />
            {section === 'overview' && <div className="contents">
            {/* Plan summary */}
            <section className="overflow-hidden rounded-[var(--td-radius)] border border-slate-800 bg-[#15181e] p-6 text-white sm:p-7">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-[10px] font-medium tracking-[0.16em] text-slate-400">ACCESS PROFILE</p>
                  <h1 className="mt-2 text-2xl font-semibold tracking-tight">
                    {TIER_LABELS[me.tier] ?? me.tier}
                  </h1>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {(me.scopes ?? []).map((s) => (
                      <code key={s} className="rounded-md bg-white/10 px-1.5 py-0.5 font-mono text-[11px] text-blue-200">
                        {s}
                      </code>
                    ))}
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-1.5">
                    {(me.data_categories ?? []).map((category) => (
                      <span key={category} className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[11px] font-medium text-slate-200">
                        {DATA_CATEGORY_DETAILS[category]?.label ?? category}
                      </span>
                    ))}
                    {me.data_categories.length === 0 && <span className="text-xs text-rose-300">尚未开通数据分类</span>}
                  </div>
                </div>
                <div className="relative text-right">
                  <Badge tone={me.enabled ? 'green' : 'rose'}>{me.enabled ? '服务正常' : '已暂停'}</Badge>
                  <p className="mt-2 text-xs text-slate-400">
                    {me.expires_at ? (
                      (() => {
                        const d = daysUntil(me.expires_at)
                        if (d !== null && d <= 0) return (
                          <span className="font-medium text-rose-300">已于 {me.expires_at.slice(0, 10)} 过期</span>
                        )
                        return (
                          <>有效期至 {me.expires_at.slice(0, 10)}
                            {d !== null && <span className={d! <= 14 ? ' font-medium text-amber-300' : ''}> · 剩余 {d} 天</span>}
                          </>
                        )
                      })()
                    ) : (
                      '长期有效'
                    )}
                  </p>
                </div>
              </div>

              <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-white/10 pt-5 sm:grid-cols-4">
                {[
                  // Commercial tiers are metered per minute; legacy tiers per hour.
                  ...(me.minute_request_limit
                    ? [['每分钟请求', `${me.minute_request_limit} 次`]]
                    : [['每小时请求', me.hourly_request_limit === null ? '不限' : `${me.hourly_request_limit} 次`]]),
                  ['并发上限', me.max_concurrent === null ? '不限' : `${me.max_concurrent} 路`],
                  ['每日请求', me.daily_limit === null ? '不限' : `${me.daily_limit.toLocaleString('zh-CN')} 次`],
                  ['今日已用', `${me.usage.today_count.toLocaleString('zh-CN')} 次`],
                ].map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-[11px] tracking-wide text-slate-400">{k}</dt>
                    <dd className="mt-1 text-lg font-semibold tabular-nums">{v}</dd>
                  </div>
                ))}
              </dl>
            </section>

            {/* Usage */}
            <Card
              title="近 30 天调用量"
              action={
                me.daily_limit !== null ? (
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-slate-400">今日额度</span>
                    <ProgressBar value={me.usage.today_count} limit={me.daily_limit} />
                  </div>
                ) : undefined
              }
            >
              {!history || history.every((d) => d.total === 0) ? (
                <div className="py-10 text-center">
                  <p className="text-sm font-medium text-slate-500">还没有调用记录</p>
                  <p className="mt-1 text-xs text-slate-400">按下方接入指南发起第一次请求后，这里会出现用量曲线</p>
                </div>
              ) : (
                <div className="h-60 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={history} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
                      <defs>
                        <linearGradient id="custFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#2563eb" stopOpacity={0.28} />
                          <stop offset="100%" stopColor="#2563eb" stopOpacity={0.02} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={(v: string) => v.slice(5)} tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={{ stroke: '#e2e8f0' }} tickLine={false} />
                      <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} allowDecimals={false} />
                      <Tooltip
                        formatter={(value) => [`${Number(value).toLocaleString('zh-CN')} 次`, '你的请求']}
                        labelStyle={{ fontSize: 12, color: '#475569' }}
                        contentStyle={{ borderRadius: 10, border: '1px solid #e2e8f0', boxShadow: '0 4px 16px rgb(15 23 42 / 0.08)', fontSize: 12 }}
                      />
                      <Area type="monotone" dataKey="total" stroke="#2563eb" strokeWidth={2} fill="url(#custFill)" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>
            </div>}

            {section === 'docs' && (
              <nav aria-label="文档分类" className="flex w-fit rounded-[var(--td-radius-sm)] bg-slate-100 p-1">
                {([['platform', '平台说明'], ['api', 'API 快速开始'], ['agent', 'Agent 接入']] as const).map(([value, label]) => (
                  <button key={value} type="button" aria-pressed={docSection === value} onClick={() => setDocSection(value)} className={`min-h-9 rounded px-4 text-xs font-medium focus-visible:outline-2 focus-visible:outline-[var(--td-accent)] ${docSection === value ? 'bg-white text-[var(--td-ink)] shadow-[var(--td-shadow-1)]' : 'text-[var(--td-muted)] hover:text-[var(--td-ink)]'}`}>
                    {label}
                  </button>
                ))}
              </nav>
            )}

            {section === 'docs' && docSection === 'platform' && (
              <div className="space-y-5">
                <Card title="数据分类">
                  <div className="grid gap-3 sm:grid-cols-3">
                    {(me.data_categories ?? []).map((category) => (
                      <div key={category} className="rounded-[var(--td-radius-sm)] border border-[var(--td-line)] bg-[#f8f9fb] p-4">
                        <h3 className="text-sm font-semibold text-[var(--td-ink)]">{DATA_CATEGORY_DETAILS[category]?.label ?? category}</h3>
                        <p className="mt-2 text-xs leading-5 text-[var(--td-muted)]">{DATA_CATEGORY_DETAILS[category]?.detail}</p>
                      </div>
                    ))}
                    {me.data_categories.length === 0 && (
                      <div className="rounded-[var(--td-radius-sm)] border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 sm:col-span-3">
                        当前密钥尚未开通任何数据分类，请联系管理员配置访问范围。
                      </div>
                    )}
                  </div>
                  <p className="mt-4 text-xs leading-5 text-[var(--td-muted)]">这里展示当前密钥已开通的分类；最终可用数据集仍以该密钥请求 <code className="rounded bg-slate-100 px-1 py-0.5 font-mono">GET /v1/catalog</code> 返回的目录为准。</p>
                </Card>

                <div className="grid gap-5 lg:grid-cols-2">
                  <Card title="账户权限与额度">
                    <dl className="divide-y divide-slate-100 text-sm">
                      {[
                        ['接口权限', '目录发现与数据读取 / 查询'],
                        ['数据分类', me.data_categories.length ? me.data_categories.map((category) => DATA_CATEGORY_DETAILS[category]?.label ?? category).join('、') : '未开通'],
                        ['分钟上限', me.minute_request_limit ? `${me.minute_request_limit.toLocaleString('zh-CN')} 次 / 分钟` : '按当前账户档位执行'],
                        ['并发上限', me.max_concurrent === null ? '不限' : `${me.max_concurrent} 路`],
                        ['每日上限', me.daily_limit === null ? '不限' : `${me.daily_limit.toLocaleString('zh-CN')} 次`],
                      ].map(([term, detail]) => (
                        <div key={term} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
                          <dt className="text-[var(--td-muted)]">{term}</dt>
                          <dd className="text-right font-medium text-[var(--td-ink)]">{detail}</dd>
                        </div>
                      ))}
                    </dl>
                  </Card>
                  <Card title="Agent-first 接入">
                    <p className="text-sm leading-6 text-[var(--td-muted)]">TradingDatas 主要为能够调用 HTTP 工具的 Agent 提供金融数据基础设施。</p>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {['Claude', 'Codex', 'OpenClaw', 'Hermes'].map((agent) => (
                        <span key={agent} className="rounded-md border border-blue-100 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">{agent}</span>
                      ))}
                    </div>
                    <p className="mt-4 text-xs leading-5 text-[var(--td-muted)]">标准流程：先读取目录，再使用目录返回的 dataset ID、schema 与字段执行查询，并检查 freshness、lineage 和 degraded 状态。</p>
                  </Card>
                </div>
              </div>
            )}

            {/* Integration guide */}
            {section === 'docs' && docSection === 'api' && <div>
            <Card title="API 接入指南">
              <div className="space-y-5">
                <div>
                  <p className="mb-1.5 text-xs font-medium text-slate-600">服务地址（Base URL）</p>
                  <div className="flex items-center gap-2">
                    <code className="min-w-0 flex-1 truncate rounded-lg bg-slate-100 px-3 py-2 font-mono text-xs text-slate-700">
                      {client.baseUrl}
                    </code>
                    <CopyButton text={client.baseUrl} label="复制地址" />
                  </div>
                </div>

                <div>
                  <p className="mb-1.5 text-xs font-medium text-slate-600">可用端点</p>
                  <div className="overflow-hidden rounded-lg border border-slate-100">
                    <table className="w-full text-xs">
                      <tbody>
                        {[
                          ['GET', '/v1/catalog', '浏览数据集目录（取 dataset_id 与 schema_major）'],
                          ['POST', '/v1/query', '查询具体数据集的数据行'],
                          ['GET', '/portal/api/me', '查看本页的套餐与配额信息'],
                        ].map(([method, path, desc]) => (
                          <tr key={path} className={TABLE_ROW_CLASS}>
                            <td className="w-14 px-3 py-2.5">
                              <Badge tone={method === 'GET' ? 'green' : 'blue'}>{method}</Badge>
                            </td>
                            <td className="px-3 py-2.5 font-mono text-slate-700">{path}</td>
                            <td className="px-3 py-2.5 text-slate-500">{desc}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div>
                  <p className="mb-1.5 text-xs font-medium text-slate-600">
                    认证方式 · 所有请求携带 <code className="rounded bg-slate-100 px-1 py-0.5 font-mono">Authorization: Bearer 你的API密钥</code> 请求头
                  </p>
                  <pre className="overflow-x-auto rounded-lg bg-slate-900 px-4 py-3 font-mono text-[11px] leading-relaxed text-slate-200">
{curlExample}
                  </pre>
                  <div className="mt-2 flex justify-end">
                    <CopyButton text={curlExample} label="复制示例" />
                  </div>
                </div>

                <div className="rounded-lg bg-amber-50 px-3.5 py-3 text-xs leading-relaxed text-amber-800 ring-1 ring-amber-200 ring-inset">
                  ⚠️ API 密钥等同于账户凭证：请勿写入公开代码仓库或分享给他人；怀疑泄露时立即联系管理员重置。
                  超出并发、频率（如每分钟请求上限）或每日限额时会收到 <code className="font-mono">429</code> 响应，请按提示退避重试。
                </div>
              </div>
            </Card>
            </div>}

            {/* Agent onboarding: copy-ready prompt / tool defs / sample code */}
            {section === 'docs' && docSection === 'agent' && <div>
            <Card title="Agent 接入 · 一键复制">
              <div className="space-y-5">
                <p className="text-xs leading-relaxed text-slate-500">
                  把下面的内容复制进你的 AI Agent（系统提示、工具定义或脚本），即可让它直接使用你的数据接口。
                </p>

                <div>
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <p className="text-xs font-medium text-slate-600">给 AI 助手的接入提示词（粘贴到 Agent 的系统提示中）</p>
                    <CopyButton text={agentPrompt} label="复制提示词" />
                  </div>
                  <pre className="max-h-72 overflow-auto rounded-lg bg-slate-900 px-4 py-3 font-mono text-[11px] leading-relaxed text-slate-200 whitespace-pre-wrap">
{agentPrompt}
                  </pre>
                </div>

                <div>
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <p className="text-xs font-medium text-slate-600">Function Calling 工具定义（OpenAI 兼容格式）</p>
                    <CopyButton text={toolDefsJson} label="复制工具定义" />
                  </div>
                  <pre className="max-h-64 overflow-auto rounded-lg bg-slate-900 px-4 py-3 font-mono text-[11px] leading-relaxed text-slate-200">
{toolDefsJson}
                  </pre>
                </div>

                <div>
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <p className="text-xs font-medium text-slate-600">Python 调用示例（标准库，无需安装依赖）</p>
                    <CopyButton text={pythonExample} label="复制 Python 示例" />
                  </div>
                  <pre className="max-h-72 overflow-auto rounded-lg bg-slate-900 px-4 py-3 font-mono text-[11px] leading-relaxed text-slate-200">
{pythonExample}
                  </pre>
                </div>
              </div>
            </Card>
            </div>}
          </>
        )}
      </main>
    </div>
  )
}
