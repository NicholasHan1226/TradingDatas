import { useEffect, useMemo, useState } from 'react'
import { Activity, ChartNoAxesCombined, CircleCheckBig, Eye, MousePointerClick, RotateCcw, ShieldCheck } from 'lucide-react'
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
import type { UsageOverview } from '../../lib/types'
import { resetConsoleAnalytics, useConsoleAnalytics } from '../../lib/consoleAnalytics'
import {
  Card,
  Button,
  EmptyState,
  ErrorBanner,
  LoadingPanel,
  PageIntro,
  ProgressBar,
  StatCard,
  Modal,
  fmtNumber,
} from '../../components/ui'

interface HistoryResponse {
  history: { date: string; total: number }[]
}

export default function UsageView({ client }: { client: ApiClient }) {
  const [overview, setOverview] = useState<UsageOverview | null>(null)
  const [history, setHistory] = useState<{ date: string; total: number }[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [resetOpen, setResetOpen] = useState(false)
  const consoleAnalytics = useConsoleAnalytics()

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const [usage, hist] = await Promise.all([
          client.get<UsageOverview>('/admin/api/usage'),
          client.get<HistoryResponse>('/admin/api/usage/history', { days: '30' }),
        ])
        if (!alive) return
        setOverview(usage)
        setHistory(hist.history ?? [])
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : '加载失败')
      }
    })()
    return () => {
      alive = false
    }
  }, [client])

  const dailyRows = useMemo(
    () =>
      overview
        ? Object.entries(overview.daily).sort((a, b) => b[1].count - a[1].count)
        : [],
    [overview],
  )
  const hourlyRows = useMemo(
    () =>
      overview
        ? Object.entries(overview.hourly).sort((a, b) => b[1].count_in_window - a[1].count_in_window)
        : [],
    [overview],
  )
  const todayTotal = dailyRows.reduce((sum, [, v]) => sum + v.count, 0)
  const hourlyTotal = hourlyRows.reduce((sum, [, v]) => sum + v.count_in_window, 0)

  if (!overview && !error) return <LoadingPanel />
  if (error) return <ErrorBanner message={error} />

  return (
    <div className="space-y-6">
      <PageIntro
        eyebrow="请求分析"
        title="调用与容量概览"
        description="从实时窗口到月度趋势，持续观察客户请求与服务容量。"
        action={<span className="border-l border-[var(--td-line)] pl-3 text-[11px] font-medium text-[var(--td-muted)]">最近 30 天</span>}
      />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="今日请求总数" value={todayTotal.toLocaleString('zh-CN')} sub={`${dailyRows.length} 个客户有调用`} />
        <StatCard label="当前小时窗口" value={hourlyTotal.toLocaleString('zh-CN')} sub="滑动 60 分钟" />
        <StatCard label="去重缓存条目" value={(overview?.cache?.dedup_entries ?? 0).toLocaleString('zh-CN')} sub={`${((overview?.cache?.dedup_bytes ?? 0) / 1024).toFixed(1)} KB 内存`} />
        <StatCard label="进行中请求" value={String(overview?.cache?.active_requests ?? 0)} tone={Number(overview?.cache?.active_requests ?? 0) > 0 ? 'good' : 'default'} />
      </div>

      <Card title="近 30 天请求趋势">
        {!history || history.length === 0 ? (
          <EmptyState icon={ChartNoAxesCombined} title="还没有用量数据" hint="客户完成首次 API 调用后，这里会出现趋势图。" />
        ) : (
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={history} margin={{ top: 8, right: 8, bottom: 0, left: -14 }}>
                <defs>
                  <linearGradient id="usageFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#2563eb" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="#2563eb" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                <XAxis
                  dataKey="date"
                  tickFormatter={(v: string) => v.slice(5)}
                  tick={{ fontSize: 11, fill: '#94a3b8' }}
                  axisLine={{ stroke: '#e2e8f0' }}
                  tickLine={false}
                />
                <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip
                  formatter={(value) => [`${Number(value).toLocaleString('zh-CN')} 次`, '请求量']}
                  labelStyle={{ fontSize: 12, color: '#475569' }}
                  contentStyle={{
                    borderRadius: 10,
                    border: '1px solid #e2e8f0',
                    boxShadow: '0 4px 16px rgb(15 23 42 / 0.08)',
                    fontSize: 12,
                  }}
                />
                <Area type="monotone" dataKey="total" stroke="#2563eb" strokeWidth={2} fill="url(#usageFill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      <Card
        title={<span className="inline-flex items-center gap-2"><ShieldCheck aria-hidden size={15} className="text-[var(--td-accent)]" />控制台体验</span>}
        action={<Button variant="ghost" size="sm" onClick={() => setResetOpen(true)}><RotateCcw aria-hidden size={13} />重置本地统计</Button>}
      >
        <div className="grid border-y border-[var(--td-line)] sm:grid-cols-2 xl:grid-cols-4">
          {([
            [Eye, '页面浏览', consoleAnalytics.workspaces.admin.views + consoleAnalytics.workspaces.customer.views, 'blue'],
            [CircleCheckBig, '完成任务', consoleAnalytics.workspaces.admin.completions + consoleAnalytics.workspaces.customer.completions, 'cyan'],
            [MousePointerClick, '工作区操作', consoleAnalytics.workspaces.admin.actions + consoleAnalytics.workspaces.customer.actions, 'violet'],
            [Activity, '界面错误', consoleAnalytics.workspaces.admin.errors + consoleAnalytics.workspaces.customer.errors, 'orange'],
          ] as const).map(([Icon, label, value, tone]) => (
            <div key={label} className="border-b border-[var(--td-line)] px-4 py-5 sm:border-r xl:border-b-0 xl:last:border-r-0">
              <div className="flex items-center gap-2 text-[11px] font-medium text-[var(--td-muted)]">
                <span className={`flex h-6 w-6 items-center justify-center rounded-[5px] analytics-icon-${tone}`}><Icon aria-hidden size={13} /></span>{label}
              </div>
              <div className="mt-4 text-[25px] font-semibold tracking-[-0.05em] tabular-nums text-[var(--td-ink)]">{value.toLocaleString('zh-CN')}</div>
            </div>
          ))}
        </div>
        <div className="mt-5 grid gap-4 border-t border-slate-100 pt-5 md:grid-cols-2">
          {(['admin', 'customer'] as const).map((workspace) => {
            const metrics = consoleAnalytics.workspaces[workspace]
            const total = metrics.views + metrics.actions + metrics.completions + metrics.errors
            return (
              <div key={workspace} className="border-l-2 border-[var(--td-line-strong)] px-4 py-1">
                <div className="flex items-center justify-between gap-4">
                  <div><div className="text-sm font-semibold text-[var(--td-ink)]">{workspace === 'admin' ? '管理员工作台' : '客户工作台'}</div><div className="mt-1 text-[11px] text-[var(--td-muted)]">浏览 {metrics.views} · 完成 {metrics.completions} · 错误 {metrics.errors}</div></div>
                  <span className="font-mono text-xs text-[var(--td-faint)]">{total} 次</span>
                </div>
              </div>
            )
          })}
        </div>
        <p className="mt-4 text-[11px] leading-5 text-[var(--td-faint)]">仅在当前浏览器进行匿名聚合，不记录 Token、客户 ID、数据集 ID、请求内容或外部设备信息；不会发送到服务器。</p>
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="今日 · 按客户" action={<span className="text-[11px] text-slate-400">已用 / 日限额</span>}>
          {dailyRows.length === 0 ? (
            <EmptyState icon={ChartNoAxesCombined} title="今天还没有调用" hint="当天产生请求后会按客户显示用量。" />
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {dailyRows.map(([tenant, v]) => (
                  <tr key={tenant} className="border-b border-slate-50 last:border-0">
                    <td className="py-2.5 pr-3 font-medium text-slate-700">{tenant}</td>
                    <td className="py-2.5 pr-3 font-mono text-xs whitespace-nowrap text-slate-600">
                      {v.count.toLocaleString('zh-CN')} / {fmtNumber(v.daily_limit)}
                    </td>
                    <td className="w-32 py-2.5 text-right">
                      <ProgressBar value={v.count} limit={v.daily_limit} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="当前小时窗口 · 按客户" action={<span className="text-[11px] text-slate-400">窗口内 / 套餐上限</span>}>
          {hourlyRows.length === 0 ? (
            <EmptyState icon={ChartNoAxesCombined} title="当前窗口没有调用" hint="新请求出现后会显示窗口用量与套餐上限。" />
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {hourlyRows.map(([tenant, v]) => (
                  <tr key={tenant} className="border-b border-slate-50 last:border-0">
                    <td className="py-2.5 pr-3 font-medium text-slate-700">{tenant}</td>
                    <td className="py-2.5 font-mono text-xs whitespace-nowrap text-slate-600">
                      {v.count_in_window} / {fmtNumber(v.tier_limit)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <Modal open={resetOpen} onClose={() => setResetOpen(false)} title="重置本地体验统计" width="max-w-md">
        <p className="text-sm leading-6 text-[var(--td-muted)]">只会清除当前浏览器中的匿名聚合计数，不影响服务器用量、客户账户、Token 或数据服务。</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setResetOpen(false)}>取消</Button>
          <Button variant="danger" onClick={() => { resetConsoleAnalytics(); setResetOpen(false) }}>确认重置</Button>
        </div>
      </Modal>
    </div>
  )
}
