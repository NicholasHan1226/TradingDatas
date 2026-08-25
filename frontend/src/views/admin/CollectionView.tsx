import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, ChevronsUpDown, Columns3, Database, RotateCcw } from 'lucide-react'
import {
  columnVisibilityFeature,
  createColumnHelper,
  createSortedRowModel,
  functionalUpdate,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_basic,
  tableFeatures,
  useTable,
  type ColumnVisibilityState,
  type SortingState,
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { ApiClient } from '../../lib/api'
import type { CollectionStatus, DatasetRow } from '../../lib/types'
import { usePersistentState } from '../../lib/persistence'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  ControlBar,
  EmptyState,
  ErrorBanner,
  LoadingPanel,
  Modal,
  PageIntro,
  SearchField,
  SelectInput,
  StatCard,
  ACTIVATION_LABELS,
  CADENCE_LABELS,
  RUNTIME_STATE_LABELS,
  TABLE_ROW_CLASS,
} from '../../components/ui'

const EMPTY_DATASETS: DatasetRow[] = []

const STATE_TONES: Record<string, 'green' | 'rose' | 'amber' | 'blue' | 'slate'> = {
  success: 'green', empty: 'blue', failed: 'rose', stale: 'amber', degraded: 'amber',
}

function StateBadge({ row }: { row: DatasetRow }) {
  const state = row.runtime_state || '-'
  return (
    <div>
      <Badge tone={STATE_TONES[state] ?? 'slate'}>{RUNTIME_STATE_LABELS[state] ?? state}{row.degraded ? ' · 降级' : ''}</Badge>
      {row.reasons && row.reasons.length > 0 && (
        <div className="mt-1 max-w-64 truncate text-[10px] text-slate-400" title={row.reasons.join('; ')}>{row.reasons.join('; ')}</div>
      )}
    </div>
  )
}

const TABLE_FEATURES = tableFeatures({
  columnVisibilityFeature,
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric, basic: sortFn_basic },
})

const helper = createColumnHelper<typeof TABLE_FEATURES, DatasetRow>()
const COLUMNS = helper.columns([
  helper.accessor('dataset_id', {
    header: '数据集', enableHiding: false, sortFn: 'alphanumeric',
    cell: ({ getValue }) => <span className="font-mono text-xs font-medium text-slate-700">{getValue()}</span>,
  }),
  helper.accessor('market', { header: '市场', sortFn: 'alphanumeric' }),
  helper.accessor('cadence', {
    header: '频率', sortFn: 'alphanumeric',
    cell: ({ getValue }) => CADENCE_LABELS[getValue()] ?? getValue(),
  }),
  helper.accessor('provider', { header: '提供方', sortFn: 'alphanumeric' }),
  helper.accessor('activation', {
    header: '激活', sortFn: 'alphanumeric',
    cell: ({ getValue }) => {
      const value = getValue() ?? ''
      return <Badge tone={value === 'active' ? 'blue' : 'slate'}>{ACTIVATION_LABELS[value] || value || '未设置'}</Badge>
    },
  }),
  helper.accessor((row) => row.runtime_state ?? '', {
    id: 'runtime_state', header: '最近运行', sortFn: 'alphanumeric', cell: ({ row }) => <StateBadge row={row.original} />,
  }),
  helper.accessor((row) => row.data_through ?? '', {
    id: 'data_through', header: '数据截止', sortFn: 'alphanumeric',
    cell: ({ getValue }) => <span className="font-mono text-[11px] whitespace-nowrap text-slate-500">{getValue() || '—'}</span>,
  }),
])

const COLUMN_WIDTHS: Record<string, string> = {
  dataset_id: 'minmax(280px,2fr)', market: 'minmax(110px,0.65fr)', cadence: 'minmax(140px,0.8fr)',
  provider: 'minmax(120px,0.7fr)', activation: 'minmax(90px,0.55fr)', runtime_state: 'minmax(180px,1fr)',
  data_through: 'minmax(210px,1.15fr)',
}

