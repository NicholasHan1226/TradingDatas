import { useEffect, useMemo, useState } from 'react'
import type { ApiClient } from '../../lib/api'
import type { CollectionStatus, DatasetRow } from '../../lib/types'
import {
  INPUT_CLASS,
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  LoadingPanel,
  SelectInput,
  StatCard,
} from '../../components/ui'

const STATE_TONES: Record<string, 'green' | 'rose' | 'amber' | 'slate'> = {
  success: 'green',
  failed: 'rose',
  stale: 'amber',
  degraded: 'amber',
}

function StateBadge({ row }: { row: DatasetRow }) {
  const state = row.runtime_state || '-'
  return (
    <Badge tone={STATE_TONES[state] ?? 'slate'}>
      {state}
      {row.degraded ? ' · 降级' : ''}
    </Badge>
  )
}

export default function CollectionView({ client }: { client: ApiClient }) {
  const [status, setStatus] = useState<CollectionStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [market, setMarket] = useState('')
  const [activation, setActivation] = useState('')
  const [stateFilter, setStateFilter] = useState('')
  const [search, setSearch] = useState('')

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const data = await client.get<CollectionStatus>('/admin/api/collection/status')
        if (alive) setStatus(data)
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : '加载失败')
      }
    })()
    return () => {
      alive = false
    }
  }, [client])

  const datasets = status?.datasets ?? []

  const markets = useMemo(
    () => [...new Set(datasets.map((d) => d.market))].filter(Boolean).sort(),
    [datasets],
  )

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return datasets.filter(
      (d) =>
        (!market || d.market === market) &&
        (!activation || d.activation === activation) &&
        (!stateFilter || (d.runtime_state || '') === stateFilter) &&
        (!q || d.dataset_id.toLowerCase().includes(q)),
    )
  }, [datasets, market, activation, stateFilter, search])

  const activeCount = datasets.filter((d) => d.activation === 'active').length
  const degradedCount = datasets.filter((d) => d.degraded).length
  const failedCount = datasets.filter((d) => d.runtime_state === 'failed').length

  if (!status && !error) return <LoadingPanel label="加载采集状态…" />
  if (error) return <ErrorBanner message={error} />

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="数据集总数" value={status?.total ?? datasets.length} />
        <StatCard label="采集激活" value={activeCount} tone="good" />
        <StatCard
          label="运行失败"
          value={failedCount}
          tone={failedCount > 0 ? 'bad' : 'default'}
        />
        <StatCard
          label="质量降级"
          value={degradedCount}
          tone={degradedCount > 0 ? 'warn' : 'default'}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索数据集 ID…"
          className={`w-64 ${INPUT_CLASS}`}
        />
        <SelectInput value={market} onChange={(e) => setMarket(e.target.value)} className="!w-auto">
          <option value="">全部市场</option>
          {markets.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </SelectInput>
        <SelectInput value={activation} onChange={(e) => setActivation(e.target.value)} className="!w-auto">
          <option value="">全部激活状态</option>
          <option value="active">active</option>
          <option value="paused">paused</option>
        </SelectInput>
        <SelectInput value={stateFilter} onChange={(e) => setStateFilter(e.target.value)} className="!w-auto">
          <option value="">全部运行状态</option>
          <option value="success">success</option>
          <option value="failed">failed</option>
          <option value="stale">stale</option>
        </SelectInput>
        <span className="ml-auto text-xs text-slate-400 dark:text-slate-500">
          显示 {filtered.length.toLocaleString('zh-CN')} / {datasets.length.toLocaleString('zh-CN')} 个数据集
        </span>
      </div>

      <Card className="overflow-hidden !p-0">
        {filtered.length === 0 ? (
          <EmptyState title="没有匹配的数据集" hint="调整筛选条件试试" />
        ) : (
          <div className="max-h-[62vh] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-[1] bg-slate-50 dark:bg-slate-900/95 backdrop-blur">
                <tr className="border-b border-slate-100 dark:border-slate-800 text-left text-[11px] font-medium tracking-wide text-slate-500 dark:text-slate-400 uppercase">
                  <th className="px-5 py-3">数据集</th>
                  <th className="px-3 py-3">市场</th>
                  <th className="px-3 py-3">频率</th>
                  <th className="px-3 py-3">提供方</th>
                  <th className="px-3 py-3">激活</th>
                  <th className="px-3 py-3">最近运行</th>
                  <th className="px-5 py-3">数据截止</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((d) => (
                  <tr key={`${d.dataset_id}|${d.provider}`} className="border-b border-slate-50 dark:border-slate-800/70 transition-colors last:border-0 hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
                    <td className="px-5 py-3 font-mono text-xs font-medium text-slate-700 dark:text-slate-200">{d.dataset_id}</td>
                    <td className="px-3 py-3 text-xs text-slate-600 dark:text-slate-300">{d.market}</td>
                    <td className="px-3 py-3 text-xs whitespace-nowrap text-slate-600 dark:text-slate-300">{d.cadence}</td>
                    <td className="px-3 py-3 text-xs text-slate-600 dark:text-slate-300">{d.provider}</td>
                    <td className="px-3 py-3">
                      <Badge tone={d.activation === 'active' ? 'green' : 'slate'}>{d.activation}</Badge>
                    </td>
                    <td className="px-3 py-3">
                      <StateBadge row={d} />
                      {d.reasons && d.reasons.length > 0 && (
                        <div className="mt-1 max-w-64 truncate text-[10px] text-slate-400 dark:text-slate-500" title={d.reasons.join('; ')}>
                          {d.reasons.join('; ')}
                        </div>
                      )}
                    </td>
                    <td className="px-5 py-3 font-mono text-[11px] whitespace-nowrap text-slate-500 dark:text-slate-400">
                      {d.data_through ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
