import { useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import type { ApiClient } from '../../lib/api'
import TokensView from './TokensView'
import UsageView from './UsageView'
import CollectionView from './CollectionView'
import HealthView from './HealthView'
import DataView from './DataView'

type SectionKey = 'tokens' | 'usage' | 'collection' | 'health' | 'browser'

interface NavItem {
  key: SectionKey
  label: string
  title: string
  icon: ReactNode
}

function Icon({ path }: { path: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-[18px] w-[18px] shrink-0"
    >
      <path d={path} />
    </svg>
  )
}

const NAV: NavItem[] = [
  {
    key: 'tokens',
    label: '客户管理',
    title: '客户管理',
    icon: (
      <Icon path="M15 19.128a9.38 9.38 0 0 0 2.625.372 9.337 9.337 0 0 0 4.121-.952 4.125 4.125 0 0 0-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 0 1 8.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0 1 11.964-3.07M12 6.375a3.375 3.375 0 1 1-6.75 0 3.375 3.375 0 0 1 6.75 0Zm8.25 2.25a2.625 2.625 0 1 1-5.25 0 2.625 2.625 0 0 1 5.25 0Z" />
    ),
  },
  {
    key: 'usage',
    label: '用量总览',
    title: 'API 用量总览',
    icon: <Icon path="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />,
  },
  {
    key: 'collection',
    label: '采集状态',
    title: '数据采集状态',
    icon: <Icon path="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 5.625c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />,
  },
  {
    key: 'health',
    label: '健康告警',
    title: '系统健康与告警',
    icon: <Icon path="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />,
  },
  {
    key: 'browser',
    label: '数据浏览',
    title: '数据目录浏览',
    icon: <Icon path="M7.5 3.75v16.5m0-16.5h9m-9 16.5h9m-9-16.5a48.67 48.67 0 0 0-3.75 9.75m14.25-9.75a48.67 48.67 0 0 1 3.75 9.75m-17.25 0a48.764 48.764 0 0 0 3 .75m14.25-.75a48.764 48.764 0 0 1-3 .75" />,
  },
]

export default function AdminApp({
  client,
  onLogout,
}: {
  client: ApiClient
  onLogout: () => void
}) {
  const [section, setSection] = useState<SectionKey>('tokens')

  const views: Record<SectionKey, ReactNode> = {
    tokens: <TokensView client={client} />,
    usage: <UsageView client={client} />,
    collection: <CollectionView client={client} />,
    health: <HealthView client={client} />,
    browser: <DataView client={client} />,
  }

  return (
    <div className="flex min-h-full bg-slate-50">
      {/* Sidebar */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-white/10 bg-slate-950 text-slate-300 lg:flex">
        <div className="px-6 pt-7 pb-8">
          <div className="text-[17px] font-bold tracking-[-0.055em] text-white">TradingDatas</div>
          <div className="mt-1 text-[10px] font-medium tracking-[0.18em] text-slate-500">ADMIN WORKSPACE</div>
        </div>

        <nav className="flex-1 space-y-1 px-4">
          {NAV.map((item) => {
            const active = item.key === section
            return (
              <button
                key={item.key}
                onClick={() => setSection(item.key)}
                className={`relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-400 ${
                  active
                    ? 'bg-white/10 font-medium text-white'
                    : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
                }`}
              >
                {active && (
                  <motion.span
                    layoutId="nav-active"
                    className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-blue-400"
                  />
                )}
                {item.icon}
                {item.label}
              </button>
            )
          })}
        </nav>

        <div className="border-t border-white/10 px-4 py-4">
          <div className="mb-3 px-3 text-[10px] font-medium tracking-[0.16em] text-slate-600">CONTROL PLANE</div>
          <button
            onClick={onLogout}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-slate-500 transition-colors hover:bg-white/5 hover:text-slate-300"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
              <path d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15m3 0 3-3m0 0-3-3m3 3H9" />
            </svg>
            退出登录
          </button>
        </div>
      </aside>

      {/* Content */}
      <main className="min-w-0 flex-1 overflow-y-auto bg-slate-50">
        <header className="sticky top-0 z-10 border-b border-slate-200/80 bg-white/90 px-5 py-4 backdrop-blur md:px-8">
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
            <div>
              <div className="mb-0.5 text-[10px] font-semibold tracking-[0.16em] text-slate-400 uppercase">TradingDatas · Control Plane</div>
              <p className="text-xs text-slate-500">运营管理工作区</p>
            </div>
            <div className="flex items-center gap-3">
              <span className="hidden items-center gap-1.5 text-xs text-slate-500 sm:inline-flex">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> 已认证会话
              </span>
              <select
                aria-label="切换控制台页面"
                value={section}
                onChange={(event) => setSection(event.target.value as SectionKey)}
                className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs font-medium text-slate-700 outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30 lg:hidden"
              >
                {NAV.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
              </select>
            </div>
          </div>
        </header>
        <div className="mx-auto max-w-6xl px-5 py-6 pb-14 md:px-8">
          <AnimatePresence mode="wait">
            <motion.div
              key={section}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.18 }}
            >
              {views[section]}
            </motion.div>
          </AnimatePresence>
        </div>
      </main>
    </div>
  )
}
