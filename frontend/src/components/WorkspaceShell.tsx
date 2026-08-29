import { useEffect, useRef, type ComponentType, type ReactNode } from 'react'
import { ArrowSquareOut, SignOut } from '@phosphor-icons/react'

type WorkspaceIcon = ComponentType<{
  size?: number | string
  className?: string
  'aria-hidden'?: boolean
}>

export interface WorkspaceNavItem<Key extends string> {
  key: Key
  label: string
  description: string
  icon: WorkspaceIcon
  accent?: 'blue' | 'cyan' | 'violet' | 'orange'
}

export default function WorkspaceShell<Key extends string>({
  workspaceLabel,
  items,
  active,
  onSelect,
  onSwitch,
  switchLabel,
  onLogout,
  identity,
  children,
}: {
  workspaceLabel: string
  items: WorkspaceNavItem<Key>[]
  active: Key
  onSelect: (key: Key) => void
  onSwitch?: () => void
  switchLabel?: string
  onLogout: () => void
  identity?: string
  children: ReactNode
}) {
  const navRef = useRef<HTMLElement>(null)

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'auto' })
    const activeButton = navRef.current?.querySelector<HTMLElement>('[aria-current="page"]')
    activeButton?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
  }, [active])

  return (
    <div className="min-h-full bg-[var(--td-canvas)]" data-workspace="admin">
      <header className="workspace-header sticky top-3 z-20 mx-auto w-[calc(100%-24px)] max-w-[1480px] overflow-hidden rounded-[22px] border border-[var(--td-line)] bg-[rgb(252_251_248/0.92)] text-[var(--td-ink)] shadow-[0_14px_42px_rgb(19_30_50/0.09)] backdrop-blur-xl sm:top-4 sm:w-[calc(100%-40px)]">
        <div className="flex min-h-16 items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-4 sm:gap-6">
            <a href="https://tradingdatas.com/" className="shrink-0 text-[22px] font-bold tracking-[-0.065em] text-[var(--td-ink)] sm:text-[24px]" aria-label="返回 TradingDatas 首页">
              <span className="tracking-[-0.075em]">Trading</span><span className="font-semibold tracking-[-0.045em]">Datas</span>
            </a>
            <div className="h-6 w-px bg-[var(--td-line-strong)]" />
            <span className="truncate text-[13px] font-medium text-[var(--td-ink-soft)]">{workspaceLabel}</span>
          </div>

          <div className="flex shrink-0 items-center gap-1 sm:gap-2">
            {identity && <span className="hidden max-w-48 truncate px-2 py-2 text-[12px] font-medium text-[var(--td-ink-soft)] md:inline">{identity}</span>}
            {onSwitch && (
              <button type="button" onClick={onSwitch} className="workspace-action" aria-label={switchLabel}>
                <ArrowSquareOut aria-hidden size={15} weight="regular" />
                <span className="hidden sm:inline">{switchLabel}</span>
              </button>
            )}
            <button type="button" onClick={onLogout} className="workspace-action" aria-label="退出登录">
              <SignOut aria-hidden size={15} weight="regular" />
              <span className="hidden sm:inline">退出</span>
            </button>
          </div>
        </div>

        <nav ref={navRef} aria-label={`${workspaceLabel}导航`} className="workspace-nav flex snap-x snap-mandatory gap-7 overflow-x-auto border-t border-[var(--td-line)] px-4 sm:px-6 lg:px-8">
          {items.map((item) => {
            const Icon = item.icon
            const selected = item.key === active
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => onSelect(item.key)}
                aria-current={selected ? 'page' : undefined}
                aria-label={`${item.label}：${item.description}`}
                className={`group relative flex min-h-11 min-w-max snap-center items-center gap-2.5 pb-0.5 text-[13px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-[var(--td-accent)] ${selected ? 'text-[var(--td-accent)]' : 'text-[var(--td-muted)] hover:text-[var(--td-ink)]'}`}
              >
                <Icon aria-hidden size={17} className="shrink-0" />
                <span>{item.label}</span>
                <span className={`absolute inset-x-0 bottom-0 h-0.5 ${selected ? 'bg-[var(--td-accent)]' : 'bg-transparent'}`} />
              </button>
            )
          })}
        </nav>
      </header>

      <main className="mx-auto max-w-[1480px] px-4 pb-16 pt-10 sm:px-7 sm:pt-12 lg:px-10">
        {children}
      </main>
    </div>
  )
}
