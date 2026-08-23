import { useEffect, useMemo, useState } from 'react'
import type { ApiClient } from '../../lib/api'
import type { DatasetRow, QueryResult } from '../../lib/types'
import {
  Badge,
  Button,
  Card,
  CopyButton,
  EmptyState,
  ErrorBanner,
  LoadingPanel,
} from '../../components/ui'

interface CatalogResponse {
  datasets?: DatasetRow[]
}

const STATE_TONES: Record<string, 'green' | 'rose' | 'amber' | 'slate'> = {
  success: 'green',
  failed: 'rose',
  stale: 'amber',
  degraded: 'amber',
}

export default function DataView({ client }: { client: ApiClient }) {
  const [rows, setRows] = useState<DatasetRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<DatasetRow | null>(null)
  const [sample, setSample] = useState<{
    loading: boolean
    error: string | null
    fields: string[]
    items: Record<string, unknown>[]
    cursor: string | null
  } | null>(null)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const data = await client.get<CatalogResponse>('/v1/catalog', { limit: '500' })
        if (!alive) return
        setRows(data.datasets ?? [])
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : '加载目录失败')
      }
    })()
    return () => {
      alive = false
    }
  }, [client])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!rows) return []
    return rows.filter((d) => !q || d.dataset_id.toLowerCase().includes(q))
  }, [rows, search])

  const runSample = async (dataset: DatasetRow) => {
    setSelected(dataset)
    setSample({ loading: true, error: null, fields: [], items: [], cursor: null })
    try {
      const result = await client.post<QueryResult>('/v1/query', {
        dataset_id: dataset.dataset_id,
        limit: 20,
      })
      const inner = result.data ?? {}
      setSample({
        loading: false,
        error: null,
        fields: inner.fields ?? (inner.items?.[0] ? Object.keys(inner.items[0]) : []),
        items: inner.items ?? [],
        cursor: result.next_cursor ?? null,
      })
    } catch (err) {
      setSample({
        loading: false,
        error: err instanceof Error ? err.message : '查询失败',
        fields: [],
        items: [],
        cursor: null,
      })
    }
  }

  const runNextPage = async () => {
    if (!selected || !sample?.cursor) return
    setSample({ ...sample, loading: true })
    try {
      const result = await client.post<QueryResult>('/v1/query', {
        dataset_id: selected.dataset_id,
        limit: 20,
        cursor: sample.cursor,
      })
      const inner = result.data ?? {}
      setSample({
        loading: false,
        error: null,
        fields: sample.fields.length ? sample.fields : inner.fields ?? [],
        items: [...sample.items, ...(inner.items ?? [])],
        cursor: result.next_cursor ?? null,
      })
    } catch (err) {
      setSample({
        ...sample,
        loading: false,
        error: err instanceof Error ? err.message : '翻页失败',
      })
    }
  }

  const curlExample = selected
    ? `curl -X POST ${client.baseUrl}/v1/query \\\n  -H "Authorization: Bearer <你的API密钥>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"dataset_id": "${selected.dataset_id}", "limit": 20}'`
    : ''

  if (!rows && !error) return <LoadingPanel label="加载数据目录…" />
  if (error) return <ErrorBanner message={error} />

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(320px,2fr)_3fr]">
      {/* Catalog list */}
      <Card title={`数据目录（${filtered.length}）`} className="overflow-hidden flex flex-col !p-0 max-h-[72vh]">
        <div className="border-b border-slate-100 p-3">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索数据集…"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 focus:outline-none"
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {filtered.length === 0 ? (
            <EmptyState title="没有匹配的数据集" />
          ) : (
            filtered.map((d) => (
              <button
                key={`${d.dataset_id}|${d.provider}`}
                onClick={() => void runSample(d)}
                className={`flex w-full items-center justify-between gap-2 border-b border-slate-50 px-4 py-2.5 text-left transition-colors last:border-0 hover:bg-slate-50 ${
                  selected?.dataset_id === d.dataset_id && selected?.provider === d.provider
                    ? 'bg-blue-50/70'
                    : ''
                }`}
              >
                <div className="min-w-0">
                  <div className="truncate font-mono text-xs font-medium text-slate-700">{d.dataset_id}</div>
                  <div className="text-[10px] text-slate-400">{d.market} · {d.cadence}</div>
                </div>
                <Badge tone={STATE_TONES[d.runtime_state ?? ''] ?? 'slate'}>{d.runtime_state ?? '-'}</Badge>
              </button>
            ))
          )}
        </div>
      </Card>

      {/* Sample data */}
      <div className="space-y-5">
        {!selected ? (
          <Card>
            <EmptyState
              title="从左侧选择一个数据集"
              hint="将自动拉取最近 20 条样本数据，并生成对应的 curl 示例"
            />
          </Card>
        ) : (
          <>
            <Card
              title={<span className="font-mono text-xs">{selected.dataset_id}</span>}
              action={<CopyButton text={curlExample} label="复制 curl 示例" />}
            >
              <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
                {[
                  ['市场', selected.market],
                  ['领域', selected.domain ?? '—'],
                  ['频率', selected.cadence],
                  ['提供方', selected.provider],
                  ['激活', selected.activation],
                  ['数据截止', selected.data_through ?? '—'],
                  ['新鲜度', selected.freshness_state ?? '—'],
                ].map(([k, v]) => (
                  <div key={k}>
                    <span className="text-slate-400">{k}</span>
                    <div className="mt-0.5 font-medium text-slate-700">{v}</div>
                  </div>
                ))}
              </div>
            </Card>

            <Card title={`样本数据（${sample?.items.length ?? 0} 条）`}>
              {sample?.loading ? (
                <LoadingPanel label="查询中…" />
              ) : sample?.error ? (
                <ErrorBanner message={sample.error} />
              ) : !sample || sample.items.length === 0 ? (
                <EmptyState title="该窗口内没有返回数据行" />
              ) : (
                <>
                  <div className="max-h-80 overflow-auto rounded-lg border border-slate-100">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0 bg-slate-50">
                        <tr>
                          {sample.fields.map((f) => (
                            <th key={f} className="px-3 py-2 text-left font-medium whitespace-nowrap text-slate-500">{f}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {sample.items.map((item, i) => (
                          <tr key={i} className="border-t border-slate-50">
                            {sample.fields.map((f) => {
                              const v = item[f]
                              return (
                                <td key={f} className="max-w-56 truncate px-3 py-1.5 font-mono whitespace-nowrap text-slate-600" title={typeof v === 'object' ? JSON.stringify(v) : String(v ?? '')}>
                                  {v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v)}
                                </td>
                              )
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {sample.cursor && (
                    <div className="mt-3 text-center">
                      <Button variant="secondary" size="sm" onClick={() => void runNextPage()}>
                        加载更多
                      </Button>
                    </div>
                  )}
                </>
              )}
            </Card>

            <Card title="接口调用示例">
              <pre className="overflow-x-auto rounded-lg bg-slate-900 px-4 py-3 font-mono text-[11px] leading-relaxed whitespace-pre text-slate-200">
{curlExample}
              </pre>
            </Card>
          </>
        )}
      </div>
    </div>
  )
}
