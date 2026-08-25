// Shared precision-utility design system for the admin console and portal.
import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Bitcoin, ChartCandlestick, Check, CircleAlert, Copy, Inbox, LoaderCircle, Newspaper, Search, Tag, X, type LucideIcon } from 'lucide-react'
import { recordConsoleEvent, type ConsoleWorkspace } from '../lib/consoleAnalytics'

// ---------- Buttons ----------

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

const BUTTON_STYLES: Record<ButtonVariant, string> = {
  primary:
    'border border-transparent bg-[var(--td-accent)] text-white hover:bg-[var(--td-accent-strong)] active:bg-[#1838ae] shadow-[var(--td-shadow-1)] disabled:bg-[#a7b5ee]',
  secondary:
    'bg-white text-[var(--td-ink-soft)] border border-[var(--td-line-strong)] hover:border-[#aaa9a4] hover:bg-[#f7f7f5] active:bg-[#efefec]',
  ghost: 'border border-transparent text-[var(--td-muted)] hover:bg-[#f0f0ed] hover:text-[var(--td-ink)]',
  danger:
    'bg-white text-rose-600 border border-rose-200 hover:bg-rose-50 active:bg-rose-100',
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  className = '',
  children,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: 'sm' | 'md'
  loading?: boolean
}) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={`inline-flex items-center justify-center gap-1.5 rounded-[var(--td-radius-sm)] font-medium transition-[color,background-color,border-color,box-shadow] duration-[var(--td-duration-fast)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--td-accent)] disabled:cursor-not-allowed disabled:opacity-60 ${
        size === 'sm' ? 'min-h-8 px-2.5 py-1.5 text-xs' : 'min-h-10 px-4 py-2 text-sm'
      } ${BUTTON_STYLES[variant]} ${className}`}
    >
      {loading && <Spinner size={size === 'sm' ? 12 : 14} />}
      {children}
    </button>
  )
}

export function Spinner({ size = 16, className = '' }: { size?: number; className?: string }) {
  return <LoaderCircle aria-hidden className={`animate-spin text-current ${className}`} size={size} />
}

export function LoadingPanel({ label = '加载中…' }: { label?: string }) {
  return (
    <div role="status" className="flex min-h-64 items-center justify-center gap-2 py-16 text-sm text-[var(--td-muted)]">
      <Spinner /> {label}
    </div>
  )
}

export function EmptyState({
  title,
  hint,
  icon: Icon = Inbox,
  action,
}: {
  title: string
  hint?: string
  icon?: LucideIcon
  action?: ReactNode
}) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center px-5 py-12 text-center">
      <span className="flex h-10 w-10 items-center justify-center rounded-[var(--td-radius)] border border-[var(--td-line)] bg-[var(--td-surface-subtle)] text-[var(--td-accent)]">
        <Icon aria-hidden size={19} strokeWidth={1.7} />
      </span>
      <div className="mt-4 text-sm font-semibold text-[var(--td-ink-soft)]">{title}</div>
      {hint && <div className="mt-1.5 max-w-sm text-xs leading-5 text-[var(--td-muted)]">{hint}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-[var(--td-radius)] border border-rose-200 bg-rose-50/90 px-4 py-3.5 text-sm text-rose-700 shadow-[var(--td-shadow-hairline)]">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-rose-100"><CircleAlert aria-hidden className="h-3.5 w-3.5" /></span>
      <span className="leading-5">{message}</span>
    </div>
  )
}

// ---------- Page composition ----------

export function PageIntro({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-5 border-b border-[var(--td-line)] pb-6">
      <div className="max-w-[720px]">
        {eyebrow && (
          <p className="mb-3 flex items-center gap-2 text-[10px] font-semibold tracking-[0.08em] text-[var(--td-accent)] before:h-1.5 before:w-1.5 before:rounded-full before:bg-[var(--td-accent)]">
            {eyebrow}
          </p>
        )}
        <h1 className="text-[28px] font-semibold leading-[1.12] tracking-[-0.052em] text-[var(--td-ink)] sm:text-[34px]">{title}</h1>
        {description && <p className="mt-3 max-w-2xl text-[13px] leading-6 text-[var(--td-muted)]">{description}</p>}
      </div>
      {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
    </div>
  )
}

export function ControlBar({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`flex flex-wrap items-center gap-2.5 rounded-[10px] border border-[var(--td-line)] bg-[rgb(255_255_255/0.74)] p-2.5 shadow-[var(--td-shadow-hairline)] ${className}`}>
      {children}
    </div>
  )
}

