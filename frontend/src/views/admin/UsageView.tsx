import { useEffect, useMemo, useState } from 'react'
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
import {
  Card,
  EmptyState,
  ErrorBanner,
  LoadingPanel,
  ProgressBar,
  StatCard,
  fmtNumber,
} from '../../components/ui'

interface HistoryResponse {
  history: { date: string; total: number }[]
}

export default function UsageView({ client }: { client: ApiClient }) {
  const [overview, setOverview] = useState<UsageOverview | null>(null)
  const [history, setHistory] = useState<{ date: string; total: number }[] | null>(null)
  const [error, setError] = useState<string | null>(null)

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
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="今日请求总数" value={todayTotal.toLocaleString('zh-CN')} sub={`${dailyRows.length} 个客户有调用`} />
        <StatCard label="当前小时窗口" value={hourlyTotal.toLocaleString('zh-CN')} sub="滑动 60 分钟" />
        <StatCard label="去重缓存条目" value={(overview?.cache?.dedup_entries ?? 0).toLocaleString('zh-CN')} sub={`${((overview?.cache?.dedup_bytes ?? 0) / 1024).toFixed(1)} KB 内存`} />
        <StatCard label="进行中请求" value={String(overview?.cache?.active_requests ?? 0)} tone={Number(overview?.cache?.active_requests ?? 0) > 0 ? 'good' : 'default'} />
      </div>

      <Card title="近 30 天请求趋势">
        {!history || history.length === 0 ? (
          <EmptyState title="还没有用量数据" hint="客户开始调用 API 后这里会出现趋势图" />
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
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
                <XAxis
                  dataKey="date"
                  tickFormatter={(v: string) => v.slice(5)}
                  tick={{ fontSize: 11, fill: 'var(--chart-tick)' }}
                  axisLine={{ stroke: '#e2e8f0' }}
                  tickLine={false}
                />
                <YAxis tick={{ fontSize: 11, fill: 'var(--chart-tick)' }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip
                  formatter={(value) => [`${Number(value).toLocaleString('zh-CN')} 次`, '请求量']}
                  labelStyle={{ fontSize: 12, color: 'var(--tooltip-text)' }}
                  contentStyle={{
                    borderRadius: 10,
                    border: '1px solid var(--tooltip-border)',
                          backgroundColor: 'var(--tooltip-bg)',
                          color: 'var(--tooltip-text)',
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

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="今日 · 按客户" action={<span className="text-[11px] text-slate-400 dark:text-slate-500">已用 / 日限额</span>}>
          {dailyRows.length === 0 ? (
            <EmptyState title="今天还没有调用" />
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {dailyRows.map(([tenant, v]) => (
                  <tr key={tenant} className="border-b border-slate-50 dark:border-slate-800/70 last:border-0">
                    <td className="py-2.5 pr-3 font-medium text-slate-700 dark:text-slate-200">{tenant}</td>
                    <td className="py-2.5 pr-3 font-mono text-xs whitespace-nowrap text-slate-600 dark:text-slate-300">
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

        <Card title="当前小时窗口 · 按客户" action={<span className="text-[11px] text-slate-400 dark:text-slate-500">窗口内 / 套餐上限</span>}>
          {hourlyRows.length === 0 ? (
            <EmptyState title="当前小时没有调用" />
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {hourlyRows.map(([tenant, v]) => (
                  <tr key={tenant} className="border-b border-slate-50 dark:border-slate-800/70 last:border-0">
                    <td className="py-2.5 pr-3 font-medium text-slate-700 dark:text-slate-200">{tenant}</td>
                    <td className="py-2.5 font-mono text-xs whitespace-nowrap text-slate-600 dark:text-slate-300">
                      {v.count_in_window} / {fmtNumber(v.tier_limit)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  )
}
