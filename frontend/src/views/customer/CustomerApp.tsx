import { useEffect, useMemo, useState } from 'react'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowRight, Article, BookOpenText, Check as PhosphorCheck, CirclesThree, Code, CopySimple, Cube, Database, Gauge, House, Key, ListBullets, Robot, Sun, WaveSine } from '@phosphor-icons/react'
import type { ApiClient } from '../../lib/api'
import type { DataCategory, PortalInfo, PortalMeResponse, PortalUsageResponse } from '../../lib/types'
import WorkspaceShell, { type WorkspaceNavItem } from '../../components/WorkspaceShell'
import { CopyButton, ErrorBanner, LoadingPanel, PageIntro, TIER_LABELS, fmtNumber } from '../../components/ui'
import { recordConsoleEvent } from '../../lib/consoleAnalytics'
import type { CustomerSection, DocSection } from '../../lib/workspaceRoute'

type SectionKey = CustomerSection
type DocKey = DocSection

const NAV: WorkspaceNavItem<SectionKey>[] = [
  { key: 'overview', label: '概览', description: 'Agent 接入与用量', icon: House, accent: 'blue' },
  { key: 'access', label: '权限', description: '市场、限额、有效期', icon: Key, accent: 'cyan' },
  { key: 'docs', label: '文档', description: 'API 与 Agent 接入', icon: Article, accent: 'violet' },
]

const AGENTS = [
  { name: 'Claude', icon: Sun },
  { name: 'Codex', icon: Cube },
  { name: 'OpenClaw', icon: CirclesThree },
  { name: 'Hermes', icon: WaveSine },
] as const
type AgentName = (typeof AGENTS)[number]['name']
type StudioLanguage = 'python' | 'curl'

const DATA_CATEGORY_DETAILS: Record<DataCategory, { label: string; detail: string; tone: string }> = {
  a_share: { label: 'A 股', detail: '行情、基础资料与基本面数据', tone: 'border-blue-200 bg-blue-50 text-blue-700' },
  crypto: { label: '加密资产', detail: '公共现货与衍生市场数据', tone: 'border-violet-200 bg-violet-50 text-violet-700' },
  news: { label: '新闻', detail: '新闻、公告与客观事件数据', tone: 'border-orange-200 bg-orange-50 text-orange-700' },
}

function daysUntil(iso: string | null): number | null {
  if (!iso) return null
  return Math.ceil((Date.parse(iso.endsWith('Z') ? iso : `${iso}Z`) - Date.now()) / 86_400_000)
}

function expiryLabel(expiresAt: string | null): { main: string; detail: string; tone: 'green' | 'amber' | 'rose' } {
  if (!expiresAt) return { main: '长期有效', detail: '账户没有设置到期日', tone: 'green' }
  const days = daysUntil(expiresAt)
  if (days !== null && days <= 0) return { main: '已过期', detail: expiresAt.slice(0, 10), tone: 'rose' }
  return {
    main: `${days} 天`,
    detail: `有效期至 ${expiresAt.slice(0, 10)}`,
    tone: days !== null && days <= 14 ? 'amber' : 'green',
  }
}