export default function CollectionView({ client }: { client: ApiClient }) {
  const [status, setStatus] = useState<CollectionStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [columnsOpen, setColumnsOpen] = useState(false)
  const [market, setMarket] = usePersistentState('td.console.collection.market.v1', '')
  const [activation, setActivation] = usePersistentState('td.console.collection.activation.v1', '')
  const [stateFilter, setStateFilter] = usePersistentState('td.console.collection.runtime.v1', '')
  const [search, setSearch] = usePersistentState('td.console.collection.search.v1', '')
  const [sorting, setSorting] = usePersistentState<SortingState>('td.console.collection.sorting.v1', [{ id: 'dataset_id', desc: false }])
  const [columnVisibility, setColumnVisibility] = usePersistentState<ColumnVisibilityState>('td.console.collection.columns.v1', {})

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
    return () => { alive = false }
  }, [client])

  const datasets = status?.datasets ?? EMPTY_DATASETS
  const markets = useMemo(() => [...new Set(datasets.map((d) => d.market))].filter(Boolean).sort(), [datasets])
  const runtimeStates = useMemo(
    () => [...new Set(datasets.map((d) => d.runtime_state).filter((value): value is string => Boolean(value)))].sort(),
    [datasets],
  )
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return datasets.filter((d) =>
      (!market || d.market === market) && (!activation || d.activation === activation) &&
      (!stateFilter || (d.runtime_state || '') === stateFilter) && (!q || d.dataset_id.toLowerCase().includes(q)),
    )
  }, [datasets, market, activation, stateFilter, search])

  const table = useTable({
    features: TABLE_FEATURES, columns: COLUMNS, data: filtered,
    getRowId: (row) => `${row.dataset_id}|${row.provider}`,
    state: { sorting, columnVisibility },
    onSortingChange: (updater) => setSorting((current) => functionalUpdate(updater, current)),
    onColumnVisibilityChange: (updater) => setColumnVisibility((current) => functionalUpdate(updater, current)),
    enableSortingRemoval: false,
  })

  const scrollRef = useRef<HTMLDivElement>(null)
  const tableRows = table.getRowModel().rows
  const virtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 54,
    getItemKey: (index) => tableRows[index]?.id ?? index,
    overscan: 10,
  })
  const gridTemplateColumns = table.getVisibleLeafColumns().map((column) => COLUMN_WIDTHS[column.id] ?? 'minmax(120px,1fr)').join(' ')

  const activeCount = datasets.filter((d) => d.activation === 'active').length
  const degradedCount = datasets.filter((d) => d.degraded).length
  const failedCount = datasets.filter((d) => d.runtime_state === 'failed').length
  const resetView = () => {
    setMarket(''); setActivation(''); setStateFilter(''); setSearch('')
    setSorting([{ id: 'dataset_id', desc: false }]); setColumnVisibility({})
  }

  if (!status && !error) return <LoadingPanel label="加载采集状态…" />
  if (error) return <ErrorBanner message={error} />

  return (
    <div className="space-y-6">
      <PageIntro eyebrow="数据运行面" title="数据采集状态" description="跟踪数据集激活状态、最新运行结果与质量降级信号。排序、筛选和列布局会保存在当前浏览器。" />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="数据集总数" value={status?.total ?? datasets.length} />
        <StatCard label="采集激活" value={activeCount} tone="good" />
        <StatCard label="运行失败" value={failedCount} tone={failedCount > 0 ? 'bad' : 'default'} />
        <StatCard label="质量降级" value={degradedCount} tone={degradedCount > 0 ? 'warn' : 'default'} />
      </div>

      <ControlBar>
        <SearchField className="w-full md:w-64" aria-label="搜索数据集" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索数据集 ID…" />
        <SelectInput value={market} onChange={(e) => setMarket(e.target.value)} className="!w-auto flex-1 sm:flex-none">
          <option value="">全部市场</option>{markets.map((m) => <option key={m} value={m}>{m}</option>)}
        </SelectInput>
        <SelectInput value={activation} onChange={(e) => setActivation(e.target.value)} className="!w-auto flex-1 sm:flex-none">
          <option value="">全部激活状态</option><option value="active">已启用</option><option value="paused">已暂停</option>
        </SelectInput>
        <SelectInput value={stateFilter} onChange={(e) => setStateFilter(e.target.value)} className="!w-auto flex-1 sm:flex-none">
          <option value="">全部运行状态</option>{runtimeStates.map((state) => <option key={state} value={state}>{RUNTIME_STATE_LABELS[state] ?? state}</option>)}
        </SelectInput>
        <div className="ml-auto flex w-full items-center justify-end gap-2 sm:w-auto">
          <span className="hidden text-xs text-slate-400 xl:inline">{tableRows.length.toLocaleString('zh-CN')} / {datasets.length.toLocaleString('zh-CN')} 个数据集</span>
          <Button variant="secondary" size="sm" onClick={() => setColumnsOpen(true)}><Columns3 aria-hidden size={14} /> 列</Button>
          <Button variant="ghost" size="sm" onClick={resetView} aria-label="重置表格视图"><RotateCcw aria-hidden size={14} /> 重置</Button>
        </div>
      </ControlBar>

      <Card className="overflow-hidden" bodyClassName="!p-0">
        {tableRows.length === 0 ? <EmptyState icon={Database} title="没有匹配的数据集" hint="调整市场、状态或搜索条件后再试。" action={<Button variant="secondary" size="sm" onClick={resetView}>清除筛选</Button>} /> : (
          <>
          <div id="collection-scroll-hint" className="border-b border-slate-100 bg-slate-50/70 px-4 py-2 text-[10px] text-slate-500 sm:hidden">左右滑动查看全部字段 · 数据集列保持可见</div>
          <div ref={scrollRef} className="max-h-[62vh] overflow-auto" tabIndex={0} aria-label="数据集运行状态表格" aria-describedby="collection-scroll-hint">
            <table className="min-w-[980px] w-full text-sm" style={{ display: 'grid' }}>
              <thead className="sticky top-0 z-[2] grid border-b border-[var(--td-line)] bg-[#f7f8fa]">
                {table.getHeaderGroups().map((group) => (
                  <tr key={group.id} className="grid" style={{ gridTemplateColumns }}>
                    {group.headers.map((header) => {
                      const sorted = header.column.getIsSorted()
                      return (
                        <th key={header.id} className={`min-w-0 px-4 py-3 text-left text-[10px] font-semibold tracking-[0.07em] text-[var(--td-muted)] uppercase ${header.column.id === 'dataset_id' ? 'sticky left-0 z-[3] bg-[#f7f8fa] shadow-[1px_0_0_var(--td-line)]' : ''}`}>
                          {header.isPlaceholder ? null : (
                            <button type="button" onClick={header.column.getToggleSortingHandler()} className="inline-flex items-center gap-1.5 rounded text-left hover:text-[var(--td-ink)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--td-accent)]" aria-label={`按${String(header.column.columnDef.header)}排序`}>
                              <table.FlexRender header={header} />
                              {sorted === 'asc' ? <ChevronUp aria-hidden size={12} /> : sorted === 'desc' ? <ChevronDown aria-hidden size={12} /> : <ChevronsUpDown aria-hidden size={12} className="text-slate-300" />}
                            </button>
                          )}
                        </th>
                      )
                    })}
                  </tr>
                ))}
              </thead>
              <tbody className="relative grid" style={{ height: `${virtualizer.getTotalSize()}px` }}>
                {virtualizer.getVirtualItems().map((virtualRow) => {
                  const row = tableRows[virtualRow.index]
                  return (
                    <tr key={row.id} data-index={virtualRow.index} ref={virtualizer.measureElement} className={`group absolute top-0 left-0 grid w-full ${TABLE_ROW_CLASS}`} style={{ gridTemplateColumns, transform: `translateY(${virtualRow.start}px)` }}>
                      {row.getVisibleCells().map((cell) => <td key={cell.id} className={`min-w-0 px-4 py-3 text-xs text-slate-600 ${cell.column.id === 'dataset_id' ? 'sticky left-0 z-[1] bg-white shadow-[1px_0_0_var(--td-line)] group-hover:bg-[#f6f8fc]' : ''}`}><table.FlexRender cell={cell} /></td>)}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          </>
        )}
      </Card>

      <Modal open={columnsOpen} onClose={() => setColumnsOpen(false)} title="自定义数据列" width="max-w-md">
        <p className="mb-4 text-xs leading-5 text-[var(--td-muted)]">隐藏不常用字段，表格布局会保存在当前浏览器。数据集名称始终显示。</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {table.getAllLeafColumns().filter((column) => column.getCanHide()).map((column) => (
            <div key={column.id} className="rounded-lg border border-slate-200 px-3 py-2.5">
              <Checkbox checked={column.getIsVisible()} onChange={(checked) => column.toggleVisibility(checked)} label={String(column.columnDef.header)} />
            </div>
          ))}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => table.toggleAllColumnsVisible(true)}>显示全部</Button>
          <Button onClick={() => setColumnsOpen(false)}>完成</Button>
        </div>
      </Modal>
    </div>
  )
}
