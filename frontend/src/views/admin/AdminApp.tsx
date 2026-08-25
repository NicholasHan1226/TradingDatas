import type { ReactNode } from 'react'
import { ChartBar, Database, Key, MagnifyingGlass, Pulse } from '@phosphor-icons/react'
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
  { key: 'tokens', label: '客户', description: '账户、套餐与授权', group: 'Access', icon: Key, accent: 'blue' },
  { key: 'usage', label: '用量', description: '请求趋势与配额', group: 'Access', icon: ChartBar, accent: 'violet' },
  { key: 'collection', label: '数据管道', description: '采集与新鲜度', group: 'Data', icon: Database, accent: 'cyan' },
  { key: 'health', label: '运行健康', description: '风险与诊断', group: 'Data', icon: Pulse, accent: 'orange' },
  { key: 'browser', label: '数据浏览', description: '目录与样本验证', group: 'Data', icon: MagnifyingGlass, accent: 'blue' },
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
      workspaceLabel="管理员工作台"
      items={NAV}
      active={section}
      onSelect={onSectionChange}
      onSwitch={onViewCustomer}
      switchLabel="查看客户门户"
      onLogout={onLogout}
      layout="side"
    >
      {views[section]}
    </WorkspaceShell>
  )
}
