import { useEffect, useState } from 'react'
import type { ApiClient } from '../../lib/api'
import type { HealthAlert } from '../../lib/types'
import { Card, ErrorBanner, LoadingPanel } from '../../components/ui'

interface AlertsResponse {
  alerts?: HealthAlert[]
}

const SEVERITY_ORDER = ['critical', 'warning', 'info'] as const

const SEVERITY_META: Record<string, { label: string; card: string; badge: string }> = {
  critical: {
    label: '严重',
    card: 'border-l-rose-500 bg-rose-50/50',
    badge: 'bg-rose-100 text-rose-700',
  },
  warning: {
    label: '警告',
    card: 'border-l-amber-500 bg-amber-50/50',
    badge: 'bg-amber-100 text-amber-700',
  },
  info: {
    label: '提示',
    card: 'border-l-blue-400 bg-blue-50/40',
    badge: 'bg-blue-100 text-blue-700',
  },
}

export default function HealthView({ client }: { client: ApiClient }) {
  const [alerts, setAlerts] = useState<HealthAlert[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const data = await client.get<AlertsResponse>('/admin/api/health/alerts')
        if (!alive) return
        const items = [...(data.alerts ?? [])]
        items.sort(
          (a, b) =>
            SEVERITY_ORDER.indexOf(a.severity as (typeof SEVERITY_ORDER)[number]) -
            SEVERITY_ORDER.indexOf(b.severity as (typeof SEVERITY_ORDER)[number]),
        )
        setAlerts(items)
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : '加载失败')
      }
    })()
    return () => {
      alive = false
    }
  }, [client])

  if (alerts === null && !error) return <LoadingPanel />
  if (error) return <ErrorBanner message={error} />

  if (!alerts || alerts.length === 0) {
    return (
      <Card>
        <div className="flex flex-col items-center py-10 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 text-emerald-600">
              <path d="m4.5 12.75 6 6 9-13.5" />
            </svg>
          </div>
          <h3 className="mt-4 text-base font-semibold text-slate-800 dark:text-slate-100">全部正常</h3>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">当前没有任何健康告警</p>
        </div>
      </Card>
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500 dark:text-slate-400">
        共 {alerts.length} 条告警 · 按严重程度排序
      </p>
      {alerts.map((a, idx) => {
        const meta = SEVERITY_META[a.severity] ?? SEVERITY_META.info
        return (
          <div
            key={idx}
            className={`rounded-xl border border-slate-200 dark:border-slate-700 border-l-4 p-4 shadow-[0_1px_2px_rgb(15_23_42/0.04)] ${meta.card}`}
          >
            <div className="flex items-start justify-between gap-3">
              <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{a.title}</h3>
              <span className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-medium ${meta.badge}`}>
                {meta.label}
              </span>
            </div>
            {a.detail && (
              <p className="mt-1.5 text-xs leading-relaxed break-words text-slate-500 dark:text-slate-400">{a.detail}</p>
            )}
          </div>
        )
      })}
    </div>
  )
}
