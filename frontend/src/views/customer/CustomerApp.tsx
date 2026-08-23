import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
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
import type { PortalInfo, PortalMeResponse, PortalUsageResponse } from '../../lib/types'
import {
  Badge,
  Button,
  Card,
  CopyButton,
  ErrorBanner,
  LoadingPanel,
  ProgressBar,
  TIER_LABELS,
} from '../../components/ui'

function daysUntil(iso: string | null): number | null {
  if (!iso) return null
  const ms = Date.parse(iso.endsWith('Z') ? iso : iso + 'Z') - Date.now()
  return Math.ceil(ms / 86_400_000)
}

export default function CustomerApp({
  client,
  tenantId,
  onLogout,
}: {
  client: ApiClient
  tenantId: string
  onLogout: () => void
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
    return () => {
      alive = false
    }
  }, [client])

  const curlExample = `curl -X POST ${client.baseUrl}/v1/query \\
  -H "Authorization: Bearer <你的API密钥>" \\
  -H "Content-Type: application/json" \\
  -d '{"dataset_id": "cn.equity.daily", "limit": 20}'`

  if (!me && !error) return <LoadingPanel label="加载你的套餐信息…" />

  return (
    <div className="min-h-full bg-slate-100">
      {/* Top bar */}
      <header className="sticky top-0 z-10 border-b border-slate-200/80 bg-white/85 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 shadow-md shadow-blue-600/25">
              <svg viewBox="0 0 24 24" fill="none" className="h-4.5 w-4.5 text-white">
                <path d="M4 17l5-7 4.5 3.5L20 5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <span className="text-sm font-semibold tracking-tight text-slate-900">TradingDatas</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="font-mono text-xs text-slate-500">{tenantId}</span>
            <Button variant="secondary" size="sm" onClick={onLogout}>退出</Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-6 py-8 pb-16">
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
          {error && <ErrorBanner message={error} />}
        </motion.div>

        {me && (
          <>
            {/* Plan summary */}
            <section className="rounded-2xl bg-gradient-to-br from-slate-900 via-slate-900 to-blue-950 p-6 text-white shadow-lg">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-xs tracking-wide text-slate-400">我的套餐</p>
                  <h1 className="mt-1 text-2xl font-semibold tracking-tight">
                    {TIER_LABELS[me.tier] ?? me.tier}
                  </h1>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {(me.scopes ?? []).map((s) => (
                      <code key={s} className="rounded-md bg-white/10 px-1.5 py-0.5 font-mono text-[11px] text-blue-200">
                        {s}
                      </code>
                    ))}
                  </div>
                </div>
                <div className="text-right">
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
                  ['并发上限', me.max_concurrent === null ? '不限' : `${me.max_concurrent} 路`],
                  ['每小时请求', me.hourly_request_limit === null ? '不限' : `${me.hourly_request_limit} 次`],
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

            {/* Integration guide */}
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
                          ['GET', '/v1/catalog', '浏览可用的数据集目录'],
                          ['POST', '/v1/query', '查询具体数据集的数据行'],
                          ['GET', '/portal/api/me', '查看本页的套餐与配额信息'],
                        ].map(([method, path, desc]) => (
                          <tr key={path} className="border-b border-slate-50 last:border-0">
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
                  超出并发或频率限制时会收到 <code className="font-mono">429</code> 响应，请按提示退避重试。
                </div>
              </div>
            </Card>
          </>
        )}
      </main>
    </div>
  )
}
