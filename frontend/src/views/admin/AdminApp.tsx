import { useState, type ReactNode } from 'react'
import type { ApiClient } from '../../lib/api'
import { Button } from '../../components/ui'
import TokensView from './TokensView'
import UsageView from './UsageView'
import CollectionView from './CollectionView'
import HealthView from './HealthView'
import DataView from './DataView'

type SectionKey = 'tokens' | 'usage' | 'collection' | 'health' | 'browser'

interface NavItem {
  key: SectionKey
  label: string
  description: string
  group: '访问管理' | '数据运行面'
  path: string
}

function Icon({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className="h-[17px] w-[17px] shrink-0" aria-hidden>
      <path d={path} />
    </svg>
  )
}

const NAV: NavItem[] = [
  { key: 'tokens', label: '客户与密钥', description: '访问与套餐', group: '访问管理', path: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm13 10v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75' },
  { key: 'usage', label: '调用用量', description: '趋势与容量', group: '访问管理', path: 'M4 19V9m8 10V5m8 14v-7' },
  { key: 'collection', label: '采集状态', description: '数据集运行状态', group: '数据运行面', path: 'M4 6c0-1.1 3.6-2 8-2s8 .9 8 2-3.6 2-8 2-8-.9-8-2Zm0 0v6c0 1.1 3.6 2 8 2s8-.9 8-2V6m-16 6v6c0 1.1 3.6 2 8 2s8-.9 8-2v-6' },
  { key: 'health', label: '健康告警', description: '风险与异常', group: '数据运行面', path: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Zm-3-10 2 2 4-4' },
  { key: 'browser', label: '数据浏览器', description: '目录与样本查询', group: '数据运行面', path: 'M4 5h16v14H4zM4 9h16M9 9v10' },
]

export default function AdminApp({
  client,
  onLogout,
  onViewCustomer,
}: {
  client: ApiClient
  onLogout: () => void
  onViewCustomer: () => void
}) {
  const [section, setSection] = useState<SectionKey>('tokens')

  const views: Record<SectionKey, ReactNode> = {
    tokens: <TokensView client={client} />,
    usage: <UsageView client={client} />,
    collection: <CollectionView client={client} />,
    health: <HealthView client={client} />,
    browser: <DataView client={client} />,
  }
  const activeItem = NAV.find((item) => item.key === section) ?? NAV[0]

  return (
    <div className="flex min-h-full bg-[var(--td-canvas)]">
      <aside className="hidden w-[248px] shrink-0 flex-col border-r border-blue-950 bg-[#0c1324] lg:flex">
        <div className="flex h-16 items-center border-b border-white/10 px-5">
          <div>
            <div className="text-[18px] font-bold tracking-[-0.055em] text-white">TradingDatas</div>
            <div className="mt-0.5 text-[10px] font-medium tracking-[0.1em] text-blue-300/70">ADMIN CONSOLE</div>
          </div>
        </div>

        <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-5" aria-label="管理控制台导航">
          {(['访问管理', '数据运行面'] as const).map((group) => (
            <div key={group}>
              <p className="mb-1.5 px-2.5 text-[11px] font-medium text-slate-600">{group}</p>
              <div className="space-y-0.5">
                {NAV.filter((item) => item.group === group).map((item) => {
                  const active = item.key === section
                  return (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => setSection(item.key)}
                      aria-current={active ? 'page' : undefined}
                      className={`flex w-full items-center gap-3 rounded-[var(--td-radius-sm)] px-2.5 py-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-400 ${active ? 'bg-blue-500/15 text-white ring-1 ring-inset ring-blue-400/20' : 'text-slate-400 hover:bg-white/5 hover:text-slate-100'}`}
                    >
                      <Icon path={item.path} />
                      <span className="min-w-0">
                        <span className="block text-[13px] font-medium">{item.label}</span>
                        <span className={`block truncate text-[10px] ${active ? 'text-blue-300' : 'text-slate-600'}`}>{item.description}</span>
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t border-white/10 p-3">
          <div className="mb-2 flex items-center justify-between rounded-[var(--td-radius-sm)] border border-white/8 bg-white/[0.04] px-3 py-2.5">
            <div>
              <div className="text-[10px] text-slate-600">当前会话</div>
              <div className="mt-0.5 text-xs font-medium text-slate-200">管理员</div>
            </div>
            <span className="rounded border border-blue-400/20 bg-blue-400/10 px-1.5 py-0.5 text-[9px] text-blue-300">ADMIN</span>
          </div>
          <button type="button" onClick={onViewCustomer} className="flex w-full items-center gap-2 rounded-[var(--td-radius-sm)] px-3 py-2 text-xs text-slate-500 hover:bg-white/5 hover:text-slate-200 focus-visible:outline-2 focus-visible:outline-blue-400">
            <Icon path="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
            查看用户前台
          </button>
          <button type="button" onClick={onLogout} className="mt-0.5 flex w-full items-center gap-2 rounded-[var(--td-radius-sm)] px-3 py-2 text-xs text-slate-500 hover:bg-rose-500/10 hover:text-rose-300 focus-visible:outline-2 focus-visible:outline-rose-400">
            <Icon path="M10 17l5-5-5-5m5 5H3m11-9h5a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5" />
            退出登录
          </button>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto">
        <header className="sticky top-0 z-10 flex h-16 items-center border-b border-[var(--td-line)] bg-white/95 px-5 backdrop-blur md:px-8">
          <div className="mx-auto flex w-full max-w-[1320px] items-center justify-between gap-4">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-[var(--td-ink)]">{activeItem.label}</div>
              <div className="mt-0.5 text-[11px] text-[var(--td-faint)]">TradingDatas · {activeItem.group}</div>
            </div>
            <div className="flex items-center gap-2">
              <span className="hidden text-xs text-[var(--td-muted)] sm:inline">管理员工作区</span>
              <Button variant="secondary" size="sm" onClick={onViewCustomer} className="lg:hidden">用户前台</Button>
              <select aria-label="切换控制台页面" value={section} onChange={(event) => setSection(event.target.value as SectionKey)} className="h-8 max-w-32 rounded-[var(--td-radius-sm)] border border-[var(--td-line-strong)] bg-white px-2 text-xs font-medium text-[var(--td-ink-soft)] outline-none focus-visible:ring-2 focus-visible:ring-blue-600/20 lg:hidden">
                {NAV.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
              </select>
              <Button variant="ghost" size="sm" className="lg:hidden" aria-label="退出登录" onClick={onLogout}>退出</Button>
            </div>
          </div>
        </header>
        <div className="mx-auto max-w-[1320px] px-5 py-7 pb-14 md:px-8">{views[section]}</div>
      </main>
    </div>
  )
}