export default function CustomerApp({
  client,
  tenantId,
  section,
  docSection,
  onSectionChange,
  onDocSectionChange,
  onLogout,
  onViewAdmin,
}: {
  client: ApiClient
  tenantId: string
  section: SectionKey
  docSection: DocKey
  onSectionChange: (section: SectionKey) => void
  onDocSectionChange: (section: DocKey) => void
  onLogout: () => void
  onViewAdmin?: () => void
}) {
  const [me, setMe] = useState<PortalInfo | null>(null)
  const [history, setHistory] = useState<{ date: string; total: number }[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedAgent, setSelectedAgent] = useState<AgentName>('Claude')
  const [studioLanguage, setStudioLanguage] = useState<StudioLanguage>('python')
  const [copiedStudio, setCopiedStudio] = useState(false)

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
    return () => { alive = false }
  }, [client])

  const curlExample = useMemo(() => `# 先读取目录，确认 dataset_id 与 schema_major
curl ${client.baseUrl}/v1/catalog \\
  -H "Authorization: Bearer <你的API密钥>"

# 再查询数据
curl -X POST ${client.baseUrl}/v1/query \\
  -H "Authorization: Bearer <你的API密钥>" \\
  -H "Content-Type: application/json" \\
  -d '{"dataset_id":"cn.dataset.adj_factor","schema_major":2,
       "filters":{"ts_code":{"eq":"000001.SZ"}},"limit":100}'`, [client.baseUrl])

  const pythonExample = useMemo(() => `import requests

base_url = "${client.baseUrl}"
headers = {
    "Authorization": "Bearer YOUR_TRADINGDATAS_API_KEY",
    "Content-Type": "application/json",
}

catalog = requests.get(f"{base_url}/v1/catalog", headers=headers)
catalog.raise_for_status()

query = {
    "dataset_id": "cn.dataset.adj_factor",
    "schema_major": 2,
    "filters": {"ts_code": {"eq": "000001.SZ"}},
    "limit": 100,
}
result = requests.post(f"{base_url}/v1/query", headers=headers, json=query)
print(result.json())`, [client.baseUrl])

  const agentPrompt = useMemo(() => `你是金融数据分析 Agent。通过 TradingDatas 只读 API 获取真实数据。

连接规则
- API Base：${client.baseUrl}
- 每次请求携带 Authorization: Bearer <用户提供的API密钥>
- 不得把密钥写入代码仓库、提示词日志或输出

调用流程
1. 先调用 GET /v1/catalog，读取可用 dataset_id、schema_major、字段、过滤操作符与单页上限。
2. 再调用 POST /v1/query；dataset_id 与 schema_major 必须来自本次 catalog 响应。
3. 使用 filters、order、limit 查询；有 next_cursor 时按游标继续翻页。
4. 检查 metadata.data_through、freshness_state、degraded 与 reasons，再向用户说明数据状态。

异常处理
- 429：停止并按退避策略重试，不得并发轰击。
- 401：提示用户检查密钥状态或有效期。
- 只读数据服务，不生成或执行交易指令。`, [client.baseUrl])

  const toolDefsJson = useMemo(() => JSON.stringify([
    {
      type: 'function',
      function: {
        name: 'tradingdatas_catalog',
        description: '读取 TradingDatas 可用数据集目录。任何查询前必须先调用。',
        parameters: { type: 'object', properties: {}, required: [] },
      },
    },
    {
      type: 'function',
      function: {
        name: 'tradingdatas_query',
        description: '查询目录中已授权的数据集。',
        parameters: {
          type: 'object',
          properties: {
            dataset_id: { type: 'string' },
            schema_major: { type: 'integer' },
            filters: { type: 'object' },
            order: { type: 'array', items: { type: 'string' } },
            limit: { type: 'integer' },
            cursor: { type: 'string' },
          },
          required: ['dataset_id', 'schema_major'],
        },
      },
    },
  ], null, 2), [])

  const copyStudio = async () => {
    try {
      await navigator.clipboard.writeText(studioLanguage === 'python' ? pythonExample : curlExample)
      recordConsoleEvent('copy_succeeded', 'customer')
      setCopiedStudio(true)
      window.setTimeout(() => setCopiedStudio(false), 1600)
    } catch {
      setError('复制失败，请手动选择内容复制。')
    }
  }

  if (!me && !error) return <LoadingPanel label="加载账户工作台…" />

  const expiry = me ? expiryLabel(me.expires_at) : null
  const dailyRemaining = me?.daily_limit === null || me?.daily_limit === undefined
    ? null
    : Math.max(0, me.daily_limit - me.usage.today_count)
  const studioCode = studioLanguage === 'python' ? pythonExample : curlExample

  return (
    <WorkspaceShell
      workspace="customer"
      workspaceLabel="客户工作台"
      items={NAV}
      active={section}
      onSelect={onSectionChange}
      onSwitch={onViewAdmin}
      switchLabel="返回管理工作台"
      onLogout={onLogout}
      previewing={Boolean(onViewAdmin)}
      identity={tenantId}
      layout="side"
    >
      {error && <ErrorBanner message={error} />}
      {me && section === 'overview' && (
        <div className="space-y-0">
          <section className="grid border-b border-[var(--td-line)] pb-10 pt-1 xl:grid-cols-[minmax(420px,0.85fr)_minmax(0,1.4fr)] xl:pb-12" aria-labelledby="customer-workbench-heading">
            <div className="flex min-w-0 flex-col justify-center border-b border-[var(--td-line)] pb-9 xl:border-r xl:border-b-0 xl:pr-10 xl:pb-0">
              <div className="flex items-center gap-2 text-[11px] font-semibold text-[var(--td-accent)]">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--td-accent)]" /> Agent-first 数据服务
              </div>
              <h1 id="customer-workbench-heading" className="mt-5 max-w-[580px] text-[34px] font-semibold leading-[1.12] tracking-[-0.055em] text-[var(--td-ink)] sm:text-[38px] xl:text-[38px]">
                让 Agent 用一种方式<br className="hidden sm:block" />读取多市场金融数据
              </h1>
              <p className="mt-5 max-w-xl text-[14px] leading-7 text-[var(--td-muted)]">
                通过统一目录发现可用数据，再按标准查询合同读取结果，并依据可追溯状态判断数据是否适合当前任务。
              </p>

              <div className="mt-8 divide-y divide-[var(--td-line)] border-y border-[var(--td-line)]">
                {[
                  [ListBullets, '统一目录', '发现数据集、字段与查询约束'],
                  [Code, '标准查询', '使用同一份 catalog / query 合同'],
                  [Database, '可追溯状态', '检查数据时间、质量与降级原因'],
                ].map(([Icon, label, detail]) => (
                  <div key={String(label)} className="grid grid-cols-[28px_92px_minmax(0,1fr)] items-center gap-3 py-3.5">
                    <Icon aria-hidden size={18} className="text-[var(--td-ink-soft)]" />
                    <span className="text-[12px] font-semibold text-[var(--td-ink)]">{String(label)}</span>
                    <span className="text-[11px] leading-5 text-[var(--td-muted)]">{String(detail)}</span>
                  </div>
                ))}
              </div>

              <div className="mt-7 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => document.getElementById('agent-studio-heading')?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                  className="inline-flex min-h-11 items-center gap-3 rounded-[var(--td-radius-sm)] bg-[var(--td-accent)] px-5 text-[13px] font-semibold text-white transition-colors hover:bg-[var(--td-accent-strong)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--td-accent)]"
                >
                  开始配置 <ArrowRight aria-hidden size={15} />
                </button>
                <button
                  type="button"
                  onClick={() => { onDocSectionChange('quickstart'); onSectionChange('docs') }}
                  className="inline-flex min-h-11 items-center gap-2 px-2 text-[12px] font-semibold text-[var(--td-ink-soft)] transition-colors hover:text-[var(--td-accent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--td-accent)]"
                >
                  查看完整文档 <ArrowRight aria-hidden size={14} />
                </button>
              </div>
            </div>

            <section id="agent-studio" className="min-w-0 pt-9 xl:pl-10 xl:pt-0" aria-labelledby="agent-studio-heading">
              <div className="flex flex-col gap-4 border-b border-[var(--td-line)] pb-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-[10px] font-semibold tracking-[0.06em] text-[var(--td-faint)]">AGENT SETUP</div>
                  <h2 id="agent-studio-heading" className="mt-1 text-[19px] font-semibold tracking-[-0.025em] text-[var(--td-ink)]">Agent 设置工作台</h2>
                </div>
                <div className="flex max-w-full gap-1 overflow-x-auto" role="tablist" aria-label="选择 Agent">
                  {AGENTS.map((agent) => {
                    const AgentIcon = agent.icon
                    const selected = selectedAgent === agent.name
                    return (
                      <button
                        key={agent.name}
                        type="button"
                        role="tab"
                        aria-selected={selected}
                        onClick={() => setSelectedAgent(agent.name)}
                        className={`inline-flex min-h-9 min-w-max items-center gap-2 border-b-2 px-3 text-[11px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--td-accent)] ${selected ? 'border-[var(--td-accent)] text-[var(--td-accent)]' : 'border-transparent text-[var(--td-muted)] hover:text-[var(--td-ink)]'}`}
                      >
                        <AgentIcon aria-hidden size={14} /> {agent.name}
                      </button>
                    )
                  })}
                </div>
              </div>

              <ol className="grid border-b border-[var(--td-line)] sm:grid-cols-3" aria-label="接入步骤">
                {[
                  ['01', '选择 Agent', selectedAgent],
                  ['02', '添加访问密钥', '使用环境变量保存'],
                  ['03', '运行首次查询', '验证目录与查询结果'],
                ].map(([number, label, detail], index) => (
                  <li key={number} className={`grid grid-cols-[28px_minmax(0,1fr)] gap-2 py-3 sm:px-4 ${index > 0 ? 'border-t border-[var(--td-line)] sm:border-t-0 sm:border-l' : ''}`}>
                    <span className={`flex h-6 w-6 items-center justify-center rounded-full border text-[10px] font-semibold ${index === 0 ? 'border-[var(--td-accent)] bg-[var(--td-accent)] text-white' : 'border-[var(--td-line-strong)] text-[var(--td-muted)]'}`}>{number}</span>
                    <span>
                      <span className="block text-[11px] font-semibold text-[var(--td-ink)]">{label}</span>
                      <span className="mt-0.5 block text-[10px] leading-4 text-[var(--td-faint)]">{detail}</span>
                    </span>
                  </li>
                ))}
              </ol>

              <div className="mt-5 overflow-hidden rounded-[var(--td-radius-lg)] border border-[var(--td-line-strong)] bg-white shadow-[var(--td-shadow-hairline)]">
                <div className="flex items-center justify-between border-b border-[var(--td-line)] bg-[#f6f7f8]">
                  <div className="flex" role="tablist" aria-label="示例语言">
                    {([['python', 'Python'], ['curl', 'cURL']] as const).map(([key, label]) => (
                      <button
                        key={key}
                        type="button"
                        role="tab"
                        aria-selected={studioLanguage === key}
                        onClick={() => { setStudioLanguage(key); setCopiedStudio(false) }}
                        className={`min-h-11 border-b-2 px-5 text-[11px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-[var(--td-accent)] ${studioLanguage === key ? 'border-[var(--td-accent)] bg-white text-[var(--td-accent)]' : 'border-transparent text-[var(--td-muted)] hover:text-[var(--td-ink)]'}`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={copyStudio}
                    aria-live="polite"
                    className="inline-flex min-h-11 items-center gap-2 px-4 text-[11px] font-semibold text-[var(--td-ink-soft)] transition-colors hover:bg-white hover:text-[var(--td-accent)] focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-[var(--td-accent)]"
                  >
                    {copiedStudio ? <PhosphorCheck aria-hidden size={14} /> : <CopySimple aria-hidden size={14} />}
                    {copiedStudio ? '已复制' : '复制示例'}
                  </button>
                </div>

                <div className="max-h-[280px] overflow-auto bg-[#fbfbfc] py-4 font-mono text-[11px] leading-[1.72] text-[#343842]">
                  {studioCode.split('\n').map((line, index) => (
                    <div key={`${index}-${line}`} className="grid min-w-[620px] grid-cols-[44px_minmax(0,1fr)] px-4 sm:px-5">
                      <span className="select-none pr-4 text-right text-[#a4a8b2]">{index + 1}</span>
                      <code className="whitespace-pre">{line || ' '}</code>
                    </div>
                  ))}
                </div>

                <div className="flex flex-col gap-2 border-t border-[#dfe4f3] bg-[#f1f4ff] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 flex h-5 w-5 items-center justify-center rounded-full border border-[#b9c7ff] text-[var(--td-accent)]"><PhosphorCheck aria-hidden size={11} /></span>
                    <div>
                      <div className="text-[11px] font-semibold text-[#2946a8]">示例已按真实接口合同准备</div>
                      <div className="mt-0.5 text-[10px] leading-4 text-[#66719a]">密钥保持占位符；运行前请保存到本地环境变量。</div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => { onDocSectionChange('quickstart'); onSectionChange('docs') }}
                    className="inline-flex min-h-8 items-center gap-2 text-[10px] font-semibold text-[var(--td-accent)] hover:text-[var(--td-accent-strong)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--td-accent)]"
                  >
                    查看请求与响应说明 <ArrowRight aria-hidden size={12} />
                  </button>
                </div>
              </div>
            </section>
          </section>

          <section className="border-b border-[var(--td-line)] py-7" aria-labelledby="account-capacity-heading">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <h2 id="account-capacity-heading" className="text-[17px] font-semibold tracking-[-0.025em] text-[var(--td-ink)]">账户能力</h2>
                <span className={`inline-flex items-center gap-1.5 text-[10px] font-semibold ${me.enabled ? 'text-[var(--td-success)]' : 'text-[var(--td-danger)]'}`}><span className="h-1.5 w-1.5 rounded-full bg-current" />{me.enabled ? '服务可用' : '服务已暂停'}</span>
              </div>
              <div className="text-[10px] text-[var(--td-faint)]">{tenantId} · {TIER_LABELS[me.tier] ?? me.tier}</div>
            </div>

            <dl className="mt-5 grid border-y border-[var(--td-line)] sm:grid-cols-2 xl:grid-cols-4">
              <div className="px-0 py-5 sm:px-5 sm:first:pl-0">
                <dt className="flex items-center gap-2 text-[11px] font-medium text-[var(--td-muted)]"><Article aria-hidden size={15} />账户有效期</dt>
                <dd className="mt-3 text-[22px] font-semibold tabular-nums tracking-[-0.03em] text-[var(--td-ink)]">{expiry?.main ?? '—'}</dd>
                <div className="mt-1 text-[10px] text-[var(--td-faint)]">{expiry?.detail ?? '—'}</div>
              </div>
              <div className="border-t border-[var(--td-line)] px-0 py-5 sm:border-t-0 sm:border-l sm:px-5">
                <dt className="flex items-center gap-2 text-[11px] font-medium text-[var(--td-muted)]"><Gauge aria-hidden size={15} />并发请求</dt>
                <dd className="mt-3 text-[22px] font-semibold tabular-nums tracking-[-0.03em] text-[var(--td-ink)]">{me.max_concurrent === null ? '不限' : me.max_concurrent}</dd>
                <div className="mt-1 text-[10px] text-[var(--td-faint)]">{me.max_concurrent === null ? '当前账户不限制并行数' : '当前账户同时请求上限'}</div>
              </div>
              <div className="border-t border-[var(--td-line)] px-0 py-5 sm:border-l sm:px-5 xl:border-t-0">
                <dt className="flex items-center gap-2 text-[11px] font-medium text-[var(--td-muted)]"><WaveSine aria-hidden size={15} />今日剩余额度</dt>
                <dd className="mt-3 text-[22px] font-semibold tabular-nums tracking-[-0.03em] text-[var(--td-ink)]">{dailyRemaining === null ? '不限' : `${fmtNumber(dailyRemaining)} / ${fmtNumber(me.daily_limit)}`}</dd>
                <div className="mt-1 text-[10px] text-[var(--td-faint)]">今日已请求 {fmtNumber(me.usage.today_count)}</div>
              </div>
              <div className="border-t border-[var(--td-line)] px-0 py-5 sm:border-l sm:px-5 xl:border-t-0">
                <dt className="flex items-center gap-2 text-[11px] font-medium text-[var(--td-muted)]"><Database aria-hidden size={15} />已授权市场</dt>
                <dd className="mt-3 flex flex-wrap gap-2">
                  {me.data_categories.map((category) => (
                    <span key={category} className={`rounded-[4px] border px-2.5 py-1 text-[10px] font-semibold ${DATA_CATEGORY_DETAILS[category]?.tone ?? 'border-[var(--td-line)] text-[var(--td-muted)]'}`}>{DATA_CATEGORY_DETAILS[category]?.label ?? category}</span>
                  ))}
                  {!me.data_categories.length && <span className="text-[11px] text-[var(--td-danger)]">尚未开通市场</span>}
                </dd>
                <div className="mt-2 text-[10px] text-[var(--td-faint)]">最终范围以实时目录返回为准</div>
              </div>
            </dl>
          </section>

          <section className="pt-7" aria-labelledby="usage-heading">
            <div className="grid gap-6 xl:grid-cols-[220px_minmax(0,1fr)_220px] xl:items-stretch">
              <div>
                <h2 id="usage-heading" className="text-[17px] font-semibold tracking-[-0.025em] text-[var(--td-ink)]">每日查询用量</h2>
                <div className="mt-5 text-[30px] font-semibold tabular-nums tracking-[-0.045em] text-[var(--td-ink)]">{fmtNumber(me.usage.today_count)}</div>
                <p className="mt-1 text-[10px] text-[var(--td-muted)]">今日已用查询量</p>
              </div>

              {!history || history.every((item) => item.total === 0) ? (
                <div className="flex min-h-32 items-center border-y border-[var(--td-line)] text-[12px] text-[var(--td-muted)]">完成首次 API 请求后，这里会显示调用节奏。</div>
              ) : (
                <div className="h-36 min-w-0 border-y border-[var(--td-line)] py-4">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={history} margin={{ top: 8, right: 8, bottom: 0, left: 8 }} accessibilityLayer>
                      <XAxis dataKey="date" hide />
                      <YAxis hide allowDecimals={false} />
                      <Tooltip formatter={(value) => [`${Number(value).toLocaleString('zh-CN')} 次`, '请求']} labelFormatter={(value) => String(value)} contentStyle={{ borderRadius: 6, border: '1px solid #e1e0dc', boxShadow: '0 8px 24px rgb(22 22 22 / .08)', fontSize: 11 }} />
                      <Line type="monotone" dataKey="total" stroke="var(--td-accent)" strokeWidth={2} dot={false} activeDot={{ r: 3, fill: 'var(--td-accent)' }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              <div className="border-t border-[var(--td-line)] pt-5 xl:border-t-0 xl:border-l xl:pl-6 xl:pt-0">
                <div className="text-[10px] font-semibold text-[var(--td-faint)]">近 30 天</div>
                <div className="mt-2 text-[19px] font-semibold tabular-nums text-[var(--td-ink)]">{history?.reduce((sum, item) => sum + item.total, 0).toLocaleString('zh-CN') ?? '—'}</div>
                <div className="mt-5 text-[10px] font-semibold text-[var(--td-faint)]">频率窗口</div>
                <div className="mt-2 text-[12px] font-medium text-[var(--td-ink-soft)]">{me.minute_request_limit ? `${fmtNumber(me.minute_request_limit)} 次 / 分钟` : `${fmtNumber(me.hourly_request_limit)} 次 / 小时`}</div>
              </div>
            </div>
          </section>
        </div>
      )}

      {me && section === 'access' && (
        <div className="space-y-6">
          <PageIntro eyebrow="账户能力" title="权限与额度" description="查看这把 API 密钥当前真正生效的市场、速率和账户期限。" />
          <div className="grid overflow-hidden rounded-[var(--td-radius-lg)] border border-[var(--td-line)] bg-white shadow-[var(--td-shadow-hairline)] xl:grid-cols-[360px_minmax(0,1fr)]">
            <section className="border-b border-[var(--td-line)] bg-[#f3f5fb] p-6 text-[var(--td-ink)] xl:border-r xl:border-b-0 xl:p-8" aria-labelledby="account-contract-heading">
              <div className="text-[11px] font-medium tracking-[0.04em] text-[var(--td-faint)]">当前账户</div>
              <h2 id="account-contract-heading" className="mt-3 text-[22px] font-semibold tracking-[-0.035em]">{tenantId}</h2>
              <div className="mt-2 flex items-center gap-2 text-[12px] text-[var(--td-muted)]"><span className={`h-1.5 w-1.5 rounded-full ${me.enabled ? 'bg-[var(--td-success)]' : 'bg-[var(--td-danger)]'}`} />{me.enabled ? '服务可用' : '服务已暂停'} · {TIER_LABELS[me.tier] ?? me.tier}</div>
              <dl className="mt-10 divide-y divide-[var(--td-line)] border-y border-[var(--td-line)]">
                {[
                  ['账户有效期', expiry?.main ?? '—', expiry?.detail ?? ''],
                  ['今日请求', fmtNumber(me.usage.today_count), `每日上限 ${fmtNumber(me.daily_limit)}`],
                ].map(([label, value, detail]) => <div key={label} className="grid grid-cols-[1fr_auto] gap-6 py-5"><dt className="text-[11px] text-[var(--td-muted)]">{label}</dt><dd className="text-right"><div className="text-[17px] font-medium tabular-nums">{value}</div><div className="mt-1 text-[10px] text-[var(--td-faint)]">{detail}</div></dd></div>)}
              </dl>
              <p className="mt-6 text-[11px] leading-5 text-[var(--td-muted)]">权限数据来自当前账户，不是示例套餐或静态说明。</p>
            </section>

            <div className="min-w-0 p-6 xl:p-8">
              <section aria-labelledby="runtime-limits-heading">
                <div className="flex items-end justify-between gap-4"><div><div className="text-[11px] font-medium text-[var(--td-accent)]">运行额度</div><h2 id="runtime-limits-heading" className="mt-1 text-[18px] font-semibold tracking-[-0.025em] text-[var(--td-ink)]">调用能力</h2></div><span className="font-mono text-[10px] text-[var(--td-faint)]">ACCOUNT LIMITS</span></div>
                <dl className="mt-5 grid border-y border-[var(--td-line)] sm:grid-cols-3 sm:divide-x sm:divide-[var(--td-line)]">
                  {[
                    ['请求频率', fmtNumber(me.minute_request_limit ?? me.hourly_request_limit), me.minute_request_limit ? '次 / 分钟' : '次 / 小时'],
                    ['并发上限', me.max_concurrent === null ? '不限' : String(me.max_concurrent), me.max_concurrent === null ? '不限制并行数' : '并行请求'],
                    ['每日上限', fmtNumber(me.daily_limit), '次 / 自然日'],
                  ].map(([label, value, detail]) => <div key={label} className="border-b border-[var(--td-line)] py-5 last:border-b-0 sm:border-b-0 sm:px-5 sm:first:pl-0 sm:last:pr-0"><dt className="text-[11px] text-[var(--td-muted)]">{label}</dt><dd className="mt-2 text-[26px] font-semibold tracking-[-0.05em] tabular-nums text-[var(--td-ink)]">{value}</dd><div className="mt-1 text-[10px] text-[var(--td-faint)]">{detail}</div></div>)}
                </dl>
              </section>

              <section className="mt-9" aria-labelledby="market-access-heading">
                <div className="flex items-center justify-between gap-4"><h2 id="market-access-heading" className="text-[13px] font-semibold text-[var(--td-ink)]">已开通市场</h2><span className="text-[10px] text-[var(--td-faint)]">{me.data_categories.length} 个分类</span></div>
                <div className="mt-3 divide-y divide-[var(--td-line)] border-y border-[var(--td-line)]">
                  {me.data_categories.map((category, index) => { const item = DATA_CATEGORY_DETAILS[category]; return <div key={category} className="grid gap-2 py-4 sm:grid-cols-[32px_120px_1fr_auto] sm:items-center"><span className={`flex h-7 w-7 items-center justify-center rounded-[5px] text-[10px] font-semibold ${index === 0 ? 'bg-[#edf3ff] text-[#315cff]' : index === 1 ? 'bg-[#f1eeff] text-[#7057d6]' : 'bg-[#fff1e8] text-[#bb5c24]'}`}>{String(index + 1).padStart(2, '0')}</span><span className="text-[13px] font-semibold text-[var(--td-ink)]">{item.label}</span><span className="text-[11px] text-[var(--td-muted)]">{item.detail}</span><span className="text-[10px] font-medium text-[var(--td-accent)]">已授权</span></div> })}
                  {!me.data_categories.length && <div className="py-5 text-sm text-[var(--td-danger)]">当前密钥尚未开通数据分类，请联系管理员配置。</div>}
                </div>
                <p className="mt-3 text-[11px] leading-5 text-[var(--td-muted)]">最终可用数据集以当前密钥调用 <code className="rounded-[4px] bg-[var(--td-surface-subtle)] px-1.5 py-0.5 font-mono text-[10px]">GET /v1/catalog</code> 的实时返回为准。</p>
              </section>

              <section className="mt-9" aria-labelledby="endpoint-access-heading">
                <h2 id="endpoint-access-heading" className="text-[13px] font-semibold text-[var(--td-ink)]">接口能力</h2>
                <div className="mt-3 grid border-t border-[var(--td-line)] md:grid-cols-3">
                  {[
                    ['01', '发现目录', '读取数据集、字段、过滤条件与分页限制。'],
                    ['02', '读取与查询', '按已授权市场读取数据，不包含写入或交易能力。'],
                    ['03', '查看账户', '查看自身权限、有效期与用量，不读取其他客户信息。'],
                  ].map(([number, title, detail]) => <div key={title} className="border-b border-[var(--td-line)] py-4 md:border-r md:px-5 md:first:pl-0 md:last:border-r-0"><span className="font-mono text-[10px] text-[var(--td-accent)]">{number}</span><div className="mt-2 text-[12px] font-semibold text-[var(--td-ink)]">{title}</div><p className="mt-1 text-[11px] leading-5 text-[var(--td-muted)]">{detail}</p></div>)}
                </div>
              </section>
            </div>
          </div>
        </div>
      )}

      {me && section === 'docs' && (
        <div className="space-y-6">
          <PageIntro eyebrow="开发者资源" title="文档中心" description="从第一次请求到 Agent 工具配置，把接入所需内容放在一条清晰路径里。" />
          <div className="grid overflow-hidden rounded-[var(--td-radius-lg)] border border-[var(--td-line)] bg-white shadow-[var(--td-shadow-hairline)] lg:grid-cols-[240px_minmax(0,1fr)]">
            <nav aria-label="文档目录" className="h-fit border-b border-[var(--td-line)] bg-[var(--td-surface-subtle)] p-3 lg:min-h-[540px] lg:border-r lg:border-b-0 lg:p-4">
              <div className="px-3 pt-2 pb-3 text-[10px] font-semibold tracking-[0.04em] text-[var(--td-faint)]">文档目录</div>
              {([
                ['quickstart', Code, 'API 快速开始', '认证与首次查询'],
                ['agents', Robot, 'Agent 接入', '提示词与工具定义'],
                ['reference', BookOpenText, '使用约定', '分页、限流与安全'],
              ] as const).map(([key, Icon, label, detail]) => (
                <button key={key} type="button" onClick={() => onDocSectionChange(key)} aria-current={docSection === key ? 'page' : undefined} className={`relative flex w-full items-start gap-3 border-t border-[var(--td-line)] px-3 py-4 text-left focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--td-accent)] ${docSection === key ? 'bg-white text-[var(--td-accent-strong)] before:absolute before:inset-y-3 before:left-0 before:w-0.5 before:bg-[var(--td-accent)]' : 'text-[var(--td-muted)] hover:bg-white/70 hover:text-[var(--td-ink)]'}`}>
                  <Icon aria-hidden size={16} className="mt-0.5 shrink-0" />
                  <span><span className="block text-xs font-semibold">{label}</span><span className="mt-0.5 block text-[10px] opacity-70">{detail}</span></span>
                </button>
              ))}
            </nav>

            <div className="min-w-0 p-5 sm:p-7 lg:p-9">
            {docSection === 'quickstart' && <article>
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--td-line)] pb-5"><div><div className="text-[10px] font-medium text-[var(--td-accent)]">QUICKSTART</div><h2 className="mt-1 text-[20px] font-semibold tracking-[-0.03em] text-[var(--td-ink)]">API 快速开始</h2></div><CopyButton text={curlExample} label="复制示例" /></div>
              <div className="mt-7 grid gap-7 xl:grid-cols-[0.8fr_1.4fr]">
                <div className="space-y-4">
                  {[
                    ['01', '认证请求', '所有请求都使用 Bearer API 密钥。'],
                    ['02', '发现数据集', '先读取 /v1/catalog，确认数据合同。'],
                    ['03', '查询与翻页', '通过 /v1/query 查询，使用 next_cursor 继续翻页。'],
                  ].map(([number, title, detail]) => <div key={number} className="flex gap-3"><span className="font-mono text-[10px] text-[var(--td-accent)]">{number}</span><div><div className="text-sm font-semibold text-[var(--td-ink)]">{title}</div><p className="mt-1 text-xs leading-5 text-[var(--td-muted)]">{detail}</p></div></div>)}
                </div>
                <pre className="max-h-[420px] overflow-auto rounded-[var(--td-radius)] border border-[var(--td-line-strong)] bg-[#fbfbfc] p-5 font-mono text-[11px] leading-6 text-[#343842] whitespace-pre-wrap shadow-[var(--td-shadow-hairline)]">{curlExample}</pre>
              </div>
            </article>}

            {docSection === 'agents' && <article className="space-y-8">
              <div className="border-b border-[var(--td-line)] pb-5"><div className="text-[10px] font-medium text-[var(--td-accent)]">AGENT SETUP</div><h2 className="mt-1 text-[20px] font-semibold tracking-[-0.03em] text-[var(--td-ink)]">Agent 接入</h2><p className="mt-2 text-[12px] leading-5 text-[var(--td-muted)]">把真实目录发现、查询和异常处理规则一次交给你的 Agent。</p></div>
              <section aria-labelledby="agent-prompt-heading"><div className="mb-3 flex items-center justify-between gap-4"><h3 id="agent-prompt-heading" className="text-[13px] font-semibold text-[var(--td-ink)]">接入提示词</h3><CopyButton text={agentPrompt} label="复制提示词" /></div><pre className="max-h-[420px] overflow-auto rounded-[var(--td-radius)] border border-[var(--td-line-strong)] bg-[#fbfbfc] p-5 font-mono text-[11px] leading-6 text-[#343842] whitespace-pre-wrap shadow-[var(--td-shadow-hairline)]">{agentPrompt}</pre></section>
              <section aria-labelledby="tool-schema-heading"><div className="mb-3 flex items-center justify-between gap-4"><h3 id="tool-schema-heading" className="text-[13px] font-semibold text-[var(--td-ink)]">Function Calling 定义</h3><CopyButton text={toolDefsJson} label="复制定义" /></div><pre className="max-h-[380px] overflow-auto rounded-[var(--td-radius)] border border-[var(--td-line-strong)] bg-[#fbfbfc] p-5 font-mono text-[11px] leading-6 text-[#343842] shadow-[var(--td-shadow-hairline)]">{toolDefsJson}</pre></section>
            </article>}

            {docSection === 'reference' && <article>
              <div className="border-b border-[var(--td-line)] pb-5"><div className="text-[10px] font-medium text-[var(--td-accent)]">REFERENCE</div><h2 className="mt-1 text-[20px] font-semibold tracking-[-0.03em] text-[var(--td-ink)]">使用约定</h2><p className="mt-2 text-[12px] leading-5 text-[var(--td-muted)]">查询边界、分页策略和密钥安全的最低要求。</p></div>
              <div className="mt-5 grid md:grid-cols-2">
                {[
                  ['只读边界', 'TradingDatas 提供数据目录与查询，不写入数据，也不生成或执行交易指令。'],
                  ['限流与重试', '收到 429 后停止当前批次，并采用指数退避；并发不得超过账户上限。'],
                  ['游标分页', 'next_cursor 非空时继续翻页；不要自行构造或复用其他查询的游标。'],
                  ['密钥安全', '密钥只放在环境变量或安全凭证存储中，不写入仓库、日志和公开提示词。'],
                ].map(([title, detail], index) => <section key={title} className="border-b border-[var(--td-line)] py-5 md:px-5 md:odd:border-r md:odd:pl-0"><span className="font-mono text-[10px] text-[var(--td-accent)]">0{index + 1}</span><div className="mt-2 text-[13px] font-semibold text-[var(--td-ink)]">{title}</div><p className="mt-2 text-[11px] leading-5 text-[var(--td-muted)]">{detail}</p></section>)}
              </div>
            </article>}
            </div>
          </div>
        </div>
      )}
    </WorkspaceShell>
  )
}