export function SearchField({
  className = '',
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className={`relative min-w-0 ${className}`}>
      <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-400" />
      <input
        type="search"
        {...props}
        className="min-h-10 w-full rounded-[8px] border border-[var(--td-line-strong)] bg-white py-2 pr-3 pl-9 text-sm text-[var(--td-ink)] shadow-[0_1px_1px_rgb(15_23_42/0.02)] outline-none transition-[border-color,box-shadow] duration-[var(--td-duration-fast)] placeholder:text-[var(--td-faint)] hover:border-[#aebbd0] focus:border-[var(--td-accent)] focus:ring-4 focus:ring-[rgb(49_92_246/0.10)]"
      />
    </div>
  )
}

export const TABLE_HEAD_CLASS =
  'sticky top-0 z-[1] border-b border-[var(--td-line)] bg-[#f5f7fb] text-left text-[10px] font-semibold tracking-[0.055em] text-[var(--td-muted)]'
export const TABLE_ROW_CLASS =
  'border-b border-[var(--td-line)] transition-colors last:border-0 hover:bg-[#f7f9ff] focus-within:bg-[var(--td-accent-quiet)]/70'

// ---------- Cards & stats ----------

export function Card({
  title,
  action,
  className = '',
  bodyClassName = '',
  children,
}: {
  title?: ReactNode
  action?: ReactNode
  className?: string
  bodyClassName?: string
  children: ReactNode
}) {
  return (
    <section
      className={`overflow-hidden rounded-[12px] border border-[var(--td-line)] bg-[var(--td-surface-raised)] shadow-[var(--td-shadow-hairline)] ${className}`}
    >
      {(title || action) && (
        <header className="flex min-h-12 flex-wrap items-center justify-between gap-3 border-b border-[var(--td-line)] px-4 py-3.5 sm:px-5">
          <h2 className="text-[13px] font-semibold tracking-[-0.01em] text-[var(--td-ink-soft)]">{title}</h2>
          {action}
        </header>
      )}
      <div className={`p-4 sm:p-5 ${bodyClassName}`}>{children}</div>
    </section>
  )
}

export function StatCard({
  label,
  value,
  sub,
  tone = 'default',
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: 'default' | 'good' | 'warn' | 'bad'
}) {
  const toneClass = {
    default: 'text-slate-900',
    good: 'text-emerald-600',
    warn: 'text-amber-600',
    bad: 'text-rose-600',
  }[tone]
  const toneDot = {
    default: 'bg-slate-300',
    good: 'bg-emerald-500',
    warn: 'bg-amber-500',
    bad: 'bg-rose-500',
  }[tone]
  return (
    <div className="relative overflow-hidden rounded-[12px] border border-[var(--td-line)] bg-[var(--td-surface-raised)] px-4 py-4 shadow-[var(--td-shadow-hairline)]">
      <span className={`absolute top-4 right-4 h-1.5 w-1.5 rounded-full ${toneDot}`} />
      <div className="flex items-center gap-2 pr-5 text-[11px] font-medium text-[var(--td-muted)]">{label}</div>
      <div className={`mt-3.5 text-[26px] font-semibold leading-none tracking-[-0.05em] tabular-nums ${toneClass}`}>{value}</div>
      {sub && <div className="mt-2 text-xs text-[var(--td-faint)]">{sub}</div>}
    </div>
  )
}

// ---------- Badges ----------

type BadgeTone = 'slate' | 'blue' | 'green' | 'amber' | 'rose' | 'violet'

const BADGE_STYLES: Record<BadgeTone, string> = {
  slate: 'border-[#deddd8] bg-[#f5f5f2] text-[#62625f]',
  blue: 'border-[#ccd6ff] bg-[#f0f3ff] text-[#274bc7]',
  green: 'border-[#bfe5d7] bg-[#edf8f3] text-[#087553]',
  amber: 'border-[#f1d5aa] bg-[#fff7e9] text-[#9b5800]',
  rose: 'border-[#f0c6cf] bg-[#fff0f3] text-[#b32748]',
  violet: 'border-[#d9d1f7] bg-[#f4f1ff] text-[#654dc7]',
}

