import { useEffect, useMemo, useState } from 'react'
import { Database, SearchX } from 'lucide-react'
import type { ApiClient } from '../../lib/api'
import type { CollectionStatus, DatasetRow, QueryResult } from '../../lib/types'
import { recordConsoleEvent } from '../../lib/consoleAnalytics'
import { usePersistentState } from '../../lib/persistence'
import {
  Badge,
  Button,
  Card,
  CopyButton,
  EmptyState,
  ErrorBanner,
  LoadingPanel,
  PageIntro,
  SearchField,
  TABLE_HEAD_CLASS,
  TABLE_ROW_CLASS,
  ACTIVATION_LABELS,
  RUNTIME_STATE_LABELS,
} from '../../components/ui'

type CatalogDatasetRow = Omit<DatasetRow, 'provider'> & { provider?: string }

interface CatalogResponse {
  data?: CatalogDatasetRow[]
}

const STATE_TONES: Record<string, 'green' | 'rose' | 'amber' | 'blue' | 'slate'> = {
  success: 'green',
  empty: 'blue',
  failed: 'rose',
  stale: 'amber',
  degraded: 'amber',
}

export default function DataView({ client }: { client: ApiClient }) {
  const [rows, setRows] = useState<DatasetRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = usePersistentState('td.console.browser.search.v1', '')
  const [selected, setSelected] = useState<DatasetRow | null>(null)
  const [sample, setSample] = useState<{
    loading: boolean
    error: string | null
    fields: string[]
    items: Record<string, unknown>[]
    cursor: string | null
    metadata?: QueryResult['metadata']
  } | null>(null)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const catalog = await client.get<CatalogResponse>('/v1/catalog', { limit: '500' })
        if (!alive) return
        const catalogRows = (catalog.data ?? []).map((row) => ({
          ...row,
          provider: row.provider ?? '—',
        }))
        // The public catalog is already sufficient to browse and query data.
        // Render it immediately instead of blocking the whole page on the
        // admin-only runtime decoration request below.
        setRows(catalogRows)
        try {
          const collection = await client.get<CollectionStatus>('/admin/api/collection/status')
          if (!alive) return
          const runtimeByDataset = new Map(
            (collection.datasets ?? []).map((row) => [row.dataset_id, row]),
          )
          setRows((current) => current?.map((row) => {
            const runtime = runtimeByDataset.get(row.dataset_id)
            return {
              ...row,
              provider: runtime?.provider ?? row.provider,
              activation: runtime?.activation ?? row.activation,
              runtime_state: runtime?.runtime_state ?? row.runtime_state,
              degraded: runtime?.degraded ?? row.degraded,
              freshness_state: runtime?.freshness_state ?? row.freshness_state,
              data_through: runtime?.data_through ?? row.data_through,
              observed_at: runtime?.observed_at ?? row.observed_at,
              reasons: runtime?.reasons ?? row.reasons,
              coverage: runtime?.coverage ?? row.coverage,
            }
          }) ?? current)
        } catch {
          // Catalog is independently useful; runtime decoration is best-effort.
        }
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
        schema_major: dataset.schema_major,
        limit: 20,
      })
      const items = result.data ?? []
      recordConsoleEvent('dataset_query_succeeded', 'admin')
      setSample({
        loading: false,
        error: null,
        fields: items[0] ? Object.keys(items[0]) : [],
        items,
        cursor: result.next_cursor ?? null,
        metadata: result.metadata,
      })
    } catch (err) {
      recordConsoleEvent('request_failed', 'admin')
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
        schema_major: selected.schema_major,
        limit: 20,
        cursor: sample.cursor,
      })
      const items = result.data ?? []
      recordConsoleEvent('dataset_query_succeeded', 'admin')
      setSample({
        loading: false,
        error: null,
        fields: sample.fields.length ? sample.fields : items[0] ? Object.keys(items[0]) : [],
        items: [...sample.items, ...items],
        cursor: result.next_cursor ?? null,
        metadata: result.metadata,
      })
    } catch (err) {
      recordConsoleEvent('request_failed', 'admin')
      setSample({
        ...sample,
        loading: false,
        error: err instanceof Error ? err.message : '翻页失败',
      })
    }
  }

  const curlExample = selected
    ? `curl -X POST ${client.baseUrl}/v1/query \\\n  -H "Authorization: Bearer <你的API密钥>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"dataset_id": "${selected.dataset_id}", "schema_major": ${selected.schema_major}, "limit": 20}'`
    : ''

  if (!rows && !error) return <LoadingPanel label="加载数据目录…" />
  if (error) return <ErrorBanner message={error} />

  return (
    <div className="space-y-6">
      <PageIntro
        eyebrow="目录验证"
        title="数据目录浏览"
        description="检索可用数据集，验证结构，并从当前目录直接发起只读样本查询。"
      />
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(320px,2fr)_3fr]">
        {/* Catalog list */}
        <Card title="数据目录" action={<span className="text-xs text-slate-400">{filtered.length} 项</span>} className="max-h-[72vh] overflow-hidden flex flex-col" bodyClassName="!p-0">
          <div className="border-b border-slate-100 p-3">
            <SearchField
              aria-label="搜索数据目录"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索数据集…"
            />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {filtered.length === 0 ? (
              <EmptyState icon={SearchX} title="没有匹配的数据集" hint="尝试缩短关键词或清除搜索条件。" />
            ) : (
              filtered.map((d) => {
                const active = selected?.dataset_id === d.dataset_id && selected?.provider === d.provider
                return (
                  <button
                    key={`${d.dataset_id}|${d.provider}`}
                    type="button"
                    aria-pressed={active}
                    onClick={() => void runSample(d)}
                    className={`flex w-full items-center justify-between gap-2 border-l-2 ${TABLE_ROW_CLASS} px-4 py-2.5 text-left focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-blue-500 ${
                      active ? 'border-l-[var(--td-accent)] bg-[var(--td-accent-quiet)]' : 'border-l-transparent'
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="truncate font-mono text-xs font-medium text-slate-700">{d.dataset_id}</div>
                      <div className="text-[10px] text-slate-400">v{d.schema_major} · {d.market} · {d.cadence}</div>
                    </div>
                    <Badge tone={STATE_TONES[d.runtime_state ?? ''] ?? 'slate'}>{RUNTIME_STATE_LABELS[d.runtime_state ?? ''] ?? d.runtime_state ?? '尚未观测'}</Badge>
                  </button>
                )
              })
            )}
          </div>
        </Card>

        {/* Sample data */}
        <div className="space-y-5">
        {!selected ? (
          <Card>
            <EmptyState
              icon={Database}
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
                  ['Schema', `v${selected.schema_major}`],
                  ['领域', selected.domain ?? '—'],
                  ['频率', selected.cadence],
                  ['提供方', selected.provider],
                  ['激活', ACTIVATION_LABELS[selected.activation] ?? selected.activation],
                  ['数据截止', selected.data_through ?? '—'],
                  ['新鲜度', RUNTIME_STATE_LABELS[selected.freshness_state ?? ''] ?? selected.freshness_state ?? '—'],
                  ['已存记录', selected.coverage?.row_count?.toLocaleString('zh-CN') ?? '—'],
                ].map(([k, v]) => (
                  <div key={k}>
                    <span className="text-slate-400">{k}</span>
                    <div className="mt-0.5 font-medium text-slate-700">{v}</div>
                  </div>
                ))}
              </div>
            </Card>

            <Card title="样本数据" action={<span className="text-xs text-slate-400">{sample?.items.length ?? 0} 条</span>}>
              {sample?.loading ? (
                <LoadingPanel label="查询中…" />
              ) : sample?.error ? (
                <ErrorBanner message={sample.error} />
              ) : !sample || sample.items.length === 0 ? (
                <EmptyState
                  icon={Database}
                  title={sample?.metadata?.runtime_state === 'empty' ? '当前采集窗口没有新增行' : '该窗口内没有返回数据行'}
                  hint={sample?.metadata?.runtime_state === 'empty'
                    ? '这是本次采集窗口的真实空结果；目录内的历史覆盖不会被当作当前数据回传。'
                    : undefined}
                />
              ) : (
                <>
                  <div className="max-h-80 overflow-auto rounded-lg border border-slate-100">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className={TABLE_HEAD_CLASS}>
                          {sample.fields.map((f) => (
                            <th key={f} className="px-3 py-2 text-left font-medium whitespace-nowrap text-slate-500">{f}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {sample.items.map((item, i) => (
                          <tr key={i} className={TABLE_ROW_CLASS}>
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
    </div>
  )
}
