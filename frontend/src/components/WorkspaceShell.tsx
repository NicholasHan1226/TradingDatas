import { useEffect, useRef, type ComponentType, type ReactNode } from 'react'
import { ArrowLeft, ArrowSquareOut, SignOut } from '@phosphor-icons/react'

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
  layout = 'top',
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
  layout?: 'top' | 'side'
  children: ReactNode
}) {
  const navRef = useRef<HTMLElement>(null)

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'auto' })
    const activeButton = navRef.current?.querySelector<HTMLElement>('[aria-current="page"]')
    activeButton?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
  }, [active])

  if (layout === 'side') {
    const groups = items.reduce<Array<{ label?: string; items: WorkspaceNavItem<Key>[] }>>((result, item) => {
      const last = result[result.length - 1]
      if (!last || last.label !== item.group) result.push({ label: item.group, items: [item] })
      else last.items.push(item)
      return result
    }, [])

    return (
      <div className="workspace-frame min-h-full bg-[var(--td-canvas)] lg:grid lg:grid-cols-[244px_minmax(0,1fr)]" data-workspace={workspace}>
        <aside className="workspace-rail sticky top-0 hidden h-screen flex-col lg:flex">
          <div className="px-6 pb-8 pt-7">
            <div className="text-[23px] font-bold tracking-[-0.065em] text-white">
              <span className="tracking-[-0.075em]">Trading</span><span className="font-semibold tracking-[-0.045em]">Datas</span>
            </div>
            <div className="mt-8 flex items-center gap-2 text-[10px] font-semibold tracking-[0.12em] text-[#91a5d8]">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--td-cyan)] shadow-[0_0_0_4px_rgb(45_212_234/0.12)]" />
              {workspaceLabel}
            </div>
          </div>

          <nav ref={navRef} aria-label={`${workspaceLabel}导航`} className="flex-1 px-3">
            <div className="space-y-6">
              {groups.map((group) => (
                <div key={group.label ?? 'workspace'}>
                  {group.label && <div className="px-3 pb-2 text-[9px] font-semibold tracking-[0.14em] text-[#6378ab]">{group.label}</div>}
                  <div className="space-y-1">
                    {group.items.map((item) => {
                      const Icon = item.icon
                      const selected = item.key === active
                      return (
                        <button
                          key={item.key}
                          type="button"
                          onClick={() => onSelect(item.key)}
                          aria-current={selected ? 'page' : undefined}
                          aria-label={`${item.label}：${item.description}`}
                          className={`workspace-rail-item workspace-rail-item-${item.accent ?? 'blue'} group flex min-h-11 w-full items-center gap-3 rounded-[8px] px-3 text-left text-[13px] font-medium transition-[color,background-color,box-shadow] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#95a9ff] ${selected ? 'is-active' : ''}`}
                        >
                          <Icon aria-hidden size={17} className="shrink-0" />
                          <span className="min-w-0 flex-1">{item.label}</span>
                          {selected && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          </nav>

          <div className="border-t border-white/8 p-3">
            {identity && <div className="truncate px-3 pb-2 pt-1 text-[11px] font-medium text-[#afbee3]">{identity}</div>}
            {onSwitch && (
              <button type="button" onClick={onSwitch} className="workspace-rail-action w-full justify-start" aria-label={switchLabel}>
                <ArrowSquareOut aria-hidden size={15} weight="regular" />
                <span>{switchLabel}</span>
              </button>
            )}
            <button type="button" onClick={onLogout} className="workspace-rail-action mt-1 w-full justify-start" aria-label="退出登录">
              <SignOut aria-hidden size={15} weight="regular" />
              <span>退出登录</span>
            </button>
          </div>
        </aside>

        <div className="min-w-0">
          <header className="workspace-mobile-header sticky top-0 z-20 lg:hidden">
            <div className="flex min-h-16 items-center justify-between gap-3 px-4 sm:px-7">
              <div className="flex min-w-0 items-center gap-3">
                <div className="shrink-0 text-[21px] font-bold tracking-[-0.065em] text-white"><span className="tracking-[-0.075em]">Trading</span><span className="font-semibold tracking-[-0.045em]">Datas</span></div>
                <div className="h-5 w-px bg-white/20" />
                <span className="truncate text-[11px] font-medium text-[#b4c2e6]">{workspaceLabel}</span>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {onSwitch && <button type="button" onClick={onSwitch} className="workspace-mobile-action" aria-label={switchLabel}><ArrowSquareOut aria-hidden size={15} /></button>}
                <button type="button" onClick={onLogout} className="workspace-mobile-action" aria-label="退出登录"><SignOut aria-hidden size={15} /></button>
              </div>
            </div>
            <nav ref={navRef} aria-label={`${workspaceLabel}导航`} className="workspace-nav flex snap-x snap-mandatory gap-7 overflow-x-auto px-4 sm:px-7">
              {items.map((item) => {
                const Icon = item.icon
                const selected = item.key === active
                return (
                  <button key={item.key} type="button" onClick={() => onSelect(item.key)} aria-current={selected ? 'page' : undefined} aria-label={`${item.label}：${item.description}`} className={`relative flex min-h-11 min-w-max snap-center items-center gap-2 pb-0.5 text-[12px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-[var(--td-accent)] ${selected ? 'text-[var(--td-accent)]' : 'text-[var(--td-muted)] hover:text-[var(--td-ink)]'}`}>
                    <Icon aria-hidden size={16} /><span>{item.label}</span><span className={`absolute inset-x-0 bottom-0 h-0.5 ${selected ? 'bg-[var(--td-accent)]' : 'bg-transparent'}`} />
                  </button>
                )
              })}
            </nav>
          </header>

          {previewing && (
            <div className="border-b border-[#d9d6f4] bg-[#f1efff]">
              <div className="mx-auto max-w-[1480px] px-4 py-2 text-[11px] leading-5 text-[#534e7a] sm:px-7 lg:px-10"><strong className="font-semibold">客户视角预览</strong> · 当前使用管理员账户数据，仅用于检查客户界面。</div>
            </div>
          )}

          <main className="workspace-content mx-auto max-w-[1540px] px-4 py-6 pb-16 sm:px-7 sm:py-8 lg:px-9 xl:px-12">
            {children}
          </main>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-full bg-[var(--td-canvas)]" data-workspace={workspace}>
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

      {previewing && (
        <div className="border-b border-[#d9d6f4] bg-[#f1efff]">
          <div className="mx-auto max-w-[1480px] px-4 py-2 text-[11px] leading-5 text-[#534e7a] sm:px-7 lg:px-10">
            <strong className="font-semibold">客户视角预览</strong> · 当前使用管理员账户数据，仅用于检查客户界面。
          </div>
        </div>
      )}

      <main className="mx-auto max-w-[1480px] px-4 pb-16 pt-10 sm:px-7 sm:pt-12 lg:px-10">
        {children}
      </main>
    </div>
  )
}