export function Badge({ tone = 'slate', children }: { tone?: BadgeTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex min-h-5 items-center rounded-[4px] border px-1.5 py-0.5 text-[10px] font-medium tracking-[0.01em] ${BADGE_STYLES[tone]}`}
    >
      {children}
    </span>
  )
}

export const TIER_TONES: Record<string, BadgeTone> = {
  free: 'slate',
  starter: 'blue',
  research: 'violet',
  pro: 'green',
  basic: 'blue',
  standard: 'violet',
  flagship: 'green',
  enterprise: 'violet',
  internal: 'amber',
}

export const TIER_LABELS: Record<string, string> = {
  free: '免费版',
  starter: '入门版',
  research: '研究版',
  pro: '专业版',
  basic: '基础版',
  standard: '标准版',
  flagship: '旗舰版',
  enterprise: '企业版',
  internal: '平台管理',
}

export const RUNTIME_STATE_LABELS: Record<string, string> = {
  success: '运行正常',
  empty: '本次无新增',
  failed: '运行失败',
  stale: '更新状态待确认',
  degraded: '数据状态需关注',
  unobserved: '等待首次回执',
  unknown: '状态暂未确认',
}

export const RUNTIME_REASON_LABELS: Record<string, { label: string; detail: string }> = {
  freshness_sla_exceeded: { label: '超过预期更新窗口', detail: '请核对最近一次成功回执与下一采集窗口。' },
  data_through_in_future: { label: '数据时间需要校验', detail: '服务保留真实时间水位，不会把后续数据回填为较早时点。' },
  storage_failed: { label: '本次写入未完成', detail: '请检查该数据集的采集回执与存储状态。' },
  receipt_execution_inconsistent: { label: '回执完整性待确认', detail: '请核对本次执行记录与已写入事实是否一致。' },
  provider_unavailable: { label: '上游服务暂不可用', detail: '请确认上游服务状态、授权与限流情况。' },
  provider_error: { label: '上游调用未成功', detail: '请检查上游响应，并在合适窗口再次执行。' },
  no_recognized_receipt: { label: '尚未找到有效运行回执', detail: '请确认该数据集是否已进入正式采集计划。' },
}

export function runtimeTone(state?: string, degraded?: boolean): BadgeTone {
  if (degraded || state === 'degraded' || state === 'stale') return 'amber'
  if (state === 'success') return 'green'
  if (state === 'failed') return 'rose'
  if (state === 'empty') return 'blue'
  return 'slate'
}

export function runtimeLabel(state?: string, degraded?: boolean): string {
  if (degraded && state !== 'failed') return RUNTIME_STATE_LABELS.degraded
  return RUNTIME_STATE_LABELS[state ?? ''] ?? state ?? RUNTIME_STATE_LABELS.unknown
}

export function runtimeReason(reasons?: string[]): { label: string; detail: string; raw?: string } | null {
  const raw = reasons?.[0]
  if (!raw) return null
  return { ...(RUNTIME_REASON_LABELS[raw] ?? { label: '运行状态需要确认', detail: '请查看最近回执与数据时间后继续处理。' }), raw }
}

export function RuntimeStatus({
  state,
  degraded = false,
  reasons,
  detail = false,
}: {
  state?: string
  degraded?: boolean
  reasons?: string[]
  detail?: boolean
}) {
  const reason = runtimeReason(reasons)
  return (
    <div className="min-w-0">
      <Badge tone={runtimeTone(state, degraded)}>{runtimeLabel(state, degraded)}</Badge>
      {detail && reason && <p className="mt-1.5 max-w-64 truncate text-[10px] leading-4 text-[var(--td-faint)]" title={reason.raw}>{reason.label}</p>}
    </div>
  )
}

export const CADENCE_LABELS: Record<string, string> = {
  event: '事件驱动',
  on_demand: '按需',
  session_minute: '盘中分钟',
  intraday: '盘中',
  postclose_daily: '日终',
  daily_reference: '每日参考',
  daily: '每日',
  weekly: '每周',
  monthly: '每月',
  quarterly_reporting: '季度',
  hourly: '每小时',
}

export const ACTIVATION_LABELS: Record<string, string> = {
  active: '已启用',
  paused: '已暂停',
  disabled: '未启用',
  contract_ready: '合同就绪',
  observed: '已观测',
  stable: '稳定运行',
}

export function ScopeChip({ scope }: { scope: string }) {
  const labels: Record<string, string> = {
    read: '读取',
    query: '查询',
    catalog: '目录',
    admin: '管理',
  }
  return (
    <span className="inline-flex min-h-6 items-center rounded-[5px] border border-[var(--td-line)] bg-[var(--td-surface-subtle)] px-2 py-1 text-[10px] font-semibold text-[var(--td-ink-soft)]">
      {labels[scope] ?? scope}
    </span>
  )
}

const CATEGORY_META: Record<string, { label: string; icon: LucideIcon; className: string }> = {
  a_share: { label: 'A 股', icon: ChartCandlestick, className: 'border-blue-200 bg-blue-50 text-blue-700' },
  crypto: { label: '加密资产', icon: Bitcoin, className: 'border-violet-200 bg-violet-50 text-violet-700' },
  news: { label: '新闻', icon: Newspaper, className: 'border-orange-200 bg-orange-50 text-orange-700' },
}

export function DataCategoryTag({ category }: { category: string }) {
  const meta = CATEGORY_META[category] ?? { label: category, icon: Tag, className: 'border-slate-200 bg-slate-50 text-slate-600' }
  const Icon = meta.icon
  return <span className={`inline-flex min-h-6 items-center gap-1.5 rounded-[7px] border px-2 py-1 text-[10px] font-semibold ${meta.className}`}><Icon aria-hidden size={12} strokeWidth={1.8} />{meta.label}</span>
}

export function fmtNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return '不限'
  return value.toLocaleString('zh-CN')
}

// ---------- Inputs ----------

const INPUT_CLASS =
  'min-h-10 w-full rounded-[8px] border border-[var(--td-line-strong)] bg-white px-3 py-2 text-sm text-[var(--td-ink)] placeholder:text-[var(--td-faint)] shadow-[0_1px_1px_rgb(15_23_42/0.02)] transition-[border-color,box-shadow] duration-[var(--td-duration-fast)] hover:border-[#aebbd0] focus:border-[var(--td-accent)] focus:ring-4 focus:ring-[rgb(49_92_246/0.10)] focus:outline-none'

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-slate-400">{hint}</span>}
    </label>
  )
}

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${INPUT_CLASS} ${props.className ?? ''}`} />
}

