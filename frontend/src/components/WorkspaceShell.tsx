import { useEffect, useRef, type ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { ArrowLeftRight, LogOut } from 'lucide-react'

export interface WorkspaceNavItem<Key extends string> {
  key: Key
  label: string
  description: string
  icon: LucideIcon
  group?: string
  accent?: 'blue' | 'cyan' | 'violet' | 'orange'
}

const ACCENT_CLASS = {
  blue: 'bg-blue-500',
  cyan: 'bg-cyan-400',
  violet: 'bg-violet-400',
  orange: 'bg-orange-400',
}

const ICON_CLASS = {
  blue: 'bg-blue-500/14 text-blue-300 ring-blue-400/15',
  cyan: 'bg-cyan-400/12 text-cyan-300 ring-cyan-300/15',
  violet: 'bg-violet-400/14 text-violet-300 ring-violet-300/15',
  orange: 'bg-orange-400/12 text-orange-300 ring-orange-300/15',
}

export default function WorkspaceShell<Key extends string>({
  workspace,
  workspaceLabel,
  items,
  active,
  onSelect,
  onSwitch,
  switchLabel,
  onLogout,
  previewing = false,
  identity,
  children,
}: {
  workspace: 'admin' | 'customer'
  workspaceLabel: string
  items: WorkspaceNavItem<Key>[]
  active: Key
  onSelect: (key: Key) => void
  onSwitch?: () => void
  switchLabel?: string
  onLogout: () => void
  previewing?: boolean
  identity?: string
  children: ReactNode
}) {
  const activeItem = items.find((item) => item.key === active) ?? items[0]
  const navRef = useRef<HTMLElement>(null)

  useEffect(() => {
    const activeButton = navRef.current?.querySelector<HTMLElement>('[aria-current="page"]')
    activeButton?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
  }, [active])

  return (
    <div className="min-h-full bg-[var(--td-canvas)]" data-workspace={workspace}>
      <div className="h-1 bg-[linear-gradient(90deg,var(--td-accent)_0_42%,var(--td-cyan)_42%_64%,var(--td-violet)_64%_82%,var(--td-orange)_82%)]" />
      <header className="workspace-header sticky top-0 z-20 bg-[var(--td-shell)] text-white shadow-[0_1px_0_rgb(255_255_255/0.08)]">
        <div className="mx-auto flex min-h-[68px] max-w-[1440px] items-center justify-between gap-4 px-4 sm:px-7 lg:px-10">
          <div className="flex min-w-0 items-center gap-5 sm:gap-7">
            <div className="shrink-0">
              <div className="text-[19px] font-bold tracking-[-0.06em] text-white">TradingDatas</div>
              <div className="mt-0.5 text-[9px] font-semibold tracking-[0.16em] text-slate-500">FINANCIAL DATA</div>
            </div>
            <div className="hidden h-7 w-px bg-white/10 sm:block" />
            <div className="hidden min-w-0 sm:block">
              <div className="text-[10px] font-medium tracking-[0.11em] text-slate-500 uppercase">{workspaceLabel}</div>
              <div className="mt-0.5 truncate text-sm font-medium text-slate-200">{activeItem.label}</div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {identity && <span className="hidden max-w-48 truncate rounded-md border border-white/10 bg-white/[0.04] px-2.5 py-1.5 font-mono text-[10px] text-slate-400 md:inline">{identity}</span>}
            {onSwitch && !previewing && (
              <button type="button" onClick={onSwitch} className="workspace-action" aria-label={switchLabel}>
                <ArrowLeftRight aria-hidden size={15} />
                <span className="hidden sm:inline">{switchLabel}</span>
              </button>
            )}
            <button type="button" onClick={onLogout} className="workspace-action" aria-label="退出登录">
              <LogOut aria-hidden size={15} />
              <span className="hidden sm:inline">退出</span>
            </button>
          </div>
        </div>

        <div className="relative border-t border-white/[0.07] after:pointer-events-none after:absolute after:inset-y-0 after:right-0 after:w-8 after:bg-gradient-to-l after:from-[var(--td-shell)] after:to-transparent sm:after:hidden">
          <nav ref={navRef} aria-label={`${workspaceLabel}导航`} className="workspace-nav mx-auto flex max-w-[1440px] snap-x snap-mandatory gap-1 overflow-x-auto px-3 pr-9 sm:px-6 lg:px-9">
            {items.map((item) => {
              const Icon = item.icon
              const selected = item.key === active
              const accent = item.accent ?? 'blue'
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => onSelect(item.key)}
                  aria-current={selected ? 'page' : undefined}
                  className={`group relative flex min-h-12 min-w-max snap-center items-center gap-2.5 px-3.5 py-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-blue-400 ${selected ? 'text-white' : 'text-slate-500 hover:text-slate-200'}`}
                >
                  <span className={`flex h-7 w-7 items-center justify-center rounded-[8px] ring-1 ring-inset transition-colors ${selected ? ICON_CLASS[accent] : 'bg-white/[0.025] text-slate-600 ring-white/[0.05] group-hover:text-slate-300'}`}>
                    <Icon aria-hidden size={14} strokeWidth={1.8} />
                  </span>
                  <span>
                    <span className="block text-[12px] font-medium">{item.label}</span>
                    <span className={`hidden text-[9px] tracking-wide lg:block ${selected ? 'text-slate-400' : 'text-slate-600'}`}>{item.description}</span>
                  </span>
                  <span className={`absolute inset-x-3 bottom-0 h-0.5 ${selected ? ACCENT_CLASS[accent] : 'bg-transparent'}`} />
                </button>
              )
            })}
          </nav>
        </div>
      </header>

      {previewing && (
        <div className="border-b border-blue-200 bg-blue-50">
          <div className="mx-auto flex max-w-[1380px] flex-col items-start gap-2 px-4 py-2.5 text-xs leading-5 text-blue-800 sm:flex-row sm:items-center sm:justify-between sm:px-8">
            <span><strong className="font-semibold">客户视角预览</strong> · 当前使用管理员账户数据，仅用于检查客户界面。</span>
            {onSwitch && <button type="button" onClick={onSwitch} className="shrink-0 rounded-md bg-white/70 px-2.5 py-1 font-semibold text-blue-700 ring-1 ring-blue-200 hover:bg-white hover:text-blue-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 sm:bg-transparent sm:px-0 sm:py-0 sm:ring-0 sm:underline sm:decoration-blue-300 sm:underline-offset-4">返回管理工作台</button>}
          </div>
        </div>
      )}

      <main className="mx-auto max-w-[1380px] px-4 py-6 pb-16 sm:px-7 sm:py-8 lg:px-10">
        {children}
      </main>
    </div>
  )
}
