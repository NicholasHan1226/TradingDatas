import { useEffect, useRef, type ComponentType, type ReactNode } from 'react'
import { ArrowLeft, SignOut } from '@phosphor-icons/react'

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
  group?: string
  accent?: 'blue' | 'cyan' | 'violet' | 'orange'
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
  const navRef = useRef<HTMLElement>(null)

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'auto' })
    const activeButton = navRef.current?.querySelector<HTMLElement>('[aria-current="page"]')
    activeButton?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
  }, [active])

  return (
    <div className="min-h-full bg-[var(--td-canvas)]" data-workspace={workspace}>
      <header className="workspace-header sticky top-0 z-20 border-b border-[var(--td-line)] bg-[rgb(250_249_246/0.96)] text-[var(--td-ink)] backdrop-blur-xl">
        <div className="mx-auto flex min-h-16 max-w-[1480px] items-center justify-between gap-4 px-4 sm:px-7 lg:px-10">
          <div className="flex min-w-0 items-center gap-4 sm:gap-6">
            <div className="shrink-0 text-[22px] font-bold tracking-[-0.065em] text-[var(--td-ink)] sm:text-[24px]">
              <span className="tracking-[-0.075em]">Trading</span><span className="font-semibold tracking-[-0.045em]">Datas</span>
            </div>
            <div className="h-6 w-px bg-[var(--td-line-strong)]" />
            <span className="truncate text-[13px] font-medium text-[var(--td-ink-soft)]">{workspaceLabel}</span>
          </div>

          <div className="flex shrink-0 items-center gap-1 sm:gap-2">
            {identity && <span className="hidden max-w-48 truncate px-2 py-2 text-[12px] font-medium text-[var(--td-ink-soft)] md:inline">{identity}</span>}
            {onSwitch && (
              <button type="button" onClick={onSwitch} className="workspace-action" aria-label={switchLabel}>
                <ArrowLeft aria-hidden size={15} weight="regular" />
                <span className="hidden sm:inline">{switchLabel}</span>
              </button>
            )}
            <button type="button" onClick={onLogout} className="workspace-action" aria-label="退出登录">
              <SignOut aria-hidden size={15} weight="regular" />
              <span className="hidden sm:inline">退出</span>
            </button>
          </div>
        </div>

        <nav ref={navRef} aria-label={`${workspaceLabel}导航`} className="workspace-nav mx-auto flex max-w-[1480px] snap-x snap-mandatory gap-7 overflow-x-auto px-4 sm:px-7 lg:px-10">
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

      {previewing && (
        <div className="border-b border-[#d9d6f4] bg-[#f1efff]">
          <div className="mx-auto max-w-[1480px] px-4 py-2 text-[11px] leading-5 text-[#534e7a] sm:px-7 lg:px-10">
            <strong className="font-semibold">客户视角预览</strong> · 当前使用管理员账户数据，仅用于检查客户界面。
          </div>
        </div>
      )}

      <main className="mx-auto max-w-[1480px] px-4 py-6 pb-16 sm:px-7 sm:py-8 lg:px-10">
        {children}
      </main>
    </div>
  )
}