export function SelectInput(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${INPUT_CLASS} ${props.className ?? ''}`} />
}

export function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  label: ReactNode
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-1.5 text-sm text-slate-700 select-none">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500/30"
      />
      {label}
    </label>
  )
}

export function ToggleSwitch({
  checked,
  onChange,
  disabled = false,
  busy = false,
  label,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  disabled?: boolean
  busy?: boolean
  label?: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled || busy}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--td-accent)] disabled:opacity-50 ${
        checked ? 'bg-[var(--td-accent)]' : 'bg-[#c9c9c4]'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
          checked ? 'translate-x-4.5' : 'translate-x-0.5'
        }`}
      />
    </button>
  )
}

// ---------- Modal ----------

export function Modal({
  open,
  onClose,
  title,
  width = 'max-w-lg',
  children,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  width?: string
  children: ReactNode
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => { if (!next) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/45" />
        <Dialog.Content className={`fixed top-1/2 left-1/2 z-50 w-[calc(100%-2rem)] ${width} max-h-[88vh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[var(--td-radius-lg)] border border-slate-200 bg-white shadow-[var(--td-shadow-2)] focus:outline-none`}>
            <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
              <Dialog.Title className="text-sm font-semibold text-slate-800">{title}</Dialog.Title>
              <Dialog.Close asChild>
                <Button variant="ghost" size="sm" aria-label="关闭">
                  <X aria-hidden className="h-4 w-4" />
                </Button>
              </Dialog.Close>
            </header>
            <div className="px-5 py-4">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

// ---------- Toasts ----------

interface ToastItem {
  id: number
  kind: 'ok' | 'err'
  text: string
}

const ToastContext = createContext<(kind: ToastItem['kind'], text: string) => void>(() => {})

let toastSeq = 0

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])

  const push = useCallback((kind: ToastItem['kind'], text: string) => {
    const id = ++toastSeq
    setItems((prev) => [...prev.slice(-3), { id, kind, text }])
    setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 3500)
  }, [])

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed top-4 right-4 left-4 z-60 flex flex-col gap-2 sm:left-auto sm:w-80">
          {items.map((t) => (
            <div
              key={t.id}
              role="status"
              className={`pointer-events-auto flex items-center gap-2 rounded-[var(--td-radius)] px-4 py-3 text-sm shadow-lg ${
                t.kind === 'ok'
                  ? 'bg-slate-900 text-white'
                  : 'border border-rose-200 bg-rose-50 text-rose-700'
              }`}
            >
              {t.kind === 'ok' ? (
                <Check aria-hidden className="h-4 w-4 shrink-0 text-emerald-400" />
              ) : (
                <CircleAlert aria-hidden className="h-4 w-4 shrink-0" />
              )}
              <span>{t.text}</span>
            </div>
          ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}

// ---------- Copy button ----------

export function CopyButton({ text, label = '复制' }: { text: string; label?: string }) {
  const toast = useToast()
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      const workspace = (document.querySelector('[data-workspace]')?.getAttribute('data-workspace') ?? 'customer') as ConsoleWorkspace
      recordConsoleEvent('copy_succeeded', workspace)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      toast('err', '复制失败，请手动选择文本复制')
    }
  }

  return (
    <Button variant="secondary" size="sm" onClick={copy}>
      {copied ? <Check aria-hidden size={13} /> : <Copy aria-hidden size={13} />}
      {copied ? '已复制' : label}
    </Button>
  )
}

// ---------- Progress bar ----------

export function ProgressBar({ value, limit }: { value: number; limit: number | null }) {
  if (limit === null || limit <= 0) {
    return <span className="text-xs text-slate-400">无限额</span>
  }
  const pct = Math.min(100, Math.round((value / limit) * 100))
  const color =
    pct >= 95 ? 'bg-rose-500' : pct >= 75 ? 'bg-amber-500' : 'bg-blue-500'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-[11px] text-slate-500">{pct}%</span>
    </div>
  )
}
