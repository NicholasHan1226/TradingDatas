import { useEffect, useMemo, useState } from 'react'
import { Activity, AlertOctagon, CircleCheckBig, Clock3, DatabaseZap, ShieldAlert } from 'lucide-react'
import type { ApiClient } from '../../lib/api'
import type { HealthAlert } from '../../lib/types'
import { CADENCE_LABELS, Card, ControlBar, EmptyState, ErrorBanner, LoadingPanel, PageIntro, StatCard, runtimeLabel, runtimeReason } from '../../components/ui'

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

function displayTime(value?: string | null) {
  if (!value) return '暂无'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false })
}

export default function HealthView({ client }: { client: ApiClient }) {
  const [alerts, setAlerts] = useState<HealthAlert[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [severityFilter, setSeverityFilter] = useState<'all' | (typeof SEVERITY_ORDER)[number]>('all')

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const data = await client.get<AlertsResponse>('/admin/api/health/alerts')
        if (!alive) return
        const items = [...(data.alerts ?? [])]
        const rank = (severity: string) => {
          const index = SEVERITY_ORDER.indexOf(severity as (typeof SEVERITY_ORDER)[number])
          return index === -1 ? SEVERITY_ORDER.length : index
        }
        items.sort((a, b) => rank(a.severity) - rank(b.severity))
        setAlerts(items)
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : '加载失败')
      }
    })()
    return () => {
      alive = false
    }
  }, [client])

  const severityCounts = useMemo(
    () => Object.fromEntries(SEVERITY_ORDER.map((severity) => [severity, alerts?.filter((item) => item.severity === severity).length ?? 0])) as Record<(typeof SEVERITY_ORDER)[number], number>,
    [alerts],
  )
  const visibleAlerts = severityFilter === 'all'
    ? alerts ?? []
    : (alerts ?? []).filter((item) => item.severity === severityFilter)

  if (alerts === null && !error) return <LoadingPanel />
  if (error) return <ErrorBanner message={error} />

  if (!alerts || alerts.length === 0) {
    return (
      <div className="space-y-5">
        <PageIntro
          eyebrow="运行诊断"
          title="系统健康与告警"
          description="按照影响等级汇总当前运行时风险与需要关注的服务信号。"
        />
        <Card>
          <div className="flex flex-col items-center py-10 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-[var(--td-radius)] border border-[#ccd6ff] bg-[var(--td-accent-quiet)]">
              <CircleCheckBig aria-hidden className="h-6 w-6 text-[var(--td-accent)]" />
            </div>
            <h3 className="mt-4 text-base font-semibold text-slate-800">全部正常</h3>
            <p className="mt-1 text-sm text-slate-500">当前没有任何健康告警</p>
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageIntro
        eyebrow="运行诊断"
        title="运行健康"
        description="将数据采集、时效与回执完整性问题收敛为可执行的运营任务。"
        action={<span className="text-xs text-slate-400">{alerts.length} 条 · 已按严重程度排序</span>}
      />
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="严重" value={severityCounts.critical} tone={severityCounts.critical > 0 ? 'bad' : 'default'} />
        <StatCard label="警告" value={severityCounts.warning} tone={severityCounts.warning > 0 ? 'warn' : 'default'} />
        <StatCard label="提示" value={severityCounts.info} />
      </div>
      <ControlBar className="justify-between">
        <div className="flex flex-wrap gap-1" aria-label="按严重程度筛选告警">
          {([
            ['all', '全部'],
            ['critical', '严重'],
            ['warning', '警告'],
            ['info', '提示'],
          ] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={severityFilter === value}
              onClick={() => setSeverityFilter(value)}
              className={`min-h-8 rounded-[var(--td-radius-sm)] px-2.5 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 ${
                severityFilter === value
                  ? 'bg-slate-900 text-white shadow-[0_1px_2px_rgb(15_23_42/0.15)]'
                  : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-400">显示 {visibleAlerts.length} / {alerts.length} 条</span>
      </ControlBar>
      {visibleAlerts.length === 0 ? (
        <Card><EmptyState icon={CircleCheckBig} title="当前筛选下没有告警" hint="这一严重程度暂时没有需要处理的项目。" /></Card>
      ) : <div className="grid gap-3 xl:grid-cols-2">
        {visibleAlerts.map((a, idx) => {
          const meta = SEVERITY_META[a.severity] ?? SEVERITY_META.info
          const AlertIcon = a.kind === 'receipt_integrity' ? ShieldAlert : a.severity === 'critical' ? AlertOctagon : Activity
          return (
            <article
              key={a.alert_id ?? `${a.title}-${idx}`}
              className={`group relative overflow-hidden rounded-[var(--td-radius-lg)] border border-slate-200 border-l-[3px] p-5 shadow-[0_1px_3px_rgb(15_23_42/0.05)] ${meta.card}`}
            >
              <div className="flex items-start gap-3">
                <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/80 bg-white/75 shadow-[0_1px_2px_rgb(15_23_42/0.06)]">
                  <AlertIcon aria-hidden className="h-4 w-4 text-slate-700" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <h3 className="break-all font-mono text-[12px] font-semibold leading-5 text-slate-800">{a.dataset_id ?? a.title}</h3>
                    <span className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-medium ${meta.badge}`}>
                      {meta.label}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[13px] font-medium text-slate-700">{a.dataset_id ? a.title.split(':').slice(1).join(':').trim() : a.title}</p>
                </div>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-y border-slate-200/70 py-3 text-xs sm:grid-cols-4">
                <div><span className="block text-[10px] text-slate-400">状态</span><span className="mt-1 block font-medium text-slate-700">{runtimeLabel(a.runtime_state)}</span></div>
                <div><span className="block text-[10px] text-slate-400">来源</span><span className="mt-1 block font-medium text-slate-700">{a.provider ?? '平台回执'}</span></div>
                <div><span className="block text-[10px] text-slate-400">采集频率</span><span className="mt-1 block font-medium text-slate-700">{CADENCE_LABELS[a.cadence ?? ''] ?? a.cadence ?? '—'}</span></div>
                <div><span className="block text-[10px] text-slate-400">最近观测</span><span className="mt-1 block truncate font-mono text-[10px] text-slate-600" title={a.observed_at ?? undefined}>{displayTime(a.observed_at)}</span></div>
              </div>
              {runtimeReason(a.reason_codes) && (
                <div className="mt-3 flex items-start gap-2 rounded-[8px] border border-white/90 bg-white/65 px-3 py-2.5">
                  <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--td-violet)]" />
                  <div className="min-w-0"><span className="text-[10px] font-semibold text-[var(--td-ink-soft)]">状态原因：{runtimeReason(a.reason_codes)?.label}</span><p className="mt-0.5 text-[10px] leading-4 text-[var(--td-muted)]">{runtimeReason(a.reason_codes)?.detail}</p></div>
                </div>
              )}
              <div className="mt-4 flex items-start gap-2 rounded-lg border border-white/90 bg-white/65 px-3 py-2.5">
                <DatabaseZap aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--td-accent)]" />
                <div className="min-w-0">
                  <span className="block text-[10px] font-semibold tracking-[0.04em] text-slate-400">建议处理</span>
                  <p className="mt-0.5 text-xs leading-5 text-slate-600">{a.suggested_action ?? '查看运行详情并核对最近回执。'}</p>
                </div>
              </div>
              {a.data_through && <div className="mt-3 flex items-center gap-1.5 text-[10px] text-slate-400"><Clock3 aria-hidden size={12} /> 数据截止 <span className="font-mono text-slate-500">{a.data_through}</span></div>}
            </article>
          )
        })}
      </div>}
    </div>
  )
}
