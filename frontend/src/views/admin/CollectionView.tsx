import { useEffect, useMemo, useState } from 'react'
import type { ApiClient } from '../../lib/api'
import type { CollectionStatus, DatasetRow } from '../../lib/types'
import {
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  LoadingPanel,
  PageIntro,
  SearchField,
  SelectInput,
  StatCard,
  TABLE_HEAD_CLASS,
  TABLE_ROW_CLASS,
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
      <PageIntro
        eyebrow="COLLECTION CONTROL"
        title="数据采集状态"
        description="跟踪数据集激活状态、最新运行结果与质量降级信号。"
      />
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

      <div className="flex flex-wrap items-center gap-3 rounded-[var(--td-radius)] border border-slate-200/80 bg-white/70 p-3 shadow-[0_1px_2px_rgb(15_23_42/0.02)]">
        <SearchField
          className="w-full md:w-64"
          aria-label="搜索数据集"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索数据集 ID…"
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
        <span className="ml-auto text-xs text-slate-400">
          显示 {filtered.length.toLocaleString('zh-CN')} / {datasets.length.toLocaleString('zh-CN')} 个数据集
        </span>
      </div>

      <Card className="overflow-hidden" bodyClassName="!p-0">
        {filtered.length === 0 ? (
          <EmptyState title="没有匹配的数据集" hint="调整筛选条件试试" />
        ) : (
          <div className="max-h-[62vh] overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={TABLE_HEAD_CLASS}>
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
                  <tr key={`${d.dataset_id}|${d.provider}`} className={TABLE_ROW_CLASS}>
                    <td className="px-5 py-3 font-mono text-xs font-medium text-slate-700">{d.dataset_id}</td>
                    <td className="px-3 py-3 text-xs text-slate-600">{d.market}</td>
                    <td className="px-3 py-3 text-xs whitespace-nowrap text-slate-600">{d.cadence}</td>
                    <td className="px-3 py-3 text-xs text-slate-600">{d.provider}</td>
                    <td className="px-3 py-3">
                      <Badge tone={d.activation === 'active' ? 'green' : 'slate'}>{d.activation}</Badge>
                    </td>
                    <td className="px-3 py-3">
                      <StateBadge row={d} />
                      {d.reasons && d.reasons.length > 0 && (
                        <div className="mt-1 max-w-64 truncate text-[10px] text-slate-400" title={d.reasons.join('; ')}>
                          {d.reasons.join('; ')}
                        </div>
                      )}
                    </td>
                    <td className="px-5 py-3 font-mono text-[11px] whitespace-nowrap text-slate-500">
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
