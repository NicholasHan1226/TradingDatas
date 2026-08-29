import type { ReactNode } from 'react'
import { ChartBar, Key, MagnifyingGlass, Pulse } from '@phosphor-icons/react'
import type { ApiClient } from '../../lib/api'
import WorkspaceShell, { type WorkspaceNavItem } from '../../components/WorkspaceShell'
import TokensView from './TokensView'
import UsageView from './UsageView'
import CollectionView from './CollectionView'
import HealthView from './HealthView'
import DataView from './DataView'
import type { AdminSection } from '../../lib/workspaceRoute'

type SectionKey = AdminSection

const NAV: WorkspaceNavItem<SectionKey>[] = [
  { key: 'tokens', label: '客户与权限', description: '账户、套餐与授权', icon: Key, accent: 'blue' },
  { key: 'health', label: '运行异常', description: '只看需要处理的采集与回执问题', icon: Pulse, accent: 'orange' },
  { key: 'usage', label: '用量', description: '请求趋势与频率', icon: ChartBar, accent: 'violet' },
  { key: 'browser', label: '数据核验', description: '目录与样本回读', icon: MagnifyingGlass, accent: 'cyan' },
]

export default function AdminApp({
  client,
  section,
  onSectionChange,
  onLogout,
  onViewCustomer,
}: {
  client: ApiClient
  section: SectionKey
  onSectionChange: (section: SectionKey) => void
  onLogout: () => void
  onViewCustomer: () => void
}) {
  const views: Record<SectionKey, ReactNode> = {
    tokens: <TokensView client={client} />,
    usage: <UsageView client={client} />,
    collection: <CollectionView client={client} />,
    health: <HealthView client={client} />,
    browser: <DataView client={client} />,
  }

  return (
    <WorkspaceShell
      workspace="admin"
      workspaceLabel="管理员控制台"
      items={NAV}
      active={section}
      onSelect={onSectionChange}
      onSwitch={onViewCustomer}
      switchLabel="打开官网 Account"
      onLogout={onLogout}
      layout="top"
    >
      {views[section]}
    </WorkspaceShell>
  )
}
