import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { BookOpen, Bot, Check, CircleGauge, Clock3, Code2, Sparkles } from 'lucide-react'
import { Article, Check as PhosphorCheck, CirclesThree, CopySimple, Cube, House, Key, Sun, WaveSine } from '@phosphor-icons/react'
import type { ApiClient } from '../../lib/api'
import type { DataCategory, PortalInfo, PortalMeResponse, PortalUsageResponse } from '../../lib/types'
import WorkspaceShell, { type WorkspaceNavItem } from '../../components/WorkspaceShell'
import { Card, CopyButton, ErrorBanner, LoadingPanel, PageIntro, TIER_LABELS, fmtNumber } from '../../components/ui'
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
type SetupTab = 'prompt' | 'tools' | 'api'

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
  const [setupTab, setSetupTab] = useState<SetupTab>('prompt')
  const [copiedSetup, setCopiedSetup] = useState(false)

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

  const visibleAgentPrompt = useMemo(() => `你是使用 TradingDatas 的金融数据 Agent。请遵循以下流程：

1. 先调用 GET /v1/catalog，确认数据集、字段与查询约束。
2. 再调用 POST /v1/query；数据集与 schema 版本必须来自本次目录响应。
3. 检查 data_through、freshness_state、degraded 与 reasons。
4. 收到 429 后停止当前批次，并按退避策略重试。
5. 不得记录、输出或转发用户的 API 密钥。`, [])

  const apiExampleVisible = useMemo(() => `# 先读取目录
GET /v1/catalog
Authorization: Bearer <你的 API 密钥>

# 再提交查询
POST /v1/query
{
  "dataset_id": "cn.dataset.adj_factor",
  "schema_major": 2,
  "limit": 100
}`, [])

  const setupContent = setupTab === 'prompt'
    ? { label: '复制提示词', visible: visibleAgentPrompt, copy: `${agentPrompt}\n\n目标 Agent：${selectedAgent}` }
    : setupTab === 'tools'
      ? { label: '复制定义', visible: toolDefsJson, copy: toolDefsJson }
      : { label: '复制示例', visible: apiExampleVisible, copy: curlExample }

  const copySetup = async () => {
    try {
      await navigator.clipboard.writeText(setupContent.copy)
      recordConsoleEvent('copy_succeeded', 'customer')
      setCopiedSetup(true)
      window.setTimeout(() => setCopiedSetup(false), 1600)
    } catch {
      setError('复制失败，请手动选择内容复制。')
    }
  }

  if (!me && !error) return <LoadingPanel label="加载账户工作台…" />

  const expiry = me ? expiryLabel(me.expires_at) : null

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
    >
      {error && <ErrorBanner message={error} />}
      {me && section === 'overview' && (
        <div className="grid gap-0 xl:grid-cols-[minmax(0,1.9fr)_minmax(310px,0.88fr)]">
          <div className="min-w-0 pr-0 xl:pr-10">
            <div className="max-w-3xl">
              <h1 className="text-[34px] font-semibold leading-[1.12] tracking-[-0.055em] text-[var(--td-ink)] sm:text-[38px]">Agent 接入</h1>
              <p className="mt-3 text-[14px] leading-6 text-[var(--td-muted)]">复制提示词或工具定义，交给 Claude、Codex、OpenClaw 或 Hermes。</p>
            </div>

            <section className="mt-8" aria-labelledby="agent-selector-heading">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                <div>
                  <h2 id="agent-selector-heading" className="text-[13px] font-semibold text-[var(--td-ink)]">选择 Agent</h2>
                  <div className="mt-3 flex max-w-full gap-1 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" role="tablist" aria-label="Agent">
                    {AGENTS.map((agent) => {
                      const AgentIcon = agent.icon
                      return (
                        <button
                          key={agent.name}
                          type="button"
                          role="tab"
                          aria-selected={selectedAgent === agent.name}
                          onClick={() => setSelectedAgent(agent.name)}
                          className={`inline-flex min-h-11 min-w-max items-center gap-1 rounded-[var(--td-radius-sm)] border px-1 text-[10px] font-medium transition-colors sm:gap-2 sm:px-3 sm:text-[13px] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--td-accent)] ${selectedAgent === agent.name ? 'border-[var(--td-accent)] bg-white text-[var(--td-ink)]' : 'border-transparent text-[var(--td-muted)] hover:border-[var(--td-line)] hover:bg-white hover:text-[var(--td-ink)]'}`}
                        >
                          <AgentIcon aria-hidden size={15} weight="regular" />
                          {agent.name}
                        </button>
                      )
                    })}
                  </div>
                </div>
                <p className="max-w-sm border-l-2 border-[var(--td-orange)] pl-3 text-[11px] leading-5 text-[var(--td-muted)]">为 {selectedAgent} 调整说明语境；目录与查询合同保持一致。</p>
              </div>

              <div className="mt-6 overflow-hidden rounded-[var(--td-radius)] border border-[var(--td-line-strong)] bg-white shadow-[var(--td-shadow-1)]">
                <div className="flex flex-col border-b border-[var(--td-line)] bg-[#f4f4f2] sm:flex-row sm:items-stretch sm:justify-between">
                  <div className="flex overflow-x-auto" role="tablist" aria-label="接入内容">
                    {([
                      ['prompt', '接入提示词'],
                      ['tools', '工具定义'],
                      ['api', 'API 示例'],
                    ] as const).map(([key, label]) => (
                      <button
                        key={key}
                        type="button"
                        role="tab"
                        aria-selected={setupTab === key}
                        onClick={() => { setSetupTab(key); setCopiedSetup(false) }}
                        className={`min-h-11 min-w-max border-r border-[var(--td-line)] px-5 text-[12px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-[var(--td-accent)] ${setupTab === key ? 'bg-[var(--td-lilac-quiet)] text-[var(--td-ink)] shadow-[inset_0_-2px_0_#7a66e8]' : 'text-[var(--td-muted)] hover:bg-white/70 hover:text-[var(--td-ink)]'}`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={copySetup}
                    className="group flex min-h-11 items-center justify-between gap-3 border-t border-[var(--td-line)] px-4 text-[12px] font-semibold text-[var(--td-ink)] transition-colors hover:bg-white focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-[var(--td-accent)] sm:border-t-0 sm:border-l"
                    aria-live="polite"
                  >
                    <span>{copiedSetup ? '已复制' : setupContent.label}</span>
                    <span className="flex h-6 w-6 items-center justify-center rounded-[4px] bg-[var(--td-ink)] text-white transition-transform group-hover:translate-x-0.5">
                      {copiedSetup ? <PhosphorCheck aria-hidden size={13} /> : <CopySimple aria-hidden size={13} />}
                    </span>
                  </button>
                </div>
                <pre className="min-h-[300px] overflow-auto whitespace-pre-wrap bg-[#fffefa] px-5 py-5 font-mono text-[12px] leading-6 text-[#343039] sm:px-7">{setupContent.visible}</pre>
              </div>

              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <p className="text-[11px] leading-5 text-[var(--td-faint)]">复制内容会自动带入当前服务配置；密钥仍使用占位符。</p>
                <button
                  type="button"
                  onClick={() => {
                    onDocSectionChange(setupTab === 'api' ? 'quickstart' : 'agents')
                    onSectionChange('docs')
                  }}
                  className="inline-flex min-h-9 items-center gap-2 rounded-[var(--td-radius-sm)] border border-[var(--td-line)] bg-white px-3 text-[11px] font-semibold text-[var(--td-ink-soft)] transition-colors hover:border-[var(--td-line-strong)] hover:text-[var(--td-ink)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--td-accent)]"
                >
                  <Article aria-hidden size={14} /> 打开接入文档
                </button>
              </div>
            </section>

            <section className="mt-9 border-t border-[var(--td-line)] pt-7" aria-labelledby="usage-heading">
              <div className="flex items-end justify-between gap-4">
                <div>
                  <h2 id="usage-heading" className="text-[17px] font-semibold tracking-[-0.02em] text-[var(--td-ink)]">近 30 天用量</h2>
                  <p className="mt-1 text-[11px] text-[var(--td-muted)]">{history?.reduce((sum, item) => sum + item.total, 0).toLocaleString('zh-CN') ?? '—'} 次请求</p>
                </div>
                <span className="text-[11px] text-[var(--td-muted)]">今日 {fmtNumber(me.usage.today_count)}</span>
              </div>

              {!history || history.every((item) => item.total === 0) ? (
                <div className="mt-5 border-y border-[var(--td-line)] py-8 text-[12px] text-[var(--td-muted)]">完成首次 API 请求后，这里会显示调用节奏。</div>
              ) : (
                <div className="mt-4 h-28 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={history} margin={{ top: 6, right: 0, bottom: 0, left: 0 }} accessibilityLayer>
                      <XAxis dataKey="date" hide />
                      <YAxis hide allowDecimals={false} />
                      <Tooltip formatter={(value) => [`${Number(value).toLocaleString('zh-CN')} 次`, '请求']} labelFormatter={(value) => String(value)} contentStyle={{ borderRadius: 6, border: '1px solid #e1e0dc', boxShadow: '0 8px 24px rgb(22 22 22 / .08)', fontSize: 11 }} />
                      <Bar dataKey="total" fill="var(--td-accent)" radius={[2, 2, 0, 0]} maxBarSize={8} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              <div className="mt-3 border-t border-[var(--td-line)]">
                <div className="grid grid-cols-[1fr_auto] gap-4 py-3 text-[10px] font-semibold tracking-[0.04em] text-[var(--td-faint)] uppercase">
                  <span>最近活跃日</span><span>请求</span>
                </div>
                {(history ?? []).filter((item) => item.total > 0).slice(-3).reverse().map((item) => (
                  <div key={item.date} className="grid grid-cols-[1fr_auto] gap-4 border-t border-[var(--td-line)] py-3 text-[12px] text-[var(--td-ink-soft)]">
                    <time dateTime={item.date}>{item.date}</time>
                    <span className="tabular-nums">{item.total.toLocaleString('zh-CN')}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <aside className="mt-10 min-w-0 border-t border-[var(--td-line)] bg-[#f3f4f5] px-5 py-7 xl:mt-0 xl:border-t-0 xl:border-l xl:px-8 xl:py-8" aria-labelledby="access-summary-heading">
            <h2 id="access-summary-heading" className="text-[21px] font-semibold tracking-[-0.035em] text-[var(--td-ink)]">账户与权限</h2>

            <div className="mt-8 border-b border-[var(--td-line)] pb-7">
              <div className="text-[12px] font-semibold text-[var(--td-ink)]">账户与计划</div>
              <div className="mt-4 flex flex-wrap gap-x-2 text-[13px] text-[var(--td-ink-soft)]"><span>{tenantId}</span><span aria-hidden>·</span><span>{TIER_LABELS[me.tier] ?? me.tier}</span></div>
            </div>

            <div className="border-b border-[var(--td-line)] py-7">
              <div className="text-[12px] font-semibold text-[var(--td-ink)]">市场授权</div>
              <div className="mt-4 divide-y divide-[var(--td-line)]">
                {me.data_categories.map((category) => (
                  <div key={category} className="flex items-center justify-between gap-4 py-3 text-[12px]">
                    <span className="text-[var(--td-ink-soft)]">{DATA_CATEGORY_DETAILS[category]?.label ?? category}</span>
                    <span className="text-[var(--td-muted)]">已授权</span>
                  </div>
                ))}
                {!me.data_categories.length && <p className="py-3 text-[12px] text-[var(--td-danger)]">尚未开通市场</p>}
              </div>
            </div>

            <div className="py-7">
              <div className="text-[12px] font-semibold text-[var(--td-ink)]">额度与使用</div>
              <dl className="mt-4 space-y-4 text-[12px]">
                {[
                  ['今日请求', fmtNumber(me.usage.today_count)],
                  ['并发上限', me.max_concurrent === null ? '不限' : `${me.max_concurrent} 路`],
                  ['每日上限', fmtNumber(me.daily_limit)],
                  ['有效期', expiry?.main ?? '—'],
                ].map(([label, value]) => (
                  <div key={label} className="flex items-center justify-between gap-4">
                    <dt className="text-[var(--td-muted)]">{label}</dt>
                    <dd className="font-medium tabular-nums text-[var(--td-ink-soft)]">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </aside>
        </div>
      )}

      {me && section === 'access' && (
        <div className="space-y-6">
          <PageIntro eyebrow="ACCESS PROFILE" title="权限与额度" description="这里展示当前 API 密钥实际生效的市场范围、请求限制和账户有效期。" />
          <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
            <Card title="账户状态"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600"><Check size={18} /></div><div><div className="text-lg font-semibold text-[var(--td-ink)]">{me.enabled ? '可用' : '已暂停'}</div><div className="text-xs text-[var(--td-muted)]">{TIER_LABELS[me.tier] ?? me.tier}</div></div></div></Card>
            <Card title="有效期"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-50 text-amber-600"><Clock3 size={18} /></div><div><div className="text-lg font-semibold text-[var(--td-ink)]">{expiry?.main}</div><div className="text-xs text-[var(--td-muted)]">{expiry?.detail}</div></div></div></Card>
            <Card title="请求频率"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600"><CircleGauge size={18} /></div><div><div className="text-lg font-semibold text-[var(--td-ink)]">{fmtNumber(me.minute_request_limit ?? me.hourly_request_limit)}</div><div className="text-xs text-[var(--td-muted)]">{me.minute_request_limit ? '次 / 分钟' : '次 / 小时'}</div></div></div></Card>
            <Card title="并发上限"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-50 text-violet-600"><Sparkles size={18} /></div><div><div className="text-lg font-semibold text-[var(--td-ink)]">{me.max_concurrent === null ? '不限' : `${me.max_concurrent} 路`}</div><div className="text-xs text-[var(--td-muted)]">每日 {fmtNumber(me.daily_limit)} 次</div></div></div></Card>
          </div>
          <Card title="已开通市场">
            <div className="grid gap-3 md:grid-cols-3">
              {me.data_categories.map((category) => {
                const item = DATA_CATEGORY_DETAILS[category]
                return <div key={category} className={`rounded-xl border p-5 ${item.tone}`}><div className="text-base font-semibold">{item.label}</div><p className="mt-2 text-xs leading-5 opacity-80">{item.detail}</p></div>
              })}
              {!me.data_categories.length && <div className="rounded-xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700 md:col-span-3">当前密钥尚未开通数据分类，请联系管理员配置。</div>}
            </div>
            <p className="mt-4 text-xs leading-5 text-[var(--td-muted)]">最终可用数据集以当前密钥调用 <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono">GET /v1/catalog</code> 的实时返回为准。</p>
          </Card>
          <Card title="接口权限">
            <div className="grid gap-4 sm:grid-cols-3">
              {[
                ['发现目录', '读取数据集、字段、过滤条件与分页限制。'],
                ['读取与查询', '按已授权市场读取数据，不包含写入或交易能力。'],
                ['查看账户', '查看自身权限、有效期与用量，不读取其他客户信息。'],
              ].map(([title, detail]) => <div key={title} className="border-l-2 border-[var(--td-accent)] pl-4"><div className="text-sm font-semibold text-[var(--td-ink)]">{title}</div><p className="mt-1 text-xs leading-5 text-[var(--td-muted)]">{detail}</p></div>)}
            </div>
          </Card>
        </div>
      )}

      {me && section === 'docs' && (
        <div className="space-y-6">
          <PageIntro eyebrow="DOCUMENTATION" title="文档中心" description="从第一次请求到 Agent 工具配置，所有接入说明集中在这里。" />
          <div className="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
            <nav aria-label="文档目录" className="h-fit rounded-[var(--td-radius)] border border-[var(--td-line)] bg-white p-2 shadow-[var(--td-shadow-1)]">
              {([
                ['quickstart', Code2, 'API 快速开始', '认证与首次查询'],
                ['agents', Bot, 'Agent 接入', '提示词与工具定义'],
                ['reference', BookOpen, '使用约定', '分页、限流与安全'],
              ] as const).map(([key, Icon, label, detail]) => (
                <button key={key} type="button" onClick={() => onDocSectionChange(key)} aria-current={docSection === key ? 'page' : undefined} className={`flex w-full items-start gap-3 rounded-lg px-3 py-3 text-left focus-visible:outline-2 focus-visible:outline-[var(--td-accent)] ${docSection === key ? 'bg-[var(--td-accent-quiet)] text-[var(--td-accent-strong)]' : 'text-[var(--td-muted)] hover:bg-slate-50 hover:text-[var(--td-ink)]'}`}>
                  <Icon aria-hidden size={16} className="mt-0.5 shrink-0" />
                  <span><span className="block text-xs font-semibold">{label}</span><span className="mt-0.5 block text-[10px] opacity-70">{detail}</span></span>
                </button>
              ))}
            </nav>

            {docSection === 'quickstart' && <Card title="API 快速开始" action={<CopyButton text={curlExample} label="复制示例" />}>
              <div className="grid gap-5 xl:grid-cols-[1fr_1.35fr]">
                <div className="space-y-4">
                  {[
                    ['01', '认证请求', '所有请求都使用 Bearer API 密钥。'],
                    ['02', '发现数据集', '先读取 /v1/catalog，确认数据合同。'],
                    ['03', '查询与翻页', '通过 /v1/query 查询，使用 next_cursor 继续翻页。'],
                  ].map(([number, title, detail]) => <div key={number} className="flex gap-3"><span className="font-mono text-[10px] text-[var(--td-accent)]">{number}</span><div><div className="text-sm font-semibold text-[var(--td-ink)]">{title}</div><p className="mt-1 text-xs leading-5 text-[var(--td-muted)]">{detail}</p></div></div>)}
                </div>
                <pre className="max-h-[420px] overflow-auto rounded-xl bg-[#0b1020] p-5 font-mono text-[11px] leading-6 text-slate-300 whitespace-pre-wrap">{curlExample}</pre>
              </div>
            </Card>}

            {docSection === 'agents' && <div className="space-y-5">
              <Card title="给 Agent 的接入提示词" action={<CopyButton text={agentPrompt} label="复制提示词" />}><pre className="max-h-[420px] overflow-auto rounded-xl bg-[#0b1020] p-5 font-mono text-[11px] leading-6 text-slate-300 whitespace-pre-wrap">{agentPrompt}</pre></Card>
              <Card title="Function Calling 工具定义" action={<CopyButton text={toolDefsJson} label="复制定义" />}><pre className="max-h-[380px] overflow-auto rounded-xl bg-[#0b1020] p-5 font-mono text-[11px] leading-6 text-slate-300">{toolDefsJson}</pre></Card>
            </div>}

            {docSection === 'reference' && <Card title="使用约定">
              <div className="grid gap-6 md:grid-cols-2">
                {[
                  ['只读边界', 'TradingDatas 提供数据目录与查询，不写入数据，也不生成或执行交易指令。'],
                  ['限流与重试', '收到 429 后停止当前批次，并采用指数退避；并发不得超过账户上限。'],
                  ['游标分页', 'next_cursor 非空时继续翻页；不要自行构造或复用其他查询的游标。'],
                  ['密钥安全', '密钥只放在环境变量或安全凭证存储中，不写入仓库、日志和公开提示词。'],
                ].map(([title, detail]) => <div key={title}><div className="text-sm font-semibold text-[var(--td-ink)]">{title}</div><p className="mt-2 text-xs leading-5 text-[var(--td-muted)]">{detail}</p></div>)}
              </div>
            </Card>}
          </div>
        </div>
      )}
    </WorkspaceShell>
  )
}
