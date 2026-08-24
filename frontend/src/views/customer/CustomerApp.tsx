import { useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { BookOpen, Bot, ChartNoAxesCombined, Check, CircleGauge, Clock3, Code2, Database, KeyRound, ShieldCheck, Sparkles } from 'lucide-react'
import type { ApiClient } from '../../lib/api'
import type { DataCategory, PortalInfo, PortalMeResponse, PortalUsageResponse } from '../../lib/types'
import WorkspaceShell, { type WorkspaceNavItem } from '../../components/WorkspaceShell'
import { Badge, Card, CopyButton, EmptyState, ErrorBanner, LoadingPanel, PageIntro, ProgressBar, TIER_LABELS, fmtNumber } from '../../components/ui'
import type { CustomerSection, DocSection } from '../../lib/workspaceRoute'

type SectionKey = CustomerSection
type DocKey = DocSection

const NAV: WorkspaceNavItem<SectionKey>[] = [
  { key: 'overview', label: '首页', description: '账户与使用概览', icon: ChartNoAxesCombined, accent: 'blue' },
  { key: 'access', label: '权限与额度', description: '市场、限额、有效期', icon: ShieldCheck, accent: 'cyan' },
  { key: 'docs', label: '文档中心', description: 'API 与 Agent 接入', icon: BookOpen, accent: 'violet' },
]

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
        <div className="space-y-6">
          <PageIntro eyebrow="CUSTOMER HOME" title="你的数据服务，一眼掌握" description="确认账户状态、市场权限与调用额度，然后把 API 接入你的 Agent。" />

          <section className="relative overflow-hidden rounded-[18px] bg-[var(--td-shell)] px-6 py-6 text-white shadow-[0_18px_48px_rgb(13_19_32/0.16)] sm:px-8 sm:py-7">
            <div className="absolute inset-x-0 top-0 h-1 bg-[linear-gradient(90deg,var(--td-accent),var(--td-cyan),var(--td-violet),var(--td-orange))]" />
            <div className="grid gap-7 lg:grid-cols-[1.15fr_1fr] lg:items-end">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={me.enabled ? 'green' : 'rose'}>{me.enabled ? '服务可用' : '服务已暂停'}</Badge>
                  <span className="font-mono text-[10px] text-slate-500">{tenantId}</span>
                </div>
                <p className="mt-5 text-[10px] font-semibold tracking-[0.14em] text-slate-500 uppercase">Current plan</p>
                <h1 className="mt-1 text-3xl font-semibold tracking-[-0.045em]">{TIER_LABELS[me.tier] ?? me.tier}</h1>
                <div className="mt-5 flex flex-wrap gap-2">
                  {me.data_categories.map((category) => (
                    <span key={category} className="rounded-md border border-white/10 bg-white/[0.06] px-2.5 py-1.5 text-xs text-slate-200">
                      {DATA_CATEGORY_DETAILS[category]?.label ?? category}
                    </span>
                  ))}
                  {!me.data_categories.length && <span className="text-xs text-rose-300">尚未开通数据分类</span>}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-x-6 gap-y-5 border-t border-white/10 pt-5 sm:grid-cols-4 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-7">
                {[
                  ['今日请求', fmtNumber(me.usage.today_count)],
                  [me.minute_request_limit ? '每分钟' : '每小时', fmtNumber(me.minute_request_limit ?? me.hourly_request_limit)],
                  ['并发上限', me.max_concurrent === null ? '不限' : `${me.max_concurrent} 路`],
                  ['剩余有效期', expiry?.main ?? '—'],
                ].map(([label, value]) => (
                  <div key={label}>
                    <div className="text-[10px] text-slate-500">{label}</div>
                    <div className="mt-1.5 text-[17px] font-semibold tracking-[-0.025em] tabular-nums text-white">{value}</div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(320px,0.75fr)]">
            <Card title="近 30 天调用量" action={me.daily_limit !== null ? <ProgressBar value={me.usage.today_count} limit={me.daily_limit} /> : <span className="text-xs text-slate-400">每日不限额</span>}>
              {!history || history.every((item) => item.total === 0) ? (
                <EmptyState icon={ChartNoAxesCombined} title="还没有调用记录" hint="完成首次 API 请求后，这里会出现调用趋势。" />
              ) : (
                <div className="h-64 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={history} margin={{ top: 12, right: 8, bottom: 0, left: -18 }} accessibilityLayer>
                      <defs><linearGradient id="customerUsageFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--td-accent)" stopOpacity={0.25} /><stop offset="100%" stopColor="var(--td-accent)" stopOpacity={0.01} /></linearGradient></defs>
                      <CartesianGrid stroke="#e8ebf0" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={(value: string) => value.slice(5)} tick={{ fontSize: 10, fill: '#97a0af' }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 10, fill: '#97a0af' }} axisLine={false} tickLine={false} allowDecimals={false} />
                      <Tooltip formatter={(value) => [`${Number(value).toLocaleString('zh-CN')} 次`, '调用量']} contentStyle={{ borderRadius: 10, border: '1px solid #e2e6ec', boxShadow: '0 12px 32px rgb(13 19 32 / .1)', fontSize: 12 }} />
                      <Area type="monotone" dataKey="total" stroke="var(--td-accent)" strokeWidth={2} fill="url(#customerUsageFill)" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>

            <Card title="开始使用" className="bg-[#fbfcff]">
              <ol className="space-y-5">
                {[
                  [KeyRound, '准备 API 密钥', '当前登录密钥即可用于已授权的只读请求。'],
                  [Database, '读取数据目录', '先读取 catalog，确认可用数据集与字段。'],
                  [Bot, '连接你的 Agent', '复制接入说明与工具定义到 Claude、Codex 等 Agent。'],
                ].map(([Icon, title, detail], index) => {
                  const StepIcon = Icon as typeof KeyRound
                  return <li key={String(title)} className="flex gap-3"><div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--td-accent-quiet)] text-[var(--td-accent)]"><StepIcon size={15} /></div><div><div className="text-sm font-semibold text-[var(--td-ink)]"><span className="mr-2 text-[10px] text-[var(--td-faint)]">0{index + 1}</span>{String(title)}</div><p className="mt-1 text-xs leading-5 text-[var(--td-muted)]">{String(detail)}</p></div></li>
                })}
              </ol>
              <button type="button" onClick={() => onSectionChange('docs')} className="mt-6 inline-flex items-center gap-2 text-xs font-semibold text-[var(--td-accent)] hover:text-[var(--td-accent-strong)] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--td-accent)]">打开接入文档 <Code2 size={14} /></button>
            </Card>
          </div>
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
